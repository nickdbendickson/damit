"""DamIT Runner's breach run: the DamSafety Runner's one-dam workflow on LISFLOOD-FP (or the built-in engine), with
the ANUGA tier, for DamIT. The engine: LISFLOOD_EXE, else the provider setting, NDBREACH_LISFLOOD, PATH or an install
place, else the built-in engine with a warning (lisflood.find_exe); the record keeps which one ran and why
(engine_selection).

  1. the sunny-day breach hydrograph (breach.make_hydrograph: no inflow, no outlet or spillway flow, the reservoir
     starting at the top of dam; METHOD piping, TR-60 or another of the DamSafety methods, or the user's CSV);
  2. the breach inflow at the lowest ground of the downstream toe band, 5 m to H x (downstream slope + 1) out
     (3:1 when the slope is not known), at most 150 m from the dam line, the side check on (geom.place_inflow);
  3. the first domain: the steepest-descent path from the inflow (LENGTH_MI) on a depression-filled planning DEM
     (cell max(30 m, CELL)), HALF_WIDTH_MI either side, snapped to the model cell;
  4. the automatic clock: the hydrograph duration + the domain diagonal / 0.5 m/s, at least 2 h, at most
     DURATION_MAX_HR (and 336 h);
  5. LISFLOOD-FP runs; an edge deeper than EDGE_TOL_FT moves out by STEP_MI, and so does an edge that carries
     >= 10 % of the outflow once OUTFLOW_EXTEND_PCT (5 %) of the breach volume has left the model (up to MAX_EXTENT_MI and MAX_RUNS
     domain runs); a flood still arriving in the last 10 % of the clock gets 1.5 x the clock (not a domain run);
     a run is stopped at its wall-clock limit (LISFLOOD_MAX_WALL_S, 0 = 24 h) and the loop at its budget
     (LISFLOOD_MAX_TOTAL_WALL_S, 0 = MAX_RUNS x the per-run limit);
  6. GRID_REFINE: a coarse (> 10 m) run that floods >= 1,000 ac with a median wet depth <= 1 ft is run again at
     10 m on the same domain and clock, and that run is the record;
  7. TIER 1 (or FORCE_ANUGA): ANUGA on the DamSafety Runner's default mesh over that extent (mesh.py; once more
     with the buffer doubled when it reaches the mesh edge); its maxima are the final results;
  8. the final rasters (ft, ft/s, h) and vectors under DamSafety names.
"""
import json
import math
import os
import time

import numpy as np

from . import breach as BR
from . import geom as G
from . import lisflood as LF
from . import rasters as R
from .units import ACRE, FT, MILE

MAX_SIM_S = 336 * 3600.0
FRONT_SPEED_MPS = 0.5
PLANNING_CELL_M = 30.0
GRID_REFINE_CELL_M = 10.0
GRID_SPREAD_WARN_CELL_M = 10.0
GRID_SPREAD_WARN_MIN_AC = 1000.0
GRID_SPREAD_WARN_MEDIAN_FT = 1.0
OUTFLOW_EDGE_SHARE = 0.10
OUTFLOW_WARN_PCT = 5.0       # DamSafety H08: warn when at least this share of the volume left the model
DEPTH_CLASSES_FT = (0.0, 1.0, 3.0, 6.0, 10.0)
TIERS = ("LISFLOOD-FP only", "LISFLOOD-FP for the extent, then ANUGA (final results from ANUGA)",
         "LISFLOOD-FP then HEC-RAS 2D (final results from HEC-RAS; needs HEC-RAS 6.6, see help)")
TIER_LISFLOOD, TIER_ANUGA, TIER_HECRAS = 0, 1, 2

FINAL_RASTERS = {"depth": ("Depth (Max).tif", "ft"), "velocity": ("Velocity (Max).tif", "ft/s"),
                 "arrival": ("Arrival Time.tif", "hours after breach"), "wse": ("WSE (Max).tif", "ft")}
QA_RASTERS = {"depth": "hmax_ft.tif", "velocity": "vmax_fps.tif", "arrival": "arr_hr.tif", "wse": "wsemax_ft.tif"}
VECTORS = {"depth_polygons": "Flood Polygons (Max Depth).geojson", "extent": "Flood Extent.geojson",
           "arrival_zones": "Arrival Zones.geojson"}

DEFAULTS = dict(method=BR.METHOD_PIPING, tier=TIER_LISFLOOD, force_anuga=False, cell_m=10.0, manning=0.06,
                arrival_ft=0.1, edge_tol_ft=1.0, outflow_extend_pct=5.0, length_mi=4.0, half_width_mi=1.0,
                step_mi=3.0, max_extent_mi=20.0, max_runs=6, max_wall_s=0.0, max_total_wall_s=0.0, duration_hr=0.0,
                duration_max_hr=96.0, grid_refine=True, grid_check_cell_m=0.0, lisflood_exe="", anuga_python="",
                anuga_fine_m2=100.0, anuga_coarse_m2=1000.0, anuga_near_mi=1.0, anuga_buffer_m=500.0, threads=0,
                keep_files=True, products=True, contours_hr=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0), z_units="auto",
                pipe_fraction=0.5, pipe_dia_ft=0.5,
                # 0.5.0: the scenario. The preset is the sunny day from the top of dam with a piping breach.
                scenario="sunny", start_pool="top", trigger="peak")
# 0.5.0: the scenarios (the ids of the ported engine's core/workflow.py)
SCENARIO_SUNNY, SCENARIO_FLOOD, SCENARIO_FLOOD_NO_BREACH = "sunny", "flood", "flood_no_breach"
SCENARIOS = (SCENARIO_SUNNY, SCENARIO_FLOOD, SCENARIO_FLOOD_NO_BREACH)
SCENARIO_LABELS = {
    SCENARIO_SUNNY: "Sunny day: no inflow; the breach starts at the top of dam unless you choose another pool",
    SCENARIO_FLOOD: "Flood (PMP/PMF inflow) with a breach",
    SCENARIO_FLOOD_NO_BREACH: "Flood (PMP/PMF inflow), NO breach: through the spillways and over the crest"}
