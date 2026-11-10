"""The ANUGA tier: after LISFLOOD-FP (or the built-in engine) has found the extent, ANUGA runs on a mesh over the
flooded area plus ANUGA_BUFFER m, refined to ANUGA_FINE m2 triangles within ANUGA_NEAR_MI of the inflow (ANUGA_COARSE
m2 elsewhere), and its maxima are the final results, as in the DamSafety Runner's middle tier.

The worker (anuga_env/anuga_worker.py, vendored from the DamSafety Runner) runs in the ANUGA Python
(ANUGA_PYTHON), started through lisflood.launch under the same wall-clock limit. Simplified against the DamSafety
Runner: the outer mesh polygon is the rectangle around the flood plus the buffer (inside the DEM) and the refined
polygon an octagon around the inflow; no gmsh mesher, culverts, breaklines or checkpoints."""
import json
import math
import os
import shutil

import numpy as np

from . import lisflood as LF

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anuga_env", "anuga_worker.py")


class AnugaError(RuntimeError):
    pass


def find_python(setting=""):
    """ANUGA_PYTHON, else a python of a conda env named 'anuga' beside this one, else None."""
    s = str(setting or "").strip()
    if s:
        if os.path.isfile(s):
            return s
        found = shutil.which(s)
        if found:
            return found
        raise AnugaError("ANUGA Python not found: {}".format(s))
    for base in (os.environ.get("CONDA_PREFIX", ""), os.path.expanduser("~/miniforge3"),
                 os.path.expanduser("~/miniconda3"), os.path.expanduser("~/anaconda3")):
        if not base:
            continue
        root = base.split(os.sep + "envs" + os.sep)[0]
        for p in (os.path.join(root, "envs", "anuga", "bin", "python"),
                  os.path.join(root, "envs", "anuga", "python.exe")):
            if os.path.isfile(p):
                return p
    return None


def octagon(center, radius, n=8):
    a = np.linspace(0.0, 2 * math.pi, n, endpoint=False) + math.pi / n
    return np.column_stack([center[0] + radius * np.cos(a), center[1] + radius * np.sin(a)])


def mesh_polygons(dem, depth, inflow_xy, arrival_m, buffer_m, near_m):
    wet = np.isfinite(depth) & (depth >= arrival_m)
    xs, ys = dem.x_centers(), dem.y_centers()
    rr, cc = np.nonzero(wet)
    if not len(rr):
        x0 = x1 = inflow_xy[0]
        y0 = y1 = inflow_xy[1]
    else:
        x0, x1 = xs[cc].min(), xs[cc].max()
        y0, y1 = ys[rr].min(), ys[rr].max()
    bx0, by0, bx1, by1 = dem.bounds
    pad = 2 * dem.dx
    x0, y0 = max(x0 - buffer_m, bx0 + pad), max(y0 - buffer_m, by0 + pad)
    x1, y1 = min(x1 + buffer_m, bx1 - pad), min(y1 + buffer_m, by1 - pad)
    outer = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    room = min(inflow_xy[0] - x0, x1 - inflow_xy[0], inflow_xy[1] - y0, y1 - inflow_xy[1]) - 2 * dem.dx
    r = min(near_m, room)
    fine = octagon(inflow_xy, r) if r > 5 * dem.dx else np.zeros((0, 2))
    return outer, fine


def inlet_line(inflow_xy, direction, width_m):
    ux, uy = direction
    px, py = -uy, ux
    h = 0.5 * max(width_m, 1.0)
    x, y = inflow_xy
    return np.array([[x - px * h, y - py * h], [x + px * h, y + py * h]])


def write_job(path, dem, outer, fine, inlet, hydrograph, p):
    job = {"dem": np.where(np.isfinite(dem.data), dem.data, np.nan).astype(np.float32), "dem_x0": dem.x0,
           "dem_y0": dem.y0, "dem_dx": dem.dx, "manning_n": p["manning"], "manning": np.zeros(0),
           "boundary": outer, "fine": fine, "inlet": inlet, "fine_area": p["fine_m2"],
           "coarse_area": p["coarse_m2"], "hyd_t": np.asarray(hydrograph.t_s, float),
           "hyd_q": np.asarray(hydrograph.q_cms, float), "sim_time": p["sim_time_s"], "yieldstep": 300.0,
           "arrival_depth": p["arrival_m"], "velocity_min_depth": 0.03, "algorithm": "DE0",
           "threads": int(p.get("threads") or 1), "edge_bc": "outflow",
           "out_x0": dem.x0, "out_y0": dem.y0, "out_dx": dem.dx, "out_nx": dem.nx, "out_ny": dem.ny}
    np.savez(path, **job)
    return path


def run(workdir, dem, depth, inflow_xy, direction, breach_width_m, hydrograph, p, cancel=None, log=None):
    """Write the job, run the worker, read result.npz. Returns {'depth', 'velocity', 'arrival_hr', 'wse',
    'stats'} on the DEM grid. p: manning, fine_m2, coarse_m2, near_m, buffer_m, sim_time_s, arrival_m, threads,
    python, wall_s."""
    py = find_python(p.get("python"))
    if not py:
        raise AnugaError("No ANUGA Python: set ANUGA_PYTHON to the python of an environment with ANUGA installed.")
    os.makedirs(workdir, exist_ok=True)
    outer, fine = mesh_polygons(dem, depth, inflow_xy, p["arrival_m"], p["buffer_m"], p["near_m"])
    inlet = inlet_line(inflow_xy, direction, breach_width_m)
    job = write_job(os.path.join(workdir, "anuga_job.npz"), dem, outer, fine, inlet, hydrograph, p)
    out = os.path.join(workdir, "anuga_result.npz")
    env = dict(os.environ, OMP_NUM_THREADS=str(int(p.get("threads") or 1)))
    if log:
        log("ANUGA: {} {} (mesh {:.0f} m2 / {:.0f} m2, near {:.0f} m, buffer {:.0f} m)".format(
            py, os.path.basename(WORKER), p["fine_m2"], p["coarse_m2"], p["near_m"], p["buffer_m"]))
    LF.launch([py, WORKER, job, out], workdir, os.path.join(workdir, "anuga.log"), LF.wall_limit_s(p.get("wall_s")),
              env, cancel, "ANUGA")
    if not os.path.isfile(out):
        raise AnugaError("ANUGA wrote no result ({})".format(out))
    r = np.load(out, allow_pickle=False)
    try:
        stats = json.loads(str(r["stats"])) if "stats" in r else {}
    except ValueError:
        stats = {}
    res = {k: np.asarray(r[k], float) for k in ("depth", "velocity", "arrival_hr", "wse")}
    for k, a in res.items():
        if a.shape != dem.data.shape:
            raise AnugaError("ANUGA {} has shape {}, the grid is {}".format(k, a.shape, dem.data.shape))
    res["depth"] = np.where(np.isfinite(res["depth"]), res["depth"], 0.0)
    res["velocity"] = np.where(np.isfinite(res["velocity"]), res["velocity"], 0.0)
    res["stats"] = stats
    return res
