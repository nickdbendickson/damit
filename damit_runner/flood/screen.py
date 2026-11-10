"""DamIT Screener's 2D screening flood: the DamSafety Screening tool-7 driver (core/runner.simulate) for one dam, on
its built-in finite-volume engine (fv_engine, hydrograph injection; engine "builtin", the DamSafety Screening
default) or on LISFLOOD-FP (engine "lisflood": the ACC solver, the same injection cells as QVAR point sources,
through DamIT Runner's launcher lisflood.py; the executable from lisflood.find_exe, and the built-in engine with a
warning when none is found).

  * the cell: GRID_M (default 20 m, the DamSafety Screening window's default); 0 = automatic by reservoir size
    (domain.CELL_TABLE) and breach width;
  * the clip: RADIUS_M (1,500 m) around the breach inflow, a corridor of CORRIDOR_HW_M (600 m) either side of
    the steepest-descent path (everything else a wall);
  * the clock: SIMH h (12; 0 = hydrograph + travel time), extended x 1.5 while the flood still spreads, to
    SIMMAX h (96);
  * the corridor widens when the flood reaches its wall; a flood at the clip edge gets a clip twice as big up to
    RADIUS_MAX_M (12,000 m) - downloaded fresh from the USGS 3DEP service (larger_clips 1, the default, as the
    DamSafety Screening "USGS 3DEP service" choice; terrain3dep.py, into the dam folder's
    screen_inputs/terrain_3dep/), from a local DEM (larger_clips 2) or not at all (larger_clips 0: the first clip
    only; a flood at the edge is flagged truncated). A failed download is said in the notes and the larger clip
    then comes from the run's DEM (flagged);
  * a wall-clock limit (timeout_s, from DAMIT_SCREENING_TIMEOUT_S): when it is reached the maxima so far are
    kept and flagged partial.

DamIT changes against DamSafety Screening: the inflow cells sit across the breach at the toe-band inflow point
(geom.place_inflow, Nick's rule: 5 m to H x (downstream slope + 1), 3:1 default, 150 m cap, side check) instead
of 2.5 x breach height + 5 m along the azimuth; no reservoir-in-grid, cascade, buildings or baseline options."""
import math
import os
import time

import numpy as np

from . import rasters as R
from .fv_engine import Engine
from .screening import domain as DM
from .screening import triage as TG
from .screening.gridutil import NODATA
from .units import FT

DEFAULTS = dict(grid_m=20.0, simh=12.0, simmax=96.0, corridor=True, corridor_hw_m=600.0, radius_m=1500.0,
                radius_max_m=12000.0, manning=0.05, wet_m=0.05, timeout_s=3600.0, larger_clips=1, local_dem="",
                max_attempts=8, z_units="auto", dem_cell=1.0, engine="builtin", lisflood_exe="", workdir="",
                threads=1, arrival_m=0.03048)
LARGER_CLIPS = ("first clip only", "larger clips from a fresh USGS 3DEP download", "larger clips from a local DEM")
ENGINES = ("builtin", "lisflood")
BUILTIN_NAME = "DamIT Screener built-in 2D engine (finite volume, from DamSafety Screening fv_engine)"