START_POOLS = ("top", "normal", "stated")           # breach.START_POOLS
START_POOL_LABELS = {"top": "Top of dam (the preset)", "normal": "Normal pool (NORMAL_POOL_FT)",
                     "stated": "An elevation I state (START_WSE_FT)"}
TRIGGERS = ("peak", "time", "wse")                  # core/flood.py TRIGGERS
TRIGGER_LABELS = {"peak": "at the highest pool level", "time": "at a set time (hours after the inflow starts)",
                  "wse": "when the pool reaches an elevation (ft)"}


class RunError(RuntimeError):
    pass


def grid_spread_flagged(cell_m, flooded_acres, median_depth_ft):
    return (cell_m > GRID_SPREAD_WARN_CELL_M and flooded_acres >= GRID_SPREAD_WARN_MIN_AC
            and median_depth_ft <= GRID_SPREAD_WARN_MEDIAN_FT)


def auto_sim_time(duration_s, bounds, cap_s):
    w, h = bounds[2] - bounds[0], bounds[3] - bounds[1]
    t = duration_s + math.hypot(w, h) / FRONT_SPEED_MPS
    return float(min(cap_s, MAX_SIM_S, max(2 * 3600.0, t)))


def snap_bounds(b, cell):
    return (math.floor(b[0] / cell) * cell, math.floor(b[1] / cell) * cell,
            math.ceil(b[2] / cell) * cell, math.ceil(b[3] / cell) * cell)


def edge_flux_shares(depth, valid=None):
    d = np.where(np.isfinite(depth), depth, 0.0)
    if valid is not None:
        d = np.where(valid, d, 0.0)
    d = np.clip(d, 0.0, None) ** (5.0 / 3.0)
    w = {"N": float(d[0, :].sum()), "S": float(d[-1, :].sum()), "W": float(d[:, 0].sum()), "E": float(d[:, -1].sum())}
    tot = sum(w.values())
    return {k: (v / tot if tot > 0 else 0.0) for k, v in w.items()}


# ------------------------------------------------------------------------------------------------- site --
def site(p, wkt, log):
    """Dam point, line, downstream side and inflow point in the model CRS. p holds lon/lat inputs."""
    ll = p.get("dam_lonlat")
    line_ll = p.get("dam_line_lonlat")
    point_given = bool(ll) or bool(p.get("dam_point_given"))
    if not ll and line_ll:
        a = np.asarray(line_ll, float)
        ll = (float(a[:, 0].mean()), float(a[:, 1].mean()))
    if not ll:
        raise RunError("no dam position: give X / Y (or a dam folder with dam.json lon / lat or dam_line.geojson)")
    dam_xy = R.transform_points([ll], "EPSG:4326", wkt)[0]
    inventory_xy, inventory_ll = dam_xy, (float(ll[0]), float(ll[1]))
    line = R.transform_points(line_ll, "EPSG:4326", wkt) if line_ll and len(line_ll) >= 2 else None
    dam_point = None
    if line is not None and point_given:
        length_m = G.polyline_length_m(line)
        dist = G.distance_to_polyline_m(inventory_xy, line)
        thr = G.off_line_threshold_m(length_m)
        off = dist is not None and dist > thr
        note = None
        if off:
            note = ("the inventory / official point is {:.0f} m from the dam line (threshold {:.0f} m: "
                    "100 m, or half the {:.0f} m line when that is shorter). The model uses the dam line; "
                    "check that the point and the line are the same dam (DWR-2659: the official DWR point "
                    "sat on a different pool)."
                    .format(dist, thr, length_m))
        dam_point = {"lonlat": [inventory_ll[0], inventory_ll[1]],
                     "xy": [float(inventory_xy[0]), float(inventory_xy[1])],
                     "line_distance_m": None if dist is None else round(float(dist), 1),
                     "threshold_m": round(float(thr), 1), "dam_line_length_m": round(float(length_m), 1),
                     "off_line": bool(off), "how": note}
    if line is not None and not p.get("dam_point_given"):
        a = np.asarray(line, float)
        mids = 0.5 * (a[:-1] + a[1:])
        k = int(np.argmin(np.hypot(mids[:, 0] - dam_xy[0], mids[:, 1] - dam_xy[1])))
        dam_xy = (float(mids[k, 0]), float(mids[k, 1])) if len(a) == 2 else dam_xy
        if dam_point is not None:
            dam_point["snapped_xy"] = [float(dam_xy[0]), float(dam_xy[1])]
    res_xy = None
    if p.get("reservoir_lonlat"):
        res_xy = R.transform_points([p["reservoir_lonlat"]], "EPSG:4326", wkt)[0]
    downstream, how = G.downstream_from(dam_xy, line, res_xy, p.get("azimuth_deg"))
    span = 250.0
    if line is not None:
        a = np.asarray(line, float)
        span += 0.5 * float(np.hypot(*(a.max(axis=0) - a.min(axis=0))))
    fine_cell = max(1.0, min(float(p.get("fine_cell_m") or 2.0), float(p["cell_m"])))
    fb = (dam_xy[0] - span, dam_xy[1] - span, dam_xy[0] + span, dam_xy[1] + span)
    fine = R.read_window(p["dem"], snap_bounds(fb, fine_cell), fine_cell, wkt, p.get("z_units"))
    if downstream is None:
        downstream, how = G.downstream_from_dem(fine, dam_xy, line)
    top_m = float(p["top_ft"]) * FT
    h_m = float(p["height_ft"]) * FT
    ds_slope = p.get("ds_slope")
    if p.get("inflow_lonlat"):
        inflow, note, band = R.transform_points([p["inflow_lonlat"]], "EPSG:4326", wkt)[0], "given (INFLOW_POINT)", None
    elif p.get("inflow_xy"):
        inflow, note, band = tuple(p["inflow_xy"]), "given (INFLOW_POINT, model CRS)", None
    else:
        inflow, note, band = G.place_inflow(fine, dam_xy, line, downstream, h_m, top_m, ds_slope)
    if inflow is None:
        raise RunError("no breach inflow point: " + note)
    z_near = np.nanmin(fine.data) if np.isfinite(fine.data).any() else float("nan")
    checks = []
    if np.isfinite(z_near) and (z_near > top_m or top_m - z_near > 10 * max(h_m, 1.0)):
        checks.append("the DEM near the dam ({:.1f} ft) does not fit the top of dam {:.2f} ft and height {:.1f} ft; "
                      "check the DEM's vertical units and datum (Z_UNITS)".format(z_near / FT, top_m / FT, h_m / FT))
    log("Breach inflow at {:.1f}, {:.1f}: {}".format(inflow[0], inflow[1], note))
    z_how = getattr(fine, "z_how", None)
    if z_how:
        log("DEM elevations: " + z_how)
    if dam_point and dam_point.get("off_line") and dam_point.get("how"):
        checks.append(dam_point["how"])
        log("Warning: " + dam_point["how"])
    return {"dam_xy": dam_xy, "line": line, "reservoir_xy": res_xy, "downstream": downstream, "downstream_how": how,
            "inflow_xy": inflow, "inflow_how": note, "toe_band": band, "fine_cell_m": fine_cell, "checks": checks,
            "dam_point": dam_point, "z_how": z_how, "z_to_m": getattr(fine, "z_to_m", None)}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def flood_inputs(p, dam):
    """0.5.0: the flood (PMP/PMF) inputs of a flood scenario from the run parameters: the inflow hydrograph CSV
    (hours, cfs), a spillway rating CSV (ft, cfs) and/or the normal pool, an auxiliary spillway weir, and when the
    dam fails. The routing is the ported engine's core/flood.py (the same code as the DamSafety Runner)."""
    from ..core import flood as FL
    inflow = p.get("inflow_csv")
    if not inflow or not os.path.isfile(str(inflow)):
        raise RunError("the flood scenario needs the inflow hydrograph CSV (INFLOW_CSV: time hr, discharge cfs; "
                       "DamIT PMP writes one): {}".format(inflow))
    spill = p.get("spillway_csv") or None
    if spill and not os.path.isfile(str(spill)):
        raise RunError("the spillway rating CSV does not exist: {}".format(spill))
    trig = str(p.get("trigger") or "peak")
    val = _num(p.get("trigger_value"))
    if p.get("scenario") == SCENARIO_FLOOD and trig != "peak" and val is None:
        raise RunError("give TRIGGER_VALUE (the failure time in hours or the pool elevation in ft) for the chosen "
                       "trigger")
    fi = FL.FloodInputs.from_files(str(inflow), str(spill) if spill else None,
                                   normal_pool_ft=_num(p.get("normal_pool_ft")),
                                   crest_length_ft=dam.crest_length_ft, trigger=trig, trigger_value=val)
    fi.set_aux_weir(_num(p.get("aux_crest_ft")), _num(p.get("aux_length_ft")), _num(p.get("aux_c")))
    return fi


