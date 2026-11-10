"""damit_run Processing tools: rundam (prepare / record a breach run) and checkhandoff."""
from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputBoolean,
                       QgsProcessingOutputFolder, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFile, QgsProcessingParameterNumber,
                       QgsProcessingParameterString)

from ..qgis_compat import FILE_FILE, FILE_FOLDER
from ..core import catalog_bridge as CB
from ..core import rundam as RD

try:
    from qgis.core import Qgis
    _DOUBLE = Qgis.ProcessingNumberParameterType.Double
except AttributeError:                                           # QGIS < 3.36
    _DOUBLE = QgsProcessingParameterNumber.Double


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
        return "Prepare breach run for one dam"

    def shortHelpString(self):  # noqa: N802
        return ("Takes a damit_handoff.json from damit_screen:handoff (or the dam, preset / custom methods, "
                "scenarios and paths as parameters), checks it against DamIT Catalog and prepares a NEW run "
                "folder: run_setup.json (scenarios, cutoffs, methods, modifiers, label map, paths, catalog "
                "metadata and citations), a copy of the package, README_run.md and the expected-output contract "
                "for DamIT Hazard (damit:classify).\n\nDamIT Runner 0.1.0 is prepare / record only: it never "
                "launches LISFLOOD-FP, ANUGA, HEC-RAS, Wine, ndbreach:rundam or ndbreach:batch. Choosing an engine "
                "or turning DRY_RUN off is refused with an error. Classification is DamIT Hazard's job.\n\n"
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
        P(QgsProcessingParameterEnum("ENGINE", "Model engine", RD.ENGINE_LABELS, defaultValue=0))
        P(QgsProcessingParameterBoolean("DRY_RUN", "Dry run: prepare and record only (no model launch)",
                                        defaultValue=True))
        self.addOutput(QgsProcessingOutputFolder("RUN_FOLDER", "Run folder"))
        self.addOutput(QgsProcessingOutputString("STATUS", "Status"))
        self.addOutput(QgsProcessingOutputBoolean("READY_TO_RUN", "Ready to run"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        engine = self.parameterAsEnum(params, "ENGINE", context)
        dry = self.parameterAsBool(params, "DRY_RUN", context)
        try:
            RD.refuse_engine(engine, dry)                        # before anything else
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
            folder, setup = RD.prepare_run(pkg, self.parameterAsFile(params, "OUTPUT_FOLDER", context), cat,
                                           engine, dry)
        except (RD.RunError, HO.HandoffError, ValueError) as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("Prepared (no model launched): {}".format(folder))
        if setup.get("nid_warning"):
            feedback.pushInfo("NID ID: " + setup["nid_warning"])
        for g in setup["gaps"]:
            feedback.pushWarning("not ready to run: missing {}".format(g)) if hasattr(feedback, "pushWarning") \
                else feedback.pushInfo("not ready to run: missing {}".format(g))
        return {"RUN_FOLDER": folder, "STATUS": setup["status"], "READY_TO_RUN": setup["ready_to_run"]}


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
