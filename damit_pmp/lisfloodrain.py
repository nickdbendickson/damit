"""DamIT PMP: a LISFLOOD-FP rain-on-grid job, set up the way damit_runner sets up its LISFLOOD-FP run.

Mirrors anugarain.py. What is the runner's, as verbatim sha-pinned copies in runner_shared/:
  * lisflood.py   the settings class (LisfloodSettings), the solver names and choice rules (ACC default; FV2 and
                  MWDG2 only by name, FV1 / DG2 refused), local_grid (lower-left origin at 0, 0: the LISFLOOD-FP
                  build is single precision), the gauge-section clipping (_gauge_line), the .mass reader and the
                  executable helpers;
  * data_conventions.py   the executable search (DAMIT_LISFLOOD, PATH, the usual build folders);
  * grid.py       the model-DEM Grid and its ESRI ASCII writer (what LISFLOOD-FP reads);
  * units.py      its unit constants.
New here: the .rain file, the .par / .bci of a rain run (no breach inflow: runner_inputs_match() pins every
shared .par line to lisflood.write_inputs), the same domain as damit_pmp:anugarain (outer ring and all), and the
result readers. Atlas 14 stays the only depth source. NODATA outside the domain polygon is a wall in LISFLOOD-FP;
the grid is cropped to the domain so the FREE edges (as in the runner) touch it: water leaves where the domain reaches the edge.
"""
import json
import math
import os

import numpy as np

from . import anugarain as AR
from .runner_shared import data_conventions as DC
from .runner_shared import lisflood as L
from .runner_shared.grid import NODATA, Grid

JobError = AR.JobError
NAME = "rain"                                   # resroot: rain.par, rain.dem.asc, results/rain.max ...
TERRAIN_NAME = "Model Terrain (LISFLOOD).tif"   # the runner's name for the model DEM product
PAR_NAME, RAIN_NAME, BCI_NAME, GAUGE_NAME = NAME + ".par", NAME + ".rain", NAME + ".bci", NAME + ".gauge"
MANIFEST_NAME = "run_manifest.json"
RESULTS_NAME = "lisflood_rain_results.json"
MAX_DEPTH_NAME = "lisflood_max_depth.tif"
DEFAULTS = dict(cell_m=10.0, buffer_m=0.0, manning_n=0.06, solver="ACC", initial_tstep_s=10.0, massint_s=300.0,
                threads=1, theta=1.0, cfl=None, extra_h=6.0, closed_edges=())
SOLVER_CHOICES = ("ACC", "FV2", "MWDG2")        # the runner's MAIN_SOLVERS, upper-case names for the dropdown
CUDA_NOTE = ("FV2 and MWDG2 are the CUDA solvers of LISFLOOD-FP 8: a CPU build does not stop, it silently runs "
             "another solver (check the log), so the result is then NOT that solver's. ACC (CPU) is the default.")
RUNNER_FILES = ("lisflood.py", "data_conventions.py", "grid.py", "units.py", "wallclock.py")
MM_PER_HR = 3.6e6                                # m/s -> mm/hr
WET_M = (0.05, 0.30)


def runner_sources():
    """sha256 of the runner_shared copies this job uses (the CI test pins them to the runner)."""
    return {f: AR.sha256_file(os.path.join(AR.HERE, "runner_shared", f)) for f in RUNNER_FILES}