class LisfloodEngine:
    """fv_engine.Engine's interface (add_source, run -> depth / vel / dv / arrive_h maxima) on LISFLOOD-FP: the
    clip (corridor walls as no-data) and the injection cells as QVAR point sources, written with DamIT Runner's
    lisflood.write_inputs and run with lisflood.run under the time left. A run stopped at the limit has no maxima
    (hmax None)."""

    def __init__(self, grid, dem_m, cell, manning, exe, workdir, threads=1, arrival_m=0.03048, log=None):
        from .geom import Grid
        self.grid = Grid(np.where(dem_m > NODATA + 1, dem_m, np.nan), grid.x0, grid.y0, cell)
        self.manning, self.exe, self.workdir = float(manning), exe, workdir
        self.threads, self.arrival_m, self.log = threads, arrival_m, log
        self.cells, self.hydro = [], None
        self.hmax = self.vmax = self.dvmax = self.arrive = None
        self.t = 0.0
        self.mass = None
        self.info = {}

    def add_source(self, cells_rc, t_s, q_m3s, start_s=0.0):
        self.cells = list(cells_rc)
        self.hydro = _Hydro(np.asarray(t_s, float) + float(start_s), np.asarray(q_m3s, float))

    def run(self, t_end, max_wall_s=None, cancel=None, **_):
        from . import lisflood as LF
        import shutil
        if os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir, ignore_errors=True)
        par = LF.write_inputs(self.workdir, self.grid, self.grid.xy(*self.cells[0]), self.hydro, t_end,
                              manning_n=self.manning, arrival_depth_m=self.arrival_m, cells=self.cells)
        try:
            self.info = LF.run(self.workdir, par, self.exe, max_wall_s or 0.0, self.threads, cancel, self.log)
        except LF.WallLimit as e:
            raise TimeoutError(str(e))
        r = LF.read_results(self.workdir, self.grid, self.arrival_m)
        d = np.where(np.isfinite(r["depth"]), r["depth"], 0.0)
        v = np.where(np.isfinite(r["velocity"]), r["velocity"], 0.0)
        arr = np.where(np.isfinite(r["arrival_hr"]), r["arrival_hr"], NODATA)
        self.hmax, self.vmax, self.dvmax, self.arrive, self.t = d, v, d * v, arr, float(t_end)
        return {"depth": d, "vel": v, "dv": d * v, "arrive_h": arr, "t": float(t_end), "mass": None}


class _Hydro:
    def __init__(self, t_s, q_cms):
        self.t_s, self.q_cms = t_s, q_cms

    def resampled(self, dt_s):
        t = np.union1d(np.arange(0.0, float(self.t_s[-1]), dt_s), self.t_s)
        return t, np.interp(t, self.t_s, self.q_cms)


def choose_engine(engine, lisflood_exe="", find_exe=None):
    """('builtin' | 'lisflood', exe, how, warning) for the screening setting engine2d. 'lisflood' with no
    LISFLOOD-FP found (or LISFLOOD_EXE 'builtin') runs the built-in engine, with a warning when it was a
    fallback."""
    e = str(engine or "builtin").lower()
    if e in ("lisflood-acc", "lisflood-fp"):
        e = "lisflood"
    if e not in ENGINES:
        raise ValueError("unknown screening engine {!r} (one of {})".format(engine, ", ".join(ENGINES)))
    if e == "builtin":
        return "builtin", None, "engine2d = builtin", None
    from . import lisflood as LF
    sel = (find_exe or LF.find_exe)(lisflood_exe)
    if LF.is_builtin(sel["exe"]):
        warn = None if not sel["warning"] else (
            "WARNING: engine2d = lisflood but no LISFLOOD-FP executable was found (lisflood_exe empty, no provider "
            "setting, nothing on PATH or in the usual install places), so the screening flood ran on the BUILT-IN "
            "engine instead (" + BUILTIN_NAME + ").")
        return "builtin", None, sel["how"], warn
    return "lisflood", sel["exe"], sel["how"], None


def injection_cells(grid, inflow_xy, downstream, width_m, n_max=25):
    """Cells across the flow at the inflow point, spread over the breach width."""
    ux, uy = downstream if downstream else (0.0, -1.0)
    px, py = -uy, ux
    cell = grid.dx
    width = min(max(width_m, 2.0 * cell), 300.0)
    n = int(min(max(round(width / cell), 1), n_max))
    out = []
    for i in range(n):
        off = (i + 0.5) / n * width - width / 2.0
        r, c = grid.rc(inflow_xy[0] + px * off, inflow_xy[1] + py * off)
        if grid.inside(r, c) and np.isfinite(grid.data[r, c]) and (r, c) not in out:
            out.append((r, c))
    r, c = grid.rc(*inflow_xy)
    if not out and grid.inside(r, c):
        out.append((r, c))
    return out