def scenario_hydrograph(p):
    """(dam, hydrograph the model runs, flood result or None) for the run's scenario.

    sunny            no inflow; the pool starts at the top of dam (the preset), the normal pool or a stated
                     elevation (start_pool); any breach method.
    flood            the inflow is routed through the reservoir, the spillways and over the crest, and the dam
                     breaches (trigger); the outflow WITH the breach is modelled. Arrival times count from breach
                     initiation (hydrograph.t_ref_s).
    flood_no_breach  the same routing with no failure; that outflow is modelled."""
    scen = str(p.get("scenario") or SCENARIO_SUNNY)
    if scen not in SCENARIOS:
        raise RunError("scenario must be one of {} (got {!r})".format(", ".join(SCENARIOS), scen))
    # the flood scenarios run on the ported engine's breach module (core/, the same source as flood/breach.py)
    B = BR
    if scen != SCENARIO_SUNNY:
        from ..core import breach as B                          # noqa: N812
    dam = B.DamData(dam_id=str(p["dam_id"]), dam_height_ft=float(p["height_ft"]),
                    storage_top_acft=float(p["storage_acft"]), top_of_dam_ft=float(p["top_ft"]),
                    surface_area_top_ac=p.get("area_ac") or None,
                    pmf_max_wse_ft=None,        # the PMF level is not a starting pool here: start_pool is
                    breach_bottom_ft=p.get("bottom_ft") or None, crest_width_ft=p.get("crest_width") or None,
                    us_slope_h=p.get("us_slope") or None, ds_slope_h=p.get("ds_slope") or None,
                    crest_length_ft=p.get("crest_length_ft") or None, name=str(p.get("name") or ""))
    dam.validate()
    ov = B.BreachOverrides(pipe_time_fraction=float(p.get("pipe_fraction", 0.5)),
                           pipe_initial_dia_ft=float(p.get("pipe_dia_ft", 0.5)))
    try:
        if scen == SCENARIO_SUNNY:
            kind = str(p.get("start_pool") or "top")
            if kind != "top":
                B.set_start_pool(dam, kind, _num(p.get("normal_pool_ft")) if kind == "normal"
                                 else _num(p.get("start_wse_ft")))
            return dam, B.make_hydrograph(dam, p["method"], ov, user_csv=p.get("user_csv") or None), None
        from ..core import flood as FL
        fi = flood_inputs(p, dam)
        if scen == SCENARIO_FLOOD_NO_BREACH:
            fr = FL.route_flood(dam, p["method"], ov, fi, breach=False)
            return dam, fr.no_breach, fr
        if p["method"] == B.METHOD_USER:
            raise RunError("the flood scenario with a breach routes the breach itself: choose a breach method, not "
                           "'my own hydrograph' (or run your hydrograph as a sunny day)")
        fr = FL.route_flood(dam, p["method"], ov, fi)
        if not fr.failed:
            raise RunError("the dam does not fail in this flood: " + " ".join(fr.notes[-1:]) + " Choose another "
                           "trigger, or run the flood with no breach.")
        return dam, fr.with_breach, fr
    except B.BreachInputError as e:
        raise RunError(str(e))


