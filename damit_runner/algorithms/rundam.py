"""damit_run Processing tools: rundam (run the breach model for one dam, or prepare / record it) and
checkhandoff."""
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProcessingAlgorithm,
                       QgsProcessingException, QgsProcessingOutputBoolean, QgsProcessingOutputFile,
                       QgsProcessingOutputFolder, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterDefinition, QgsProcessingParameterEnum, QgsProcessingParameterFile,
                       QgsProcessingParameterNumber, QgsProcessingParameterPoint, QgsProcessingParameterString,
                       QgsProject)

from ..qgis_compat import FILE_FILE, FILE_FOLDER
from ..core import catalog_bridge as CB
from ..core import rundam as RD

try:
    from qgis.core import Qgis
    _DOUBLE = Qgis.ProcessingNumberParameterType.Double
except AttributeError:                                           # QGIS < 3.36
    _DOUBLE = QgsProcessingParameterNumber.Double


TIERS = ["LISFLOOD-FP only", "LISFLOOD-FP for the extent, then ANUGA (final results from ANUGA)",
         "LISFLOOD-FP then HEC-RAS 2D (final results from HEC-RAS; needs HEC-RAS 6.6, see help)"]


def _adv(p):
    p.setFlags(p.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
    return p


def _ids(text):
    return [t.strip() for t in (text or "").replace(";", ",").split(",") if t.strip()]


class _Base(QgsProcessingAlgorithm):
    def group(self):
        return "DamIT breach runs"

    def groupId(self):  # noqa: N802
        return "damit_runs"

    def createInstance(self):  # noqa: N802
        return type(self)()


class RunDam(_Base):
    def name(self):
        return "rundam"

    def displayName(self):  # noqa: N802
        return "Run breach model for one dam"

    def shortHelpString(self):  # noqa: N802
        return ("Dam breach flood for one dam, the DamSafety Runner's rundam for the DamIT presets. Sunny day: no "
                "inflow and no outlet or spillway flow, the reservoir starting at the top of dam. The breach "
                "hydrograph comes from METHOD (Froehlich 2008 piping by default, TR-60, the other DamSafety methods, "
                "or your CSV). The breach inflow goes in at the lowest ground of the downstream toe band, 5 m to "
                "H x (downstream slope + 1) out from the dam line (3:1 when the slope is not known), never more "
                "than 150 m from it. LISFLOOD-FP runs on the DEM and the domain grows until the flood no longer "
                "leaves it deeper than the edge tolerance (MAX_RUNS, MAX_EXTENT_MI, DURATION_MAX_HR and the "
                "wall-clock limits stop it); a coarse wide, shallow flood is run again at 10 m (GRID_REFINE); "
                "Models = ANUGA (or FORCE_ANUGA) re-runs the extent on a mesh and its maxima are the results.\n\n"
                "LISFLOOD_EXE: empty = an installed LISFLOOD-FP (the provider setting, NDBREACH_LISFLOOD, lisflood "
                "on PATH or a usual install place); when none is found the built-in numpy engine runs instead, "
                "with a WARNING in the log, run_report.json and ENGINE_FALLBACK / ENGINE_NOTE (as the old ND Breach "
                "Runner did); 'builtin' = the built-in engine on request (a screening approximation, NOT "
                "LISFLOOD-FP). A path that does not exist is an error, not a fallback. HEC-RAS 2D is "
                "not run by DamIT (choosing it is refused). DamIT never starts HEC-RAS, Wine, ndbreach:rundam or "
                "ndbreach:batch.\n\n"
                "The run goes into a NEW folder under OUTPUT_FOLDER (never an existing one): run_setup.json, "
                "run_report.json, model/ and outputs/ (Depth (Max).tif ft, Velocity (Max).tif ft/s, WSE (Max).tif "
                "ft, Arrival Time.tif h, hmax_ft.tif and the QA rasters, Flood Polygons (Max Depth), Flood Extent, "
                "Arrival Zones). With DAMS_FOLDER the rasters and vectors are also copied into "
                "<DAMS_FOLDER>/<DAM_ID>/, and an empty height, storage, top of dam or area is read from its "
                "dam.json (the dam line, reservoir point and breach point too). Classification is DamIT Hazard's "
                "job (damit:classify). DRY_RUN on: prepare and record only (the 0.1.0 behaviour).\n\n"
                "NID dams only: the dam's id is its NID ID (National Inventory of Dams, e.g. ND00199), as dam_id "
                "or nid_id. A DWR-, DUG- or other non-NID id is refused; a new / proposed dam (IS_NEW) or a desk "
                "sample (IS_SAMPLE) may have none, with a warning.")

    def initAlgorithm(self, config=None):  # noqa: N802
        P = self.addParameter
        P(QgsProcessingParameterFile("HANDOFF", "Hand-off package (damit_handoff.json)", behavior=FILE_FILE,
                                     fileFilter="DamIT hand-off (*.json)", optional=True))
        P(QgsProcessingParameterString("DAM_ID", "Dam ID (without a package): the NID ID, e.g. ND00199",
                                       defaultValue="", optional=True))
        P(QgsProcessingParameterString("NID_ID", "NID ID (without a package; when DAM_ID is not the NID ID)",
                                       defaultValue="", optional=True))
        P(QgsProcessingParameterBoolean("IS_NEW", "New / proposed dam with no NID ID yet (without a package)",
                                        defaultValue=False, optional=True))
        P(QgsProcessingParameterBoolean("IS_SAMPLE", "Desk sample, not an NID inventory record (without a package)",
                                        defaultValue=False, optional=True))
        P(QgsProcessingParameterNumber("X", "Dam X (without a package)", type=_DOUBLE, optional=True))
        P(QgsProcessingParameterNumber("Y", "Dam Y (without a package)", type=_DOUBLE, optional=True))
        P(QgsProcessingParameterString("CRS", "Dam CRS authid (without a package)", defaultValue="", optional=True))
        P(QgsProcessingParameterNumber("HEIGHT_FT", "Dam height (ft)", type=_DOUBLE, optional=True))
        P(QgsProcessingParameterNumber("STORAGE_ACFT", "Storage at top of dam (ac-ft)", type=_DOUBLE, optional=True))
        P(QgsProcessingParameterEnum("MODE", "Mode", ["preset", "custom"], defaultValue=0))
        P(QgsProcessingParameterString("PRESET", "Preset ID", defaultValue="", optional=True))
        P(QgsProcessingParameterString("SCENARIOS", "Scenario IDs (comma separated)", defaultValue="", optional=True))
        P(QgsProcessingParameterString("METHODS", "Method IDs (custom mode)", defaultValue="", optional=True))
        P(QgsProcessingParameterFile("TERRAIN", "Terrain (DEM)", behavior=FILE_FILE, optional=True))
        P(QgsProcessingParameterFile("HYDROGRAPH", "Hydrograph CSV (time_hr, discharge_cfs)", behavior=FILE_FILE,
                                     fileFilter="CSV (*.csv)", optional=True))
        P(QgsProcessingParameterFile("OUTPUT_FOLDER", "Runs folder (a new sub-folder is created per run)",
                                     behavior=FILE_FOLDER))
        P(QgsProcessingParameterBoolean("DRY_RUN", "Dry run: prepare and record only (no model launch)",
                                        defaultValue=False))
        # the DamSafety Runner's rundam parameters, names and defaults
        P(QgsProcessingParameterFile("DAMS_FOLDER", "Dams folder (<folder>/<dam id>/: dam.json, dam line, reservoir "
                                     "point; the final rasters are copied there)", behavior=FILE_FOLDER,
                                     optional=True))
        P(QgsProcessingParameterFile("DEM", "DEM (a GeoTIFF or VRT; empty = TERRAIN)", behavior=FILE_FILE,
                                     optional=True))
        P(QgsProcessingParameterEnum("DEM_Z", "DEM elevation units", RD.DEM_Z_LABELS, defaultValue=0))
        P(QgsProcessingParameterNumber("TOP_FT", "Top of dam elevation (ft, the DEM's datum; empty = dam.json)",
                                       type=_DOUBLE, optional=True))
        P(QgsProcessingParameterNumber("AREA_AC", "Surface area at the top of dam (ac; empty = dam.json)",
                                       type=_DOUBLE, optional=True))
        P(QgsProcessingParameterNumber("PMF_FT", "Maximum reservoir level in the PMF (ft; recorded only: the sunny "
                                       "day starts at the top of dam)", type=_DOUBLE, optional=True))
        P(QgsProcessingParameterNumber("BOTTOM_FT", "Breach bottom elevation (ft; empty = top of dam - height)",
                                       type=_DOUBLE, optional=True))
        P(QgsProcessingParameterPoint("INFLOW_POINT", "Breach inflow point below the dam (empty = the toe band)",
                                      optional=True))
        P(QgsProcessingParameterEnum("METHOD", "Breach (ND 5.1.1(d))", RD.method_labels(), defaultValue=0))
        P(QgsProcessingParameterFile("USER_CSV", "Hydrograph CSV (for 'my own hydrograph')", behavior=FILE_FILE,
                                     fileFilter="CSV (*.csv)", optional=True))
        for name, label in (("CREST_WIDTH", "Crest width (ft): TR-60, MacDonald & Langridge-Monopolis"),
                            ("US_SLOPE", "Upstream slope, H in H:1V (TR-60, MacDonald)"),
                            ("DS_SLOPE", "Downstream slope, H in H:1V (TR-60, MacDonald; the toe band; 3 when "
                                         "empty)"),
                            ("CREST_LENGTH", "Crest length (ft; empty = dam.json dam_length_ft)")):
            P(QgsProcessingParameterNumber(name, label, type=_DOUBLE, optional=True, minValue=0))
        P(_adv(QgsProcessingParameterNumber("PIPE_FRACTION", "Pipe phase: share of the formation time as a pipe",
                                            type=_DOUBLE, defaultValue=0.5, minValue=0.05, maxValue=0.95)))
        P(_adv(QgsProcessingParameterNumber("PIPE_DIA_FT", "Pipe phase: starting pipe diameter (ft)", type=_DOUBLE,
                                            defaultValue=0.5, minValue=0.05)))
        P(QgsProcessingParameterEnum("TIER", "Models", TIERS, defaultValue=0))
        P(QgsProcessingParameterBoolean("FORCE_ANUGA", "Force ANUGA for the final results", defaultValue=False))
        P(QgsProcessingParameterNumber("CELL", "Model cell size (m; 10 m = 32.8 ft default)", type=_DOUBLE,
                                       defaultValue=10.0, minValue=0.5))
        P(_adv(QgsProcessingParameterBoolean("GRID_REFINE", "Finer grid automatically on over-spread (on by "
                                             "default)", defaultValue=True)))
        P(_adv(QgsProcessingParameterNumber("GRID_CHECK_CELL", "Finer grid: check run cell (m; 0 = off)",
                                            type=_DOUBLE, defaultValue=0.0, minValue=0.0)))
        P(QgsProcessingParameterNumber("MANNING", "Manning's n", type=_DOUBLE, defaultValue=0.06, minValue=0.005,
                                       maxValue=1.0))
        P(QgsProcessingParameterNumber("ARRIVAL_FT", "Arrival depth (ft)", type=_DOUBLE, defaultValue=0.1,
                                       minValue=0.01))
        P(QgsProcessingParameterNumber("EDGE_TOL_FT", "Extend the domain while the flood leaves an edge deeper than "
                                       "(ft)", type=_DOUBLE, defaultValue=1.0, minValue=0.01))
        P(_adv(QgsProcessingParameterNumber("OUTFLOW_EXTEND_PCT", "Also extend the edges the water leaves through "
                                            "(under the edge tolerance too) once this % of the breach volume has "
                                            "left the model (0 = off)",
                                            type=_DOUBLE, defaultValue=5.0, minValue=0.0, maxValue=100.0)))
        P(QgsProcessingParameterNumber("LENGTH_MI", "First domain: downstream length (mi)", type=_DOUBLE,
                                       defaultValue=4.0, minValue=0.25))
        P(QgsProcessingParameterNumber("HALF_WIDTH_MI", "First domain: half-width either side of the flow path "
                                       "(mi)", type=_DOUBLE, defaultValue=1.0, minValue=0.1))
        P(_adv(QgsProcessingParameterNumber("STEP_MI", "Extension step (mi)", type=_DOUBLE, defaultValue=3.0,
                                            minValue=0.1)))
        P(QgsProcessingParameterNumber("MAX_EXTENT_MI", "Largest domain side (mi)", type=_DOUBLE, defaultValue=20.0,
                                       minValue=1.0))
        P(_adv(QgsProcessingParameterNumber("MAX_RUNS", "Most LISFLOOD-FP runs", defaultValue=6, minValue=1)))
        P(_adv(QgsProcessingParameterNumber("LISFLOOD_MAX_WALL_S", "LISFLOOD-FP: longest wall-clock time for one "
                                            "run (s; 0 = automatic, 24 h)", type=_DOUBLE, defaultValue=0.0,
                                            minValue=0.0)))
        P(_adv(QgsProcessingParameterNumber("LISFLOOD_MAX_TOTAL_WALL_S", "LISFLOOD-FP: wall-clock budget for all "
                                            "runs (s; 0 = Most LISFLOOD-FP runs x the per-run limit)",
                                            type=_DOUBLE, defaultValue=0.0, minValue=0.0)))
        P(QgsProcessingParameterNumber("DURATION_HR", "Simulation duration (hr), 0 = automatic", type=_DOUBLE,
                                       defaultValue=0.0, minValue=0.0))
        P(QgsProcessingParameterNumber("DURATION_MAX_HR", "Longest simulated time (hr): the clock is lengthened up "
                                       "to this while the flood is still moving", type=_DOUBLE, defaultValue=96.0,
                                       minValue=1.0))
        P(_adv(QgsProcessingParameterNumber("ANUGA_FINE", "ANUGA: largest triangle near the dam (m2)", type=_DOUBLE,
                                            defaultValue=100.0, minValue=1.0)))
        P(_adv(QgsProcessingParameterNumber("ANUGA_COARSE", "ANUGA: largest triangle elsewhere (m2)", type=_DOUBLE,
                                            defaultValue=1000.0, minValue=1.0)))
        P(_adv(QgsProcessingParameterNumber("ANUGA_NEAR_MI", "ANUGA: refined area radius from the dam (mi)",
                                            type=_DOUBLE, defaultValue=1.0, minValue=0.0)))
        P(_adv(QgsProcessingParameterNumber("ANUGA_BUFFER", "ANUGA: mesh margin around the LISFLOOD-FP extent (m)",
                                            type=_DOUBLE, defaultValue=500.0, minValue=0.0)))
        P(_adv(QgsProcessingParameterNumber("THREADS", "Threads (0 = the solver's own)", defaultValue=0,
                                            minValue=0)))
        P(_adv(QgsProcessingParameterString("LISFLOOD_EXE", "LISFLOOD-FP executable (empty = an installed "
                                            "LISFLOOD-FP, else the built-in engine with a warning; 'builtin' = the "
                                            "built-in screening engine, a numpy approximation, NOT LISFLOOD-FP)", defaultValue="", optional=True)))
        P(_adv(QgsProcessingParameterString("ANUGA_PYTHON", "ANUGA Python interpreter (empty = auto-detected)",
                                            defaultValue="", optional=True)))
        P(_adv(QgsProcessingParameterBoolean("KEEP_FILES", "Keep the model input and output files",
                                             defaultValue=True)))
        P(_adv(QgsProcessingParameterBoolean("PRODUCTS", "Write the flood polygons and arrival zones",
                                             defaultValue=True)))
        P(_adv(QgsProcessingParameterString("CONTOURS_HR", "Arrival zones (hours after breach initiation), comma "
                                            "separated", defaultValue="0.25, 0.5, 1, 2, 4, 8", optional=True)))
        P(_adv(QgsProcessingParameterEnum("ENGINE", "Model engine (0.1.0 compatibility; 'From Models' = TIER)",
                                          RD.ENGINE_LABELS, defaultValue=0)))
        self.addOutput(QgsProcessingOutputFolder("RUN_FOLDER", "Run folder"))
        self.addOutput(QgsProcessingOutputString("STATUS", "Status"))
        self.addOutput(QgsProcessingOutputBoolean("READY_TO_RUN", "Ready to run"))
        self.addOutput(QgsProcessingOutputBoolean("MODEL_LAUNCHED", "Model launched"))
        self.addOutput(QgsProcessingOutputString("ENGINE_USED", "Engine"))
        self.addOutput(QgsProcessingOutputBoolean("ENGINE_FALLBACK", "Built-in engine used because no LISFLOOD-FP "
                                                                     "was found"))
        self.addOutput(QgsProcessingOutputString("ENGINE_NOTE", "Engine warning"))
        for name, label in (("DEPTH", "Depth (Max)"), ("VELOCITY", "Velocity (Max)"), ("ARRIVAL", "Arrival Time"),
                            ("WSE", "WSE (Max)"), ("HMAX", "hmax_ft"), ("FLOOD_POLYGONS", "Flood Polygons (Max Depth)"),
                            ("REPORT", "Run report")):
            self.addOutput(QgsProcessingOutputFile(name, label))
        self.addOutput(QgsProcessingOutputFolder("FOLDER", "Dam folder"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        engine = self.parameterAsEnum(params, "ENGINE", context)
        dry = self.parameterAsBool(params, "DRY_RUN", context)
        try:
            RD.refuse_engine(engine, dry)                        # before anything else
            if not dry and self.parameterAsEnum(params, "TIER", context) == 2:
                RD.refuse_engine(RD.ENGINE_HECRAS)
        except RD.RunError as e:
            raise QgsProcessingException(str(e))
        try:
            _, _, HO = CB.modules()
            cat = CB.load_catalog()
        except Exception as e:                                   # noqa
            raise QgsProcessingException(str(e))
        hpath = self.parameterAsFile(params, "HANDOFF", context)
        try:
            if hpath:
                pkg = HO.read(hpath)
            else:
                dam_id = self.parameterAsString(params, "DAM_ID", context)
                if not dam_id:
                    raise RD.RunError("Give a hand-off package or a dam ID")
                dam = {"dam_id": dam_id, "crs": self.parameterAsString(params, "CRS", context) or None,
                       "nid_id": self.parameterAsString(params, "NID_ID", context).strip() or None,
                       "is_new": self.parameterAsBool(params, "IS_NEW", context),
                       "is_sample": self.parameterAsBool(params, "IS_SAMPLE", context)}
                for k, p in (("x", "X"), ("y", "Y"), ("height_ft", "HEIGHT_FT"), ("storage_acft", "STORAGE_ACFT")):
                    if params.get(p) not in (None, ""):
                        dam[k] = self.parameterAsDouble(params, p, context)
                mode = ["preset", "custom"][self.parameterAsEnum(params, "MODE", context)]
                pkg = RD.package_from_params(
                    cat, dam, mode, self.parameterAsString(params, "PRESET", context).strip(),
                    _ids(self.parameterAsString(params, "SCENARIOS", context)),
                    _ids(self.parameterAsString(params, "METHODS", context)),
                    {"terrain": self.parameterAsFile(params, "TERRAIN", context) or None,
                     "hydrograph_csv": self.parameterAsFile(params, "HYDROGRAPH", context) or None})
            out_root = self.parameterAsFile(params, "OUTPUT_FOLDER", context)
            if dry:
                folder, setup = RD.prepare_run(pkg, out_root, cat, engine, dry)
            else:
                values = self._model_values(params, context)
                folder, setup = RD.run_model(pkg, out_root, values, cat,
                                             self.parameterAsFile(params, "DAMS_FOLDER", context) or None,
                                             log=feedback.pushInfo, cancel=feedback.isCanceled)
        except (RD.RunError, HO.HandoffError, ValueError) as e:
            raise QgsProcessingException(str(e))
        if dry:
            feedback.pushInfo("Prepared (DRY_RUN, no model launched): {}".format(folder))
        else:
            feedback.pushInfo("Model run finished ({}): {}".format(setup.get("engine"), folder))
            if setup.get("engine_note"):
                feedback.pushWarning(setup["engine_note"]) if hasattr(feedback, "pushWarning") \
                    else feedback.pushInfo(setup["engine_note"])
        if setup.get("nid_warning"):
            feedback.pushInfo("NID ID: " + setup["nid_warning"])
        for g in setup["gaps"]:
            feedback.pushWarning("not ready to run: missing {}".format(g)) if hasattr(feedback, "pushWarning") \
                else feedback.pushInfo("not ready to run: missing {}".format(g))
        out = {"RUN_FOLDER": folder, "STATUS": setup["status"], "READY_TO_RUN": setup["ready_to_run"],
               "MODEL_LAUNCHED": bool(setup.get("model_launched")), "ENGINE_USED": setup.get("engine") or "none",
               "FOLDER": setup.get("dam_folder"), "ENGINE_FALLBACK": bool(setup.get("engine_fallback")),
               "ENGINE_NOTE": setup.get("engine_note") or ""}
        o = setup.get("outputs") or {}
        for name, key in (("DEPTH", "depth"), ("VELOCITY", "velocity"), ("ARRIVAL", "arrival"), ("WSE", "wse"),
                          ("HMAX", "hmax"), ("FLOOD_POLYGONS", "depth_polygons")):
            out[name] = o.get(key)
        import os
        rep = os.path.join(folder, "run_report.json")
        out["REPORT"] = rep if os.path.isfile(rep) else None
        return out

    def _model_values(self, params, context):
        """The model parameters by their DamSafety names (None = not given)."""
        v = {}
        num = ("X", "Y", "HEIGHT_FT", "STORAGE_ACFT", "TOP_FT", "AREA_AC", "PMF_FT", "BOTTOM_FT", "CREST_WIDTH",
               "US_SLOPE", "DS_SLOPE", "CREST_LENGTH", "PIPE_FRACTION", "PIPE_DIA_FT", "CELL", "GRID_CHECK_CELL",
               "MANNING", "ARRIVAL_FT", "EDGE_TOL_FT", "OUTFLOW_EXTEND_PCT", "LENGTH_MI", "HALF_WIDTH_MI", "STEP_MI",
               "MAX_EXTENT_MI", "LISFLOOD_MAX_WALL_S", "LISFLOOD_MAX_TOTAL_WALL_S", "DURATION_HR",
               "DURATION_MAX_HR", "ANUGA_FINE", "ANUGA_COARSE", "ANUGA_NEAR_MI", "ANUGA_BUFFER")
        for n in num:
            if params.get(n) not in (None, ""):
                v[n] = self.parameterAsDouble(params, n, context)
        for n in ("MAX_RUNS", "THREADS"):
            v[n] = self.parameterAsInt(params, n, context)
        for n in ("METHOD", "TIER", "DEM_Z", "ENGINE"):
            v[n] = self.parameterAsEnum(params, n, context)
        for n in ("FORCE_ANUGA", "GRID_REFINE", "KEEP_FILES", "PRODUCTS"):
            v[n] = self.parameterAsBool(params, n, context)
        for n in ("LISFLOOD_EXE", "ANUGA_PYTHON", "CONTOURS_HR", "CRS", "DAM_ID"):
            v[n] = self.parameterAsString(params, n, context).strip() or None
        for n in ("DEM", "TERRAIN", "USER_CSV", "HYDROGRAPH"):
            v[n] = self.parameterAsFile(params, n, context) or None
        if params.get("INFLOW_POINT") not in (None, ""):
            pt = self.parameterAsPoint(params, "INFLOW_POINT", context)
            crs = self.parameterAsPointCrs(params, "INFLOW_POINT", context)
            wgs = QgsCoordinateReferenceSystem("EPSG:4326")
            if crs.isValid() and crs != wgs:
                pt = QgsCoordinateTransform(crs, wgs, QgsProject.instance()).transform(pt)
            v["INFLOW_LONLAT"] = (pt.x(), pt.y())
        return v


class CheckHandoff(_Base):
    def name(self):
        return "checkhandoff"

    def displayName(self):  # noqa: N802
        return "Check a hand-off package"

    def shortHelpString(self):  # noqa: N802
        return "Validates a damit_handoff.json against the schema and DamIT Catalog and lists what a run still needs. Writes nothing."

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile("HANDOFF", "Hand-off package (damit_handoff.json)",
                                                     behavior=FILE_FILE, fileFilter="DamIT hand-off (*.json)"))
        self.addOutput(QgsProcessingOutputBoolean("VALID", "Valid"))
        self.addOutput(QgsProcessingOutputString("GAPS", "Gaps"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        _, _, HO = CB.modules()
        cat = CB.load_catalog()
        try:
            pkg = HO.read(self.parameterAsFile(params, "HANDOFF", context))
        except HO.HandoffError as e:
            raise QgsProcessingException(str(e))
        errs = HO.validate(pkg, cat, check_paths=True)
        for e in errs:
            feedback.reportError(e)
        gaps = RD.readiness(pkg)
        for g in gaps:
            feedback.pushInfo("gap: " + g)
        return {"VALID": not errs, "GAPS": "; ".join(gaps), "ERRORS": errs}


ALGORITHMS = (RunDam, CheckHandoff)