def simulate(p, hydro_t_s, hydro_q_cms, site, wkt, log=print, cancel=None, engine_factory=None, fetch_terrain=None):
    """One dam. site: {'inflow_xy', 'downstream', 'breach_width_m', 'vw_m3'} in the model CRS (metres).
    p: DEFAULTS plus dem; engine 'builtin' / 'lisflood' (lisflood_exe), workdir (the dam folder: 3DEP clips and
    the LISFLOOD-FP run go under it). engine_factory(grid, dem_m, cell, manning) and fetch_terrain(bounds, wkt,
    cell, folder, radius_m, log, deadline) replace the engine and the 3DEP download (tests).
    Returns {'status', 'grid', 'depth', 'vel', 'dv', 'arrive_h', 'notes', 'engine', 'terrain', ...}."""
    o = dict(DEFAULTS)
    o.update({k: v for k, v in p.items() if v is not None})
    notes = []
    t0 = time.time()
    deadline = t0 + float(o["timeout_s"])
    cell = float(o["grid_m"]) if float(o["grid_m"] or 0) > 0 else DM.auto_cell(site.get("vw_m3"),
                                                                             site.get("breach_width_m"),
                                                                             o["dem_cell"])
    kind, exe, how, warn = choose_engine(o["engine"], o.get("lisflood_exe"))
    if warn:
        notes.append(warn)
        log(warn)
    engine_name = BUILTIN_NAME if kind == "builtin" else "LISFLOOD-FP ACC ({})".format(exe)
    if engine_factory is None:
        if kind == "builtin":
            def engine_factory(grid, dem_m, cell, manning):
                return Engine(dem_m, cell, manning=manning)
        else:
            lf_dir = os.path.join(o.get("workdir") or ".", "screen_lisflood")

            def engine_factory(grid, dem_m, cell, manning):
                return LisfloodEngine(grid, dem_m, cell, manning, exe, lf_dir, o.get("threads") or 1,
                                      float(o["arrival_m"]), log)
    if fetch_terrain is None:
        from . import terrain3dep as T3

        def fetch_terrain(bounds, wkt, cell, folder, radius_m, log, deadline):
            return T3.fetch_clip(bounds, wkt, cell, folder, radius_m, log=log, deadline=deadline)
    radius, hw = float(o["radius_m"]), float(o["corridor_hw_m"])
    use_corr = bool(o["corridor"])
    mode = int(o["larger_clips"])
    if mode == 2 and not o.get("local_dem"):
        notes.append("larger clips from a local DEM chosen but no local DEM given; the run's DEM is used")
    radius_max = radius if mode == 0 else float(o["radius_max_m"])
    t_end_h = float(hydro_t_s[np.nonzero(np.asarray(hydro_q_cms) > 1e-6)[0][-1]]) if np.any(
        np.asarray(hydro_q_cms) > 1e-6) else float(hydro_t_s[-1])
    sim_s = None
    out = None
    timed_out = False
    last_valid = 0
    last_radius = None
    on_edge = False
    terrain = {"source": "the run's DEM", "path": o["dem"], "z_units": o.get("z_units")}
    terrains = [dict(terrain, radius_m=radius)]
    clips = {}
    ix, iy = site["inflow_xy"]
    grid = None
    for attempt in range(1, int(o["max_attempts"]) + 1):
        if cancel is not None and cancel():
            return {"status": "cancelled", "notes": notes}
        b = (ix - radius, iy - radius, ix + radius, iy + radius)
        b = tuple(math.floor(v / cell) * cell if i < 2 else math.ceil(v / cell) * cell for i, v in enumerate(b))
        if attempt > 1 and radius > terrains[0]["radius_m"] and radius not in clips:
            clips[radius] = _larger_terrain(o, mode, b, wkt, cell, radius, deadline, fetch_terrain, log, notes)
            terrains.append(dict(clips[radius], radius_m=radius))
        if radius in clips:
            terrain = clips[radius]
        grid = R.read_window(terrain["path"], b, cell, wkt, terrain.get("z_units"))
        dem = np.where(np.isfinite(grid.data), grid.data, NODATA)
        valid0 = dem > NODATA + 1
        nvalid = int(valid0.sum())
        if attempt == 1 and valid0.mean() < 0.5:
            return {"status": "failed", "notes": notes + ["less than half of the terrain clip has data"]}
        # only a LARGER clip can show there is no terrain beyond (0.2.0 also tested after a corridor widening on the
        # same clip, and stopped the 2801 flood at the first 1,500 m clip)
        if last_radius is not None and radius > last_radius and nvalid < 1.02 * last_valid and on_edge:
            radius_max = radius
            notes.append("no terrain beyond the clip; could not enlarge it")
        last_valid, last_radius = nvalid, radius
        main = injection_cells(grid, site["inflow_xy"], site.get("downstream"), site.get("breach_width_m") or 10.0)
        if not main:
            return {"status": "failed", "notes": notes + ["the breach inflow point is outside the terrain"]}
        cr = int(np.mean([c[0] for c in main]))
        cc = int(np.mean([c[1] for c in main]))
        path, _ = TG.trace_path(dem, (cr, cc))
        if use_corr:
            mask = DM.corridor_mask(dem.shape, cell, path, (cr, cc), hw)
            dem_m = DM.apply_mask(dem, mask & valid0)
        else:
            dem_m = dem
        valid = dem_m > NODATA + 1
        if sim_s is None:
            sim_s = float(o["simh"]) * 3600.0 if o["simh"] else DM.initial_sim_time(t_end_h, len(path) * cell)
        eng = engine_factory(grid, dem_m, cell, float(o["manning"]))
        eng.add_source(main, hydro_t_s, hydro_q_cms, 0.0)
        prev = None
        while True:
            left = deadline - time.time()
            try:
                out = eng.run(sim_s, max_wall_s=max(left, 1.0), cancel=cancel)
            except TimeoutError:
                timed_out = True
                if getattr(eng, "hmax", None) is not None:
                    out = {"depth": eng.hmax, "vel": eng.vmax, "dv": eng.dvmax, "arrive_h": eng.arrive,
                           "t": eng.t, "mass": getattr(eng, "mass", None)}
                elif prev is not None:
                    out = prev
                else:
                    return {"status": "failed", "engine": engine_name, "notes": notes + [
                        "the screening time limit ({:.0f} s) was reached before {} finished; no partial maxima"
                        .format(float(o["timeout_s"]), engine_name)]}
                notes.append("the screening time limit ({:.0f} s) was reached at {:.2f} h simulated; the maxima so far "
                             "are kept (partial result)".format(float(o["timeout_s"]), out["t"] / 3600.0))
                break
            arr = np.where(out["arrive_h"] == NODATA, 0.0, out["arrive_h"])
            if DM.still_growing(arr, out["depth"], sim_s) and sim_s < float(o["simmax"]) * 3600.0:
                sim_s = min(sim_s * 1.5, float(o["simmax"]) * 3600.0)
                log("flood still spreading; extending the screening run to {:.1f} h".format(sim_s / 3600.0))
                prev = out
                continue
            break
        on_edge, on_wall = DM.touches_wall(out["depth"], valid, o["wet_m"], terrain=valid0)
        if timed_out:
            break
        if on_wall and use_corr:
            if hw * 2 >= radius:
                use_corr = False
                log("flood reached the corridor wall; using the full clip")
            else:
                hw *= 2
                log("flood reached the corridor wall; widening the corridor to {:.0f} m".format(hw))
            continue
        if on_edge and radius < radius_max:
            radius = min(radius * 2, radius_max)
            log("flood reached the terrain edge; enlarging the clip to {:.0f} m ({})".format(radius,
                                                                                         LARGER_CLIPS[mode]))
            continue
        break
    if on_edge:
        notes.append("flood reaches the terrain edge at the {} - result truncated".format(
            "first clip (larger clips off)" if mode == 0 else "maximum clip"))
    mass = out.get("mass") if out else None
    if mass and abs(mass.get("error_pct", 0.0)) > 0.5:
        notes.append("mass balance error {:.2f}%".format(mass["error_pct"]))
    arrive = np.where(out["arrive_h"] == NODATA, np.nan, out["arrive_h"])
    return {"status": "partial" if timed_out else "ok", "grid": grid, "cell_m": cell, "sim_s": sim_s,
            "depth": np.where(valid, out["depth"], np.nan), "vel": np.where(valid, out["vel"], np.nan),
            "dv": np.where(valid, out["dv"], np.nan), "arrive_h": arrive, "edge_flag": bool(on_edge),
            "timed_out": timed_out, "radius_m": radius, "corridor_hw_m": hw if use_corr else None,
            "larger_clips": LARGER_CLIPS[mode], "run_s": round(time.time() - t0, 1), "notes": notes,
            "mass": mass, "engine": engine_name, "engine_how": how, "engine_fallback": bool(warn),
            "terrain": {k: v for k, v in terrain.items() if k != "tiles"}, "terrains": terrains}


