"""damit:classify - suggested dam hazard class from existing flood rasters and receptor layers.

Does not run any breach or flood model: the rasters come from a model run elsewhere. The
scenario ID (S1-S7) records which run they are; the preset or the custom list picks the
methods (catalog.json); the output is a GeoPackage of the receptors styled by class and a run
report (Markdown, HTML, JSON).
"""
import json
import os

from qgis.core import (QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsField,
                       QgsFields, QgsGeometry, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingLayerPostProcessorInterface, QgsProcessingOutputNumber,
                       QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFile, QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString,
                       QgsProject, QgsRasterLayer, QgsVectorFileWriter, QgsVectorLayer,
                       QgsProcessingOutputFile)

from .. import compat, styles
from ..engine import catalog as C, core, receptors as R, report, tm11
from ..sampling import rasters as S

SCENARIO_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
DIMS = ["2D", "1D", None]
LAYERS = [("STRUCTURES", "structure", "Structures (outlines or points)", compat.SRC_ANY),
          ("ROADS", "road", "Roads", compat.SRC_LINE),
          ("RAIL", "rail", "Railroads", compat.SRC_LINE),
          ("FACILITIES", "facility", "Critical facilities (points or outlines)", compat.SRC_ANY),
          ("LIFELINES", "lifeline", "Lifelines and utilities", compat.SRC_ANY),
          ("ENVIRONMENT", "environment", "Environmental / cultural features", compat.SRC_ANY)]
RASTERS = [("DEPTH", "depth", "Maximum depth raster", False),
           ("VELOCITY", "velocity", "Maximum velocity raster", True),
           ("DV", "dv", "Maximum depth x velocity raster (optional; else per cell)", True),
           ("WSE", "wse", "Maximum water-surface elevation raster (for floor elevations)", True),
           ("NONBREACH", "nonbreach", "Non-breach depth raster (incremental rise, S5 / D1 / D2)",
            True),
           ("ARRIVAL", "arrival", "Flood-wave arrival time raster (hours)", True)]


def _cat():
    """DamIT Catalog as the classifier reads it (presets, methods and thresholds)."""
    try:
        return C.load()
    except (C.CatalogError, ImportError) as e:
        raise QgsProcessingException("DamIT Catalog could not be read: {}".format(e))


def _ids(text):
    return [x.strip() for x in (text or "").replace(";", ",").split(",") if x.strip()]


def _stat(path, role, note=""):
    try:
        st = os.stat(path.split("|")[0])
        import datetime
        mod = datetime.datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(
            timespec="seconds")
        return {"role": role, "source": path, "modified": mod, "size": st.st_size, "note": note}
    except OSError:
        return {"role": role, "source": path, "modified": None, "size": None, "note": note}


class _Style(QgsProcessingLayerPostProcessorInterface):
    instances = []

    def __init__(self, labels):
        super().__init__()
        self.labels = labels

    def postProcessLayer(self, layer, context, feedback):
        styles.apply(layer, self.labels)


