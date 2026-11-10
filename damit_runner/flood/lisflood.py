"""LISFLOOD-FP input files, the run and its results (the DamSafety Runner's file layout).

This is the ONE module of the DamIT plugins that starts a program: an external LISFLOOD-FP executable the user
chose (LISFLOOD_EXE, else the provider setting, PATH or an install place; find_exe), under a wall-clock limit, its
output in <run>/lisflood.log. LISFLOOD_EXE = "builtin" runs the vendored numpy engine (builtin_lisflood.py) in this
process instead; so does an empty LISFLOOD_EXE when no LISFLOOD-FP is found anywhere, with a warning in the log and
the run report, as the old ND Breach Runner did. ANUGA is started by anuga_run.py through
launch() here. Nothing here starts HEC-RAS, Wine, ndbreach or nddam tools."""
import os
import shutil
import subprocess
import time

import numpy as np

from . import builtin_lisflood as BL
from .geom import Grid, NODATA

BUILTIN = "builtin"
DEFAULT_MAX_WALL_S = 24 * 3600.0
ARRIVAL_TOL_M = 0.001
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}
PATCH_MISSING_MARKER = "Unknown parameter ignored: inittm_depth"


class ModelError(RuntimeError):
    pass


class WallLimit(ModelError):
    """The run hit its wall-clock limit."""


def is_builtin(exe):
    return str(exe or "").strip().lower() == BUILTIN


# Where LISFLOOD-FP is looked for when LISFLOOD_EXE is empty, in this order (the old ND Breach Runner's
# find_lisflood / nd_data.lisflood_candidates): the DamIT Runner provider setting, the ND Breach Runner / DamSafety
# Runner provider setting (read only), the NDBREACH_LISFLOOD environment variable, lisflood / lisflood-fp on PATH,
# then the usual install places. Nothing found = the built-in engine, with a warning (the old Runner's fallback).
SETTING_DAMIT = "DAMIT_RUN_LISFLOOD_EXE"
SETTING_NDBREACH = "NDBREACH_LISFLOOD_EXE"
SETTING_USE_BUILTIN = "DAMIT_RUN_USE_BUILTIN"
ENV_NDBREACH = "NDBREACH_LISFLOOD"
PATH_NAMES = ("lisflood", "lisflood-fp", "lisflood.exe")
INSTALL_GLOBS = (("lisflood-fp", "lisflood"), ("lisflood-fp*", "build", "lisflood"), ("lisflood*", "build", "lisflood"),
                 ("src", "lisflood*", "build", "lisflood"), ("Documents", "lisflood*", "build", "lisflood"),
                 ("Applications", "lisflood*", "lisflood"), (".ndbreach", "bin", "lisflood"),
                 ("Library", "Application Support", "ndbreach", "lisflood"))
SYSTEM_GLOBS = ("/opt/lisflood*/build/lisflood", "/opt/lisflood*/lisflood", "/usr/local/bin/lisflood",
                "/opt/homebrew/bin/lisflood")
FALLBACK_WARNING = ("WARNING: no LISFLOOD-FP executable was found (LISFLOOD_EXE empty, no provider setting, nothing "
                    "on PATH or in the usual install places), so the BUILT-IN engine ran instead: the same local-"
                    "inertial equations in numpy, a screening approximation and slower, not LISFLOOD-FP. Set "
                    "LISFLOOD_EXE (or Processing > Options > Providers > DamIT Runner) to a LISFLOOD-FP build for "
                    "the record run.")


def provider_setting(key):
    """A Processing provider setting (QgsSettings Processing/Configuration/<key>), '' outside QGIS."""
    try:
        from qgis.core import QgsSettings
    except ImportError:
        return ""
    try:
        v = QgsSettings().value("Processing/Configuration/" + key, "")
    except Exception:                                            # noqa: BLE001 - settings are optional
        return ""
    return "" if v is None else str(v).strip()


def _executable(p):
    return bool(p) and os.path.isfile(p) and (os.name == "nt" or os.access(p, os.X_OK))


def install_candidates(home=None):
    """LISFLOOD-FP builds in the usual install places (existing executables only)."""
    import glob
    home = home or os.path.expanduser("~")
    out = []
    for parts in INSTALL_GLOBS:
        out += sorted(glob.glob(os.path.join(home, *parts)))
    for pat in SYSTEM_GLOBS:
        out += sorted(glob.glob(pat))
    return [p for p in out if _executable(p)]


