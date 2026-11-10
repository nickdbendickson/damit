"""The damit_screen Processing tools."""
import os

from qgis.core import (QgsProcessingException, QgsProcessingOutputBoolean, QgsProcessingOutputFile,
                       QgsProcessingOutputNumber, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterFileDestination)

from ..core import steps as ST
from ..core import workflow as WF
from . import _common as C


class Preflight(C.DamitAlgorithm):
    _name, _display = "preflight", "Preflight check"
    needs_dams = False
    _help = ("Checks, in seconds, what would make the screening fail or silently skip a step: work folder and "
             "disk, DamIT Catalog, preset / custom selection and its catalog flags (unverified, secondary, "
             "dash -> M13 fallback, scenario unconfirmed), the dams layer and the fields each chosen scenario "
             "needs, terrain, and whether the receptor layer carries the fields the enabled methods read. "
             "Missing inputs are WARN or FAIL, never passed. damit_screen:runchain refuses to start on a FAIL.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.add_common()
        self.addParameter(QgsProcessingParameterFileDestination("REPORT", "Preflight report (text)",
                                                                fileFilter="Text (*.txt)", optional=True))
        self.addOutput(QgsProcessingOutputBoolean("READY", "Ready (no FAIL)"))
        self.addOutput(QgsProcessingOutputNumber("FAILS", "FAIL count"))
        self.addOutput(QgsProcessingOutputNumber("WARNINGS", "WARN count"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        work, s, dams, problems, recs, rnames = self.gather(params, context)
        checks, _, _ = WF.preflight(work, s, dams, problems, recs, rnames,
                                    C.disk_free_mb(work) if work else None)
        lines = WF.report_lines(checks)
        for ln in lines:
            feedback.pushInfo(ln)
        rep = self.parameterAsFileOutput(params, "REPORT", context) or ""
        if rep and rep.upper() != "TEMPORARY_OUTPUT":
            os.makedirs(os.path.dirname(rep) or ".", exist_ok=True)
            with open(rep, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        return {"READY": WF.ready(checks), "FAILS": sum(c["status"] == WF.FAIL for c in checks),
                "WARNINGS": sum(c["status"] == WF.WARN for c in checks), "REPORT": rep,
                "CHECKS": checks}


class RunChain(C.DamitAlgorithm):
    _name, _display = "runchain", "Run the screening chain (headless)"
    _help = ("Runs the preflight, then every dam (or the dam_ids in the settings) through: prepare, terrain, "
             "storage at each selected scenario's pool (S-codes from the preset or your choice), breach "
             "direction, hydrograph, triage (M13 presence screen), 2D screening flood (built-in "
             "engine, in this process), preliminary suggestion from the catalog when receptor hydraulics exist, and a "
             "damit_handoff.json per dam for damit_run:rundam. A preflight FAIL refuses the run.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.add_common()
        self.addParameter(QgsProcessingParameterBoolean("PREFLIGHT", "Refuse to start on a preflight FAIL",
                                                        defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean("FAIL_ON_ERROR", "Fail the tool when the chain fails",
                                                        defaultValue=True))
        self.addOutput(QgsProcessingOutputBoolean("OK", "Chain finished"))
        self.addOutput(QgsProcessingOutputNumber("DAMS", "Dams screened"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Run report"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        work, s, dams, problems, recs, rnames = self.gather(params, context)
        if not work:
            raise QgsProcessingException("Work folder: none given")
        summ = WF.run_chain(work, s, dams or [], problems, recs, rnames,
                            C.terrain_info(s.get("terrain")),
                            do_preflight=self.parameterAsBool(params, "PREFLIGHT", context),
                            log=feedback.pushInfo, cancel=feedback.isCanceled)
        if not summ["ok"] and self.parameterAsBool(params, "FAIL_ON_ERROR", context):
            raise QgsProcessingException("Screening chain {}: see the log".format(
                "refused by the preflight" if summ.get("refused") else "failed"))
        return {"OK": summ["ok"], "DAMS": len(summ["dams"]), "REPORT": summ.get("report", ""),
                "HANDOFFS": [r.get("handoff_path") for r in summ["dams"].values() if r.get("handoff_path")]}


class _OneStep(C.DamitAlgorithm):
    """Runs one screening step for every dam and writes <work>/dams/<id>/<step>.json."""
    step_key = ""

    def initAlgorithm(self, config=None):  # noqa: N802
        self.add_common()
        self.addOutput(QgsProcessingOutputNumber("COUNT", "Dams"))
        self.addOutput(QgsProcessingOutputNumber("GAPS", "Dams with a gap or failure"))

    def run_step(self, cat, config, dam, s, recs):
        raise NotImplementedError

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        work, s, dams, problems, recs, rnames = self.gather(params, context)
        self._work, self._feedback = work, feedback
        for p in problems:
            feedback.reportError(p)
        checks, cat, config = WF.preflight(work, s, dams, problems, recs, rnames)
        if cat is None or config is None:
            raise QgsProcessingException("; ".join(c["detail"] for c in checks if c["status"] == WF.FAIL))
        gaps = 0
        for d in dams or []:
            r = self.run_step(cat, config, d, s, recs)
            C.dump(os.path.join(WF.dam_folder(work, d["dam_id"]), self.step_key + ".json"), r)
            if r["status"] != ST.STATUS_OK:
                gaps += 1
            feedback.pushInfo("{} {}: {}".format(d["dam_id"], r["status"].upper(), r["detail"]))
        return {"COUNT": len(dams or []), "GAPS": gaps}


class Prepare(_OneStep):
    _name, _display, step_key = "prepare", "Prepare dam inventory", "prepare"
    _help = ("Maps the dam layer's fields onto DamIT dam fields (FIELD_MAP, e.g. dam_id=NIDID,"
             "height_ft=MAX_HT) and checks ids, duplicates and numbers. Writes <work>/damit_screen/dams.json.\n\n"
             "The dam inventory is the USACE National Inventory of Dams (NID): every dam needs an NID ID "
             "(dam_id = the NID ID, e.g. ND00199, or a nid_id field). A DWR-, DUG- or other non-NID id is a "
             "problem; only a new / proposed dam (is_new, or new_or_existing = new) or a desk sample (is_sample) "
             "may have none, recorded as a gap.")

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        work, s, dams, problems, _, _ = self.gather(params, context)
        for p in problems:
            feedback.reportError(p)
        path = C.dump(os.path.join(work, "damit_screen", "dams.json"), {"dams": dams or [], "problems": problems})
        return {"COUNT": len(dams or []), "GAPS": len(problems), "OUTPUT": path}


class Terrain(_OneStep):
    _name, _display, step_key = "terrain", "Terrain (record and check DEM)", "terrain"
    _help = "Records the DEM for each dam and checks it covers the dam point. DEM download is not in 0.1.0."

    def run_step(self, cat, config, dam, s, recs):
        return ST.terrain(dam, s.get("terrain"), C.terrain_info(s.get("terrain")))


class Storage(_OneStep):
    _name, _display, step_key = "storage", "Storage at scenario pools", "storage"
    _help = ("Storage at the top of dam and at each selected scenario's pool (S1 normal pool, S2 high water "
             "line, S3 lower of top of dam and PMF peak, S4 100-yr peak pool not below the auxiliary spillway, "
             "S5/S6/S7 flagged for the Runner). From storage_curve_csv (elev_ft + storage_acft or area_ac) or "
             "the inventory storage.")

    def run_step(self, cat, config, dam, s, recs):
        return ST.storage(dam, config["scenarios"])


class BreachDirection(_OneStep):
    _name, _display, step_key = "breachdirection", "Breach direction", "breach_direction"
    _help = "Breach azimuth from the dam record; a DEM-based estimate is not in 0.1.0 (flagged as a gap)."

    def run_step(self, cat, config, dam, s, recs):
        return ST.breach_direction(dam)


class Hydrograph(_OneStep):
    _name, _display, step_key = "hydrograph", "Breach hydrograph", "hydrograph"
    _help = ("Checks the dam's own hydrograph CSV (time_hr, discharge_cfs) and records its peak and volume; "
             "records a Froehlich (1995) peak per scenario pool as a screening reference only.")

    def run_step(self, cat, config, dam, s, recs):
        return ST.hydrograph(dam, ST.storage(dam, config["scenarios"]), config["scenarios"])


class Triage(_OneStep):
    _name, _display, step_key = "triage", "Quick screen (triage, M13)", "triage"
    _help = "Feature-presence screen with catalog method M13 (no depths); recommends a detailed run when Significant or higher or unknown."

    def run_step(self, cat, config, dam, s, recs):
        return ST.triage(cat, dam, WF.dam_receptors(recs, dam["dam_id"]))


class Engine2D(_OneStep):
    _name, _display, step_key = "engine2d", "2D screening flood", "engine2d"
    _help = ("Runs the DamSafety Screening tool-7 2D flood for each dam (the built-in finite-volume engine, in this "
             "process): the dam's hydrograph CSV, else a Froehlich (2008) piping breach from the top of dam (sunny "
             "day, no outlet or spillway flow), injected at the downstream toe (searched 5 m to H x (DS slope + 1), "
             "3:1 when the slope is missing, capped at 150 m, side check). Settings JSON: engine2d (builtin | off), "
             "grid_m (20), simh (12), simmax (96), larger_clips (0 first clip only, 1 larger clips from the same "
             "terrain, 2 from local_dem), timeout_s (0 = 0.8 x DAMIT_SCREENING_TIMEOUT_S, else 3600). Writes "
             "Screening Depth / Velocity / DV (Max) and Screening Arrival Time into <work>/dams/<id>/ and samples "
             "peak depth, velocity and DV at the receptors. LISFLOOD-FP, ANUGA, HEC-RAS and Wine are not started.")

    def run_step(self, cat, config, dam, s, recs):
        d_recs = WF.dam_receptors(recs, dam["dam_id"])
        r = ST.engine2d(dam, s, WF.dam_folder(self._work, dam["dam_id"]), ST.hydrograph(dam, ST.storage(
            dam, config["scenarios"]), config["scenarios"]), d_recs, self._feedback.pushInfo,
            lambda: self._feedback.isCanceled())
        r.pop("receptors", None)
        return r


class Suggest(_OneStep):
    _name, _display, step_key = "suggest", "Preliminary suggested class", "suggest"
    _help = ("When the receptors already carry hydraulics (depth / DV / M1 chart zone), evaluates the selected "
             "preset or custom methods from DamIT Catalog: most severe scenario, highest rule-strength class, "
             "advisories reported (applied only if opted in), modifiers, driving receptors and method IDs. "
             "Otherwise flags the gap. DamIT Hazard (damit:classify) is the classifier for finished runs.")

    def run_step(self, cat, config, dam, s, recs):
        return ST.suggest(cat, config, dam, WF.dam_receptors(recs, dam["dam_id"]), s.get("summary"),
                          s.get("apply_advisories"))


class Handoff(C.DamitAlgorithm):
    _name, _display = "handoff", "Hand-off to DamIT Runner"
    _help = ("Writes <work>/handoff/<dam>/damit_handoff.json (schema damit.handoff v1) for damit_run:rundam: dam "
             "ids, elevations, storage, scenario pools, scenarios, preset ID or custom method list, modifiers, "
             "label map, terrain / hydrograph paths, any preliminary suggestion and every gap. Runs the screening "
             "steps first, the 2D screening flood included (built-in engine, in this process).")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.add_common()
        self.addOutput(QgsProcessingOutputNumber("COUNT", "Packages written"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        work, s, dams, problems, recs, rnames = self.gather(params, context)
        checks, cat, config = WF.preflight(work, s, dams, problems, recs, rnames)
        if cat is None or config is None or not dams:
            raise QgsProcessingException("; ".join(c["detail"] for c in checks if c["status"] == WF.FAIL)
                                         or "no dams")
        paths = []
        for d in dams:
            r = WF.run_dam(cat, config, d, s, work, recs, C.terrain_info(s.get("terrain")), feedback.pushInfo,
                           feedback.isCanceled)
            if r.get("handoff_path"):
                paths.append(r["handoff_path"])
        return {"COUNT": len(paths), "PACKAGES": paths}


class Report(C.DamitAlgorithm):
    _name, _display = "report", "Screening report"
    needs_dams = False
    _help = "Rewrites the Markdown run report from <work>/damit_screen/chain_summary.json (scenarios, parameters, flags, citations)."

    def initAlgorithm(self, config=None):  # noqa: N802
        self.add_common()
        self.addOutput(QgsProcessingOutputFile("REPORT", "Run report"))
        self.addOutput(QgsProcessingOutputString("STATUS", "Status"))

    def processAlgorithm(self, params, context, feedback):  # noqa: N802
        import json
        work, s, _, _, _, _ = self.gather(params, context)
        p = os.path.join(work, "damit_screen", "chain_summary.json")
        if not os.path.exists(p):
            raise QgsProcessingException("No chain summary in {}: run damit_screen:runchain first".format(work))
        with open(p, encoding="utf-8") as fh:
            summ = json.load(fh)
        checks, cat, config = WF.preflight(work, s, [], [], None)
        if cat is None or config is None:
            raise QgsProcessingException("Catalog or preset not usable")
        return {"REPORT": WF.write_report(work, summ, cat, config), "STATUS": "ok"}


ALGORITHMS = (Preflight, RunChain, Prepare, Terrain, Storage, BreachDirection, Hydrograph, Triage, Engine2D,
              Suggest, Handoff, Report)