class Classify(QgsProcessingAlgorithm):
    def name(self):
        return "classify"

    def displayName(self):
        return "Classify dam hazard (preset or custom methods)"

    def group(self):
        return ""

    def groupId(self):
        return ""

    def shortHelpString(self):
        return ("Suggests a dam hazard class from EXISTING depth / velocity rasters and receptor "
                "layers, with a jurisdiction preset (scenarios, methods, parameters and labels "
                "from the DamIT Catalog plugin) or with methods you tick (custom: generic labels). "
                "Pick the preset from the list or type its ID in 'Preset ID' (an alias such as "
                "USBR_TM11 for USBR works too; it wins over the list). "
                "It does not run a breach or flood model.<br><br>"
                "Rule-strength results set the suggestion; advisory results are listed beside "
                "it and count only when 'Apply advisory results' is on. Missing inputs are "
                "flagged in the report, never passed silently.<br><br>"
                "Receptor attributes are read by name (type, occupants, floor_elev / "
                "floor_height_ft, aadt, road_class, func_class, sole_access, trains_per_day, "
                "passenger, ...): see the plugin README.<br><br>"
                "Informational screening aid, not a regulatory determination: the engineer of "
                "record and the regulating agency make the determination.")

    def createInstance(self):
        return Classify()

    def initAlgorithm(self, config=None):
        try:
            cat = _cat()
        except QgsProcessingException:          # DamIT Catalog missing: the run explains it
            cat = {"presets": {"FEMA333": {"label": "FEMA 333 baseline"}}, "preset_aliases": {}}
        self.preset_ids = [None] + list(cat["presets"])
        # "ID: label": the ID is visible and tools can pick an option by ID or by label
        choices = ["Custom (methods ticked below)"] + ["{}: {}".format(pid, lab)
                                                      for pid, lab in C.preset_choices(cat)]
        self.addParameter(QgsProcessingParameterEnum(
            "PRESET", "Jurisdiction preset", options=choices,
            defaultValue=self.preset_ids.index("FEMA333")))
        aliases = ", ".join("{} = {}".format(a, t) for a, t in cat.get("preset_aliases", {}).items())
        self.addParameter(QgsProcessingParameterString(
            "PRESET_ID", "Preset ID (overrides the list; {}{})".format(
                ", ".join(cat["presets"]), "; aliases " + aliases if aliases else ""),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterString(
            "METHODS", "Custom: method IDs (e.g. M1,M3,M8a)", optional=True))
        self.addParameter(QgsProcessingParameterString(
            "MODIFIERS", "Custom: modifier IDs (e.g. R1,R3)", optional=True))
        self.addParameter(QgsProcessingParameterString(
            "SCENARIOS", "Custom: scenario / domain IDs expected (e.g. S1,S5,D1)", optional=True))
        self.addParameter(QgsProcessingParameterString(
            "OVERRIDES", "Parameter overrides (JSON: {\"M2\": {\"threshold_ft\": 2.0}})",
            optional=True, multiLine=True))
        self.addParameter(QgsProcessingParameterBoolean(
            "APPLY_ADVISORY", "Apply advisory results to the suggestion", False))
        self.addParameter(QgsProcessingParameterEnum(
            "RUN_SCENARIO", "Scenario of these rasters",
            options=["(the configuration's first scenario)"] + SCENARIO_IDS, defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            "MODEL_DIM", "Model dimensionality", options=["2D", "1D", "Not known"],
            defaultValue=0))
        for key, _role, label, opt in RASTERS:
            self.addParameter(QgsProcessingParameterRasterLayer(key, label, optional=opt))
        self.addParameter(QgsProcessingParameterBoolean(
            "METRES", "Rasters are in metres (m, m/s, m\u00b2/s)", False))
        for key, _kind, label, typ in LAYERS:
            self.addParameter(QgsProcessingParameterFeatureSource(
                key, label, [typ], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            "DOMAIN", "Routed domain polygon (receptors outside are flagged)",
            [compat.SRC_POLYGON], optional=True))
        self.addParameter(QgsProcessingParameterFile(
            "EXTRA_RUNS", "More runs (JSON list: scenario, model_dim, depth, velocity, ...)",
            behavior=compat.FILE_FILE, extension="json", optional=True))
        self.addParameter(QgsProcessingParameterFile(
            "DAM_JSON", "Dam record (JSON: storage_acft, current_class, is_new, ...)",
            behavior=compat.FILE_FILE, extension="json", optional=True))
        self.addParameter(QgsProcessingParameterFile(
            "CHARTS_JSON", "Extra digitized TM-11 charts (JSON)", behavior=compat.FILE_FILE,
            extension="json", optional=True))
        self.addParameter(QgsProcessingParameterString("DAM_NAME", "Dam name", optional=True))
        self.addParameter(QgsProcessingParameterFolderDestination("OUTPUT", "Output folder"))
        self.addOutput(QgsProcessingOutputString("CLASS", "Suggested class (local label)"))
        self.addOutput(QgsProcessingOutputNumber("ORDINAL", "Suggested class (ordinal 0-4)"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Run report (Markdown)"))
        self.addOutput(QgsProcessingOutputFile("GPKG", "Receptors by class (GeoPackage)"))

    # ------------------------------------------------------------------ config -----------
    def _config(self, cat, p, context):
        idx = self.parameterAsEnum(p, "PRESET", context)
        pid = ([None] + list(cat["presets"]))[idx]
        typed = (self.parameterAsString(p, "PRESET_ID", context) or "").strip()
        if typed:
            pid = C.canonical_preset(cat, typed)
            if pid is None:
                raise QgsProcessingException("Unknown preset ID {!r}. Known: {}{}".format(
                    typed, ", ".join(cat["presets"]), "".join(
                        "; {} = {}".format(a, t) for a, t in cat.get("preset_aliases", {}).items())))
        text = self.parameterAsString(p, "OVERRIDES", context).strip()
        try:
            overrides = json.loads(text) if text else {}
        except ValueError as e:
            raise QgsProcessingException("Parameter overrides are not valid JSON: {}".format(e))
        adv = self.parameterAsBool(p, "APPLY_ADVISORY", context)
        if pid:
            return C.preset_config(cat, pid, overrides=overrides, apply_advisory=adv)
        ms = _ids(self.parameterAsString(p, "METHODS", context))
        if not ms:
            raise QgsProcessingException("Custom mode: list the method IDs to run (METHODS).")
        sd = _ids(self.parameterAsString(p, "SCENARIOS", context))
        try:
            return C.custom_config(cat, ms, _ids(self.parameterAsString(p, "MODIFIERS", context)),
                                   [s for s in sd if s.startswith("S")],
                                   [s for s in sd if s.startswith("D")], overrides,
                                   apply_advisory=adv)
        except C.CatalogError as e:
            raise QgsProcessingException(str(e))

    # ---------------------------------------------------------------- receptors ---------
    def _receptors(self, sources, rs, crs, cfg, context, feedback, domain):
        g = cfg["general"]
        f2m = compat.feet_to_map_units(crs)
        if f2m is None:
            raise QgsProcessingException("The depth raster is in a geographic CRS; use a "
                                         "projected CRS (feet or metres).")
        edge, prad, step = g["edge_ring_ft"] * f2m, g["point_radius_ft"] * f2m, \
            g["line_step_ft"] * f2m
        out, geoms = [], {}
        for key, kind, src in sources:
            xf = QgsCoordinateTransform(src.sourceCrs(), crs, context.transformContext())
            names = [f.name() for f in src.fields()]
            areas, lines, attrs = {}, {}, {}
            for feat in src.getFeatures(QgsFeatureRequest()):
                if feedback.isCanceled():
                    raise QgsProcessingException("Cancelled")
                gm = QgsGeometry(feat.geometry())
                if gm.isNull() or gm.isEmpty():
                    continue
                gm.transform(xf)
                rid = "{}:{}".format(kind, feat.id())
                geoms[rid] = (key, feat.geometry(), feat.attributes(), names)
                attrs[rid] = dict(zip(names, feat.attributes()))
                a = attrs[rid]
                if domain is not None and not gm.intersects(domain):
                    a["in_domain"] = False
                gtype = int(getattr(gm.type(), "value", gm.type()))
                if gtype == 1:                       # line
                    dens = gm.densifyByDistance(step)
                    lines[rid] = [(v.x(), v.y()) for v in dens.vertices()]
                elif gtype == 0:                     # point
                    if gm.isMultipart() and len(gm.asMultiPoint()) != 1:
                        gm = gm.centroid()
                    pt = gm.centroid().asPoint()
                    wkb = gm.centroid().asWkb()
                    areas[rid] = (bytes(wkb), (pt.x(), pt.y()), None)
                else:
                    c = gm.centroid().asPoint()
                    areas[rid] = (bytes(gm.asWkb()), (c.x(), c.y()), None)
            hyd = {}
            if areas:
                hyd.update(S.sample_structures(areas, rs, edge, prad))
            if lines:
                hyd.update(S.sample_lines(lines, rs))
            for rid, a in attrs.items():
                r = R.from_attributes(rid, kind, a, hyd.get(rid))
                if a.get("in_domain") is False:
                    r["in_domain"] = False
                out.append(r)
            feedback.pushInfo("{}: {} receptor(s) sampled".format(key.lower(), len(attrs)))
        return out, geoms

    # ------------------------------------------------------------------- main -----------
    def processAlgorithm(self, p, context, feedback):
        cat = _cat()
        cfg = self._config(cat, p, context)
        out_dir = self.parameterAsString(p, "OUTPUT", context)
        os.makedirs(out_dir, exist_ok=True)
        dam = {}
        dam_path = self.parameterAsFile(p, "DAM_JSON", context)
        layers_info = []
        if dam_path:
            with open(dam_path, encoding="utf-8") as f:
                dam = json.load(f)
            layers_info.append(_stat(dam_path, "dam record"))
        name = self.parameterAsString(p, "DAM_NAME", context)
        if name:
            dam["name"] = name
        charts_path = self.parameterAsFile(p, "CHARTS_JSON", context)
        charts = tm11.load(extra=charts_path or None)
        if charts_path:
            layers_info.append(_stat(charts_path, "extra charts"))
        sources = []
        for key, kind, _label, _t in LAYERS:
            src = self.parameterAsSource(p, key, context)
            if src is not None:
                sources.append((key, kind, src))
                lyr = self.parameterAsVectorLayer(p, key, context)
                layers_info.append(_stat(lyr.source() if lyr else key, key.lower(),
                                         "{} features".format(src.featureCount())))
        if not sources:
            raise QgsProcessingException("Give at least one receptor layer (structures, roads, "
                                         "rail, facilities, lifelines or environment).")
        si = self.parameterAsEnum(p, "RUN_SCENARIO", context)
        scen = SCENARIO_IDS[si - 1] if si > 0 else ((cfg["scenarios"] or
                                                      cfg.get("scenarios_any_of") or [None])[0])
        dim = DIMS[self.parameterAsEnum(p, "MODEL_DIM", context)]
        metres = self.parameterAsBool(p, "METRES", context)
        main = {"scenario": scen, "model_dim": dim, "label": "main run", "metres": metres}
        dep_layer = self.parameterAsRasterLayer(p, "DEPTH", context)
        if dep_layer is None:
            raise QgsProcessingException("A maximum depth raster is required.")
        for key, role, _label, _opt in RASTERS:
            lyr = self.parameterAsRasterLayer(p, key, context)
            if lyr is not None:
                main[role] = lyr.source()
        run_specs = [main]
        extra = self.parameterAsFile(p, "EXTRA_RUNS", context)
        if extra:
            with open(extra, encoding="utf-8") as f:
                more = json.load(f)
            base = os.path.dirname(extra)
            for spec in more if isinstance(more, list) else more.get("runs", []):
                spec = dict(spec)
                for _k, role, _l, _o in RASTERS:
                    if spec.get(role) and not os.path.isabs(spec[role]):
                        spec[role] = os.path.join(base, spec[role])
                run_specs.append(spec)
            layers_info.append(_stat(extra, "extra runs"))
        dom_src = self.parameterAsSource(p, "DOMAIN", context)
        runs, geoms, best = [], {}, {}
        for i, spec in enumerate(run_specs):
            paths = {role: spec.get(role) for _k, role, _l, _o in RASTERS}
            if not paths.get("depth"):
                raise QgsProcessingException("run {} has no depth raster".format(i + 1))
            for role, path in paths.items():
                if path:
                    layers_info.append(_stat(path, "{} ({})".format(role, spec.get("scenario")
                                                                    or "run {}".format(i + 1))))
            crs = QgsRasterLayer(paths["depth"], "depth").crs()
            domain = None
            if dom_src is not None:
                xf = QgsCoordinateTransform(dom_src.sourceCrs(), crs, context.transformContext())
                parts = []
                for feat in dom_src.getFeatures():
                    gg = QgsGeometry(feat.geometry())
                    gg.transform(xf)
                    parts.append(gg)
                domain = QgsGeometry.unaryUnion(parts) if parts else None
            rs = S.open_rasters(paths, metres=bool(spec.get("metres", metres)))
            feedback.pushInfo("Run {} ({}, {}): sampling".format(
                i + 1, spec.get("scenario") or "?", spec.get("model_dim") or "?"))
            recs, g = self._receptors(sources, rs, crs, cfg, context, feedback, domain)
            geoms.update(g)
            for r in recs:
                if r.get("depth_ft") is not None and (r["id"] not in best or
                                                      r["depth_ft"] > best[r["id"]]["depth_ft"]):
                    best[r["id"]] = r
                best.setdefault(r["id"], r)
            runs.append({"scenario": spec.get("scenario"), "model_dim": spec.get("model_dim"),
                         "label": spec.get("label") or "run {}".format(i + 1),
                         "breach_location": spec.get("breach_location"),
                         "receptors": recs})
            feedback.setProgress(10 + 60.0 * (i + 1) / len(run_specs))
        res = core.classify(cat, cfg, runs, dam=dam, charts=charts, layers=layers_info)
        # reports
        title = "DamIT Hazard run report" + (" - " + dam["name"] if dam.get("name") else "")
        md = os.path.join(out_dir, "damit_hazard_report.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write(report.markdown(res, cat, title))
        with open(os.path.join(out_dir, "damit_hazard_report.html"), "w", encoding="utf-8") as f:
            f.write(report.html_report(res, cat, title))
        with open(os.path.join(out_dir, "damit_hazard_report.json"), "w", encoding="utf-8") as f:
            f.write(report.as_json(res))
        gpkg = os.path.join(out_dir, "damit_hazard_receptors.gpkg")
        written = self._write_gpkg(gpkg, sources, geoms, best, res, context)
        labels = cfg["labels"]
        for key, kind, _s in sources:
            if key in written and context.project() is not None:
                uri = "{}|layername={}".format(gpkg, key.lower())
                det = context.LayerDetails("DamIT " + key.lower(), context.project(), key.lower())
                post = _Style(labels)
                _Style.instances.append(post)
                det.setPostProcessor(post)
                context.addLayerToLoadOnCompletion(uri, det)
        feedback.pushInfo("Suggested class: {} ({})".format(res["suggested_label"],
                                                            res["generic_label"]))
        for h in res["driving"][:10]:
            feedback.pushInfo("  {} {}: {} [{}]".format(h["method"], labels.get(h["class"]),
                                                        h["reason"], ", ".join(h["receptors"][:5])))
        for fl in res["flags"]:
            if fl["level"] in ("error", "warning"):
                feedback.pushWarning("{} {}: {}{}".format(
                    fl["level"].upper(), fl.get("method") or "", fl["message"],
                    " ({} receptor(s))".format(len(fl["receptors"])) if fl["receptors"] else ""))
        feedback.pushInfo(cat["disclaimer"])
        return {"CLASS": res["suggested_label"], "ORDINAL": res["suggested_class"],
                "REPORT": md, "GPKG": gpkg, "OUTPUT": out_dir}

    def _write_gpkg(self, gpkg, sources, geoms, best, res, context):
        fields = QgsFields()
        for n, t in (("rid", compat.FT_STRING), ("src_fid", compat.FT_INT),
                     ("kind", compat.FT_STRING), ("type", compat.FT_STRING),
                     ("class", compat.FT_INT), ("label", compat.FT_STRING),
                     ("adv_class", compat.FT_INT), ("methods", compat.FT_STRING),
                     ("depth_ft", compat.FT_DOUBLE), ("vel_fps", compat.FT_DOUBLE),
                     ("dv_ft2s", compat.FT_DOUBLE), ("rise_ft", compat.FT_DOUBLE),
                     ("flags", compat.FT_STRING), ("sampling", compat.FT_STRING)):
            fields.append(QgsField(n, t))
        labels = res["config"]["labels"]
        written, first = set(), True
        for key, kind, src in sources:
            wkb = src.wkbType()
            from qgis.core import QgsWkbTypes
            mem = QgsVectorLayer("{}?crs={}".format(QgsWkbTypes.displayString(wkb),
                                                    src.sourceCrs().authid()), key, "memory")
            prov = mem.dataProvider()
            prov.addAttributes(fields.toList())
            mem.updateFields()
            feats = []
            for rid, (k, geom, _a, _n) in geoms.items():
                if k != key:
                    continue
                r = best.get(rid, {})
                pr = res["per_receptor"].get(rid, {})
                cls = pr.get("rule") if pr.get("rule") is not None else -1
                f = QgsFeature(mem.fields())
                f.setGeometry(geom)
                f.setAttributes([rid, int(rid.split(":")[1]), kind, r.get("type"), cls,
                                 labels.get(cls, "No hit"), pr.get("advisory"),
                                 ",".join(sorted(pr.get("methods", []))), r.get("depth_ft"),
                                 r.get("velocity_fps"), r.get("dv_ft2s"), r.get("rise_ft"),
                                 ",".join(sorted(set(res["receptor_flags"].get(rid, [])))),
                                 r.get("sampling")])
                feats.append(f)
            prov.addFeatures(feats)
            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = "GPKG"
            opts.layerName = key.lower()
            opts.actionOnExistingFile = compat.OVERWRITE_FILE if first else compat.OVERWRITE_LAYER
            err = QgsVectorFileWriter.writeAsVectorFormatV3(mem, gpkg, context.transformContext(),
                                                            opts)
            if err[0] != compat.WRITER_NO_ERROR:
                raise QgsProcessingException("Writing {}: {}".format(gpkg, err[1]))
            first = False
            written.add(key)
        return written