def hydrograph_for(p):
    """(dam, hydrograph) of the run's scenario; see scenario_hydrograph."""
    dam, hy, _fr = scenario_hydrograph(p)
    return dam, hy


def scenario_rule(p, hy):
    """One line: what the hydrograph is."""
    scen = str(p.get("scenario") or SCENARIO_SUNNY)
    if scen == SCENARIO_FLOOD_NO_BREACH:
        return "flood inflow routed through the spillways, outlets and over the crest; NO breach"
    if scen == SCENARIO_FLOOD:
        return "flood inflow with a breach {} ({:.2f} h into the flood)".format(
            TRIGGER_LABELS.get(str(p.get("trigger") or "peak"), p.get("trigger")), hy.t_ref_s / 3600.0)
    kind = str(p.get("start_pool") or "top")
    return "sunny day, no outlet or spillway flow, starting at {}".format(
        "the top of dam" if kind == "top" else "{} ({:.2f} ft)".format(
            "the normal pool" if kind == "normal" else "a stated elevation", hy.params.get("starting_wse_ft")))


def _hydrograph_record(hy, dam, p=None):
    """The breach the run used, including the width and formation time, so a later HEC-RAS
    export writes that opening and not a recomputed one."""
    rec = hy.summary()
    rec["label"] = BR.METHOD_LABELS.get(hy.method, hy.method)
    start = hy.params.get("starting_wse_ft")
    rec["starting_wse_ft"] = dam.top_of_dam_ft if start is None else start
    rec["rule"] = scenario_rule(p or {}, hy)
    rec["breach_initiation_hr"] = round(float(getattr(hy, "t_ref_s", 0.0) or 0.0) / 3600.0, 3)
    rec["notes"] = list(hy.notes)
    return rec


# ------------------------------------------------------------------------------------------------- runs --
PROGRESS_FILE = "run_progress.json"


def write_progress(workdir, **fields):
    """run_progress.json in the run folder (0.3.1): what a watcher needs while the run is still going - the model CRS, each
    pass's folder and bounds - and the one completion marker. `complete` is True only after run_report.json is written
    (every loop, the ANUGA tier and the outputs are done). It is a progress note: a failure to write it never stops the
    run, and it is only written for a run folder's own model/ directory (growth_loop's tests use throw-away folders)."""
    if os.path.basename(os.path.normpath(workdir)) != "model":
        return None
    path = os.path.join(os.path.dirname(os.path.normpath(workdir)), PROGRESS_FILE)
    try:
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {"version": 1, "passes": [], "growth_loops_done": 0, "complete": False}
        add = fields.pop("add_pass", None)
        if add:
            state["passes"].append(add)
        if fields.pop("loop_done", False):
            state["growth_loops_done"] = int(state.get("growth_loops_done") or 0) + 1
        state.update(fields)
        state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1, default=str)
        os.replace(tmp, path)
        return path
    except OSError:
        return None


def one_run(p, wkt, s, hy, bounds, cell, sim_s, workdir, log, cancel, wall_s):
    dem = R.read_window(p["dem"], bounds, cell, wkt, p.get("z_units"))
    if not np.isfinite(dem.data).any():
        raise RunError("the DEM has no data in the model domain")
    par = LF.write_inputs(workdir, dem, s["inflow_xy"], hy, sim_s, p["manning"], p["arrival_ft"] * FT)
    info = LF.run(workdir, par, p["exe"], wall_s, p.get("threads") or 0, cancel, log)
    out = LF.read_results(workdir, dem, p["arrival_ft"] * FT)
    info = dict(info, outflow=LF.boundary_outflow(workdir))
    return dem, out, info


def flood_stats(dem, depth, arrival_m):
    wet = np.isfinite(depth) & (depth >= arrival_m)
    ac = float(wet.sum()) * dem.dx ** 2 / ACRE
    med = float(np.median(depth[wet]) / FT) if wet.any() else 0.0
    return {"flooded_acres": round(ac, 1), "median_depth_ft": round(med, 2),
            "max_depth_ft": round(float(np.nanmax(depth)) / FT, 2) if wet.any() else 0.0}


EDGE_WARN_PCT = 1.0          # 0.3.3: with a wet edge, warn when at least this share of the volume left the model (the watcher's edge flag)