def check_settings(st):
    """DEFAULTS merged with `st`, checked; JobError names the bad key. 'solver' becomes the .par keyword."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (st or {}).items() if v is not None})
    s["cell_m"] = AR._num("cell_m", s["cell_m"], AR.MIN_CELL_M)
    s["buffer_m"] = AR._num("buffer_m", s["buffer_m"], 0.0)
    s["manning_n"] = AR._num("manning_n", s["manning_n"], 0.0001, 1.0)
    s["initial_tstep_s"] = AR._num("initial_tstep_s", s["initial_tstep_s"], 0.001)
    s["massint_s"] = AR._num("massint_s", s["massint_s"], 1.0)
    s["threads"] = int(AR._num("threads", s["threads"], 0, 512))
    try:
        s["solver"] = L.solver_from_text(s["solver"])
        s["theta"] = float(s["theta"])
        if not 0.0 < s["theta"] <= 1.0:
            raise L.ModelError("ACC theta must be in (0, 1], got {}".format(s["theta"]))
        if s["cfl"] is not None:
            s["cfl"] = float(s["cfl"])
            if not 0.0 < s["cfl"] <= 1.0:
                raise L.ModelError("ACC cfl must be in (0, 1], got {}".format(s["cfl"]))
        s["closed_edges"] = tuple(sorted({str(e).upper() for e in (s["closed_edges"] or ())}))
        bad = [e for e in s["closed_edges"] if e not in L.EDGE_LETTERS]
        if bad:
            raise L.ModelError("unknown domain edge(s) to close: {}".format(", ".join(bad)))
    except L.ModelError as e:
        raise JobError(str(e))
    return s


def find_exe(explicit=""):
    """The LISFLOOD-FP executable: `explicit` when it is a file, else the runner's search
    (data_conventions.detect_lisflood). The runner's numpy 'built-in' engine is never used here."""
    v = L.resolve_exe(explicit) if explicit else ""
    if v and L.is_builtin(v):
        raise JobError("the runner's built-in numpy engine is a screening approximation, not LISFLOOD-FP: not offered here")
    if v:
        if not os.path.isfile(v):
            raise JobError("the LISFLOOD-FP executable {!r} is not a file".format(explicit))
        if not os.access(v, os.X_OK):
            raise JobError("the LISFLOOD-FP executable {!r} is not executable".format(explicit))
        return v
    return DC.detect_lisflood() or ""


# ------------------------------------------------------------------ the domain (the same as anugarain's)
def model_terrain(grid, rings, buffer_m=0.0, start_xy=None, simplify_m=None):
    """The model DEM masked to the anugarain outer ring (so both models cover the same area): the
    Grid with NODATA outside it, plus info. NODATA is a wall in LISFLOOD-FP."""
    region = AR.domain_region(grid, rings)
    ring, info = AR.outer_ring(grid, region, buffer_m, start_xy, simplify_m)
    inside = AR.domain_region(grid, [ring]) & grid.valid()
    if int(inside.sum()) < 9:
        raise JobError("the domain has fewer than 9 valid model cells")
    data = np.where(inside, grid.data, NODATA)
    # crop to the valid cells: the grid edge must touch the domain, or the FREE edges of the .bci lie in a NODATA
    # frame and the model is closed (no valid cell is on an edge, so nothing can leave). Where the domain reaches
    # the grid edge, FREE lets the water out at the bed slope; elsewhere the NODATA rim is a wall.
    rows, cols = np.where(inside.any(axis=1))[0], np.where(inside.any(axis=0))[0]
    r0, r1, c0, c1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    cropped = Grid(data[r0:r1, c0:c1], grid.x0 + c0 * grid.dx, grid.y0 - r0 * grid.dx, grid.dx, NODATA, grid.crs_wkt)
    edge = cropped.valid()
    edge_cells = {"N": int(edge[0].sum()), "S": int(edge[-1].sum()), "W": int(edge[:, 0].sum()), "E": int(edge[:, -1].sum())}
    info = dict(info, ring=ring, domain_cells=int(inside.sum()), domain_km2=float(inside.sum() * grid.dx ** 2 / 1e6),
                edge_valid_cells=edge_cells, cropped_from=[int(grid.ny), int(grid.nx)])
    return cropped, info


