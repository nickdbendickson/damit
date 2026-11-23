"""Spillway adequacy (id spillwayadequacy).

Routes each inflow hydrograph through the reservoir with no breach and reports whether the
peak pool stays at or below the top of dam minus the residual freeboard the engineer sets.
DamIT does not apply a state Inflow Design Flood table. The storm depth and the freeboard
come from the engineer (DamIT PMP can supply the storm depth; this tool does not copy
DamSafety PMP). The class is not an input and is not an output.
"""
import os

from qgis.core import (QgsProcessingException, QgsProcessingOutputFile, QgsProcessingOutputString,
                       QgsProcessingParameterFolderDestination)

from .algorithms_tools import _ToolBase
from ..core import adequacy as AD
from ..core import breach as br
from ..core import flood as fl
from ..core import outlets as outmod
from ..core.units import FT, ACFT, CFS


def _md(res, path, top):
    v = res["verdict"]
    lines = ["# Spillway adequacy", "", v["text"], "",
             "Residual freeboard is an input. DamIT does not apply a state IDF table and does "
             "not change a hazard class.", "",
             "| storm | peak inflow cfs | peak outflow cfs | peak pool ft | residual fb ft | passes |",
             "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            r["storm_id"], r["peak_inflow_cfs"], r["peak_outflow_cfs"], r["peak_pool_ft"],
            r["residual_freeboard_ft"], "yes" if r["passes"] else "NO"))
    lines += ["", "## Notes", ""] + ["- " + n for n in res["notes"]]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