def final_edge_note(rec, p, stop, sim_s, cap_s):
    """The warning for the end of a growth loop (None when there is nothing to say): the last pass still has a wet edge with
    EDGE_WARN_PCT of the breach volume gone, or OUTFLOW_WARN_PCT of it gone whatever the edges. It names the edges, their depths and
    the outflow, and says why the domain did not grow: the loop grows only for an edge deeper than EDGE_TOL_FT or an edge carrying
    OUTFLOW_EDGE_SHARE of the outflow once OUTFLOW_EXTEND_PCT has left (deliberate limits), or it stopped at a limit (named).
    DWR-2645: 0.94 ft on the S edge and 3.37 % outflow at the 96 h cap are under both, and the run said nothing (0.3.2)."""
    pct = rec.get("boundary_outflow_pct")
    arr = float(p.get("arrival_ft") or 0.1)
    tol = float(p.get("edge_tol_ft") or 0.0)
    ext = float(p.get("outflow_extend_pct") or 0.0)
    depths = rec.get("edge_depths_ft") or {}
    wet = [(e, float(depths[e])) for e in ("N", "S", "E", "W") if (depths.get(e) or 0.0) >= arr]
    big = pct is not None and pct >= OUTFLOW_WARN_PCT
    if not big and not (wet and (pct is not None and pct >= EDGE_WARN_PCT or any(d > tol for _, d in wet))):
        return None
    txt = "{}% of the breach volume left the model through its edges in the last run".format(
        "{:.1f}".format(pct) if pct is not None else "an unmeasured share")
    txt += ("; edge(s) still wet at the end: " + ", ".join("{} {:.2f} ft".format(e, d) for e, d in wet)) if wet else \
        "; no edge is wet at the end"
    txt += "; the flood area and the downstream consequences are minimums."
    at_cap = cap_s and sim_s >= float(cap_s) - 1.0
    if stop:
        txt += " The run stopped at the {}{}.".format(stop, " ({:.0f} h)".format(sim_s / 3600.0) if stop == "duration cap" else "")
    else:
        txt += (" The domain was not grown further: it grows only for an edge deeper than {:g} ft (EDGE_TOL_FT) or an edge carrying "
                "at least {:.0f}% of the outflow once {:g}% of the volume has left (OUTFLOW_EXTEND_PCT), and the last pass was "
                "under those limits (deepest wet edge {:.2f} ft, outflow {}%).".format(
                    p.get("edge_tol_ft") or 0.0, OUTFLOW_EDGE_SHARE * 100.0, ext, max([d for _, d in wet] or [0.0]),
                    "{:.1f}".format(pct) if pct is not None else "n/a"))
    if at_cap and stop != "duration cap":
        txt += " The clock was already at the {:.0f} h duration cap, so the last clock extension was the final one.".format(sim_s / 3600.0)
    return txt


def growth_loop(p, wkt, s, hy, bounds, cell, workdir, log, cancel, fixed=None):
    """The domain-growth loop. fixed = (bounds, sim_s): one run on that domain and clock (grid refine / check)."""
    tol_m = p["edge_tol_ft"] * FT
    arr_m = p["arrival_ft"] * FT
    step = p["step_mi"] * MILE
    max_extent = p["max_extent_mi"] * MILE
    per_run = LF.wall_limit_s(p["max_wall_s"])
    budget = float(p["max_total_wall_s"] or 0) or float(p["max_runs"]) * per_run
    cap_s = min(MAX_SIM_S, float(p["duration_max_hr"] or 0) * 3600.0 or MAX_SIM_S)
    duration_s = float(hy.duration_s)
    if fixed:
        bounds, sim_s = fixed
    else:
        sim_s = float(p["duration_hr"]) * 3600.0 if p["duration_hr"] else auto_sim_time(duration_s, bounds, cap_s)
    limit = p.get("_dem_extent")
    if limit and not fixed:
        bounds = G.clip_bounds(bounds, limit) or bounds
    t0 = time.time()
    it, passes, warnings = 1, [], []
    stop = None
    while True:
        if cancel is not None and cancel():
            raise RunError("cancelled")
        wd = os.path.join(workdir, "run{:02d}_{:g}m".format(len(passes) + 1, cell))
        left = budget - (time.time() - t0)
        dem, out, info = one_run(p, wkt, s, hy, bounds, cell, sim_s, wd, log, cancel, min(per_run, max(left, 60.0)))
        depth = out["depth"]
        valid = np.isfinite(dem.data)
        edges = G.edge_depths(depth, valid)
        over = [e for e in ("N", "S", "E", "W") if edges[e] > tol_m]
        # the DamSafety Runner's OUTFLOW_EXTEND_PCT (Grok audit 3.1, DamSafety 3.16.8): once that share of the breach
        # volume has left the model, every edge that carries a real share of it (OUTFLOW_EDGE_SHARE of the outflow,
        # wet past the arrival depth) moves out too, even under the depth tolerance
        leak = []
        ofl = info.get("outflow") or {}
        out_pct = ofl.get("outflow_pct")
        ext_pct = float(p.get("outflow_extend_pct") or 0.0)
        if not fixed and ext_pct > 0 and out_pct is not None and out_pct >= ext_pct:
            shares = G.edge_flux_shares(depth, valid)
            leak = [e for e in ("N", "S", "E", "W") if e not in over and edges[e] > arr_m
                    and shares[e] >= OUTFLOW_EDGE_SHARE]
            if leak:
                log("{:.0f}% of the breach volume left the model; the water leaves through {} under {:g} ft, so {} "
                    "moves out too.".format(out_pct, ", ".join(leak), p["edge_tol_ft"],
                                             "that edge" if len(leak) == 1 else "those edges"))
                over = over + leak
        arr = out["arrival_hr"]
        arr_max = float(np.nanmax(arr)) if np.isfinite(arr).any() else 0.0
        moving = arr_max > 0.9 * sim_s / 3600.0
        rec = {"run": it, "pass": len(passes) + 1, "bounds": [round(b, 1) for b in bounds], "cell_m": cell,
               "cells": int(dem.data.size), "sim_time_hr": round(sim_s / 3600.0, 2),
               "edge_depths_ft": {k: round(v / FT, 2) for k, v in edges.items()}, "over": over,
               "over_outflow": leak, "boundary_outflow_pct": out_pct,
               "clock_extension": bool(passes) and passes[-1]["run"] == it,
               "still_moving": moving, "engine": info["engine"], "wall_s": round(info["wall_s"], 1),
               "wall_limit_s": info["wall_limit_s"]}
        rec.update(flood_stats(dem, depth, arr_m))
        passes.append(rec)
        write_progress(workdir, crs_wkt=wkt, add_pass={"pass": rec["pass"], "dir": os.path.basename(wd),
                                                       "bounds": rec["bounds"], "cell_m": cell, "wall_s": rec["wall_s"]})
        log("Pass {} (domain run {}): {:.1f} x {:.1f} mi, {:g} m, {:.1f} h simulated; edges over {:g} ft: {}; "
            "{}".format(rec["pass"], it, (bounds[2] - bounds[0]) / MILE, (bounds[3] - bounds[1]) / MILE, cell,
                        sim_s / 3600.0, p["edge_tol_ft"], ", ".join(over) or "none",
                        "still moving" if moving else "settled"))
        if fixed:
            break
        if not over and moving is False:
            break
        if over and it >= int(p["max_runs"]):
            stop = "domain-run limit"
            warnings.append("Stopped after {} domain runs with the flood leaving through {} deeper than {:.1f} ft. A "
                            "clock extension is not counted as a run. The duration cap did not stop this run."
                            .format(it, ", ".join(over), p["edge_tol_ft"]))
            break
        new_bounds = G.expand_bounds(bounds, over, step) if over else bounds
        if over and limit:
            new_bounds = G.clip_bounds(new_bounds, limit) or bounds
            stuck = [e for e in over if new_bounds[{"W": 0, "S": 1, "E": 2, "N": 3}[e]] ==
                     bounds[{"W": 0, "S": 1, "E": 2, "N": 3}[e]]]
            if stuck:
                warnings.append("The flood leaves through {} {} where the DEM ends; the domain cannot grow there (a "
                                "larger DEM is needed).".format(", ".join(stuck), "deeper than {:.1f} ft".format(
                                    p["edge_tol_ft"]) if not set(stuck) & set(leak) else
                                    "(deeper than {:.1f} ft, or carrying the outflow)".format(p["edge_tol_ft"])))
                over = [e for e in over if e not in stuck]
                if not over and not moving:
                    stop = "DEM extent"
                    break
        if over and max(new_bounds[2] - new_bounds[0], new_bounds[3] - new_bounds[1]) > max_extent:
            stop = "maximum extent"
            warnings.append("The next domain would be larger than {:.0f} mi with the flood leaving through {}."
                            .format(p["max_extent_mi"], ", ".join(over)))
            break
        if time.time() - t0 >= budget:
            stop = "wall-clock budget"
            warnings.append("Stopped at the wall-clock budget for all runs ({:.1f} h); the results are this pass's."
                            .format(budget / 3600.0))
            break
        new_sim = sim_s
        if not p["duration_hr"]:
            new_sim = min(cap_s, max(auto_sim_time(duration_s, new_bounds, cap_s), sim_s * (1.5 if moving else 1.0)))
        elif moving and sim_s < cap_s - 1.0:
            new_sim = min(cap_s, sim_s * 1.5)
        if not over and new_sim <= sim_s * 1.001:
            stop = "duration cap"
            warnings.append("The flood is still advancing after {:.0f} h, the duration cap; results stop there."
                            .format(sim_s / 3600.0))
            break
        sim_s = new_sim
        if over:
            bounds = new_bounds
            it += 1
    if not fixed and passes:
        note = final_edge_note(passes[-1], p, stop, sim_s, cap_s)
        if note:
            warnings.append(note)
    write_progress(workdir, loop_done=True)
    return {"dem": dem, "out": out, "bounds": bounds, "sim_s": sim_s, "passes": passes, "warnings": warnings,
            "stop": stop, "info": info}