def write_tif(path, grid, data=None, nodata=NODATA):
    """A float32 GeoTIFF of the grid (or of `data` on its cells), north-up, in the grid's CRS."""
    gdal = AR._gdal()
    arr = np.asarray(grid.data if data is None else data, dtype=np.float32)
    arr = np.where(np.isfinite(arr), arr, nodata).astype(np.float32)
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.nx, grid.ny, 1, gdal.GDT_Float32,
                                              options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform((grid.x0, grid.dx, 0.0, grid.y0, 0.0, -grid.dx))
    if grid.crs_wkt:
        ds.SetProjection(grid.crs_wkt)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(float(nodata))
    b.WriteArray(arr)
    ds.FlushCache()
    ds = None
    return path


# ------------------------------------------------------------------ inputs
def rain_text(t, r_m_s, comment=""):
    """The LISFLOOD-FP .rain file: a comment line, 'n seconds', then 'rate_mm_per_hr time_s' rows. The
    rows are the ANUGA series' own breakpoints, linearly interpolated by both solvers (np.interp in the ANUGA
    script), so the storm volume is the same. A series that ends above 0 gets a final zero row 1 s later."""
    t = np.asarray(t, float)
    r = np.asarray(r_m_s, float) * MM_PER_HR
    if len(t) != len(r) or len(t) < 2:
        raise JobError("the rain series needs 2+ rows")
    keep = np.concatenate([[True], np.diff(t) > 0])              # LISFLOOD-FP needs strictly increasing times
    t, r = t[keep], r[keep]
    if r[-1] > 0:
        t, r = np.append(t, t[-1] + 1.0), np.append(r, 0.0)
    lines = ["# {}".format(comment or "rainfall, mm/hr: written by damit_pmp:lisfloodrain"), "{} seconds".format(len(t))]
    lines += ["{:.6f} {:.3f}".format(a, b) for a, b in zip(r, t)]
    return "\n".join(lines) + "\n"


def depth_mm(t, r_m_s):
    """The storm depth (mm) of the piecewise-linear series."""
    return AR.rain_depth_m(t, r_m_s) * 1000.0


def gauge_from_ab(a, b, downstream_xy=None):
    """A LISFLOOD-FP gauge dict (the runner's gauge_section) from the discharge line a-b: centred on the
    middle of the line, as wide as the line, measuring the flow along the line's normal that points away
    from `downstream_xy` (the flow-path start) when given, else towards +x / +y. LISFLOOD-FP sections run
    along a grid axis, so an oblique line becomes the E/W or N/S section of the nearest direction."""
    ax, ay = a
    bx, by = b
    width = math.hypot(bx - ax, by - ay)
    if width <= 0:
        raise JobError("the two ends of the discharge line are the same point")
    cx, cy = 0.5 * (ax + bx), 0.5 * (ay + by)
    nx, ny = -(by - ay) / width, (bx - ax) / width
    if downstream_xy is not None:
        if (cx - downstream_xy[0]) * nx + (cy - downstream_xy[1]) * ny < 0:
            nx, ny = -nx, -ny
    elif nx < 0 or (nx == 0 and ny < 0):
        nx, ny = -nx, -ny
    g = L.gauge_section((cx, cy), (nx, ny), width)
    g["name"] = "dam_section"
    return g


def par_lines(st, sim_time_s, has_manning_grid=False, gauge=False):
    """The .par lines of a rain run: the keywords and order of lisflood.write_inputs, minus the breach
    inflow (bdyfile) and the arrival-time patch (hazard, inittm_depth), plus rainfall."""
    lines = [
        "DEMfile {}.dem.asc".format(NAME),
        "resroot {}".format(NAME),
        "dirroot results",
        "sim_time {:.0f}".format(sim_time_s),
        "initial_tstep {:.3f}".format(st["initial_tstep_s"]),
        "massint {:.0f}".format(st["massint_s"]),
        "saveint {:.0f}".format(sim_time_s + 10.0),
        "bcifile {}".format(BCI_NAME),
        "rainfall {}".format(RAIN_NAME),
        st["solver"],
    ]
    if st["solver"] in L.LIMIT_SLOPES_SOLVERS:
        lines.append("limitslopes")
    lines += ["elevoff", "depthoff"]
    if st["solver"] == L.SOLVER_ACC:
        if st["theta"] < 1.0:
            lines.append("theta {:.3f}".format(st["theta"]))
        if st["cfl"] is not None:
            lines.append("cfl {:.3f}".format(st["cfl"]))
    lines.append("fpfric {:.4f}".format(st["manning_n"]))
    if gauge:
        lines.append("gaugefile {}".format(GAUGE_NAME))
    return lines


