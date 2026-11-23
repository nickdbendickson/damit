"""Catalog-driven Hazard tools (DamIT Hazard 0.4.9).

Each tool calls the Catalog engine or a raster import. None of them applies a state rule,
and none of them lowers a class that DamIT already published. QGIS is imported here, so
the pure-Python tests do not import this module.
"""
import json
import os

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingOutputNumber, QgsProcessingOutputString,
                       QgsProcessingParameterFile, QgsProcessingParameterNumber,
                       QgsProcessingParameterString)

from .. import compat


def _folder_behavior():
    try:
        from qgis.core import Qgis
        return Qgis.ProcessingFileParameterBehavior.Folder
    except Exception:
        return QgsProcessingParameterFile.Folder


def _file(name, label, optional=False, ext=None):
    kw = {}
    if ext:
        kw["extension"] = ext
    return QgsProcessingParameterFile(name, label, behavior=compat.FILE_FILE, optional=optional, **kw)


def _dir(name, label, optional=False):
    return QgsProcessingParameterFile(name, label, behavior=_folder_behavior(), optional=optional)


class _Tool(QgsProcessingAlgorithm):
    def group(self):
        return "Catalog tools"

    def groupId(self):
        return "catalog"

    def createInstance(self):
        return self.__class__()

    def _text(self, parameters, name, context):
        return (self.parameterAsString(parameters, name, context) or "").strip()

    def _path(self, parameters, name, context):
        return self.parameterAsFile(parameters, name, context) or ""


