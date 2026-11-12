#!/usr/bin/env python3
"""run_digest.py 1.0.0 - a deterministic review of one DamIT Runner run (no LLM, no network).

The digest reads what the Runner already wrote (run_setup.json, run_report.json with its per-pass
records, the per-pass LISFLOOD-FP results, the dam folder, the Hazard report) and answers the
questions Nick asks of every run:

  mass balance and NaNs         per-pass volume error (the Runner's own number when it recorded one,
                                else the .mass file, same formula), domain volume against what went in,
                                water entering through an edge
  edges                         per-pass outflow % and the depth at each edge; early passes that leaked
                                (the domain grew and the final pass is clean) versus a leaking final pass
  progress / stall              sim time against the planned time, a pass that never finished, a .mass
                                file that stopped growing, a run that stopped while the flood still moved
  height                        crest minus streambed against the inventory height
  datum                         NAVD88 only for DWR elevations; 0-300 ft is a local datum
  toe inflow                    distance from the dam line against H x (downstream slope + 1), 3:1 when the
                                slope is unknown, 5 m minimum, 150 m cap
  sunny day                     starting WSE = top of dam; no outlet or spillway flow (outlets empty)
  receptors                     points on a NoData cell, or a dry cell, next to wet cells
  hazard drivers to review      unscored roads, trains/day (BNSF KO = 15), judgment-zone hits, ...

The VERDICT (OK / WATCH / PROBLEM) is set here, by code, from the flags alone. The local AI (Lumo)
only explains it and never changes or gates it.

CLI:
  python3 run_digest.py RUN_DIR [--phase run_end] [--dam-folder DIR] [--points CSV] [--json]
                        [--out DIR] [--pass N] [--stall-s 900] [--rail-lookup CSV]
Exit code: 0 always, unless --exit-code (then 0 OK, 1 WATCH, 2 PROBLEM).
Reads the run folder only; writes nothing into it (--out writes elsewhere).
"""
import argparse
import csv
import glob
import json
import math
import os
import re
import sys
import time
import traceback

VERSION = "1.3.0"
SCHEMA = "damit.run_digest"

OK, WATCH, PROBLEM = "OK", "WATCH", "PROBLEM"
INFO = "INFO"                       # a note: never changes the verdict
_RANK = {INFO: 0, OK: 0, WATCH: 1, PROBLEM: 2}

FT = 0.3048                         # m per ft
CFS = 0.028316846592                # m3/s per cfs
ACFT = 1233.48183754752             # m3 per ac-ft

# Every threshold the digest uses, in one place (also written to the knowledge pack).
THRESHOLDS = {
    "mass_error_watch_pct": 0.5,        # per-pass |volume error| / injected volume
    "mass_error_problem_pct": 1.0,      # the Runner's own limit (STABILITY_RETRY_PCT, "limit 1%")
    "domain_volume_ratio_problem": 1.10,    # refine.MAX_VOLUME_RATIO: water held / water put in
    "edge_inflow_problem_pct": 2.0,     # water entering through an edge, % of injected
    "edge_wet_ft": 0.1,                 # an edge cell this deep counts as a wet edge
    "edge_outflow_watch_pct": 1.0,      # boundary outflow that is worth a flag in an early pass
    "edge_tol_ft": 1.0,                 # the Runner's edge tolerance (parameters.edge_tol_ft)
    "outflow_extend_pct": 5.0,          # the Runner's outflow growth trigger (parameters.outflow_extend_pct)
    "progress_min": 0.99,               # a pass must reach this share of its planned sim time
    "stall_s": 900.0,                   # a running pass whose .mass has not grown for this long
    "height_watch_ft": 0.5,             # |crest - streambed - inventory height|
    "height_problem_ft": 5.0,
    "height_problem_frac": 0.15,
    "start_wse_tol_ft": 0.05,           # starting WSE against the top of dam
    "toe_inner_m": 5.0,
    "toe_cap_m": 150.0,
    "toe_default_slope": 3.0,           # 3:1 when the downstream slope is not known
    "toe_band_tol_m": 1.0,
    "local_datum_max_ft": 300.0,        # 0-300 ft is a local datum, not NAVD88 (ND is ~800-3,500 ft)
    "wet_ft": 0.1,                      # arrival depth: a cell this deep is wet
    "near_wet_ft": 1.0,                 # a dry receptor cell whose neighbour is this deep is flagged
    "bnsf_ko_trains_per_day": 15.0,     # Nick's rule (DamSafety's value)
    "max_ids_listed": 10,               # receptor / road ids named in a flag line, then "(+N more)"
}

KNOWN_FLAG_IDS = (
    "MASS_NAN", "MASS_BALANCE", "DOMAIN_VOLUME", "EDGE_INFLOW", "EDGE_OUTFLOW_EARLY", "EDGE_OUTFLOW_FINAL",
    "PASS_UNFINISHED", "STALL", "STOPPED_MOVING", "HEIGHT_MISMATCH", "BREACH_BOTTOM_RAISED", "DATUM",
    "START_WSE", "TOE_INFLOW", "TOE_BAND", "OUTLET_FLOW", "ENGINE_FALLBACK", "RUN_WARNINGS",
    "RECEPTOR_NODATA", "RECEPTOR_DRY_NEXT_TO_WET", "ROADS_UNSCORED", "HAZARD_REVIEW", "RAIL_TRAINS",
    "NO_RUN_FILES", "DAM_RECORD_MISSING", "TOE_UNCHECKED", "TOE_SOURCE_RUN_REPORT", "RECEPTORS_UNCHECKED",
)

# Elevations from 300 ft up to this are taken to be in the NAVD88 range when no datum is stated (ND is ~800-3,500 ft;
# nothing in the contiguous US is above 14,500 ft).
NAVD88_RANGE_MAX_FT = 15000.0


# ----------------------------------------------------------------------------- small helpers
def describe_error(e):
    """The exception's type and message; a type alone when the message is empty (GDAL/PROJ errors often are)."""
    msg = " ".join(str(e).split())
    return "%s: %s" % (type(e).__name__, msg) if msg else "%s (no message)" % type(e).__name__


