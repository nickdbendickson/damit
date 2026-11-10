"""The ANUGA tier: after LISFLOOD-FP (or the built-in engine) has found the extent, ANUGA runs on the DamSafety
Runner's default mesh (mesh.py, ported from DWR_Plugins main: the flooded area plus ANUGA_BUFFER m traced from the
flood mask, refined to ANUGA_FINE m2 triangles in the flooded area within ANUGA_NEAR_MI of the inflow, ANUGA_COARSE
m2 elsewhere), and its maxima are the final results, as in the DamSafety Runner's middle tier. As there, the inlet
line is at least three cells wide, and when the ANUGA flood reaches the mesh edge deeper than EDGE_TOL_FT the mesh is
traced again once from both floods with the buffer doubled.

The worker (anuga_env/anuga_worker.py, vendored from the DamSafety Runner) runs in the ANUGA Python
(ANUGA_PYTHON), started through lisflood.launch under the same wall-clock limit. Not ported: the gmsh mesher,
culverts, embankment breaklines, the fine-terrain bed, checkpoints and worker adoption."""
import json
import os
import shutil

import numpy as np

from . import lisflood as LF
from . import mesh as M

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


def have_scipy():
    import importlib.util
    try:
        return importlib.util.find_spec("scipy.ndimage") is not None
    except ImportError:
        return False


def mesh_polygons(dem, flooded, inflow_xy, buffer_m, near_m):
    """The DamSafety Runner's default ANUGA mesh polygons (outer, fine) for a flood mask (mesh.py)."""
    return M.mesh_polygons(dem, flooded, inflow_xy, M.MeshSettings(buffer_m, near_m))


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


def _save_ring(path, ring):
    if len(ring):
        np.savetxt(path, ring, delimiter=",", header="x,y", comments="", fmt="%.3f")


def edge_depth_m(depth):
    d = np.where(np.isfinite(depth), depth, 0.0)
    return float(max(d[0, :].max(), d[-1, :].max(), d[:, 0].max(), d[:, -1].max())) if d.size else 0.0


def run(workdir, dem, depth, inflow_xy, direction, breach_width_m, hydrograph, p, cancel=None, log=None):
    """Write the job, run the worker, read result.npz. Returns {'depth', 'velocity', 'arrival_hr', 'wse',
    'stats', 'mesh'} on the DEM grid. p: manning, fine_m2, coarse_m2, near_m, buffer_m, sim_time_s, arrival_m,
    threads, python, wall_s, edge_tol_m (the DamSafety Runner's second pass: None = no second pass)."""
    py = find_python(p.get("python"))
    if not py:
        raise AnugaError("No ANUGA Python: set ANUGA_PYTHON to the python of an environment with ANUGA installed.")
    if not have_scipy():
        raise AnugaError("The ANUGA mesh needs scipy in the QGIS Python (scipy.ndimage), as the DamSafety Runner's "
                         "does.")
    os.makedirs(workdir, exist_ok=True)
    flooded = M.flooded_mask(depth)
    buffer_m = float(p["buffer_m"])
    width = max(3.0 * dem.dx, float(breach_width_m or 0.0))
    inlet = M.inlet_line(inflow_xy, direction, width)
    runs = []
    res = None
    for k in range(2):
        outer, fine = mesh_polygons(dem, flooded, inflow_xy, buffer_m, p["near_m"])
        _save_ring(os.path.join(workdir, "mesh_boundary.csv"), outer)
        _save_ring(os.path.join(workdir, "mesh_fine_area.csv"), fine)
        res = _run_once(workdir, py, dem, outer, fine, inlet, hydrograph, p, cancel, log, buffer_m)
        edge = edge_depth_m(res["depth"]) if not res["stats"].get("max_edge_depth_m") else float(
            res["stats"]["max_edge_depth_m"])
        runs.append({"buffer_m": buffer_m, "outer_vertices": int(len(outer)), "fine_vertices": int(len(fine)),
                     "max_edge_depth_ft": round(edge / 0.3048, 2), "triangles": res["stats"].get("triangles")})
        tol = p.get("edge_tol_m")
        if tol is None or edge <= float(tol) or k == 1:
            if tol is not None and edge > float(tol):
                res.setdefault("notes", []).append(
                    "ANUGA: the flood reaches the mesh boundary {:.1f} ft deep; its extent is limited by the "
                    "LISFLOOD-FP domain.".format(edge / 0.3048))
            break
        if log:
            log("ANUGA flood reaches the mesh edge ({:.1f} ft); widening the mesh.".format(edge / 0.3048))
        flooded = M.flooded_mask(res["depth"]) | flooded
        buffer_m *= 2.0
    res["mesh"] = {"mesher": "DamSafety Runner default (ANUGA create_domain_from_regions)", "runs": runs,
                   "inlet_width_m": round(width, 1)}
    return res


def _run_once(workdir, py, dem, outer, fine, inlet, hydrograph, p, cancel, log, buffer_m):
    job = write_job(os.path.join(workdir, "anuga_job.npz"), dem, outer, fine, inlet, hydrograph, p)
    out = os.path.join(workdir, "anuga_result.npz")
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, OMP_NUM_THREADS=str(int(p.get("threads") or 1)))
    if log:
        log("ANUGA: {} {} (mesh: {} outer / {} refined vertices, {:.0f} m2 / {:.0f} m2, near {:.0f} m, buffer "
            "{:.0f} m)".format(py, os.path.basename(WORKER), len(outer), len(fine), p["fine_m2"], p["coarse_m2"],
                               p["near_m"], buffer_m))
    LF.launch([py, WORKER, job, out], workdir, os.path.join(workdir, "anuga.log"), LF.wall_limit_s(p.get("wall_s")),
              env, cancel, "ANUGA")
    if not os.path.isfile(out):
        raise AnugaError("ANUGA wrote no result ({})".format(out))
    with np.load(out, allow_pickle=False) as r:
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