def run_breach(p, out_dir, log=print, cancel=None):
    """One dam. p: DEFAULTS plus dem, dam_id, height_ft, storage_acft, top_ft and the site inputs (lon/lat).
    Writes the run under out_dir (model/ and outputs/). Returns the run record (json-safe)."""
    q = dict(DEFAULTS)
    q.update({k: v for k, v in p.items() if v is not None})
    p = q
    tier = int(p["tier"])
    if tier == TIER_HECRAS:
        raise RunError("HEC-RAS 2D is not run by DamIT Runner (it needs HEC-RAS 6.6 and Wine on Linux); choose "
                       "LISFLOOD-FP only, or LISFLOOD-FP then ANUGA")
    sel = LF.find_exe(p.get("lisflood_exe"))
    p["exe"] = sel["exe"]
    log("Flood engine: {} ({})".format("the built-in engine" if LF.is_builtin(p["exe"]) else p["exe"], sel["how"]))
    if sel["warning"]:
        log(sel["warning"])
    os.makedirs(out_dir, exist_ok=True)
    model_dir = os.path.join(out_dir, "model")
    outputs = os.path.join(out_dir, "outputs")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(outputs, exist_ok=True)
    lonlat = p.get("dam_lonlat") or (tuple(np.asarray(p["dam_line_lonlat"], float).mean(axis=0))
                                     if p.get("dam_line_lonlat") else None)
    if not lonlat:
        raise RunError("no dam position")
    wkt = R.model_wkt(p["dem"], lonlat)
    dam, hy, flood_res = scenario_hydrograph(p)
    scen = str(p.get("scenario") or SCENARIO_SUNNY)
    log("{}: {} ({}; top of dam {:.2f} ft); peak {:,.0f} cfs, {:.1f} h".format(
        "Flood outflow, no breach" if scen == SCENARIO_FLOOD_NO_BREACH else "Breach hydrograph",
        BR.METHOD_LABELS.get(hy.method, hy.method), scenario_rule(p, hy), dam.top_of_dam_ft, hy.peak_cfs,
        hy.duration_s / 3600.0))
    if scen != SCENARIO_SUNNY or str(p.get("start_pool") or "top") != "top":
        for n in hy.notes:                                       # what the choice means, where the user sees it
            log("Note: " + n)
    hy.to_csv(os.path.join(outputs, "breach_hydrograph.csv"))
    s = site(p, wkt, log)
    cell = float(p["cell_m"])
    # first domain from the flow trace on the planning DEM
    L = p["length_mi"] * MILE
    W = p["half_width_mi"] * MILE
    pc = max(PLANNING_CELL_M, cell)
    ix, iy = s["inflow_xy"]
    half = L + W + 2 * pc
    plan = R.read_window(p["dem"], snap_bounds((ix - half, iy - half, ix + half, iy + half), pc), pc, wkt,
                         p.get("z_units"))
    path, plen = G.trace_downstream(plan, s["inflow_xy"], L)
    bounds = G.path_bounds(path + [s["dam_xy"]], W, snap=cell)
    warnings = list(s["checks"]) + ([sel["warning"]] if sel["warning"] else [])
    if scen == SCENARIO_FLOOD_NO_BREACH:
        warnings.append("NO breach is modelled: the flood is the routed outflow through the spillways and outlets and "
                        "over the crest, put in at the toe of the dam. The rasters are not a dam failure flood; do "
                        "not classify the dam's hazard from this run alone.")
    elif scen == SCENARIO_FLOOD:
        warnings.append("Flood with a breach: this run models the outflow WITH the breach only. For the incremental "
                        "effect of the failure run the same flood with no breach and compare (or use Run breach "
                        "model, DamSafety engine, which runs both).")
    d_end = math.hypot(path[-1][0] - s["dam_xy"][0], path[-1][1] - s["dam_xy"][1])
    if plen < 0.25 * L:
        warnings.append("The steepest-descent path from the breach inflow is only {:.0f} m long and ends {:.0f} m from "
                        "the dam; check the inflow point.".format(plen, d_end))
    ext = R.extent_in(p["dem"], wkt)
    p["_dem_extent"] = (math.ceil(ext[0] / cell) * cell, math.ceil(ext[1] / cell) * cell,
                        math.floor(ext[2] / cell) * cell, math.floor(ext[3] / cell) * cell)
    g = growth_loop(p, wkt, s, hy, bounds, cell, model_dir, log, cancel)
    record_cell = cell
    refine = None
    st = flood_stats(g["dem"], g["out"]["depth"], p["arrival_ft"] * FT)
    if p["grid_refine"] and cell > GRID_REFINE_CELL_M and grid_spread_flagged(cell, st["flooded_acres"],
                                                                               st["median_depth_ft"]):
        log("Grid refine: {:g} m flooded {:.0f} ac with a median depth of {:.2f} ft; running again at {:g} m on the "
            "same domain and clock (the record).".format(cell, st["flooded_acres"], st["median_depth_ft"],
                                                         GRID_REFINE_CELL_M))
        g2 = growth_loop(p, wkt, s, hy, snap_bounds(g["bounds"], GRID_REFINE_CELL_M), GRID_REFINE_CELL_M, model_dir,
                         log, cancel, fixed=(snap_bounds(g["bounds"], GRID_REFINE_CELL_M), g["sim_s"]))
        refine = {"from_cell_m": cell, "to_cell_m": GRID_REFINE_CELL_M, "coarse": st,
                  "fine": flood_stats(g2["dem"], g2["out"]["depth"], p["arrival_ft"] * FT)}
        g2["passes"] = g["passes"] + g2["passes"]
        g2["warnings"] = g["warnings"] + g2["warnings"]
        g2["stop"] = g["stop"]
        g, record_cell = g2, GRID_REFINE_CELL_M
    check = None
    if float(p.get("grid_check_cell_m") or 0) > 0:
        cc = float(p["grid_check_cell_m"])
        gc = growth_loop(p, wkt, s, hy, snap_bounds(g["bounds"], cc), cc, model_dir, log, cancel,
                         fixed=(snap_bounds(g["bounds"], cc), g["sim_s"]))
        a = flood_stats(gc["dem"], gc["out"]["depth"], p["arrival_ft"] * FT)
        b = flood_stats(g["dem"], g["out"]["depth"], p["arrival_ft"] * FT)
        diff = 100.0 * abs(a["flooded_acres"] - b["flooded_acres"]) / b["flooded_acres"] if b["flooded_acres"] else 0
        check = {"cell_m": cc, "stats": a, "area_diff_pct": round(diff, 1)}
        if diff > 25.0:
            warnings.append("The {:g} m check floods {:.0f}% more or less area than the record.".format(cc, diff))
    dem, out = g["dem"], dict(g["out"])
    final_engine = g["info"]["engine"]
    anuga = None
    if tier == TIER_ANUGA or p["force_anuga"]:
        from . import anuga_run as AR
        width = float(hy.params.get("avg_breach_width_ft") or 100.0) * FT
        res = AR.run(os.path.join(model_dir, "anuga"), dem, out["depth"], s["inflow_xy"], s["downstream"], width, hy,
                     {"manning": p["manning"], "fine_m2": p["anuga_fine_m2"], "coarse_m2": p["anuga_coarse_m2"],
                      "near_m": p["anuga_near_mi"] * MILE, "buffer_m": p["anuga_buffer_m"], "sim_time_s": g["sim_s"],
                      "arrival_m": p["arrival_ft"] * FT, "threads": p.get("threads") or 1,
                      "python": p.get("anuga_python"), "wall_s": p["max_wall_s"],
                      "edge_tol_m": p["edge_tol_ft"] * FT}, cancel, log)
        anuga = dict(res.get("stats") or {}, mesh=res.get("mesh"))
        warnings += [n for n in res.get("notes") or [] if n not in warnings]
        out = {k: res[k] for k in ("depth", "velocity", "arrival_hr", "wse")}
        final_engine = "ANUGA"
    t_ref_hr = float(getattr(hy, "t_ref_s", 0.0) or 0.0) / 3600.0
    if t_ref_hr > 0:
        # 0.5.0, flood with a breach: arrival times count from breach initiation, not from the start of the inflow
        # (ground the spillway flow wetted before the breach gets 0), as the DamSafety Runner reports them
        arr = np.asarray(out["arrival_hr"], float)
        out["arrival_hr"] = np.where(np.isfinite(arr), np.clip(arr - t_ref_hr, 0.0, None), np.nan)
    files = write_outputs(outputs, dem, wkt, out, p, s)
    stats = flood_stats(dem, out["depth"], p["arrival_ft"] * FT)
    record = {"dam_id": p["dam_id"], "engine": final_engine, "extent_engine": g["info"]["engine"],
              "engine_selection": {"lisflood_exe": p["exe"], "how": sel["how"], "fallback": bool(sel["warning"]),
                                   "warning": sel["warning"]},
              "tier": TIERS[tier], "force_anuga": bool(p["force_anuga"]), "record_cell_m": record_cell,
              "sim_time_hr": round(g["sim_s"] / 3600.0, 2), "bounds": [round(b, 1) for b in g["bounds"]],
              "crs_wkt": wkt, "passes": g["passes"], "stop_reason": g["stop"], "warnings": warnings + g["warnings"],
              "grid_refine": refine, "grid_check": check, "anuga": anuga, "stats": stats,
              "hydrograph": _hydrograph_record(hy, dam, p),
              "scenario": scen, "breach_occurs": scen != SCENARIO_FLOOD_NO_BREACH,
              "flood": dict(flood_res.summary) if flood_res is not None else None,
              "dam": BR.dam_to_dict(dam),
              "dam_xy": [float(s["dam_xy"][0]), float(s["dam_xy"][1])],
              "work_crs": wkt,
              "inflow_point": {"xy": [float(s["inflow_xy"][0]), float(s["inflow_xy"][1])]},
              "settings": {"input_files": {"DEM": p["dem"]}, "cell_size_m": float(p["cell_m"]),
                           "manning_n": float(p["manning"]),
                           "breach_xy": [float(s["inflow_xy"][0]), float(s["inflow_xy"][1])]},
              "inflow": {"xy": list(s["inflow_xy"]), "how": s["inflow_how"], "toe_band": s["toe_band"],
                         "downstream": list(s["downstream"]) if s["downstream"] else None,
                         "downstream_how": s["downstream_how"]},
              "dam_point": s.get("dam_point"),
              "trace": {"length_mi": round(plen / MILE, 2), "points": len(path)}, "outputs": files}
    zu = str(p.get("z_units") or "auto").strip().lower()
    if zu != "auto":
        record["dem_z_to_m"] = R.z_scale({}, zu)
        record["dem_elevation_units"] = {"m": "metres", "ft": "feet", "us_ft": "us survey feet",
                                         "us_feet": "us survey feet"}.get(zu, zu)
    elif s.get("z_to_m") is not None:
        record["dem_z_to_m"] = s["z_to_m"]
        record["dem_elevation_units"] = s.get("z_how") or "auto"
    if s.get("dam_point") and s["dam_point"].get("off_line") and s["dam_point"].get("how"):
        if s["dam_point"]["how"] not in record["warnings"]:
            record["warnings"].append(s["dam_point"]["how"])
    for n in (s.get("checks") or []):
        if n and n not in record["warnings"]:
            record["warnings"].append(n)
    for w in record["warnings"]:
        log("Warning: " + str(w))                    # 0.3.3: the report's warnings were never in the log
    with open(os.path.join(out_dir, "run_report.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1, default=str)
    write_progress(model_dir, complete=True)       # after run_report.json: the whole breach pipeline is done
    return record


def write_outputs(folder, dem, wkt, out, p, s):
    """The final rasters (US units) and vectors in `folder`, the DamSafety Runner's names."""
    files = {}
    d_ft = np.where(np.isfinite(out["depth"]) & (out["depth"] > 0), out["depth"] / FT, np.nan)
    v_fps = np.where(np.isfinite(d_ft), np.nan_to_num(out["velocity"]) / FT, np.nan)
    wse_ft = np.where(np.isfinite(d_ft), out["wse"] / FT, np.nan)
    arr = np.asarray(out["arrival_hr"], float)
    grids = {"depth": d_ft, "velocity": v_fps, "arrival": arr, "wse": wse_ft}
    for k, (name, unit) in FINAL_RASTERS.items():
        files[k] = R.write_tif(os.path.join(folder, name), dem.like(grids[k]), wkt)
        R.write_tif(os.path.join(folder, QA_RASTERS[k]), dem.like(grids[k]), wkt)
    files["hmax"] = os.path.join(folder, QA_RASTERS["depth"])
    if p.get("products", True):
        cls = np.zeros(d_ft.shape, dtype=np.int16)
        labels = {}
        for i, lo in enumerate(DEPTH_CLASSES_FT):
            hi = DEPTH_CLASSES_FT[i + 1] if i + 1 < len(DEPTH_CLASSES_FT) else None
            with np.errstate(invalid="ignore"):
                m = np.isfinite(d_ft) & ((d_ft > 0) if lo == 0 else (d_ft >= lo))
                if hi is not None:
                    m &= d_ft < hi
            cls[m] = i + 1
            labels[i + 1] = "{:g}-{} ft".format(lo, "{:g}".format(hi) if hi else "+")
        files["depth_polygons"] = R.polygonize(os.path.join(folder, VECTORS["depth_polygons"]), cls, dem, wkt,
                                               "max_depth", labels=labels)
        ext = (np.isfinite(d_ft) & (d_ft >= p["arrival_ft"])).astype(np.int16)
        files["extent"] = R.polygonize(os.path.join(folder, VECTORS["extent"]), ext, dem, wkt, "flood_extent")
        hrs = sorted(float(h) for h in (p.get("contours_hr") or ()))
        if hrs:
            az = np.zeros(arr.shape, dtype=np.int16)
            lab = {}
            for i in range(len(hrs) - 1, -1, -1):
                with np.errstate(invalid="ignore"):
                    az[np.isfinite(arr) & (arr <= hrs[i])] = i + 1
                lab[i + 1] = "<= {:g} h".format(hrs[i])
            files["arrival_zones"] = R.polygonize(os.path.join(folder, VECTORS["arrival_zones"]), az, dem, wkt,
                                                  "arrival_zones", labels=lab)
    with open(os.path.join(folder, "units.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v[1] for k, v in FINAL_RASTERS.items()}, fh, indent=1)
    return files