def find_exe(exe, settings=None, environ=None, home=None):
    """Which engine runs, and why: {'exe', 'how', 'warning'}. exe: the LISFLOOD_EXE parameter. settings: a
    function key -> value for the provider settings (default provider_setting). 'builtin' (or 'built-in') = the
    built-in engine, on request. A path or program name that is not found is an error (DamIT does not replace a
    LISFLOOD-FP the user named). Empty: the provider settings, NDBREACH_LISFLOOD, PATH, the usual install places;
    none = the built-in engine with FALLBACK_WARNING."""
    settings = settings or provider_setting
    environ = os.environ if environ is None else environ
    e = str(exe or "").strip()
    if is_builtin(e) or e.lower() in ("built-in", "built in"):
        return {"exe": BUILTIN, "how": "LISFLOOD_EXE = builtin", "warning": None}
    if e:
        if os.path.isfile(e):
            return {"exe": e, "how": "LISFLOOD_EXE", "warning": None}
        found = shutil.which(e)
        if found:
            return {"exe": found, "how": "LISFLOOD_EXE on PATH", "warning": None}
        raise ModelError("LISFLOOD-FP executable not found: {}. Nothing was run. Leave LISFLOOD_EXE empty to use "
                         "an installed LISFLOOD-FP (or the built-in engine when there is none), or set it to "
                         "'builtin'.".format(e))
    if str(settings(SETTING_USE_BUILTIN) or "").lower() in ("true", "1", "yes"):
        return {"exe": BUILTIN, "how": "provider setting " + SETTING_USE_BUILTIN, "warning": None}
    for key in (SETTING_DAMIT, SETTING_NDBREACH):
        v = str(settings(key) or "").strip()
        if v and is_builtin(v):
            return {"exe": BUILTIN, "how": "provider setting " + key, "warning": None}
        if v and _executable(v):
            return {"exe": v, "how": "provider setting " + key, "warning": None}
    v = str(environ.get(ENV_NDBREACH) or "").strip()
    if v and _executable(v):
        return {"exe": v, "how": ENV_NDBREACH, "warning": None}
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return {"exe": found, "how": "PATH ({})".format(name), "warning": None}
    found = install_candidates(home)
    if found:
        return {"exe": found[0], "how": "install place", "warning": None}
    return {"exe": BUILTIN, "how": "fallback: no LISFLOOD-FP found", "warning": FALLBACK_WARNING}


def resolve_exe(exe):
    """The engine to run for LISFLOOD_EXE (find_exe()['exe'])."""
    return find_exe(exe)["exe"]


def wall_limit_s(max_wall_s):
    try:
        v = float(max_wall_s or 0.0)
    except (TypeError, ValueError):
        v = 0.0
    return v if v > 0 else DEFAULT_MAX_WALL_S


def write_asc(path, a, xll, yll, dx, fmt="%.3f"):
    a = np.where(np.isfinite(a), a, NODATA)
    ny, nx = a.shape
    with open(path, "w", encoding="utf-8") as f:
        f.write("ncols {}\nnrows {}\nxllcorner {:.6f}\nyllcorner {:.6f}\ncellsize {:.6f}\nNODATA_value {:g}\n"
                .format(nx, ny, xll, yll, dx, NODATA))
        np.savetxt(f, a, fmt=fmt)


def read_asc(path):
    with open(path, encoding="utf-8") as f:
        head = {}
        for _ in range(6):
            k, v = f.readline().split()[:2]
            head[k.lower()] = float(v)
        a = np.loadtxt(f, ndmin=2)
    nod = head.get("nodata_value", NODATA)
    a = np.where(a == nod, np.nan, a)
    return a


def inflow_cells(dem, inflow_xy, line=None):
    cells = []
    r, c = dem.rc(*inflow_xy)
    valid = np.isfinite(dem.data)
    if not dem.inside(r, c) or not valid[r, c]:
        raise ModelError("the breach inflow point is outside the DEM or on no-data")
    if line is not None:
        (x0, y0), (x1, y1) = line
        n = max(2, int(np.hypot(x1 - x0, y1 - y0) / (0.5 * dem.dx)) + 1)
        for t in np.linspace(0.0, 1.0, n):
            rr, cc = dem.rc(x0 + t * (x1 - x0), y0 + t * (y1 - y0))
            if dem.inside(rr, cc) and valid[rr, cc] and (rr, cc) not in cells:
                cells.append((rr, cc))
    if (r, c) not in cells:
        cells.append((r, c))
    return cells


