"""A SMALL SYNTHETIC DamIT Runner run folder for the Lumo watcher tests.

Everything here is made up: a 20 x 20 grid of 50 m cells, invented elevations and ids. It reproduces the
shapes of the real DWR-2658 review findings (37 vs 39 ft, early-pass edge outflow, a structure in a NoData
pocket next to wet cells) without any DWR data, DSS-WISE or LISFLOOD rasters."""
import csv
import json
import os

NROWS = NCOLS = 20
CELL = 50.0
BOUNDS = [0.0, 0.0, NCOLS * CELL, NROWS * CELL]            # xmin, ymin, xmax, ymax
M_PER_FT = 0.3048

MASS_HEAD = ("Time         Tstep      MinTstep   NumTsteps    Area         Vol         Qin         Hds        "
             "Qout          Qerror       Verror       Rain-(Inf+Evap)\n")


def mass_text(n=11, step=300.0, qin=10.0, qout=0.0, verr=0.0, nan_row=None, vol_scale=1.0):
    """A .mass file: Qin constant, Qout constant, interval volume error verr (m3) on every row."""
    lines = [MASS_HEAD]
    vol = 0.0
    for i in range(n):
        t = i * step if i else 10.0
        vol = qin * t * vol_scale
        q_in = "nan" if nan_row == i else "%.3f" % qin
        lines.append("%-12.3f %-10.4f %-10.4f %-12d %-12.4f %-12.4f %-11s %-10.3f %-10.3f %-12.4f %-12.4f %-12.4f\n" % (
            t, 10.0, 10.0, i * 10, 1000.0, vol, q_in, 0.0, qout, 0.0, verr, 0.0))
    return "".join(lines)


def asc_text(arr, nodata=-9999.0):
    head = "ncols %d\nnrows %d\nxllcorner 0.000000\nyllcorner 0.000000\ncellsize %.6f\nNODATA_value %.6f\n" % (
        arr.shape[1], arr.shape[0], CELL, nodata)
    body = "\n".join("\t".join("%.3f" % (nodata if v != v else v) for v in row) for row in arr)
    return head + body + "\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def centre(row, col):
    """x, y of a cell centre (rows count down from the top edge, y = 1000 m)."""
    return (col + 0.5) * CELL, BOUNDS[3] - (row + 0.5) * CELL


POCKET = (8, 8)         # the DEM / result hole (NoData) inside the water
WET_CELL = (6, 6)
DRY_BESIDE_DEEP = (5, 13)    # a cell with only a trace of water, next to the blob's east side (cols 5..12 wet)
DRY_ZERO_BESIDE_DEEP = (5, 4)   # a cell with 0.0 depth next to the blob's west side: NoData in the Runner's own outputs
FAR_DRY = (17, 17)


def receptor_rows():
    return [("900000001", ) + centre(*POCKET), ("900000002", ) + centre(*WET_CELL),
            ("900000003", ) + centre(*DRY_BESIDE_DEEP), ("900000004", ) + centre(*FAR_DRY)]