def write_inputs(folder, terrain, t, r_m_s, st, sim_time_s, gauge=None, comment=""):
    """Write rain.dem.asc (local coordinates), rain.bci (FREE edges, as the runner), rain.rain, rain.gauge
    and rain.par into `folder`. Returns the .par path."""
    os.makedirs(folder, exist_ok=True)
    dem = L.local_grid(terrain)
    dem.write_asc(os.path.join(folder, NAME + ".dem.asc"))
    xmin, ymin, xmax, ymax = dem.bounds
    closed = st["closed_edges"]
    with open(os.path.join(folder, BCI_NAME), "w", encoding="utf-8") as f:
        for edge, lo, hi in (("N", xmin, xmax), ("S", xmin, xmax), ("E", ymin, ymax), ("W", ymin, ymax)):
            if edge not in closed:
                f.write("{} {:.3f} {:.3f} FREE\n".format(edge, lo, hi))
    with open(os.path.join(folder, RAIN_NAME), "w", encoding="utf-8") as f:
        f.write(rain_text(t, r_m_s, comment))
    if gauge:
        gx, gy = gauge["xy"][0] - terrain.x0, gauge["xy"][1] - terrain.yll
        with open(os.path.join(folder, GAUGE_NAME), "w", encoding="utf-8") as f:
            f.write("1\n")
            f.write("{:.3f} {:.3f} {} {:.3f}\n".format(
                *L._gauge_line(gx, gy, gauge["direction"], gauge["width_m"], dem.nx, dem.ny, dem.dx)))
    par = os.path.join(folder, PAR_NAME)
    with open(par, "w", encoding="utf-8") as f:
        f.write("# written by DamIT PMP (damit_pmp:lisfloodrain)\n")
        f.write("\n".join(par_lines(st, sim_time_s, gauge=bool(gauge))) + "\n")
    return par


# ------------------------------------------------------------------ results
def read_mass(path):
    """The .mass file as a dict of arrays: t_s, vol_m3 (water in the domain), qout_m3s, rain_m3 (the CUMULATIVE rain
    volume, the last column 'Rain-(Inf+Evap)') - or None when the file is missing / empty."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 12:
                    rows.append((float(p[0]), float(p[5]), float(p[8]), float(p[11])))
    except (OSError, StopIteration, ValueError):
        return None
    if not rows:
        return None
    a = np.asarray(rows, float)
    return {"t_s": a[:, 0], "vol_m3": a[:, 1], "qout_m3s": a[:, 2], "rain_m3": a[:, 3]}


def read_discharge(path):
    """(t_s, q_m3s) of the first gauge in results/rain.discharge, or None."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2:
                    try:
                        rows.append([float(p[0]), float(p[1])])
                    except ValueError:
                        continue
    except OSError:
        return None
    if not rows:
        return None
    a = np.asarray(rows, float)
    return a[:, 0], a[:, 1]


def wet_areas(depth, valid, cell_m, thresholds=WET_M):
    """{'>0.05 m': km2 ...} over the valid cells."""
    d = np.where(valid, depth, 0.0)
    return {"{:g} m".format(t): float((d > t).sum() * cell_m ** 2 / 1e6) for t in thresholds}