def _larger_terrain(o, mode, bounds, wkt, cell, radius, deadline, fetch_terrain, log, notes):
    """The terrain for a larger clip: a fresh 3DEP download (mode 1), the local DEM (mode 2), else the run's DEM."""
    run_dem = {"source": "the run's DEM", "path": o["dem"], "z_units": o.get("z_units")}
    if mode == 2:
        if o.get("local_dem"):
            return {"source": "local DEM", "path": o["local_dem"], "z_units": "auto"}
        return run_dem
    if mode != 1:
        return run_dem
    if not o.get("workdir"):
        notes.append("no dam folder for the 3DEP download; the {:.0f} m clip comes from the run's DEM".format(radius))
        return dict(run_dem, fallback=True)
    log("downloading a fresh {:.0f} m terrain clip from the USGS 3DEP service".format(radius))
    try:
        got = fetch_terrain(bounds, wkt, cell, os.path.join(o["workdir"], "screen_inputs"), radius, log, deadline)
    except Exception as e:                                       # noqa: BLE001 - said, then the run's DEM
        notes.append("the 3DEP download for the {:.0f} m clip failed ({}); that clip comes from the run's DEM"
                     .format(radius, e))
        log(notes[-1])
        return dict(run_dem, fallback=True)
    notes.append("the {:.0f} m clip is a fresh 3DEP download ({} tile(s), {})".format(radius, got.get("tiles"),
                                                                                       got.get("folder")))
    return {"source": got.get("source") or "USGS 3DEP", "path": got["path"], "z_units": got.get("z_units") or "m",
            "folder": got.get("folder"), "tiles": got.get("tiles")}