def make_run(root, report=True, passes=3, final_leak=False, mass_nan=False, verr=0.0, unfinished=False,
             top_ft=1500.0, streambed_ft=1461.0, height_ft=37.0, datum="NAVD88", src="DWR", start_wse=None,
             extra_bci=None, toe_distance=39.0, toe_outer=None, ds_slope=2.5, hazard=False, trains_ko=15.0,
             unscored_roads=0, west_edge_wet_ft=0.0, mass_in_report=None, inflow_scenario="none",
             dam_record=True, setup_dam_id=True, inflow_how=None, handoff=False):
    import numpy as np
    run = os.path.join(root, "dams", "TST00001", "run_20260101_000000")      # run folder
    dam_folder = os.path.join(root, "dams_folder", "TST00001")
    os.makedirs(run, exist_ok=True)
    bottom = streambed_ft
    setup = {"schema": "damit.run_setup", "status": "finished", "model_launched": True, "engine": "LISFLOOD-FP (/x/lisflood)",
             "dam_folder": dam_folder, "mode": "preset", "preset_id": "ND",
             "scenarios": [{"id": "S3", "params": {"pool": "min(top_of_dam, pmf_peak)", "inflow": inflow_scenario}}],
             "dam": {"dam_id": "TST00001", "name": "Synthetic Test Dam", "height_ft": height_ft, "top_of_dam_elev_ft": top_ft,
                     "pmf_peak_elev_ft": None, "stated_datum": datum},
             "parameters": {"edge_tol_ft": 1.0, "outflow_extend_pct": 5.0, "cell_m": CELL, "bottom_ft": bottom,
                            "top_ft": top_ft, "height_ft": height_ft, "ds_slope": ds_slope, "dam_id": "TST00001",
                            "z_units": "m"}}
    if not dam_record:                      # what the Screener/Runner path leaves: no dam.json, no stated datum
        setup["dam"].pop("stated_datum", None)
    if not setup_dam_id:
        setup["dam"].pop("dam_id", None)
        setup["parameters"].pop("dam_id", None)
    write(os.path.join(run, "run_setup.json"), json.dumps(setup))
    if handoff:
        write(os.path.join(run, "damit_handoff.json"), json.dumps({"dam": {"dam_id": "TST00001", "nid_id": "TST00001"}}))
    # dam folder
    fields = {"dam_id": "TST00001", "height_ft": height_ft, "top_of_dam_elev_ft": top_ft, "streambed_elev_ft": streambed_ft,
              "stated_datum": datum}
    os.makedirs(dam_folder, exist_ok=True)
    if dam_record:
        write(os.path.join(dam_folder, "dam.json"), json.dumps({"fields": fields, "sources": {
            "top_of_dam_elev_ft": {"src": src, "field": "max_pool_e_navd88", "value": top_ft}}}))
    # passes: 1 and 2 leak through N and W (early), later ones are clean unless final_leak
    rp = []
    for n in range(1, passes + 1):
        d = os.path.join(run, "model", "run%02d_50m" % n)
        early = n <= 2 and passes > 2
        leak = early or (final_leak and n == passes)
        out_pct = 10.0 if leak else 0.0
        write(os.path.join(d, "run.par"), "DEMfile run.dem.asc\nsim_time 3000\nmassint 300\n")
        bci = "P 475.000 475.000 QVAR breach\nN 0.000 1000.000 FREE\nS 0.000 1000.000 FREE\nE 0.000 1000.000 FREE\nW 0.000 1000.000 FREE\n"
        if extra_bci and n == passes:
            bci += extra_bci + "\n"
        write(os.path.join(d, "run.bci"), bci)
        last_unfinished = unfinished and n == passes
        write(os.path.join(d, "lisflood.log"), "Start Time: 0:00:01\n" if last_unfinished else
              "Start Time: 0:00:01\nFinish Date: 01/01/2026\nTotal computation time: 0.01 mins\n")
        nrows = 11 if not last_unfinished else 4
        write(os.path.join(d, "results", "run.mass"),
              mass_text(n=nrows, qout=1.0 if leak else 0.0, verr=verr if n == passes else 0.0,
                        nan_row=3 if (mass_nan and n == passes) else None))
        depth = np.zeros((NROWS, NCOLS))
        depth[5:13, 5:13] = 2.0                              # a 2 m blob
        depth[DRY_BESIDE_DEEP] = 0.02                        # a trace (0.07 ft, under the 0.1 ft wet limit) beside the blob
        if leak:
            depth[0, 10] = 0.25                              # N edge, 0.82 ft
            depth[10, 0] = 0.26                              # W edge
        if west_edge_wet_ft and n == passes:
            depth[12, 0] = west_edge_wet_ft * M_PER_FT
        vel = np.where(depth > 0, 1.5, 0.0)
        dem = np.full((NROWS, NCOLS), 100.0)
        dem[POCKET] = np.nan                                  # the hole in the results
        depth[POCKET] = 0.0
        write(os.path.join(d, "results", "run.max"), asc_text(depth))
        write(os.path.join(d, "results", "run.maxVc"), asc_text(vel))
        write(os.path.join(d, "results", "run.dem"), asc_text(dem))
        rec = {"run": 1 if n <= 2 else 2, "pass": n, "bounds": BOUNDS, "cell_m": CELL, "cells": NROWS * NCOLS,
               "sim_time_hr": 7.0 * n if n < passes else 35.5, "edge_depths_ft": {
                   "N": 0.82 if leak else 0.0, "S": 0.0, "W": 0.85 if leak else (west_edge_wet_ft or 0.0), "E": 0.0},
               "over": ["N", "W"] if (leak and n == 2) else [], "over_outflow": ["N", "W"] if (leak and n == 2) else [],
               "boundary_outflow_pct": out_pct, "still_moving": n == passes and False, "flooded_acres": 100.0 + n,
               "max_depth_ft": 6.56}
        if mass_in_report is not None and n == passes:
            rec["max_volume_error_pct"] = mass_in_report
        rp.append(rec)
    if report:
        outer = toe_outer if toe_outer is not None else round(height_ft * M_PER_FT * (ds_slope + 1.0), 4)
        write(os.path.join(run, "run_report.json"), json.dumps({
            **({"dam_id": "TST00001"} if setup_dam_id else {}), "engine": "LISFLOOD-FP (/x/lisflood)", "engine_selection": {"fallback": False, "warning": None},
            "sim_time_hr": 35.5, "bounds": BOUNDS, "crs_wkt": "", "passes": rp, "stop_reason": None, "warnings": [],
            "hydrograph": {"starting_wse_ft": start_wse if start_wse is not None else top_ft,
                           "rule": "sunny day, no outlet or spillway flow, starting at the top of dam",
                           "notes": ["The breach bottom is below the reservoir bottom (top of dam minus dam height); it was "
                                     "raised to the reservoir bottom."] if abs((top_ft - streambed_ft) - height_ft) > 0.5 else []},
            "inflow": {"how": inflow_how or "lowest ground at the downstream toe band, %d m from the line, 34.9 ft below the top of dam" % toe_distance,
                       "toe_band": {"inner_m": 5.0, "outer_m": outer, "height_known": True, "cap_m": 150.0}},
            "outputs": {}}))
    if hazard:
        flags = [{"level": "info", "code": "s7_not_applicable", "message": "S7", "receptors": []}]
        if unscored_roads:
            flags.append({"level": "warning", "code": "m8a_unknown", "message": "roads unknown", "receptors":
                          ["road:%d" % i for i in range(unscored_roads)]})
        lk = os.path.join(root, "rail_lookup.csv")
        with open(lk, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["field", "value", "trains_per_day", "source"])
            w.writerow(["SUBDIV", "KO", "%g" % trains_ko, "test"])
        write(os.path.join(dam_folder, "classify", "damit_hazard_report.json"), json.dumps({
            "suggested_label": "Low", "driving": [], "hits": [], "flags": flags,
            "layers": [{"role": "rail trains lookup", "source": lk}]}))
    return run, dam_folder


def write_points(root, rows=None):
    p = os.path.join(root, "points.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "x", "y"])
        for r in (rows or receptor_rows()):
            w.writerow(r)
    return p