def write_inputs(workdir, dem, inflow_xy, hydrograph, sim_time_s, manning_n=0.06, arrival_depth_m=0.03048,
                 name="run", inflow_line=None, massint_s=300.0, initial_tstep_s=10.0, cells=None):
    """<name>.dem.asc / .bci / .bdy / .par in local coordinates (lower-left at 0, 0), as the DamSafety Runner
    writes them: a QVAR point source per inflow cell (1/n of the breach outflow each), free edges, the ACC solver
    and inittm_depth at the arrival depth. cells: the inflow cells (row, col) when the caller chose them (DamIT
    Screener's injection cells across the breach)."""
    os.makedirs(workdir, exist_ok=True)
    cells = list(cells) if cells else inflow_cells(dem, inflow_xy, inflow_line)
    local = Grid(dem.data, 0.0, dem.ny * dem.dx, dem.dx)
    write_asc(os.path.join(workdir, name + ".dem.asc"), local.data, 0.0, 0.0, dem.dx)
    xmin, ymin, xmax, ymax = local.bounds
    with open(os.path.join(workdir, name + ".bci"), "w", encoding="utf-8") as f:
        for rr, cc in cells:
            px, py = local.xy(rr, cc)
            f.write("P {:.3f} {:.3f} QVAR breach\n".format(px, py))
        for edge, lo, hi in (("N", xmin, xmax), ("S", xmin, xmax), ("E", ymin, ymax), ("W", ymin, ymax)):
            f.write("{} {:.3f} {:.3f} FREE\n".format(edge, lo, hi))
    t, q = hydrograph.resampled(30.0)
    n = len(cells)
    with open(os.path.join(workdir, name + ".bdy"), "w", encoding="utf-8") as f:
        f.write("breach hydrograph: m3/s / (cell size x {} inflow cells)\n".format(n))
        f.write("breach\n{} seconds\n".format(len(t)))
        for tv, qv in zip(t, q):
            f.write("{:.6f} {:.4f}\n".format(qv / (dem.dx * n), tv))
    lines = ["DEMfile {}.dem.asc".format(name), "resroot {}".format(name), "dirroot results",
             "sim_time {:.0f}".format(sim_time_s), "initial_tstep {:.3f}".format(initial_tstep_s),
             "massint {:.0f}".format(massint_s), "saveint {:.0f}".format(sim_time_s + 10.0),
             "bcifile {}.bci".format(name), "bdyfile {}.bdy".format(name), "acceleration",
             "hazard", "elevoff", "depthoff", "inittm_depth {:.4f}".format(arrival_depth_m),
             "fpfric {:.4f}".format(manning_n)]
    par = os.path.join(workdir, name + ".par")
    with open(par, "w", encoding="utf-8") as f:
        f.write("# written by DamIT Runner\n" + "\n".join(lines) + "\n")
    return par


def launch(argv, cwd, log_path, wall_s, env=None, cancel=None, what="model"):
    """Start argv in cwd with its output in log_path, stop it at wall_s (WallLimit) or when cancel() is true.
    Returns the elapsed seconds. The only process launch of the DamIT plugins."""
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=logf, stderr=subprocess.STDOUT, **NO_WINDOW)
        while proc.poll() is None:
            time.sleep(1.0)
            if cancel is not None and cancel():
                proc.kill()
                proc.wait()
                raise ModelError("{} cancelled".format(what))
            if time.time() - t0 > wall_s:
                proc.kill()
                proc.wait()
                logf.write("\nStopped by DamIT: wall-clock limit {:.0f} s reached\n".format(wall_s))
                raise WallLimit("{} hit its wall-clock limit of {:.1f} h".format(what, wall_s / 3600.0))
    if proc.returncode != 0:
        with open(log_path, errors="replace", encoding="utf-8") as f:
            tail = f.read()[-1500:]
        raise ModelError("{} stopped with code {}:\n{}".format(what, proc.returncode, tail))
    return time.time() - t0