class SpillwayAdequacyAlgorithm(_ToolBase):
    def name(self):
        return "spillwayadequacy"

    def displayName(self):
        return "Spillway adequacy (does the pool stay below the freeboard you set?)"

    def shortHelpString(self):
        return ("Routes each inflow hydrograph in the folder through the reservoir with no "
                "breach: from the starting pool (the value you give, else the first spillway "
                "rating elevation that flows), through the spillway rating and optional outlets, "
                "and over the embankment crest (broad-crested weir) above the top of dam. A "
                "storm passes when the peak pool is at or below the top of dam minus the "
                "residual freeboard you set. The largest multiple of each inflow that still "
                "passes is found by bisection (up to 2x) when that option is on.\n\n"
                "The hydrographs are yours. Take a storm depth from DamIT PMP "
                "(damit_pmp:pointpf or damit_pmp:hyetograph) or from your own study and build "
                "the inflow with damit_run:rainfallrunoff, or bring a CSV (time_hr, flow_cfs). "
                "DamIT does not choose an Inflow Design Flood by hazard class and does not "
                "copy DamSafety PMP. This tool does not classify the dam and cannot lower a "
                "class. An engineer must review the inputs and the result.")

    def initAlgorithm(self, config=None):
        self._file("INFLOWS", "Folder of inflow hydrograph CSVs (time_hr, flow_cfs)",
                   folder=True, optional=False)
        self._num("TOP_FT", "Top of dam, post-settlement (ft; roadway excluded)")
        self._num("FREEBOARD_FT", "Required residual freeboard (ft). You set this; DamIT has "
                  "no state table.", minimum=0)
        self._file("SPILLWAY_CSV", "Spillway rating CSV (elevation ft, discharge cfs)", "csv")
        self._num("CREST_LENGTH", "Embankment crest length (ft), for flow over the dam",
                  optional=True, minimum=0)
        self._num("START_FT", "Starting pool (ft; empty = the first spillway rating elevation "
                  "with flow)", optional=True)
        self._file("STAGE_STORAGE_CSV", "Stage-storage CSV (elevation ft, storage ac-ft); empty = "
                   "power law from the values below", "csv")
        self._num("STORAGE_TOP", "Storage at the top of dam (ac-ft), without a stage-storage table",
                  optional=True, minimum=0)
        self._num("AREA_TOP", "Surface area at the top of dam (ac), without a table",
                  optional=True, minimum=0)
        self._num("HEIGHT_FT", "Dam height (ft), without a table", optional=True, minimum=0)
        self._text("OUTLETS", "Outlet works, one per line 'name; invert ft; diameter ft (or width "
                   "x height); cd; gate hours:fraction, ...'", advanced=True)
        self._text("SPILLWAY_GATE", "Gate on the spillway rating, hours:fraction pairs like "
                   "'0:1, 6:0.5'", advanced=True)
        self._bool("BISECT", "Find the largest multiple of each inflow that passes", True)
        self.addParameter(QgsProcessingParameterFolderDestination(
            "OUT_DIR", "Output folder (adequacy.csv, adequacy.md, governing_pool.png)"))
        self.addOutput(QgsProcessingOutputString("VERDICT", "Verdict"))
        self.addOutput(QgsProcessingOutputFile("CSV", "Adequacy CSV"))
        self.addOutput(QgsProcessingOutputFile("REPORT", "Adequacy report (markdown)"))
        self.addOutput(QgsProcessingOutputFile("PLOT", "Pool against time, governing storm (PNG)"))

    def processAlgorithm(self, parameters, context, feedback):
        o = lambda n: self._opt(parameters, n, context)            # noqa: E731
        folder = self._fileparam(parameters, "INFLOWS", context)
        top = o("TOP_FT")
        freeboard = o("FREEBOARD_FT")
        if not folder or top is None or freeboard is None:
            raise QgsProcessingException("Give the inflow folder, the top of dam and the "
                                         "residual freeboard")
        out_dir = self.parameterAsString(parameters, "OUT_DIR", context)
        os.makedirs(out_dir, exist_ok=True)
        ss = self._fileparam(parameters, "STAGE_STORAGE_CSV", context) or None
        try:
            if ss:
                res_obj = AD.TableReservoir.from_csv(ss)
                notes = ["Reservoir: stage-storage table {}.".format(ss)]
            else:
                if o("STORAGE_TOP") is None or o("HEIGHT_FT") is None:
                    raise AD.AdequacyError("Give a stage-storage CSV, or the storage at the top "
                                           "of dam and the dam height")
                dam = br.DamData(dam_id="dam", dam_height_ft=o("HEIGHT_FT"),
                                 storage_top_acft=o("STORAGE_TOP"), top_of_dam_ft=top,
                                 surface_area_top_ac=o("AREA_TOP"))
                c = br._common(dam, float(top) * FT, "top of dam")
                res_obj = c.res
                notes = ["Reservoir: power law from the storage and height you gave."]
            spill_path = self._fileparam(parameters, "SPILLWAY_CSV", context) or None
            spill = fl.Spillway.from_csv(spill_path) if spill_path else None
            outlets = outmod.parse_outlets(self._str(parameters, "OUTLETS", context))
            sched = outmod.parse_schedule(self._str(parameters, "SPILLWAY_GATE", context))
            if o("START_FT") is None:
                if spill is None:
                    raise AD.AdequacyError("Give the starting pool or a spillway rating")
                start_m = spill.first_flow_m
                notes.append("Starting pool: first spillway rating elevation with flow, "
                             "{:.2f} ft.".format(start_m / FT))
            else:
                start_m = float(o("START_FT")) * FT
                notes.append("Starting pool: given, {:.2f} ft.".format(start_m / FT))
            top_m = float(top) * FT
            if start_m >= top_m:
                raise AD.AdequacyError("the starting pool is not below the top of dam")
            allowed_m = top_m - float(freeboard) * FT
            rows, series = [], {}
            bisect = self.parameterAsBool(parameters, "BISECT", context)
            crest = o("CREST_LENGTH")
            for path in AD.find_inflows(folder):
                t, q, meta = AD.read_inflow_csv(path)
                hrs = max(240.0, float(t[-1]) / 3600.0 + 48.0)
                fi = fl.FloodInputs(t, q, spill, crest_length_ft=crest)
                fi.outlets = list(outlets or [])
                fi.spillway_schedule = sched
                r = AD.route_no_breach(res_obj, fi, top_m, start_m, hrs, 30.0)
                peak_ft = r["peak_wse_m"] / FT
                resid = float(top) - peak_ft
                passed = r["peak_wse_m"] <= allowed_m + 1e-9
                mult, capped = (AD.max_multiple(res_obj, fi, top_m, start_m, allowed_m, 30.0, hrs)
                                if bisect else (None, False))
                sid = meta.get("storm_id") or os.path.splitext(os.path.basename(path))[0]
                rows.append({
                    "storm_id": sid, "file": path, "storm_type": meta.get("storm_type", ""),
                    "duration_hr": meta.get("duration_hr", ""),
                    "peak_inflow_cfs": round(r["peak_qin_cms"] / CFS, 1),
                    "inflow_volume_acft": round(float(fi.inflow_volume_m3) / ACFT, 1),
                    "peak_outflow_cfs": round(r["peak_qout_cms"] / CFS, 1),
                    "start_pool_ft": round(start_m / FT, 2),
                    "peak_pool_ft": round(peak_ft, 2),
                    "time_of_peak_pool_hr": round(r["t_peak_wse_s"] / 3600.0, 2),
                    "top_of_dam_ft": round(float(top), 2),
                    "residual_freeboard_ft": round(resid, 2),
                    "required_freeboard_ft": round(float(freeboard), 2),
                    "overtops": bool(peak_ft > float(top)),
                    "passes": bool(passed),
                    "max_multiple_passed": None if mult is None else round(mult, 3),
                    "max_multiple_capped": bool(capped),
                    "routing_complete": r["complete"],
                })
                series[sid] = r
            if not rows:
                raise AD.AdequacyError("no inflow hydrographs")
            gov = max(rows, key=lambda x: x["peak_pool_ft"])
            ok = all(x["passes"] for x in rows)
            text = ("PASSES" if ok else "DOES NOT PASS") + (
                ": governing storm {} peaks at {:.2f} ft, {:.2f} ft below the top of dam "
                "{:.2f} ft (required residual freeboard {:.2f} ft).".format(
                    gov["storm_id"], gov["peak_pool_ft"], gov["residual_freeboard_ft"],
                    float(top), float(freeboard)))
            verdict = {"text": text, "passes": ok, "governing_storm": gov["storm_id"],
                       "required_residual_freeboard_ft": float(freeboard),
                       "allowed_peak_pool_ft": round(allowed_m / FT, 2),
                       "start_pool_ft": round(start_m / FT, 2),
                       "start_pool_rule": "given" if o("START_FT") is not None else "spillway rating"}
            result = {"rows": rows, "verdict": verdict, "series": series, "notes": notes}
        except (AD.AdequacyError, br.BreachInputError, ValueError) as e:
            raise QgsProcessingException(str(e))
        csv_p = AD.write_csv(result, os.path.join(out_dir, "adequacy.csv"))
        md_p = _md(result, os.path.join(out_dir, "adequacy.md"), top)
        png = AD.plot_governing(result, os.path.join(out_dir, "governing_pool.png"), top) or ""
        for r in rows:
            feedback.pushInfo("{storm_id}: peak pool {peak_pool_ft} ft, residual freeboard "
                              "{residual_freeboard_ft} ft -> {word}".format(
                                  word="passes" if r["passes"] else "DOES NOT PASS", **r))
        feedback.pushInfo(text)
        for n in notes:
            feedback.pushInfo("Note: " + n)
        return {"VERDICT": text, "CSV": csv_p, "REPORT": md_p, "PLOT": png, "OUT_DIR": out_dir}


ADEQUACY_ALGORITHMS = (SpillwayAdequacyAlgorithm,)