def receptor_hydraulics(res, points_xy, wet_ft=0.1):
    """Peak depth (ft), peak velocity (ft/s) and peak depth x velocity (ft2/s) at receptor points, over wet cells:
    a dry cell (< wet_ft) gives depth 0 and no velocity."""
    g = res["grid"]
    out = []
    for x, y in points_xy:
        r, c = g.rc(x, y)
        if not g.inside(r, c) or not np.isfinite(res["depth"][r, c]):
            out.append(None)
            continue
        d = float(res["depth"][r, c]) / FT
        if d < wet_ft:
            out.append({"depth_ground_ft": 0.0, "velocity_fps": 0.0, "dv_ft2s": 0.0})
            continue
        out.append({"depth_ground_ft": round(d, 2), "velocity_fps": round(float(res["vel"][r, c]) / FT, 2),
                    "dv_ft2s": round(float(res["dv"][r, c]) / FT ** 2, 2)})
    return out


def write_rasters(folder, res, wkt):
    """Screening rasters in US units in `folder` (Screening names: the preliminary flood, not the Runner's)."""
    import os
    g = res["grid"]
    d = np.where(np.isfinite(res["depth"]) & (res["depth"] > 0), res["depth"] / FT, np.nan)
    files = {"depth": R.write_tif(os.path.join(folder, "Screening Depth (Max).tif"), g.like(d), wkt),
             "velocity": R.write_tif(os.path.join(folder, "Screening Velocity (Max).tif"),
                                     g.like(np.where(np.isfinite(d), res["vel"] / FT, np.nan)), wkt),
             "dv": R.write_tif(os.path.join(folder, "Screening DV (Max).tif"),
                               g.like(np.where(np.isfinite(d), res["dv"] / FT ** 2, np.nan)), wkt),
             "arrival": R.write_tif(os.path.join(folder, "Screening Arrival Time.tif"), g.like(res["arrive_h"]), wkt)}
    return files