def error_detail(e, lines=4):
    """The last few traceback lines, and a PROJ hint when the failure looks like a PROJ database problem."""
    tb = [l for l in traceback.format_exception(type(e), e, e.__traceback__) if l.strip()]
    tail = " | ".join(" ".join(l.split()) for l in tb[-lines:])
    text = (str(e) + tail).lower()
    hint = ""
    if "proj" in text or isinstance(e, (AttributeError, TypeError)) and "transform" in text:
        hint = (" PROJ cannot open its database (proj.db): set PROJ_DATA (PROJ_LIB on GDAL before 3.x / PROJ 9) to the "
                "folder that holds proj.db, e.g. <conda env>/share/proj or the QGIS share/proj, then run again.")
    return "traceback tail: %s.%s" % (tail, hint)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _num(x, default=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _fmt(x, nd=2, unit=""):
    v = _num(x)
    return "n/a" if v is None else ("{:,.%df}{}" % nd).format(v, unit)


def _ids(ids, limit=None):
    limit = limit or THRESHOLDS["max_ids_listed"]
    ids = [str(i) for i in ids]
    return ", ".join(ids[:limit]) + (" (+%d more)" % (len(ids) - limit) if len(ids) > limit else "")


def flag_ids_text(flag, limit=None):
    """"ids a, b, c (+N more)" for a flag that carries receptor ids in its data, else "". Capped (default 10) so a long
    list cannot swell the digest or the prompt; the JSON data keeps every id."""
    ids = (flag.get("data") or {}).get("ids")
    if not isinstance(ids, (list, tuple)) or not ids:
        return ""
    limit = limit or THRESHOLDS["max_ids_listed"]
    return "ids " + ", ".join(str(i) for i in ids[:limit]) + (" (+%d more)" % (len(ids) - limit) if len(ids) > limit else "")


class Flags(object):
    """Collects flags. One flag: id, severity, where, title, detail, data."""

    def __init__(self):
        self.items = []

    def add(self, fid, severity, where, title, detail="", **data):
        assert fid in KNOWN_FLAG_IDS, fid
        self.items.append({"id": fid, "severity": severity, "where": where, "title": title, "detail": detail,
                           "data": data})


def dedupe_flags(items):
    """One flag per id (1.2.0). The same id raised more than once (EDGE_OUTFLOW_EARLY in passes 1 and 2) is listed once:
    the MOST SEVERE one is kept, the LATEST among equals. Where and what the others were is kept in the flag's data
    (`occurrences`, `also`) and in its detail, so nothing is lost, and the verdict is unchanged (it is the highest
    severity, which is the one kept). Order follows each id's first appearance."""
    best, order, others = {}, [], {}
    for f in items:
        fid = f["id"]
        if fid not in best:
            best[fid], order, others[fid] = f, order + [fid], []
        elif _RANK.get(f["severity"], 0) >= _RANK.get(best[fid]["severity"], 0):
            others[fid].append(best[fid])
            best[fid] = f
        else:
            others[fid].append(f)
    out = []
    for fid in order:
        f = best[fid]
        if others[fid]:
            also = [{"where": o["where"], "severity": o["severity"], "title": o["title"]} for o in others[fid]]
            places = ", ".join(str(o["where"]) for o in others[fid])
            f = dict(f, data=dict(f.get("data") or {}, occurrences=1 + len(also), also=also),
                     detail=((f.get("detail") or "").rstrip() + (" " if f.get("detail") else "") +
                             "Also raised at %s (%d in all; the most severe, latest one is shown)." % (
                                 places, 1 + len(also))))
        out.append(f)
    return out


def verdict_of(flags):
    """OK / WATCH / PROBLEM from the flags alone: the highest severity present."""
    top = 0
    for fl in flags:
        top = max(top, _RANK.get(fl.get("severity"), 0))
    return PROBLEM if top >= 2 else WATCH if top == 1 else OK


# ----------------------------------------------------------------------------- the LISFLOOD-FP .mass file
MASS_COLS = ("time", "tstep", "mintstep", "nsteps", "area", "vol", "qin", "hds", "qout", "qerr", "verr", "rain")


def read_mass(path):
    """Parse a LISFLOOD-FP .mass file: {rows: [[time_s, vol, qin, qout, verr]], nan_rows, bad_rows, last_t, n}.

    Columns 0, 5, 6, 8, 10 as the Runner reads them. A row with NaN/Inf in any field counts as a NaN row."""
    out = {"rows": [], "nan_rows": 0, "bad_rows": 0, "last_t": None, "n": 0, "exists": False}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            out["exists"] = True
            next(f, None)
            for line in f:
                p = line.split()
                if not p:
                    continue
                out["n"] += 1
                try:
                    vals = [float(x) for x in p]
                except ValueError:
                    out["bad_rows"] += 1
                    continue
                if any(not math.isfinite(v) for v in vals):
                    out["nan_rows"] += 1
                    continue
                if len(vals) >= 11:
                    out["rows"].append([vals[0], vals[5], vals[6], vals[8], vals[10]])
                else:
                    out["bad_rows"] += 1
    except OSError:
        pass
    if out["rows"]:
        out["last_t"] = out["rows"][-1][0]
    return out


def _trapz(xs, ys):
    s = 0.0
    for i in range(1, len(xs)):
        s += 0.5 * (ys[i] + ys[i - 1]) * (xs[i] - xs[i - 1])
    return s


def mass_balance(mass):
    """The Runner's numbers from a parsed .mass: injected volume (trapezoid of positive Qin), the signed sum of
    the interval errors as % of injected (max_volume_error_pct), worst interval, boundary outflow % (positive
    Qout), edge inflow % (negative Qout), the largest domain volume as a ratio of injected."""
    rows = mass["rows"]
    if len(rows) < 2:
        return None
    t = [r[0] for r in rows]
    inj = _trapz(t, [max(r[2], 0.0) for r in rows])
    out = _trapz(t, [max(r[3], 0.0) for r in rows])
    inn = _trapz(t, [max(-r[3], 0.0) for r in rows])
    cum = sum(r[4] for r in rows)
    worst = max(abs(r[4]) for r in rows)
    res = {"injected_m3": inj, "outflow_m3": out, "edge_inflow_m3": inn, "last_t_s": t[-1],
           "max_volume_error_pct": None, "worst_interval_error_pct": None, "outflow_pct": None,
           "edge_inflow_pct": None, "domain_volume_ratio": None, "max_domain_volume_m3": max(r[1] for r in rows)}
    if inj > 0:
        res["max_volume_error_pct"] = round(100.0 * abs(cum) / inj, 3)
        res["worst_interval_error_pct"] = round(100.0 * worst / inj, 3)
        res["outflow_pct"] = round(100.0 * out / inj, 2)
        res["edge_inflow_pct"] = round(100.0 * inn / inj, 2)
        res["domain_volume_ratio"] = round(res["max_domain_volume_m3"] / inj, 3)
    return res


# ----------------------------------------------------------------------------- rasters (numpy; GDAL for GeoTIFF)
class Grid(object):
    """data: 2-D float array, NaN = NoData. x0 = left edge, y0 = top edge (north-up), cell = size."""

    def __init__(self, data, x0, y0, cell):
        self.data, self.x0, self.y0, self.cell = data, x0, y0, cell

    def rowcol(self, x, y):
        return int(math.floor((self.y0 - y) / self.cell)), int(math.floor((x - self.x0) / self.cell))


def read_asc(path):
    """An ESRI ASCII grid (LISFLOOD-FP output): (array with NaN for NoData, header dict). Needs numpy."""
    import numpy as np
    hdr = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for _ in range(6):
            k, v = f.readline().split()[:2]
            hdr[k.lower()] = float(v)
        arr = np.loadtxt(f, dtype=float, ndmin=2)
    nd = hdr.get("nodata_value", -9999.0)
    arr = np.where(arr == nd, np.nan, arr)
    return arr.reshape(int(hdr["nrows"]), int(hdr["ncols"])), hdr


def read_tif(path):
    """A single-band GeoTIFF as a Grid (NaN for NoData); None when GDAL is not importable."""
    try:
        from osgeo import gdal
        import numpy as np
    except ImportError:
        return None
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        ds = gdal.Open(path)
        if ds is None:
            return None
        b = ds.GetRasterBand(1)
        a = b.ReadAsArray().astype(float)
        nd = b.GetNoDataValue()
        if nd is not None:
            a = np.where(a == nd, np.nan, a)
        gt = ds.GetGeoTransform()
        return Grid(a, gt[0], gt[3], abs(gt[1]))
    finally:
        gdal.PopErrorHandler()


def _pass_dirs(run_dir):
    return sorted(d for d in glob.glob(os.path.join(run_dir, "model", "run*")) if os.path.isdir(d))


PROGRESS_FILE = "run_progress.json"       # written by DamIT Runner 0.3.1+ (flood/model.py write_progress)


def load_progress(run_dir):
    """The Runner's run_progress.json: {crs_wkt, passes: [{pass, dir, bounds, cell_m}], growth_loops_done, complete}.
    It exists while the run is going, which run_report.json does not (1.3.0). {} for a run from an older Runner."""
    d = _load_json(os.path.join(run_dir, PROGRESS_FILE))
    return d if isinstance(d, dict) else {}


def progress_pass(progress, pdir):
    """The progress entry of a pass folder (by its folder name), or {}."""
    name = os.path.basename(os.path.normpath(pdir))
    # the LAST entry with the name: a later loop at the same cell size (grid check / refine) reuses run01_<cell>m, and the
    # folder on disk holds that later pass
    for e in reversed((progress or {}).get("passes") or []):
        if isinstance(e, dict) and e.get("dir") == name:
            return e
    return {}


def run_complete(run_dir, setup=None, report=None, progress=None):
    """(done, how): has the Runner's WHOLE pipeline finished (every pass of every loop, the ANUGA tier, the outputs)? The
    pass logs cannot say so: the Runner works between passes in Python, with no LISFLOOD process and no pass log growing
    (DWR-2824: the 2 s gap before pass 7 looked idle). The markers, strongest first: run_progress.json "complete" (written after
    run_report.json), run_report.json (the last file run_breach writes), run_setup.json status finished (model launched) or
    failed. How is the marker's name, for the reason line."""
    progress = load_progress(run_dir) if progress is None else progress
    if progress.get("complete") is True:
        return True, "run_progress.json says complete"
    if report is not None or os.path.exists(os.path.join(run_dir, "run_report.json")):
        return True, "run_report.json is written"
    setup = _load_json(os.path.join(run_dir, "run_setup.json")) if setup is None else setup
    st = (setup or {}).get("status")
    if st == "finished" and (setup or {}).get("model_launched"):
        return True, "run_setup.json status is finished"
    if st == "failed":
        return True, "run_setup.json status is failed"
    return False, None


def _pass_grid(pdir, ext, bounds, scale=1.0):
    """A pass's LISFLOOD-FP result raster (results/run<ext>) as a Grid, georeferenced from the Runner's bounds
    [xmin, ymin, xmax, ymax] (the ASCII files are in local coordinates). NoData where the DEM is NoData."""
    p = os.path.join(pdir, "results", "run" + ext)
    if not os.path.exists(p) or not bounds:
        return None
    a, hdr = read_asc(p)
    dem = os.path.join(pdir, "results", "run.dem")
    if os.path.exists(dem):
        import numpy as np
        d, _ = read_asc(dem)
        if d.shape == a.shape:
            a = np.where(np.isnan(d), np.nan, np.where(np.isnan(a), 0.0, a))
    a = a * scale
    cell = hdr["cellsize"]
    return Grid(a, bounds[0], bounds[1] + a.shape[0] * cell, cell)


def edge_depths_ft(arr):
    """Deepest water on each outer edge of a depth array, in the array's own unit: {'N','S','W','E'}."""
    import numpy as np

    def mx(v):
        v = v[np.isfinite(v)]
        return float(v.max()) if v.size else 0.0
    return {"N": mx(arr[0, :]), "S": mx(arr[-1, :]), "W": mx(arr[:, 0]), "E": mx(arr[:, -1])}


# ----------------------------------------------------------------------------- per-pass records
def _par(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2:
                    out[p[0]] = p[1]
    except OSError:
        pass
    return out


def _pass_number(pdir):
    m = re.match(r"run0*(\d+)", os.path.basename(pdir))
    return int(m.group(1)) if m else None


def _log_finished(pdir):
    try:
        with open(os.path.join(pdir, "lisflood.log"), encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    return ("Finish Date" in txt) or ("Total computation time" in txt)


def pass_record(run_dir, pdir, report_pass=None, bounds=None, now=None):
    """Everything the digest knows about one pass. The Runner's own per-pass record (run_report.json passes[n])
    wins where it has the number; the .mass file and the pass rasters are the fallback."""
    n = _pass_number(pdir)
    rp = report_pass or {}
    par = _par(os.path.join(pdir, "run.par"))
    mass_path = os.path.join(pdir, "results", "run.mass")
    mass = read_mass(mass_path)
    mb = mass_balance(mass)
    planned_s = _num(par.get("sim_time"))
    last_t = mass["last_t"]
    rec = {"pass": n, "dir": os.path.basename(pdir), "from_report": bool(report_pass), "nan_rows": mass["nan_rows"],
           "bad_rows": mass["bad_rows"], "mass_rows": mass["n"], "planned_sim_s": planned_s, "last_mass_s": last_t,
           "finished": _log_finished(pdir), "cell_m": _num(rp.get("cell_m"))}
    rec["mass_mtime"] = os.path.getmtime(mass_path) if mass["exists"] else None
    # sim time and progress
    st = _num(rp.get("sim_time_hr"))
    rec["sim_time_hr"] = st if st is not None else (round(last_t / 3600.0, 2) if last_t is not None else None)
    rec["progress"] = round(last_t / planned_s, 4) if (last_t is not None and planned_s) else None
    # mass balance: the Runner's number when it recorded one
    mbp = _num(rp.get("max_volume_error_pct"))
    rec["mass_error_pct"], rec["mass_error_source"] = (mbp, "run_report") if mbp is not None else (
        (mb["max_volume_error_pct"], ".mass") if mb else (None, None))
    rec["worst_interval_error_pct"] = _num(rp.get("worst_interval_error_pct"), mb and mb["worst_interval_error_pct"])
    rec["domain_volume_ratio"] = _num(rp.get("max_domain_volume_ratio"), mb and mb["domain_volume_ratio"])
    rec["edge_inflow_pct"] = mb["edge_inflow_pct"] if mb else None
    # edges
    op = _num(rp.get("boundary_outflow_pct"))
    rec["outflow_pct"], rec["outflow_source"] = (op, "run_report") if op is not None else (
        (mb["outflow_pct"], ".mass") if mb and mb["outflow_pct"] is not None else (None, None))
    ed = rp.get("edge_depths_ft")
    rec["edge_source"] = "run_report" if isinstance(ed, dict) else None
    if not isinstance(ed, dict):
        try:
            pm = os.path.join(pdir, "results", "run.max")
            if os.path.exists(pm):                       # edges need no georeference
                arr, _h = read_asc(pm)
                ed = {k: round(v / FT, 2) for k, v in edge_depths_ft(arr).items()}
            else:
                ed = None
            rec["edge_source"] = "pass raster run.max" if ed is not None else None
        except Exception:           # noqa: BLE001 - numpy missing or an unreadable raster: no edge numbers
            ed = None
    rec["edge_depths_ft"] = ed
    rec["over"] = list(rp.get("over") or [])
    rec["over_outflow"] = list(rp.get("over_outflow") or [])
    rec["still_moving"] = rp.get("still_moving")
    rec["clock_extension"] = rp.get("clock_extension")
    rec["flooded_acres"] = _num(rp.get("flooded_acres"))
    rec["max_depth_ft"] = _num(rp.get("max_depth_ft"))
    rec["wall_s"] = _num(rp.get("wall_s"))
    return rec


# ----------------------------------------------------------------------------- checks
def check_mass(passes, fl, th=THRESHOLDS):
    for p in passes:
        w = "pass %s" % p["pass"]
        if p["nan_rows"]:
            fl.add("MASS_NAN", PROBLEM, w, "NaN or Inf in the .mass file",
                   "%d row(s) of %d hold NaN/Inf (the solver blew up or wrote garbage)" % (p["nan_rows"], p["mass_rows"]),
                   nan_rows=p["nan_rows"])
        e = p["mass_error_pct"]
        if e is not None and abs(e) > th["mass_error_watch_pct"]:
            sev = PROBLEM if abs(e) > th["mass_error_problem_pct"] else WATCH
            fl.add("MASS_BALANCE", sev, w, "volume error %.3g%% of the injected volume" % abs(e),
                   "limit %.3g%% (the Runner's own); source: %s" % (th["mass_error_problem_pct"], p["mass_error_source"]),
                   pct=abs(e))
        r = p["domain_volume_ratio"]
        if r is not None and r > th["domain_volume_ratio_problem"]:
            fl.add("DOMAIN_VOLUME", PROBLEM, w, "the model holds %.2fx the water that went in" % r,
                   "an edge is importing water (limit %.2fx)" % th["domain_volume_ratio_problem"], ratio=r)
        ei = p["edge_inflow_pct"]
        if ei is not None and ei > th["edge_inflow_problem_pct"]:
            fl.add("EDGE_INFLOW", PROBLEM, w, "water enters through a model domain edge: %.1f%% of the injected volume" % ei,
                   "negative Qout in the .mass file", pct=ei)


def check_edges(passes, fl, params=None, th=THRESHOLDS, in_progress=False):
    """Early passes that leak are normal while the domain grows (WATCH: confirm the final pass is clean);
    a leaking FINAL pass is a PROBLEM. While the run is in progress (a pass_end / stall digest) the newest pass is
    not known to be final, so it is flagged as early: the Runner may still grow the domain."""
    params = params or {}
    tol = _num(params.get("edge_tol_ft"), th["edge_tol_ft"])
    ext = _num(params.get("outflow_extend_pct"), th["outflow_extend_pct"])
    last = passes[-1]["pass"] if passes else None
    for p in passes:
        ed = p["edge_depths_ft"] or {}
        wet = sorted(k for k, v in ed.items() if (_num(v, 0.0) or 0.0) >= th["edge_wet_ft"])
        op = p["outflow_pct"]
        leaking = bool(p["over"] or p["over_outflow"]) or (op is not None and op >= th["edge_outflow_watch_pct"])
        if not (wet and leaking) and not (op is not None and op >= ext):
            continue
        desc = "model domain edge(s) %s wet (%s ft); boundary outflow %s%%" % (
            "/".join(wet) or "none", ", ".join("%s %.2f" % (k, ed[k]) for k in wet) or "n/a",
            _fmt(op, 1))
        data = {"edges": wet, "depth_ft": {k: ed.get(k) for k in wet}, "outflow_pct": op}
        w = "pass %s" % p["pass"]
        if p["pass"] == last and not in_progress:
            sev = PROBLEM if (p["over"] or p["over_outflow"] or (op is not None and op >= ext) or
                              any((ed.get(k) or 0.0) >= tol for k in wet)) else WATCH
            fl.add("EDGE_OUTFLOW_FINAL", sev, w, "the FINAL pass leaks through the model domain edge" if sev == PROBLEM else
                   "the final pass has water at a model domain edge", desc + "; the flood left the model (depths and extent are "
                   "not final)", **data)
        else:
            fl.add("EDGE_OUTFLOW_EARLY", WATCH, w, "early-pass outflow through the model domain edge (%s%%)" % _fmt(op, 1),
                   desc + "; water leaving the edge of the model grid (not the breach) is normal while the domain grows, so confirm the final pass is clean", **data)


def check_progress(passes, report, fl, now=None, th=THRESHOLDS, stall_s=None):
    stall_s = stall_s if stall_s is not None else th["stall_s"]
    now = now if now is not None else time.time()
    for i, p in enumerate(passes):
        w = "pass %s" % p["pass"]
        prog, fin = p["progress"], p["finished"]
        is_last = i == len(passes) - 1
        if fin is False or (fin is None and prog is not None and prog < th["progress_min"]):
            running = report is None and is_last
            age = (now - p["mass_mtime"]) if p["mass_mtime"] else None
            if running and age is not None and age >= stall_s:
                fl.add("STALL", PROBLEM, w, "stalled: .mass has not grown for %.0f s" % age,
                       "sim time %s h of %s h planned" % (_fmt(p["sim_time_hr"], 2),
                                                          _fmt((p["planned_sim_s"] or 0) / 3600.0, 2)),
                       idle_s=age, stall_s=stall_s)
            elif not running:
                fl.add("PASS_UNFINISHED", PROBLEM, w, "the pass did not finish",
                       "log has no Finish line; sim time %s of %s h planned (%s)" % (
                           _fmt(p["sim_time_hr"], 2), _fmt((p["planned_sim_s"] or 0) / 3600.0, 2),
                           "%.0f%%" % (100 * prog) if prog is not None else "n/a"), progress=prog)
        elif prog is not None and prog < th["progress_min"] and fin:
            fl.add("PASS_UNFINISHED", WATCH, w, "the pass ended early: %.0f%% of its planned sim time" % (100 * prog),
                   "LISFLOOD-FP finished but the .mass file stops before sim_time", progress=prog)
    if report and passes:
        last = report.get("passes", [])[-1:] or []
        lp = last[0] if last else {}
        if lp.get("still_moving"):
            fl.add("STOPPED_MOVING", WATCH, "pass %s" % passes[-1]["pass"], "the run stopped while the flood still moved",
                   "stop_reason: %s; sim time %s h (the clock caps: DURATION_MAX_HR / MAX_RUNS)" % (
                       report.get("stop_reason") or "none recorded", _fmt(lp.get("sim_time_hr"), 2)),
                   stop_reason=report.get("stop_reason"))


def _dam_folder(run_dir, setup, explicit=None):
    if explicit and os.path.isdir(explicit):             # an explicit folder wins, with or without a dam.json in it
        return explicit
    cands = [explicit, (setup or {}).get("dam_folder"), os.path.dirname(os.path.abspath(run_dir))]
    for c in cands:
        if c and os.path.exists(os.path.join(c, "dam.json")):
            return c
    return explicit or (setup or {}).get("dam_folder")


def _handoff_dam(run_dir):
    h = _load_json(os.path.join(run_dir, "damit_handoff.json")) if run_dir else None
    return (h or {}).get("dam") or {}


def resolve_dam_id(setup, report, dam_folder, run_dir=None, dj_fields=None):
    """(dam_id, source). The run's own record first; with no dam.json: the run report, the hand-off, then the
    dam folder's name (the Dams folder names it by its dam id)."""
    d = (setup or {}).get("dam") or {}
    prm = (setup or {}).get("parameters") or {}
    h = _handoff_dam(run_dir)
    for v, src in ((d.get("dam_id"), "run_setup.dam"), (prm.get("dam_id"), "run_setup.parameters"),
                   ((report or {}).get("dam_id"), "run_report"), (h.get("dam_id") or h.get("nid_id"), "damit_handoff.json"),
                   ((dj_fields or {}).get("dam_id"), "dam.json"), (d.get("nid_id"), "run_setup.dam.nid_id")):
        if v:
            return str(v), src
    if dam_folder:
        name = os.path.basename(os.path.abspath(dam_folder))
        if name:
            return name, "dam folder name"
    return None, None


def dam_facts(setup, dam_folder, report=None, run_dir=None):
    """Merge the dam record the run used with the dam folder's dam.json (for the streambed). `has_record` is False
    when the dam folder has no dam.json: the streambed and the stated datum are then unknown, and a dam id is taken
    from the run report, the hand-off or the folder name."""
    d = dict((setup or {}).get("dam") or {})
    prm = (setup or {}).get("parameters") or {}
    dj = _load_json(os.path.join(dam_folder, "dam.json")) if dam_folder else None
    fields = (dj or {}).get("fields") or {}
    sources = (dj or {}).get("sources") or {}
    streambed = _num(fields.get("streambed_elev_ft"))
    dam_id, dam_id_source = resolve_dam_id(setup, report, dam_folder, run_dir, fields)
    return {
        "dam_id": dam_id,
        "dam_id_source": dam_id_source,
        "has_record": dj is not None,
        "dam_folder": dam_folder,
        "name": d.get("name") or prm.get("name"),
        "height_ft": _num(d.get("height_ft"), _num(prm.get("height_ft"))),
        "top_ft": _num(d.get("top_of_dam_elev_ft"), _num(prm.get("top_ft"))),
        "streambed_ft": streambed,
        "breach_bottom_ft": _num(prm.get("bottom_ft")),
        "pmf_ft": _num(d.get("pmf_peak_elev_ft")),
        "stated_datum": fields.get("stated_datum") or fields.get("top_of_dam_datum") or d.get("stated_datum"),
        "top_source": (sources.get("top_of_dam_elev_ft") or {}).get("src"),
        "height_note": (sources.get("height_ft") or {}).get("note"),
        "ds_slope": _num(prm.get("ds_slope")),
        "dem_z": prm.get("z_units"),
    }


def check_dam_record(f, fl):
    """No dam.json in the dam folder: say so once (INFO), and what was used instead."""
    if f["has_record"]:
        return
    fl.add("DAM_RECORD_MISSING", INFO, "run", "no dam record (dam.json) in the dam folder",
           "streambed and stated datum are unknown; the dam id (%s) comes from %s%s. Checks that need the record "
           "fall back to the run's own values or are skipped (see the DATUM, HEIGHT and TOE notes)." % (
               f["dam_id"] or "unknown", f["dam_id_source"] or "nowhere",
               "" if f["dam_folder"] else "; no dam folder was found"), dam_id=f["dam_id"], source=f["dam_id_source"])


def check_height(f, fl, th=THRESHOLDS):
    top, h = f["top_ft"], f["height_ft"]
    bed = f["streambed_ft"]
    label = "streambed"
    used = "streambed"
    if bed is None and f["breach_bottom_ft"] is not None:
        bed, used = f["breach_bottom_ft"], "breach bottom used as streambed (no streambed in dam record)"
        label = used
    if None in (top, h, bed):
        return None
    diff = (top - bed) - h
    info = {"top_ft": top, "bed_ft": bed, "bed_label": label, "bed_source": "dam record" if used == "streambed" else "BOTTOM_FT", "crest_minus_bed_ft": round(top - bed, 2),
            "inventory_height_ft": h, "diff_ft": round(diff, 2)}
    if abs(diff) >= th["height_watch_ft"]:
        sev = PROBLEM if abs(diff) >= max(th["height_problem_ft"], th["height_problem_frac"] * h) else WATCH
        if used == "streambed":
            what = "crest minus streambed is %.1f ft" % (top - bed)
        else:
            what = "crest minus %s is %.1f ft" % (used, top - bed)
        fl.add("HEIGHT_MISMATCH", sev, "run", "%s; the inventory height is %.1f ft (%+.1f ft)" % (what, h, diff),
               "top of dam %.2f - %s %.2f; the toe band and breach size use the inventory height; check which is right "
               "before trusting the breach%s%s" % (
                   top, "streambed" if used == "streambed" else "breach bottom (BOTTOM_FT)", bed,
                   "" if used == "streambed" else ". The dam folder has no streambed elevation, so BOTTOM_FT stands in "
                   "for it; if BOTTOM_FT was raised to the reservoir bottom this is not the true streambed",
                   ("; record note: " + f["height_note"]) if f["height_note"] else ""), **info)
    return info


def check_bottom_raised(report, fl):
    notes = ((report or {}).get("hydrograph") or {}).get("notes") or []
    for n in notes:
        if "raised" in str(n).lower():
            fl.add("BREACH_BOTTOM_RAISED", WATCH, "run", "the breach bottom was raised to the reservoir bottom", str(n))
            return True
    return False


def check_datum(f, fl, th=THRESHOLDS):
    """DWR elevations are NAVD88 only. Evidence of another datum is a flag. A top of dam in the NAVD88 range with no
    datum stated is NOT an alarm (the Runner never writes a stated datum itself). Only when the elevation cannot be
    judged at all (no top of dam) is the datum reported, as an INFO note."""
    top = f["top_ft"]
    datum = (f["stated_datum"] or "").upper().replace(" ", "")
    dwr = (f["top_source"] or "").upper() == "DWR"
    local = top is not None and 0.0 <= top <= th["local_datum_max_ft"]
    navd_range = top is not None and th["local_datum_max_ft"] < top <= NAVD88_RANGE_MAX_FT
    info = {"top_ft": top, "stated_datum": f["stated_datum"], "source": f["top_source"], "local_datum": local,
            "has_dam_record": f["has_record"],
            "basis": ("stated NAVD88" if datum == "NAVD88" else "stated " + str(f["stated_datum"]) if datum else
                      "NAVD88 range (no datum stated)" if navd_range else "unknown")}
    if local or (datum and datum != "NAVD88"):
        why = ("%.1f ft is in the 0-%d ft range: treated as a LOCAL datum, not NAVD88" % (top, th["local_datum_max_ft"])
               if local else "stated datum is %s, not NAVD88" % f["stated_datum"])
        fl.add("DATUM", PROBLEM if (dwr or datum) else WATCH, "run", "elevations are not NAVD88: " + why,
               "DWR elevations are NAVD88 only (NGVD29 + VERTCON); a local or NGVD29 elevation against a NAVD88 DEM "
               "moves the whole breach", **info)
    elif not datum and not navd_range:
        fl.add("DATUM", INFO, "run", "unknown datum%s" % ("" if f["has_record"] else " (no dam record)"),
               "no top of dam elevation and no stated datum: the NAVD88 rule cannot be checked%s" % (
                   "" if f["has_record"] else "; the dam folder has no dam.json"), **info)
    return info


def check_start_wse(f, report, setup, fl, th=THRESHOLDS):
    h = (report or {}).get("hydrograph") or {}
    start, top = _num(h.get("starting_wse_ft")), f["top_ft"]
    info = {"starting_wse_ft": start, "top_ft": top, "pmf_ft": f["pmf_ft"], "rule": h.get("rule")}
    if start is not None and top is not None and abs(start - top) > th["start_wse_tol_ft"]:
        fl.add("START_WSE", PROBLEM, "run", "starting WSE %.2f ft is not the top of dam / max pool %.2f ft" % (start, top),
               "sunny-day rule: the reservoir starts at the top of dam (= the DWR max pool), no outlet or spillway flow%s" % (
                   "; the PMF level (%.2f ft) is only recorded" % f["pmf_ft"] if f["pmf_ft"] else ""), **info)
    elif h.get("rule") and "no outlet or spillway flow" not in str(h["rule"]).lower():
        fl.add("OUTLET_FLOW", WATCH, "run", "the hydrograph rule does not say 'no outlet or spillway flow'", str(h["rule"]))
    return info


def check_outlets(run_dir, passes, setup, fl):
    """Sunny day: the model has ONE source, the breach hydrograph. Any other boundary source is outlet or inflow."""
    extra = []
    for p in passes[-1:]:
        bci = os.path.join(run_dir, "model", p["dir"], "run.bci")
        try:
            with open(bci, encoding="utf-8", errors="replace") as f:
                for line in f:
                    t = line.split()
                    if len(t) >= 5 and t[0] in ("P", "p") and t[3].upper() in ("QVAR", "HVAR", "QFIX", "HFIX"):
                        if not (t[3].upper() == "QVAR" and t[4].lower() == "breach"):
                            extra.append(line.strip())
                    elif len(t) >= 4 and t[0] in ("N", "S", "E", "W") and t[3].upper() in ("QVAR", "HVAR", "QFIX", "HFIX"):
                        extra.append(line.strip())
        except OSError:
            pass
    for sc in (setup or {}).get("scenarios") or []:
        infl = ((sc or {}).get("params") or {}).get("inflow")
        if infl not in (None, "none", "None", 0, "0"):
            extra.append("scenario %s inflow=%s" % (sc.get("id"), infl))
    if extra:
        fl.add("OUTLET_FLOW", PROBLEM, "run", "the model has a source besides the breach (outlet / spillway / inflow)",
               "sunny day means outlets empty and no spillway flow; found: " + "; ".join(extra[:4]), sources=extra)
    return extra


def toe_expected(height_ft, slope, th=THRESHOLDS):
    """(inner_m, outer_m, slope_used, defaulted): the downstream-toe band the breach inflow goes in. Outer is
    H x (slope + 1) in metres, 3:1 when the slope is unknown, never under 5 m, never over 150 m."""
    s = slope if (slope is not None and slope > 0) else th["toe_default_slope"]
    outer = height_ft * FT * (s + 1.0)
    return th["toe_inner_m"], max(th["toe_inner_m"], min(th["toe_cap_m"], outer)), s, not (slope and slope > 0)


DAM_LINE_NAMES = ("dam_line.geojson", "dam_line_linestring.geojson", "dam_line.gpkg", "dam_line.shp")


def dam_line_places(dam_folder, run_dir=None, setup=None, dam_id=None):
    """Every folder where the DamIT suite keeps (or is told about) the dam line, most specific first (1.3.0). The Runner
    and the Screener do not agree on one place: the DWR-2824 retest had it in <work>/inputs/ (beside the terrain), with the
    dam folder <work>/dams/<id>/ and the run folder <work>/runs/<id>/<id>/run_<ts>/ holding none.
      - the dam folder, its inputs/, and the <work>/inputs/ and <work>/handoff/<dam id>/ beside its dams/ folder;
      - the run folder, its inputs/, and the same two beside the run folder's runs/ folder;
      - the folder of every input the run setup names (terrain, receptors, hydrographs: the Screener's inputs/ folder);
      - the hand-off folder (run_setup.handoff, damit_handoff.json) and a dam_line path the setup or hand-off gives."""
    out = []

    def add(p):
        if p and p not in out:
            out.append(p)

    def around(base, up):
        """base, base/inputs, and <work>/inputs, <work>/handoff/<id> where <work> is `up` levels above base."""
        if not base:
            return
        base = os.path.abspath(base)
        add(base)
        add(os.path.join(base, "inputs"))
        work = base
        for _ in range(up):
            work = os.path.dirname(work)
        if work and work != base:
            add(os.path.join(work, "inputs"))
            if dam_id:
                add(os.path.join(work, "handoff", str(dam_id)))
    around(dam_folder, 2)                                       # <work>/dams/<id>
    around(run_dir, 4)                                          # <work>/runs/<id>/<id>/run_<ts>
    setup = setup or {}
    for v in (setup.get("inputs") or {}).values():
        if isinstance(v, str) and v:
            add(os.path.dirname(os.path.abspath(v)))
    ho = setup.get("handoff")
    if isinstance(ho, str) and ho and run_dir:
        add(os.path.dirname(os.path.abspath(os.path.join(run_dir, ho))))
    add(run_dir and os.path.abspath(run_dir))
    return out


def find_dam_line(dam_folder, run_dir=None, setup=None, dam_id=None):
    """Path of a dam line file (dam_line.geojson and its relatives) in any known place, else None (1.3.0)."""
    for base in dam_line_places(dam_folder, run_dir, setup, dam_id):
        for name in DAM_LINE_NAMES:
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    for key in ("dam_line", "dam_line_file"):                     # a path the setup / hand-off names outright
        for src in ((setup or {}).get("inputs") or {}, (setup or {}).get("parameters") or {}):
            v = src.get(key)
            if isinstance(v, str) and v and os.path.exists(v):
                return v
    return None


def _dam_line_found(dam_folder, run_dir=None, setup=None, dam_id=None):
    return find_dam_line(dam_folder, run_dir, setup, dam_id) is not None


def check_toe(f, report, fl, th=THRESHOLDS, run_dir=None, setup=None):
    inflow = (report or {}).get("inflow")
    if not inflow:
        return None
    band = inflow.get("toe_band") or {}
    info = {"toe_band": band, "how": inflow.get("how")}
    m = re.search(r"([\d.]+)\s*m from the (?:dam )?line", str(inflow.get("how") or ""))
    dist = _num(m.group(1)) if m else None
    info["distance_m"] = dist
    line_path = find_dam_line(f.get("dam_folder"), run_dir, setup, f.get("dam_id"))
    line = line_path is not None
    info["dam_line_found"] = line
    info["dam_line_path"] = line_path
    if dist is not None:
        # The distance is the Runner's own measurement (it placed the inflow with the dam line it had). It is used as it
        # is, and the digest says where it came from; with no dam line to measure again this is an INFO note, not an
        # "unchecked" warning (1.2.0).
        info["distance_source"] = "run_report" if line else "run_report, no dam_line"
        if not line:
            fl.add("TOE_SOURCE_RUN_REPORT", INFO, "run", "toe from run_report, no dam_line",
                   "the inflow is %.0f m from the dam line by the Runner's own report (%s); no dam_line.geojson was found, so "
                   "the digest cannot measure it again and uses the Runner's number." % (dist, inflow.get("how") or "no text"),
                   **info)
    if dist is None:
        how = str(inflow.get("how") or "")
        fallback = "fallback" in how.lower()
        fl.add("TOE_UNCHECKED", WATCH if fallback else INFO, "run",
               "toe inflow position not checked: the report gives no distance from the dam line",
               "%s%s. The band (5 m to H x (slope+1), 150 m cap) can still be checked; the inflow point cannot." % (
                   "the Runner's own words: '%s'" % how if how else "no inflow description in the run report",
                   "; no dam_line.geojson was found" if not line else ""), **info)
    h = f["height_ft"]
    if h:
        lo, hi, s, defaulted = toe_expected(h, f["ds_slope"])
        info.update(expected_inner_m=lo, expected_outer_m=round(hi, 2), slope=s, slope_defaulted=defaulted,
                    height_ft_used=h)
        bo = _num(band.get("outer_m"))
        if bo is not None and abs(bo - hi) > th["toe_band_tol_m"]:
            fl.add("TOE_BAND", WATCH, "run", "the toe band ends at %.1f m; H x (slope+1) gives %.1f m" % (bo, hi),
                   "H %.1f ft = %.1f m, slope %.1f:1%s, cap %d m" % (h, h * FT, s, " (default 3:1)" if defaulted else "",
                                                                      th["toe_cap_m"]), **info)
        if dist is not None and not (lo - 0.5 <= dist <= max(hi, bo or 0.0) + 0.5):
            fl.add("TOE_INFLOW", PROBLEM, "run", "the breach inflow is %.0f m from the dam line, outside the toe band "
                   "%.0f-%.1f m" % (dist, lo, hi), "inflow belongs at the lowest ground in the downstream toe band "
                   "(5 m to H x (slope+1), 150 m cap)", **info)
    return info


def check_engine(report, fl):
    es = (report or {}).get("engine_selection") or {}
    eng = str((report or {}).get("engine") or "")
    if es.get("fallback") or "built-in" in eng.lower() or "builtin" in eng.lower():
        fl.add("ENGINE_FALLBACK", WATCH, "run", "the built-in flood engine ran, not LISFLOOD-FP",
               "a screening approximation (%s)" % (es.get("warning") or eng))
    w = (report or {}).get("warnings") or []
    if w:
        fl.add("RUN_WARNINGS", WATCH, "run", "the Runner logged %d warning(s)" % len(w), "; ".join(str(x) for x in w[:3]))


# ----------------------------------------------------------------------------- receptors
def neighbours_max(arr, r, c):
    import numpy as np
    r0, r1, c0, c1 = max(r - 1, 0), min(r + 2, arr.shape[0]), max(c - 1, 0), min(c + 2, arr.shape[1])
    win = arr[r0:r1, c0:c1]
    win = win[np.isfinite(win)]
    return float(win.max()) if win.size else 0.0


def receptor_check(grid, points, th=THRESHOLDS):
    """points: [(id, x, y)] in the raster's CRS; grid.data in ft with NaN = NoData.

    nodata: the cell under the receptor is NoData and a neighbour is wet (the receptor sits in a hole in the
    results, next to water); dry_next_to_wet: the cell is dry and a neighbour is at least near_wet_ft deep."""
    import numpy as np
    nodata, dry_next, outside, n = [], [], 0, 0
    a = grid.data
    for pid, x, y in points:
        r, c = grid.rowcol(x, y)
        if not (0 <= r < a.shape[0] and 0 <= c < a.shape[1]):
            outside += 1
            continue
        n += 1
        v = a[r, c]
        nb = neighbours_max(a, r, c)
        if not np.isfinite(v):
            if nb >= th["wet_ft"]:
                nodata.append((pid, round(nb, 2)))
        elif v < th["wet_ft"] and nb >= th["near_wet_ft"]:
            dry_next.append((pid, round(nb, 2)))
    return {"sampled": n, "outside": outside, "nodata_next_to_wet": nodata, "dry_next_to_wet": dry_next}


def load_points_csv(path):
    """CSV with columns id,x,y (x,y in the raster's CRS)."""
    pts = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pts.append((row.get("id") or row.get("fd_id") or "", float(row["x"]), float(row["y"])))
    return pts


def load_points_ogr(path, grid_wkt, id_fields=("fd_id", "bid", "usastrucid"), layer=None, limit=None):
    """Structure points from a vector layer, transformed to the raster CRS. Needs GDAL; None without it."""
    try:
        from osgeo import ogr, osr
    except ImportError:
        return None
    ogr.UseExceptions()
    ds = ogr.Open(path)
    lyr = ds.GetLayerByName(layer) if layer else ds.GetLayer(0)
    src = lyr.GetSpatialRef()
    dst = osr.SpatialReference()
    dst.ImportFromWkt(grid_wkt)
    for s in (src, dst):
        if s is not None and hasattr(s, "SetAxisMappingStrategy"):
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(src, dst) if (src is not None and not src.IsSame(dst)) else None
    names = [lyr.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(lyr.GetLayerDefn().GetFieldCount())]
    idf = next((f for f in id_fields if f in names), None)
    pts = []
    for feat in lyr:
        g = feat.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        g = g.Clone()
        if tr is not None:
            g.Transform(tr)
        if g.GetGeometryName().upper() != "POINT":
            g = g.Centroid()
        x, y = g.GetX(), g.GetY()
        pts.append((str(feat.GetField(idf)) if idf else str(feat.GetFID()), x, y))
        if limit and len(pts) >= limit:
            break
    return pts


def runner_nodata(grid):
    """The depth grid with the Runner's NoData convention, so a receptor reads the same at every hook (1.2.0). The Runner's
    final Depth (Max).tif writes depth <= 0 as NoData (flood/model.py write_outputs), so a dry cell there IS NoData. A pass's
    own run.max has 0.0 on dry cells; sampled as it is, the same receptor was "dry next to wet" at a pass hook and
    "NoData next to wet" at run_end. This maps <= 0 and non-finite to NaN for every source (GeoTIFF or pass grid)."""
    import numpy as np
    with np.errstate(invalid="ignore"):
        data = np.where(np.isfinite(grid.data) & (grid.data > 0), grid.data, np.nan)
    return Grid(data, grid.x0, grid.y0, grid.cell)


def check_receptors(depth_grid, points, fl, th=THRESHOLDS, grid_source=None):
    if depth_grid is None or not points:
        return None
    res = receptor_check(depth_grid, points)
    note = (" Sampled on %s." % grid_source) if grid_source else ""
    nd, dn = res["nodata_next_to_wet"], res["dry_next_to_wet"]
    if nd:
        fl.add("RECEPTOR_NODATA", WATCH, "receptors", "%d structure(s) sit on a NoData cell next to wet cells" % len(nd),
               "ids: %s. The results have a hole at the receptor; Hazard reads NoData as dry (0 ft) and can miss a "
               "real, shallow inundation. Check these by hand.%s" % (_ids("%s (neighbour %.2f ft)" % t for t in nd), note),
               ids=[t[0] for t in nd], neighbour_ft={t[0]: t[1] for t in nd}, grid_source=grid_source)
    if dn:
        fl.add("RECEPTOR_DRY_NEXT_TO_WET", WATCH, "receptors",
               "%d structure(s) are on a dry cell beside water at least %.1f ft deep" % (len(dn), th["near_wet_ft"]),
               "ids: %s. A coarse cell can miss a building next to deep water.%s" % (
                   _ids("%s (neighbour %.2f ft)" % t for t in dn), note), ids=[t[0] for t in dn], grid_source=grid_source)
    return res


# ----------------------------------------------------------------------------- hazard drivers
# layer_none_scored (Hazard 0.2.2, INFO) is deliberately NOT here: a layer that was supplied and sampled but has no receptor in the
# scored set needs no review; only no_layer (nothing of that kind was supplied) does.
REVIEW_CODES = {
    "trains_lookup": "trains/day came from a lookup CSV that is not in the shipped rules",
    "trains_unknown": "a rail line has no trains/day: the M9a High test is not confirmed",
    "judgment_zone": "a structure is in the TM-11 judgment zone (ND counts it as Medium)",
    "judgment_zone_to_high": "a judgment-zone hit was raised to High",
    "m1_zone": "TM-11 zone note",
    "m8a_unknown": "roads with unknown class/AADT are NOT scored (M8a)",
    "m8b_attr": "no sole_access attribute: sole-access test not scored (M8b)",
    "m6_damage_unknown": "M6 damage unknown",
    "no_layer": "a receptor layer was not supplied (e.g. lifelines, M11a)",
    "outside_domain": "receptors outside the routed domain were not scored",
    "m13_guessed": "M13 descriptor guessed",
}


def read_lookup_rows(path):
    rows = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except OSError:
        pass
    return rows


def check_hazard(report_json, fl, rail_lookup=None, th=THRESHOLDS):
    """Hazard drivers that need a person: what was not scored, what came from a lookup, what is judgment."""
    if not report_json:
        return None
    flags = report_json.get("flags") or []
    counts = {}
    for x in flags:
        code = x.get("code")
        if code in REVIEW_CODES:
            counts[code] = counts.get(code, 0) + max(1, len(x.get("receptors") or []))
    info = {"suggested_label": report_json.get("suggested_label"), "driving": report_json.get("driving"),
            "hits": len(report_json.get("hits") or []), "review_counts": counts}
    n_roads = counts.get("m8a_unknown", 0)
    if n_roads:
        fl.add("ROADS_UNSCORED", WATCH, "hazard", "%d road(s) with unknown class/AADT were not scored (M8a)" % n_roads,
               "overtopped roads with unknown AADT are unscored by DamIT (the older plugin scored them Medium by "
               "assumption); check whether any of them is wet", count=n_roads)
    other = {k: v for k, v in counts.items() if k not in ("m8a_unknown", "outside_domain", "trains_unknown",
                                                         "trains_lookup")}
    if other.get("judgment_zone") or other.get("judgment_zone_to_high") or other.get("no_layer") or other.get("m8b_attr") \
            or other.get("m6_damage_unknown") or other.get("m13_guessed"):
        fl.add("HAZARD_REVIEW", WATCH, "hazard", "Hazard drivers that need a person's review",
               "; ".join("%s x%d: %s" % (k, v, REVIEW_CODES[k]) for k, v in sorted(other.items())), counts=other)
    # rail trains/day
    layers = {str(l.get("role", "")).lower(): l for l in (report_json.get("layers") or [])}
    lookup_layer = layers.get("rail trains lookup")
    lk = (lookup_layer or {}).get("source") or rail_lookup
    ko = None
    if lk:
        for row in read_lookup_rows(lk):
            if (row.get("field") or "").strip().upper() == "SUBDIV" and (row.get("value") or "").strip().upper() == "KO":
                ko = _num(row.get("trains_per_day"))
    if counts.get("trains_unknown"):
        fl.add("RAIL_TRAINS", WATCH, "hazard", "%d rail line(s) have no trains/day" % counts["trains_unknown"],
               "give RAIL_TRAINS_LOOKUP a row; Nick's rule: BNSF KO subdivision = %g trains/day (DamSafety's value)" %
               th["bnsf_ko_trains_per_day"], count=counts["trains_unknown"])
    elif lk and ko is not None and abs(ko - th["bnsf_ko_trains_per_day"]) > 1e-9:
        fl.add("RAIL_TRAINS", WATCH, "hazard", "the lookup gives KO = %g trains/day, Nick's rule is %g" % (
            ko, th["bnsf_ko_trains_per_day"]), "lookup file: %s" % lk, ko=ko)
    elif lk and ko is not None:
        info["rail_ko_trains_per_day"] = ko
    return info


# ----------------------------------------------------------------------------- the digest
def find_hazard_report(run_dir, setup, dam_folder):
    for base in (dam_folder, (setup or {}).get("dam_folder")):
        if base:
            p = os.path.join(base, "classify", "damit_hazard_report.json")
            if os.path.exists(p):
                return p
    return None


def build_digest(run_dir, phase="run_end", dam_folder=None, points=None, points_path=None, structures_path=None,
                 upto_pass=None, now=None, stall_s=None, rail_lookup=None, depth_path=None, use_hazard=True):
    """The digest of one run folder (read-only). Returns a dict: verdict, flags, checks, text."""
    run_dir = os.path.abspath(run_dir)
    now = now if now is not None else time.time()
    setup = _load_json(os.path.join(run_dir, "run_setup.json"))
    report = _load_json(os.path.join(run_dir, "run_report.json"))
    progress = load_progress(run_dir)
    fl = Flags()
    bounds = (report or {}).get("bounds")
    if not bounds:
        bounds = None
    crs_wkt = (report or {}).get("crs_wkt") or progress.get("crs_wkt") or None
    pdirs = _pass_dirs(run_dir)
    if upto_pass is not None:
        pdirs = [d for d in pdirs if (_pass_number(d) or 0) <= upto_pass]
    rpasses = (report or {}).get("passes") or []
    passes = []
    for i, pd in enumerate(pdirs):
        rp = rpasses[i] if i < len(rpasses) else None
        passes.append(pass_record(run_dir, pd, rp, bounds, now))
    if not passes and not setup and not report:
        fl.add("NO_RUN_FILES", PROBLEM, "run", "no run files found", "expected run_setup.json, run_report.json and "
               "model/run*/ in " + run_dir)
    prm = (setup or {}).get("parameters") or {}
    dam_folder = _dam_folder(run_dir, setup, dam_folder)
    facts = dam_facts(setup, dam_folder, report, run_dir)
    check_dam_record(facts, fl)

    check_mass(passes, fl)
    check_edges(passes, fl, prm, in_progress=upto_pass is not None)
    check_progress(passes, report if upto_pass is None else None, fl, now, stall_s=stall_s)
    height = check_height(facts, fl)
    check_bottom_raised(report, fl)
    datum = check_datum(facts, fl)
    wse = check_start_wse(facts, report, setup, fl)
    check_outlets(run_dir, passes, setup, fl)
    toe = check_toe(facts, report, fl, run_dir=run_dir, setup=setup)
    check_engine(report, fl)

    # peak depth / velocity over wet cells, and receptors (needs numpy; GDAL for the GeoTIFF)
    peaks, rec = None, None
    final = _pass_dirs(run_dir)[-1:] if upto_pass is None else (pdirs[-1:])
    depth_grid = None
    try:
        live = upto_pass is not None             # a run in progress: the pass's own results, not the final outputs
        dp = depth_path or os.path.join(run_dir, "outputs", "Depth (Max).tif")
        depth_grid = read_tif(dp) if (os.path.exists(dp) and not live) else None
        grid_source = "outputs/Depth (Max).tif" if depth_grid is not None else None
        # the pass's own georeference: run_progress.json has it while the run is going (a pass's domain is not the final
        # one, and run_report.json does not exist yet); the report's bounds are the final domain's (1.3.0)
        pbounds = progress_pass(progress, final[0]).get("bounds") if final else None
        if not pbounds and not (live and progress):
            pbounds = bounds
        if depth_grid is None and final and pbounds:
            depth_grid = _pass_grid(final[0], ".max", pbounds, 1.0 / FT)
            grid_source = "the %s pass grid%s" % (os.path.basename(final[0]), (" (the run is in progress; the final Depth (Max).tif "
                                                  "can differ)" if live else ""))
        if depth_grid is not None:
            import numpy as np
            wet = np.isfinite(depth_grid.data) & (depth_grid.data >= THRESHOLDS["wet_ft"])
            vg = None
            vp = os.path.join(run_dir, "outputs", "Velocity (Max).tif")
            vg = read_tif(vp) if (os.path.exists(vp) and not live) else None
            if vg is None and final and pbounds:
                vg = _pass_grid(final[0], ".maxVc", pbounds, 1.0 / FT)
            peaks = {"peak_depth_ft": round(float(np.nanmax(np.where(wet, depth_grid.data, np.nan))), 2) if wet.any() else 0.0,
                     "peak_velocity_fps": (round(float(np.nanmax(np.where(wet, vg.data, np.nan))), 2)
                                           if (vg is not None and vg.data.shape == wet.shape and wet.any()) else None),
                     "wet_cells": int(wet.sum()), "wet_ft": THRESHOLDS["wet_ft"],
                     "flooded_acres": round(float(wet.sum()) * depth_grid.cell ** 2 / 4046.8564224, 1),
                     "definition": "maxima over wet cells (depth >= %.1f ft)" % THRESHOLDS["wet_ft"]}
            pts = points
            if pts is None and points_path:
                pts = load_points_csv(points_path)
            if pts is None:
                spath = structures_path
                hr = find_hazard_report(run_dir, setup, dam_folder) if (use_hazard and upto_pass is None) else None
                if spath is None and hr:
                    for l in (_load_json(hr) or {}).get("layers") or []:
                        if str(l.get("role", "")).lower() == "structures":
                            spath = l.get("source")
                if spath and not os.path.exists(spath):
                    fl.add("RECEPTORS_UNCHECKED", INFO, "receptors", "receptors not checked: the structure layer was not found",
                           "no file at %s" % spath)
                if spath and os.path.exists(spath) and crs_wkt:
                    pts = load_points_ogr(spath, crs_wkt)
                    if pts is None:
                        fl.add("RECEPTORS_UNCHECKED", INFO, "receptors", "receptors not checked: GDAL/OGR is not installed",
                               "the structure layer %s needs the osgeo Python package (QGIS or GDAL); the other checks "
                               "are unaffected" % os.path.basename(spath))
            if pts:
                rec = check_receptors(runner_nodata(depth_grid), pts, fl, grid_source=grid_source)
    except ImportError as e:
        fl.add("RECEPTORS_UNCHECKED", INFO, "receptors", "receptors not checked: a Python package is missing",
               "%s. The structure layer needs GDAL/OGR (osgeo) and the grids need numpy; the other checks are "
               "unaffected." % e)
    except Exception as e:                  # noqa: BLE001 - a raster problem must not stop the digest
        fl.add("NO_RUN_FILES", WATCH, "run", "could not read the result rasters: %s" % describe_error(e),
               error_detail(e), error_type=type(e).__name__)

    hazard = None
    if use_hazard and upto_pass is None:
        hp = find_hazard_report(run_dir, setup, dam_folder)
        if hp:
            hazard = check_hazard(_load_json(hp), fl, rail_lookup)

    flags = dedupe_flags(fl.items)
    complete = run_complete(run_dir, setup, report, progress)
    d = {"schema": SCHEMA, "version": VERSION, "run_dir": run_dir, "phase": phase, "dam_id": facts["dam_id"],
         "name": facts["name"], "verdict": verdict_of(flags), "verdict_set_by": "code (flags only; Lumo never changes it)",
         "flags": flags, "thresholds": THRESHOLDS,
         "checks": {"passes": [{k: v for k, v in p.items() if k != "mass_mtime"} for p in passes], "height": height,
                    "datum": datum, "start_wse": wse, "toe_inflow": toe, "peaks": peaks, "receptors": rec,
                    "hazard": hazard, "dam": facts,
                    "run": {"engine": (report or {}).get("engine") or (setup or {}).get("engine"),
                            "sim_time_hr": (report or {}).get("sim_time_hr"), "stop_reason": (report or {}).get("stop_reason"),
                            "finished": bool(report) or (setup or {}).get("status") == "finished",
                            "complete": complete[0], "complete_by": complete[1]}}}
    d["text"] = render_text(d)
    d["flags_text"] = render_flag_list(d)
    return d


# ----------------------------------------------------------------------------- the 20-40 line summary
MAX_LINES = 40


def render_text(d):
    """The digest as 20-40 lines of plain text (the first thing a person, or Lumo, reads)."""
    c, L = d["checks"], []
    dam = c["dam"]
    L.append("RUN DIGEST (%s) - %s %s" % (d["phase"], d["dam_id"] or "?", dam.get("name") or ""))
    L.append("VERDICT: %s (set by code from the flags below)" % d["verdict"])
    run = c["run"]
    L.append("Engine: %s | sim %s h | %s%s" % (run.get("engine") or "n/a", _fmt(run.get("sim_time_hr"), 1),
             "finished" if run.get("finished") else "RUNNING or incomplete",
             " | stop: %s" % run["stop_reason"] if run.get("stop_reason") else ""))
    L.append("Dam: height %s ft | top of dam %s ft (%s) | streambed %s ft" % (
        _fmt(dam.get("height_ft"), 1), _fmt(dam.get("top_ft"), 2), dam.get("stated_datum") or "datum ?",
        _fmt(dam.get("streambed_ft"), 2)))
    h = c.get("height")
    if h:
        L.append("Height: crest - %s = %.1f ft vs inventory %.1f ft (diff %+.1f ft)" % (
            h["bed_label"], h["crest_minus_bed_ft"], h["inventory_height_ft"], h["diff_ft"]))
    w = c.get("start_wse") or {}
    L.append("Start WSE %s ft vs top of dam = max pool %s ft (sunny day: no outlet or spillway flow)" % (
        _fmt(w.get("starting_wse_ft"), 2), _fmt(w.get("top_ft"), 2)))
    t = c.get("toe_inflow")
    if t:
        src = " (toe from %s)" % t["distance_source"] if t.get("distance_source") == "run_report, no dam_line" else ""
        L.append("Toe inflow: %s m from the dam line%s; band %s-%s m (H x (%s:1 + 1), cap %d m)" % (
            _fmt(t.get("distance_m"), 0), src, _fmt(t.get("expected_inner_m"), 0), _fmt(t.get("expected_outer_m"), 1),
            _fmt(t.get("slope"), 1), THRESHOLDS["toe_cap_m"]))
    ps = c["passes"]
    if ps:
        L.append("Passes (%d): pass | sim h | mass err %% | edge outflow %% | wet edges" % len(ps))
        for p in ps[:8]:
            ed = p.get("edge_depths_ft") or {}
            wet = "/".join(k for k, v in sorted(ed.items()) if (_num(v, 0) or 0) >= THRESHOLDS["edge_wet_ft"]) or "none"
            L.append("  %s | %s | %s | %s | %s%s" % (p["pass"], _fmt(p["sim_time_hr"], 1), _fmt(p["mass_error_pct"], 3),
                     _fmt(p["outflow_pct"], 1), wet, "" if p["finished"] in (True, None) else " | UNFINISHED"))
        if len(ps) > 8:
            L.append("  ... %d more pass(es)" % (len(ps) - 8))
    pk = c.get("peaks")
    if pk:
        L.append("Peaks over wet cells (>= %.1f ft): depth %s ft, velocity %s ft/s, flooded %s ac" % (
            pk["wet_ft"], _fmt(pk["peak_depth_ft"], 2), _fmt(pk["peak_velocity_fps"], 2), _fmt(pk.get("flooded_acres"), 0)))
    r = c.get("receptors")
    if r:
        L.append("Receptors sampled %d (outside raster %d): NoData-next-to-wet %d, dry-next-to-deep-water %d" % (
            r["sampled"], r["outside"], len(r["nodata_next_to_wet"]), len(r["dry_next_to_wet"])))
    hz = c.get("hazard")
    if hz:
        L.append("Hazard (DamIT): %s; unscored roads %s" % (hz.get("suggested_label") or "n/a",
                 hz["review_counts"].get("m8a_unknown", 0)))
    fl = sorted(d["flags"], key=lambda x: -_RANK.get(x["severity"], 0))
    L.append("FLAGS (%d): %s" % (len(fl), ", ".join("%s %s" % (x["severity"], x["id"]) for x in fl) or "none"))
    budget = MAX_LINES - len(L) - 1
    shown = 0
    scored = [x for x in fl if x["severity"] != INFO]
    for x in scored:
        if budget - shown <= 0:
            break
        ids = flag_ids_text(x)
        L.append("- [%s] %s: %s%s" % (x["severity"], x["where"], x["title"], " [%s]" % ids if ids else ""))
        shown += 1
    if shown < len(scored):
        L.append("- ... %d more flag(s): see the complete flag list" % (len(scored) - shown))
    return "\n".join(L[:MAX_LINES])


def flag_sort_key(x):
    return (-_RANK.get(x["severity"], 0), x["id"], str(x["where"]))


def render_flag_list(d, detail_chars=170):
    """EVERY flag, deterministically (code, not a model): numbered, severity first, INFO notes last. Nothing is
    capped or left out; Lumo's commentary is written under this list and never replaces it."""
    fl = sorted(d["flags"], key=flag_sort_key)
    n = {k: sum(1 for x in fl if x["severity"] == k) for k in (PROBLEM, WATCH, INFO)}
    L = ["COMPLETE FLAG LIST - %d flag(s): %d PROBLEM, %d WATCH, %d INFO (verdict %s, set by code)" % (
        len(fl), n[PROBLEM], n[WATCH], n[INFO], d["verdict"])]
    for i, x in enumerate(fl, 1):
        ids = flag_ids_text(x)
        L.append("%d. [%s] %s (%s): %s%s" % (i, x["severity"], x["id"], x["where"], x["title"], " [%s]" % ids if ids else ""))
        det = " ".join(str(x.get("detail") or "").split())
        if det:
            L.append("   %s%s" % (det[:detail_chars], "..." if len(det) > detail_chars else ""))
    if not fl:
        L.append("(no flags)")
    return "\n".join(L)


def machine_flags(d):
    """The JSON a script reads: the verdict and every flag (id, severity, where, title, detail, data)."""
    return {"schema": SCHEMA, "version": VERSION, "dam_id": d["dam_id"], "phase": d["phase"], "verdict": d["verdict"],
            "flags": d["flags"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic digest of one DamIT Runner run (no LLM).")
    ap.add_argument("run_dir")
    ap.add_argument("--phase", default="run_end", choices=("pass_end", "stall", "before_hazard", "after_hazard", "run_end"))
    ap.add_argument("--pass", dest="upto", type=int, default=None, help="digest only passes up to N (a run in progress)")
    ap.add_argument("--dam-folder")
    ap.add_argument("--points", help="CSV id,x,y of receptors in the raster CRS")
    ap.add_argument("--structures", help="structure layer (gpkg/shp) when there is no Hazard report yet")
    ap.add_argument("--rail-lookup")
    ap.add_argument("--stall-s", type=float, default=None)
    ap.add_argument("--json", action="store_true", help="print the machine flags as JSON instead of the text")
    ap.add_argument("--out", help="write digest.json and digest.txt here (never into the run folder)")
    ap.add_argument("--exit-code", action="store_true", help="exit 0 OK, 1 WATCH, 2 PROBLEM")
    a = ap.parse_args(argv)
    d = build_digest(a.run_dir, a.phase, a.dam_folder, points_path=a.points, structures_path=a.structures,
                     upto_pass=a.upto, stall_s=a.stall_s, rail_lookup=a.rail_lookup)
    if a.out:
        if os.path.abspath(a.out).startswith(os.path.abspath(a.run_dir) + os.sep):
            print("refusing to write into the run folder", file=sys.stderr)
            return 2
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "digest.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, default=str)
        with open(os.path.join(a.out, "digest.txt"), "w", encoding="utf-8") as f:
            f.write(d["text"] + "\n")
    print(json.dumps(machine_flags(d), indent=1, default=str) if a.json else d["text"])
    return {OK: 0, WATCH: 1, PROBLEM: 2}[d["verdict"]] if a.exit_code else 0


if __name__ == "__main__":
    sys.exit(main())