class RasImport(_Tool):
    def name(self):
        return "rasimport"

    def displayName(self):
        return "Import a HEC-RAS plan as depth, velocity, arrival and water surface"

    def shortHelpString(self):
        return ("Reads a HEC-RAS 6 plan HDF and writes Depth, Velocity, Arrival and WSE "
                "GeoTIFFs. A terrain raster makes depth as water surface minus terrain. "
                "Without one, a DamIT Runner terrain re-export of the same plan is used "
                "when DAM_FOLDER has one; otherwise depth is the cell minimum. "
                "DEPTH_BASIS may be terrain, runner_reexport or cell_min. "
                "This tool does not classify. The chain calls it as damit:rasimport.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("PLAN", "HEC-RAS plan HDF"))
        self.addParameter(_file("TERRAIN", "Terrain GeoTIFF (optional)", optional=True))
        self.addParameter(_dir("DAM_FOLDER", "Dam folder (Runner re-export search)", optional=True))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addParameter(QgsProcessingParameterString(
            "DEPTH_BASIS", "Depth basis (terrain, runner_reexport or cell_min; empty = from the inputs)",
            optional=True, defaultValue=""))
        for name, label in (("DEPTH", "Depth raster"), ("VELOCITY", "Velocity raster"),
                            ("ARRIVAL", "Arrival raster"), ("WSE", "Water-surface raster")):
            self.addOutput(QgsProcessingOutputFile(name, label))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import rasimport as RI
        plan = self._path(parameters, "PLAN", context)
        if not plan or not os.path.isfile(plan):
            raise QgsProcessingException("Plan HDF not found: {}".format(plan or "(none)"))
        out = self._path(parameters, "OUTPUT", context) or self._text(parameters, "OUTPUT", context)
        if not out:
            raise QgsProcessingException("Give an output folder")
        os.makedirs(out, exist_ok=True)
        terrain = self._path(parameters, "TERRAIN", context) or None
        dam = self._path(parameters, "DAM_FOLDER", context) or None
        basis = self._text(parameters, "DEPTH_BASIS", context).lower().replace("-", "_")
        use_runner = True
        if basis in ("cell_min", "cellmin"):
            terrain, use_runner = None, False
        elif basis in ("runner_reexport", "runner"):
            terrain = None
        try:
            res = RI.import_plan(plan, out, dem_path=terrain or None,
                                 runner_dirs=[dam] if dam else None, use_runner=use_runner)
        except RI.RasImportError as e:
            raise QgsProcessingException(str(e))
        paths = res.get("paths") or {}
        for line in res.get("lines") or []:
            feedback.pushInfo(str(line))
        for note in res.get("notes") or []:
            feedback.pushInfo(str(note))
        return {"DEPTH": paths.get("depth") or "", "VELOCITY": paths.get("vel") or "",
                "ARRIVAL": paths.get("arr") or "", "WSE": paths.get("wse") or ""}


class DsswiseImport(_Tool):
    def name(self):
        return "dsswise"

    def displayName(self):
        return "Import DSS-WISE Lite results"

    def shortHelpString(self):
        return ("Reads a DSS-WISE Lite results package (a folder or a zip) and writes depth, "
                "velocity, arrival and water-surface GeoTIFFs in feet, feet per second and hours. "
                "Roles come from the file names. This tool does not classify.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("PACKAGE", "DSS-WISE Lite package (folder or zip)"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        for name, label in (("DEPTH", "Depth raster"), ("VELOCITY", "Velocity raster"),
                            ("ARRIVAL", "Arrival raster"), ("WSE", "Water-surface raster"),
                            ("SUMMARY", "Import summary")):
            self.addOutput(QgsProcessingOutputFile(name, label))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import dsswise as DW
        package = self._path(parameters, "PACKAGE", context)
        out = self._path(parameters, "OUTPUT", context)
        if not package or not os.path.exists(package):
            raise QgsProcessingException("Package not found: {}".format(package or "(none)"))
        if not out:
            raise QgsProcessingException("Give an output folder")
        work = out
        if os.path.isfile(package):
            work = os.path.join(out, "_package")
            os.makedirs(work, exist_ok=True)
            unpacked = DW.open_package(package, work)
        else:
            unpacked = package
        items = DW.scan(unpacked)
        try:
            res = DW.convert(items, out)
        except RuntimeError as e:
            raise QgsProcessingException(str(e))
        paths = res.get("paths") or {}
        for line in (res.get("lines") or []) + (res.get("notes") or []):
            feedback.pushInfo(str(line))
        summary = os.path.join(out, "DSSWISE_Import_Summary.txt")
        return {"DEPTH": paths.get(DW.R_DEPTH) or "", "VELOCITY": paths.get(DW.R_VEL) or "",
                "ARRIVAL": paths.get(DW.R_ARR) or "", "WSE": paths.get(DW.R_WSE) or "",
                "SUMMARY": summary if os.path.isfile(summary) else ""}


class BatchClassify(_Tool):
    def name(self):
        return "batch"

    def displayName(self):
        return "Classify a folder of dams"

    def shortHelpString(self):
        return ("Classifies every JSON receptor record in a folder with one Catalog preset. "
                "Each file is one dam ({receptors, dam, scenario}). One dam's class is not "
                "copied onto another. This does not lower a class: each result is that dam's "
                "own Catalog class.")

    def initAlgorithm(self, config=None):
        self.addParameter(_dir("DAMS_FOLDER", "Folder of <dam id>.json receptor records"))
        self.addParameter(QgsProcessingParameterString("PRESET_ID", "Catalog preset ID", defaultValue="USBR"))
        self.addOutput(QgsProcessingOutputFile("SUMMARY", "Batch summary JSON"))
        self.addOutput(QgsProcessingOutputString("CLASSES", "dam id = class, one per line"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import batchcls, catalog as C
        folder = self._path(parameters, "DAMS_FOLDER", context)
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException("Folder not found: {}".format(folder or "(none)"))
        try:
            cat = C.load()
            cfg = C.preset_config(cat, self._text(parameters, "PRESET_ID", context) or "USBR")
        except (C.CatalogError, ImportError) as e:
            raise QgsProcessingException("DamIT Catalog could not be read: {}".format(e))
        rows = batchcls.classify_directory(cat, cfg, folder)
        out = os.path.join(folder, "damit_batch_classes.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
        lines = ["{} = {} ({})".format(r["id"], r["suggested_class"], r["suggested_label"]) for r in rows]
        for line in lines:
            feedback.pushInfo(line)
        return {"SUMMARY": out, "CLASSES": "\n".join(lines)}


class Ensemble(_Tool):
    def name(self):
        return "ensemble"

    def displayName(self):
        return "Hazard class probability from an ensemble of breach runs"

    def shortHelpString(self):
        return ("Reads run folders. A run with status \"no breach\" is its own outcome and is "
                "not dropped. Every probability is over all runs, and P(class | breach) is "
                "beside it. The governing class is the highest class among the breach runs. "
                "A no-breach run cannot lower it. Classes already stored on run.json are used; "
                "this tool does not reclassify from ND rules. Each run's result is written "
                "under <output>/ensemble/<run id>/.")

    def initAlgorithm(self, config=None):
        self.addParameter(_dir("ENSEMBLE_FOLDER", "Ensemble folder (run sub-folders, or a Runs folder)"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addParameter(QgsProcessingParameterNumber("MAX_RUNS", "Largest number of runs",
                                                       defaultValue=200, minValue=1))
        self.addOutput(QgsProcessingOutputFile("CSV", "Class_Probability.csv"))
        self.addOutput(QgsProcessingOutputString("SUMMARY", "One-line summary"))
        self.addOutput(QgsProcessingOutputNumber("GOVERNING_CLASS", "Highest breach-run class"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import ensemble as EN
        folder = self._path(parameters, "ENSEMBLE_FOLDER", context)
        out = self._path(parameters, "OUTPUT", context)
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException("Ensemble folder not found")
        if not out:
            raise QgsProcessingException("Give an output folder")
        runs = EN.find_runs(folder, max_runs=int(self.parameterAsDouble(parameters, "MAX_RUNS", context) or 200))
        agg = EN.aggregate(runs)
        csv_path = EN.write_distribution(out, agg, runs)
        text = EN.summary_line(agg)
        feedback.pushInfo(text)
        gov = agg["governing_class"]
        return {"CSV": csv_path, "SUMMARY": text, "GOVERNING_CLASS": -1 if gov is None else int(gov)}


class Submittal(_Tool):
    def name(self):
        return "submittal"

    def displayName(self):
        return "Build a submittal package"

    def shortHelpString(self):
        return ("Zips the classify report files in a folder and writes MANIFEST.csv of their "
                "SHA-256. No form number is added. The class is not changed.")

    def initAlgorithm(self, config=None):
        self.addParameter(_dir("DAM_FOLDER", "Folder that holds the classify reports"))
        self.addParameter(QgsProcessingParameterFile("OUTPUT", "Output zip", behavior=compat.FILE_FILE))
        self.addOutput(QgsProcessingOutputFile("PACKAGE", "Submittal zip"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import submittal as SB
        folder = self._path(parameters, "DAM_FOLDER", context)
        out = self._path(parameters, "OUTPUT", context) or self._text(parameters, "OUTPUT", context)
        if not out:
            out = os.path.join(folder, "submittal.zip")
        try:
            res = SB.build_package(folder, out)
        except ValueError as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("packaged {} file(s)".format(len(res["files"])))
        return {"PACKAGE": res["zip"]}


class ReviewPackage(_Tool):
    def name(self):
        return "reviewpackage"

    def displayName(self):
        return "Review a submittal package"

    def shortHelpString(self):
        return ("Checks a package folder or zip against MANIFEST.csv. A mismatch is reported. "
                "The class is not changed.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("PACKAGE", "Package folder or zip"))
        self.addOutput(QgsProcessingOutputString("SUMMARY", "Review summary"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Review JSON"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import submittal as SB
        package = self._path(parameters, "PACKAGE", context)
        try:
            res = SB.verify_package(package)
        except ValueError as e:
            raise QgsProcessingException(str(e))
        text = "package ok" if res["ok"] else "package mismatch: {}".format(
            ", ".join(m["name"] for m in res["mismatches"]))
        feedback.pushInfo(text)
        report = os.path.join(package if os.path.isdir(package) else os.path.dirname(package),
                              "package_review.json")
        try:
            with open(report, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=1)
        except OSError:
            report = ""
        return {"SUMMARY": text, "REPORT": report}


class Checklist(_Tool):
    def name(self):
        return "checklist"

    def displayName(self):
        return "Summarize a filled review checklist"

    def shortHelpString(self):
        return ("Reads a CSV with Item and Answer (yes, no, na). A no is an open item. "
                "The summary is not a class and does not change one.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("CSV", "Checklist CSV", ext="csv"))
        self.addOutput(QgsProcessingOutputString("SUMMARY", "Open-item summary"))
        self.addOutput(QgsProcessingOutputNumber("OPEN_ITEMS", "Open items"))

    def processAlgorithm(self, parameters, context, feedback):
        import csv
        from ..engine import submittal as SB
        path = self._path(parameters, "CSV", context)
        if not path or not os.path.isfile(path):
            raise QgsProcessingException("Checklist not found")
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        res = SB.summarize_checklist(rows)
        text = "{} open item(s) of {}".format(res["n_open"], len(rows))
        feedback.pushInfo(text)
        return {"SUMMARY": text, "OPEN_ITEMS": res["n_open"]}


class Reproduce(_Tool):
    def name(self):
        return "reproduce"

    def displayName(self):
        return "Reproduce a past classification"

    def shortHelpString(self):
        return ("Reclassifies a saved receptor JSON with the same preset and publishes the "
                "higher of the saved class and the new class. A lower recompute is a review "
                "flag only. The published class is never lower than the saved class.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("RECORD", "Saved record JSON (receptors, preset_id, suggested_class)"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addOutput(QgsProcessingOutputNumber("PUBLISHED_CLASS", "Published class (never lower)"))
        self.addOutput(QgsProcessingOutputString("SUMMARY", "What changed"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Comparison JSON"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import batchcls, catalog as C, reproduce as RP
        path = self._path(parameters, "RECORD", context)
        out = self._path(parameters, "OUTPUT", context)
        if not path or not os.path.isfile(path):
            raise QgsProcessingException("Record not found")
        if not out:
            raise QgsProcessingException("Give an output folder")
        rec = batchcls.load_record(path)
        saved = rec.get("suggested_class")
        try:
            cat = C.load()
            cfg = C.preset_config(cat, rec.get("preset_id") or "USBR")
        except (C.CatalogError, ImportError) as e:
            raise QgsProcessingException("DamIT Catalog could not be read: {}".format(e))
        fresh = batchcls.classify_one(cat, cfg, rec.get("receptors") or [], dam=rec.get("dam") or {},
                                      scenario=rec.get("scenario") or "S1",
                                      dim=rec.get("model_dim") or "2D")
        cmp_ = RP.compare(saved, fresh["suggested_class"])
        os.makedirs(out, exist_ok=True)
        report = os.path.join(out, "reproduce.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump({"comparison": cmp_, "recomputed_label": fresh["suggested_label"]}, fh, indent=1)
        feedback.pushInfo(cmp_["note"])
        return {"PUBLISHED_CLASS": int(cmp_["published_class"]), "SUMMARY": cmp_["note"],
                "REPORT": report}


class MarkReviewed(_Tool):
    def name(self):
        return "markreviewed"

    def displayName(self):
        return "Mark the classification reviewed"

    def shortHelpString(self):
        return ("Records a review on dam.json under hazard_review. Class fields already in "
                "the file are written back unchanged, and no class field is added. "
                "An empty reviewer (the chain passes only the dam folder) stores a production "
                "stamp, not an acceptance. Returned does not lower the class.")

    def initAlgorithm(self, config=None):
        self.addParameter(_dir("DAM_FOLDER", "Dam folder"))
        self.addParameter(QgsProcessingParameterString("REVIEWER", "Reviewer", optional=True, defaultValue=""))
        self.addParameter(QgsProcessingParameterString("DECISION", "Decision", optional=True, defaultValue=""))
        self.addParameter(QgsProcessingParameterString("COMMENTS", "Comments", optional=True, defaultValue=""))
        self.addParameter(_file("PACKAGE", "Submittal package (optional)", optional=True))
        self.addParameter(QgsProcessingParameterNumber("OPEN_ITEMS", "Open items", optional=True, defaultValue=0))
        self.addOutput(QgsProcessingOutputFile("DAM_JSON", "dam.json"))
        self.addOutput(QgsProcessingOutputString("SUMMARY", "What was recorded"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import markreviewed as MR
        folder = self._path(parameters, "DAM_FOLDER", context)
        try:
            res = MR.mark_reviewed(folder, self._text(parameters, "REVIEWER", context),
                                   self._text(parameters, "DECISION", context) or None,
                                   comments=self._text(parameters, "COMMENTS", context),
                                   package=self._path(parameters, "PACKAGE", context) or None,
                                   open_items=int(self.parameterAsDouble(parameters, "OPEN_ITEMS", context) or 0))
        except (ValueError, OSError) as e:
            raise QgsProcessingException(str(e))
        entry = res["review"]
        text = "mark {} by {} (class not changed)".format(entry.get("decision") or entry.get("mark"),
                                                         entry.get("reviewer") or "(none)")
        feedback.pushInfo(text)
        return {"DAM_JSON": res["dam_json"], "SUMMARY": text}


class ModelGate(_Tool):
    def name(self):
        return "modelgate"

    def displayName(self):
        return "Model gate (checks of the flood rasters)"

    def shortHelpString(self):
        return ("Checks a depth GeoTIFF: wet cells on the outer edge, and interior no-data "
                "gaps with water on both sides. The result is PASS, WARN, FAIL or SKIP. "
                "It is not a class and it does not change one. Needs GDAL.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("DEPTH", "Depth GeoTIFF"))
        self.addParameter(_file("VELOCITY", "Velocity GeoTIFF", optional=True))
        self.addParameter(_dir("OUTPUT", "Output folder", optional=True))
        self.addOutput(QgsProcessingOutputString("STATUS", "PASS, WARN, FAIL or SKIP"))
        self.addOutput(QgsProcessingOutputFile("CSV", "Model gate CSV"))

    def processAlgorithm(self, parameters, context, feedback):
        import csv
        from ..engine import modelgate as MG
        depth = self._path(parameters, "DEPTH", context)
        if not depth or not os.path.isfile(depth):
            raise QgsProcessingException("Depth raster not found")
        try:
            from osgeo import gdal
        except ImportError as e:
            raise QgsProcessingException("GDAL is required to read the raster: {}".format(e))
        ds = gdal.Open(depth)
        if ds is None:
            raise QgsProcessingException("cannot open {}".format(depth))
        arr = ds.GetRasterBand(1).ReadAsArray()
        nd = ds.GetRasterBand(1).GetNoDataValue()
        ds = None
        import numpy as np
        a = np.asarray(arr, dtype=float)
        if nd is not None:
            a = np.where(a == nd, np.nan, a)
        vel = None
        vp = self._path(parameters, "VELOCITY", context)
        if vp and os.path.isfile(vp):
            vs = gdal.Open(vp)
            if vs is not None:
                vel = vs.GetRasterBand(1).ReadAsArray()
                vs = None
        res = MG.gate_arrays(a, vel)
        out = self._path(parameters, "OUTPUT", context) or os.path.dirname(depth)
        os.makedirs(out, exist_ok=True)
        csv_path = os.path.join(out, "Model_Gate.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Check", "Status", "Reason"])
            for row in res["rows"]:
                w.writerow([row["check"], row["status"], row["reason"]])
        feedback.pushInfo(res["status"])
        return {"STATUS": res["status"], "CSV": csv_path}


class Series(_Tool):
    def name(self):
        return "series"

    def displayName(self):
        return "Dams in series screen"

    def shortHelpString(self):
        return ("Reads a JSON list of dams {id, suggested_class, reaches}. reaches lists "
                "downstream dam ids that are wet in this dam's depth. Those dams are flagged. "
                "No class is changed.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("DAMS_JSON", "Dams JSON", ext="json"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Series report JSON"))
        self.addOutput(QgsProcessingOutputNumber("FLAGGED", "Dams flagged"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import series as SR
        path = self._path(parameters, "DAMS_JSON", context)
        out = self._path(parameters, "OUTPUT", context)
        with open(path, encoding="utf-8") as fh:
            dams = json.load(fh)
        res = SR.screen(dams)
        os.makedirs(out, exist_ok=True)
        report = os.path.join(out, "dams_in_series.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        feedback.pushInfo("{} dam(s) flagged; classes unchanged".format(res["n_flagged"]))
        return {"REPORT": report, "FLAGGED": res["n_flagged"]}


class Portfolio(_Tool):
    def name(self):
        return "portfolio"

    def displayName(self):
        return "Portfolio dashboard"

    def shortHelpString(self):
        return ("Reads a JSON list of stored reports {dam_id, suggested_class, suggested_label}. "
                "It does not reclassify. If one dam has two stored classes, the row shows the "
                "higher one and flags the disagreement.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("REPORTS_JSON", "Reports JSON", ext="json"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("TABLE", "Portfolio JSON"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import portfolio as PF
        path = self._path(parameters, "REPORTS_JSON", context)
        out = self._path(parameters, "OUTPUT", context)
        with open(path, encoding="utf-8") as fh:
            reports = json.load(fh)
        res = PF.rows_from_reports(reports)
        os.makedirs(out, exist_ok=True)
        table = os.path.join(out, "portfolio.json")
        with open(table, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        feedback.pushInfo("{} dam(s)".format(len(res["dams"])))
        return {"TABLE": table}


class _CreepBase(_Tool):
    def _run(self, parameters, context, feedback):
        from ..engine import creep as CR
        path = self._path(parameters, "SAMPLES_JSON", context)
        out = self._path(parameters, "OUTPUT", context)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        threshold = float(self.parameterAsDouble(parameters, "THRESHOLD_FT", context) or 0.0)
        if isinstance(data, dict) and "stored" in data:
            res = CR.watch(data.get("stored") or [], data.get("new") or [], threshold)
        else:
            res = CR.depth_change(data, threshold)
        os.makedirs(out, exist_ok=True)
        report = os.path.join(out, self.name() + ".json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        feedback.pushInfo("{} increased; no class computed".format(res["n_increased"]))
        return {"REPORT": report, "INCREASED": res["n_increased"]}


class Creep(_CreepBase):
    def name(self):
        return "creep"

    def displayName(self):
        return "Creep watch"

    def shortHelpString(self):
        return ("Compares a stored depth sample with a later one (JSON: a list of "
                "{id, depth_before_ft, depth_after_ft}, or {stored, new}). "
                "A rise above the threshold is a review row. No class is computed.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("SAMPLES_JSON", "Samples JSON", ext="json"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addParameter(QgsProcessingParameterNumber("THRESHOLD_FT", "Rise to flag, feet", defaultValue=0.0))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Creep report"))
        self.addOutput(QgsProcessingOutputNumber("INCREASED", "Rows that rose"))

    def processAlgorithm(self, parameters, context, feedback):
        return self._run(parameters, context, feedback)


class QuickCreep(_CreepBase):
    def name(self):
        return "quickcreep"

    def displayName(self):
        return "Quick creep screen"

    def shortHelpString(self):
        return ("The same depth comparison as creep watch, for one new sample and no model "
                "re-run. A rise is a review row. No class is computed.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("SAMPLES_JSON", "Samples JSON", ext="json"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addParameter(QgsProcessingParameterNumber("THRESHOLD_FT", "Rise to flag, feet", defaultValue=0.0))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Quick creep report"))
        self.addOutput(QgsProcessingOutputNumber("INCREASED", "Rows that rose"))

    def processAlgorithm(self, parameters, context, feedback):
        return self._run(parameters, context, feedback)


class FormFill(_Tool):
    def name(self):
        return "formfill"

    def displayName(self):
        return "Fill a form template"

    def shortHelpString(self):
        return ("Replaces {{field}} in a template from a JSON object of the same names. "
                "A name that is not in the JSON is left as written. There is no built-in "
                "state form. This does not classify.")

    def initAlgorithm(self, config=None):
        self.addParameter(_file("TEMPLATE", "Template file"))
        self.addParameter(_file("FIELDS", "Fields JSON", ext="json"))
        self.addParameter(_dir("OUTPUT", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("FILLED", "Filled text"))
        self.addOutput(QgsProcessingOutputString("MISSING", "Placeholders left as written"))

    def processAlgorithm(self, parameters, context, feedback):
        from ..engine import formfill as FF
        template = self._path(parameters, "TEMPLATE", context)
        fields = self._path(parameters, "FIELDS", context)
        out = self._path(parameters, "OUTPUT", context)
        with open(template, encoding="utf-8") as fh:
            text = fh.read()
        with open(fields, encoding="utf-8") as fh:
            data = json.load(fh)
        filled, missing = FF.fill(text, data)
        os.makedirs(out, exist_ok=True)
        dest = os.path.join(out, "filled.txt")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(filled)
        feedback.pushInfo("left as written: {}".format(", ".join(missing) or "(none)"))
        return {"FILLED": dest, "MISSING": ", ".join(missing)}


ALGORITHMS = (RasImport, DsswiseImport, BatchClassify, Ensemble, Submittal, ReviewPackage,
              Checklist, Reproduce, MarkReviewed, ModelGate, Series, Portfolio, Creep,
              QuickCreep, FormFill)