def run(workdir, par, exe, max_wall_s=0.0, threads=0, cancel=None, log=None):
    """Run the .par: the built-in engine in this process or LISFLOOD-FP as a program. Returns
    {'engine', 'wall_s', 'wall_limit_s', 'unpatched'}."""
    limit = wall_limit_s(max_wall_s)
    t0 = time.time()
    if is_builtin(exe):
        lines = []

        def say(m):
            lines.append(m)
            if log:
                log(m)

        def stop():
            if cancel is not None and cancel():
                return True
            return time.time() - t0 > limit
        try:
            BL.run_par(par, cancel=stop, log=say)
        except BL.Cancelled:
            if time.time() - t0 > limit:
                raise WallLimit("the built-in engine hit its wall-clock limit of {:.1f} h".format(limit / 3600.0))
            raise ModelError("built-in engine cancelled")
        except BL.EngineError as e:
            raise ModelError("built-in engine: {}".format(e))
        finally:
            with open(os.path.join(workdir, "lisflood.log"), "w", encoding="utf-8") as f:
                f.write(BL.NAME + "\n" + "\n".join(lines) + "\n")
        return {"engine": BL.NAME, "wall_s": time.time() - t0, "wall_limit_s": limit, "unpatched": False}
    env = dict(os.environ)
    if threads:
        env["OMP_NUM_THREADS"] = str(int(threads))
    wall = launch([exe, "-v", os.path.basename(par)], workdir, os.path.join(workdir, "lisflood.log"), limit, env,
                  cancel, "LISFLOOD-FP")
    with open(os.path.join(workdir, "lisflood.log"), errors="replace", encoding="utf-8") as f:
        unpatched = PATCH_MISSING_MARKER in f.read()
    if unpatched and log:
        log("WARNING: this LISFLOOD-FP ignores inittm_depth: arrival times mark the first wetting.")
    return {"engine": "LISFLOOD-FP ({})".format(exe), "wall_s": wall, "wall_limit_s": limit, "unpatched": unpatched}


def mass_rows(path):
    """The .mass file as rows [time_s, domain_vol_m3, Qin_cms, Qout_cms] (columns 0, 5, 6, 8; the DamSafety
    Runner's _read_mass_rows); an empty (0, 4) array when it is missing or short."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 11:
                    rows.append((float(p[0]), float(p[5]), float(p[6]), float(p[8])))
    except (OSError, StopIteration, ValueError):
        pass
    return np.asarray(rows, dtype=float).reshape(-1, 4)


def _trapz(y, x):
    f = getattr(np, "trapezoid", None) or np.trapz
    return float(f(y, x))


def boundary_outflow(workdir, name="run"):
    """{'injected_m3', 'outflow_m3', 'outflow_pct'} from results/<name>.mass: the water that left the model through
    its edges (positive Qout integrated over time) as a share of the water put in (Qin integrated), as the DamSafety
    Runner's read_results reports boundary_outflow_pct. None when there is no .mass file."""
    rows = mass_rows(os.path.join(workdir, "results", name + ".mass"))
    if len(rows) < 2:
        return None
    inj = _trapz(np.clip(rows[:, 2], 0.0, None), rows[:, 0])
    out = _trapz(np.clip(rows[:, 3], 0.0, None), rows[:, 0])
    return {"injected_m3": inj, "outflow_m3": out, "outflow_pct": round(100.0 * out / inj, 2) if inj > 0 else None}


def read_results(workdir, dem, arrival_depth_m, name="run", velocity_min_depth_m=0.03):
    """{'depth', 'velocity', 'arrival_hr', 'wse'} (m, m/s, h, m) on the DEM grid."""
    res = os.path.join(workdir, "results")

    def load(ext, required=True):
        p = os.path.join(res, name + ext)
        if not os.path.exists(p):
            if required:
                raise ModelError("The flood model did not write {}".format(p))
            return None
        a = read_asc(p)
        if a.shape != dem.data.shape:
            raise ModelError("{} has shape {} but the DEM is {}".format(p, a.shape, dem.data.shape))
        return a
    h = load(".max")
    h = np.where(np.isfinite(h), h, 0.0)
    v = load(".maxVc", required=False)
    v = np.zeros(h.shape) if v is None else np.where(np.isfinite(v) & (h >= velocity_min_depth_m), v, 0.0)
    arr = load(".inittm", required=False)
    wet = h >= arrival_depth_m - ARRIVAL_TOL_M
    arr = np.full(h.shape, np.nan) if arr is None else np.where(np.isfinite(arr) & (arr >= 0) & wet, arr, np.nan)
    wse = np.where(h > 0, dem.data + h, np.nan)
    valid = np.isfinite(dem.data)
    return {"depth": np.where(valid, h, np.nan), "velocity": np.where(valid, v, np.nan), "arrival_hr": arr,
            "wse": wse}