def summarize(folder, terrain, sim_time_s, rain_depth_mm):
    """Read the results of a finished run in `folder`: max depth (.max) onto the model grid, the .mass balance,
    the gauge discharge. Writes lisflood_max_depth.tif. Returns the summary dict (also lisflood_rain_results.json)."""
    res = os.path.join(folder, "results")
    maxp = os.path.join(res, NAME + ".max")
    if not os.path.isfile(maxp):
        raise JobError("LISFLOOD-FP wrote no {} (see lisflood.log)".format(maxp))
    g = Grid.read_asc(maxp)
    if g.data.shape != terrain.data.shape:
        raise JobError("the .max grid {} does not match the model grid {}".format(g.data.shape, terrain.data.shape))
    valid = terrain.valid()
    depth = np.where(g.valid() & valid, g.data, np.nan)
    write_tif(os.path.join(folder, MAX_DEPTH_NAME), terrain, depth, nodata=-9999.0)
    out = {"max_depth_m": float(np.nanmax(depth)), "mean_max_depth_wet_m": float(np.nanmean(depth[depth > WET_M[0]]))
           if np.any(depth > WET_M[0]) else 0.0,
           "wet_area_km2": wet_areas(np.nan_to_num(depth), valid, terrain.dx), "domain_km2": float(valid.sum() * terrain.dx ** 2 / 1e6),
           "storm_depth_mm": rain_depth_mm, "max_depth_file": MAX_DEPTH_NAME}
    m = read_mass(os.path.join(res, NAME + ".mass"))
    if m is not None:
        rain_in = float(m["rain_m3"][-1])
        stored = float(m["vol_m3"][-1])
        trap = getattr(np, "trapezoid", None) or np.trapz
        out["balance"] = {"last_time_s": float(m["t_s"][-1]), "rain_in_m3": rain_in, "stored_m3": stored,
                          "outflow_m3_by_difference": rain_in - stored,
                          "outflow_m3_from_qout": float(trap(m["qout_m3s"], m["t_s"])),
                          "peak_qout_m3s": float(m["qout_m3s"].max()),
                          "note": "rain_in is the last (cumulative) value of the .mass rain column; Qout is the domain-edge outflow"}
        out["finished"] = bool(m["t_s"][-1] >= 0.99 * sim_time_s)
    d = read_discharge(os.path.join(res, NAME + ".discharge"))
    if d is not None:
        t, q = d
        i = int(np.argmax(np.abs(q)))
        out["gauge"] = {"peak_abs_m3_s": float(abs(q[i])), "t_peak_s": float(t[i]), "signed_q_at_peak_m3_s": float(q[i]),
                        "volume_abs_m3": float(np.sum(0.5 * (np.abs(q[1:]) + np.abs(q[:-1])) * np.diff(t))) if len(t) > 1 else 0.0,
                        "samples": int(len(t))}
    AR.write_json(os.path.join(folder, RESULTS_NAME), out)
    return out


def runner_inputs_match():
    """Self-check used by the tests: every .par line a rain run writes that lisflood.write_inputs also knows is
    byte-identical (the runner is the source of the keywords). Returns (shared, only_rain, only_runner) line sets
    for a default ACC run."""
    import tempfile

    class _H:                                        # the least of a hydrograph write_inputs needs
        def resampled(self, dt):
            return np.array([0.0, 60.0]), np.array([0.0, 0.0])
    st = check_settings({})
    with tempfile.TemporaryDirectory() as d:
        data = np.zeros((6, 6))
        dem = Grid(data, 1000.0, 1060.0, 10.0, NODATA)
        lst = L.LisfloodSettings("x", sim_time_s=3600.0, massint_s=st["massint_s"], initial_tstep_s=st["initial_tstep_s"],
                                 manning_n=st["manning_n"], theta=st["theta"], cfl=st["cfl"])
        par = L.write_inputs(d, dem, (1025.0, 1035.0), _H(), lst, name=NAME)
        runner = {ln for ln in open(par, encoding="utf-8").read().splitlines() if ln and not ln.startswith("#")}
    mine = set(par_lines(st, 3600.0))
    return mine & runner, mine - runner, runner - mine
