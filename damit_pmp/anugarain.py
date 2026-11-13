"""ANUGA rain-on-grid job: the runner's gmsh mesh over a basin / extent, a DEM-based domain, rain.

Everything here is plain numpy / GDAL (no QGIS, no process launching; damit_pmp/launch.py is the
only module that starts a process). The mesh is the damit_runner ANUGA gmsh mesh: the spec goes to
the runner's own gmsh_mesher.py (runner_shared/, a verbatim copy; sha-pinned by a CI test) and
the outer ring, the flow-path refinement line, the sizing defaults and the quality gate are the
runner's (terrain.mask_outline / trace_downstream, gmsh_mesher.default_sizes / build_mesh).

What differs from a breach run, because rain has no breach: the domain is the basin (not the
flooded area plus a buffer), there is no inlet line, and the refinement is the flow path from an
optional start point (the runner's inflow point plays that role). The rain comes in as the series
damit_pmp:raingrid writes (time_s, rate_m_per_s) with an optional per-triangle factor from a
raster. The generated script builds the ANUGA domain with the runner's own worker helpers.
"""
import hashlib
import json
import math
import os
import shutil

import numpy as np

from .runner_shared import gmsh_mesher as gmshmod
from .runner_shared import grid as gridmod
from .runner_shared import terrain

RUNNER_FILES = ("gmsh_mesher.py", "grid.py", "terrain.py", "anuga_worker.py", "omp_probe.py",
                "anuga_dtdiag.py", "anuga_fine_maxima.py", "wallclock.py")
# beside the script (anuga_fine_maxima.py: the worker imports it at the top since DamSafety Runner 3.17.9)
SCRIPT_FILES = ("gmsh_mesher.py", "anuga_worker.py", "omp_probe.py", "anuga_dtdiag.py", "anuga_fine_maxima.py")
SCRIPT_TEMPLATE = os.path.join("templates", "run_anuga_rain.py")
SCRIPT_NAME = "run_anuga_rain.py"
JOB_NAME = "anuga_rain_job.npz"
SETTINGS_NAME = "anuga_rain_settings.json"
SPEC_NAME = "gmsh_mesh_in.json"
MESH_NAME = "gmsh_mesh.npz"
MSH_NAME = "gmsh_mesh.msh"
MANIFEST_NAME = "run_manifest.json"
RATE_NAME = "rain_rate_m_per_s.csv"
FINE_NAME = "elev_fine.npy"
HERE = os.path.dirname(os.path.abspath(__file__))

# the runner's defaults (AnugaSettings, rundam / engine parameters): the numbers a breach run uses
DEFAULTS = dict(cell_m=10.0, buffer_m=0.0, yieldstep_s=300.0, manning_n=0.06, algorithm="DE0",
                edge_bc="outflow", threads=1, gmsh_timeout_s=600.0, extra_h=6.0)
ALGORITHMS = ("DE0", "DE1", "DE2")
EDGE_BCS = ("outflow", "transmissive")
FINE_MAX_CELLS = 256e6            # AnugaSettings.elevation_max_cells
MIN_CELL_M = 0.5


class JobError(ValueError):
    """A bad input for the ANUGA rain job (the algorithm reports it as a failure)."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _num(name, v, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise JobError("{} must be a number, not {!r}".format(name, v))
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise JobError("{} = {!r} is out of range".format(name, v))
    return x


def check_settings(st):
    """The settings dict (DEFAULTS merged with `st`) checked; JobError names the bad key."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (st or {}).items() if v is not None})
    s["cell_m"] = _num("cell_m", s["cell_m"], MIN_CELL_M)
    s["buffer_m"] = _num("buffer_m", s["buffer_m"], 0.0)
    s["yieldstep_s"] = _num("yieldstep_s", s["yieldstep_s"], 1.0)
    s["manning_n"] = _num("manning_n", s["manning_n"], 0.0001, 1.0)
    s["threads"] = int(_num("threads", s["threads"], 0, 512))
    s["gmsh_timeout_s"] = _num("gmsh_timeout_s", s["gmsh_timeout_s"], 10.0)
    if str(s["algorithm"]) not in ALGORITHMS:
        raise JobError("algorithm must be one of {}".format(", ".join(ALGORITHMS)))
    if str(s["edge_bc"]).strip().lower() not in EDGE_BCS:
        raise JobError("edge_bc must be outflow or transmissive")
    s["edge_bc"] = str(s["edge_bc"]).strip().lower()
    return s


# ------------------------------------------------------------------ the model DEM
def _gdal():
    from osgeo import gdal
    gdal.UseExceptions()
    return gdal


def read_model_grid(dem_path, bounds, cell_m, band=1):
    """The DEM resampled (bilinear) to the model cell over `bounds` (xmin, ymin, xmax, ymax in the
    DEM's CRS; snapped outwards to the cell) as (Grid, info). A Grid is the runner's model-DEM
    container. info: native cell, crs_wkt, window of the native DEM for the fine elevation."""
    gdal = _gdal()
    src = gdal.Open(dem_path)
    if src is None:
        raise JobError("cannot open the DEM {}".format(dem_path))
    gt = src.GetGeoTransform()
    wkt = src.GetProjection()
    if not wkt or "PROJCS" not in wkt.upper() and "PROJCRS" not in wkt.upper():
        raise JobError("the DEM must be in a projected CRS in metres (it has {}); reproject it first".format(
            "none" if not wkt else "a geographic CRS"))
    native = abs(gt[1])
    xmin, ymin, xmax, ymax = bounds
    x0 = math.floor(xmin / cell_m) * cell_m
    y0 = math.ceil(ymax / cell_m) * cell_m
    nx = int(math.ceil((xmax - x0) / cell_m))
    ny = int(math.ceil((y0 - ymin) / cell_m))
    if nx < 3 or ny < 3:
        raise JobError("the domain is smaller than 3 model cells")
    if nx * ny > 200e6:
        raise JobError("{} x {} model cells is too many: raise cell_m".format(nx, ny))
    nd = src.GetRasterBand(band).GetNoDataValue()
    dst = gdal.Warp("", src, format="MEM", outputBounds=(x0, y0 - ny * cell_m, x0 + nx * cell_m, y0),
                    xRes=cell_m, yRes=cell_m, resampleAlg="bilinear", dstNodata=gridmod.NODATA,
                    srcNodata=nd, outputType=gdal.GDT_Float64)
    arr = dst.GetRasterBand(1).ReadAsArray().astype(np.float64)
    g = gridmod.Grid(arr, x0, y0, cell_m, gridmod.NODATA, wkt)
    return g, {"native_cell_m": native, "crs_wkt": wkt, "path": dem_path, "geotransform": list(gt)}


def read_fine_elevation(dem_path, grid, native_m, out_path, band=1):
    """The native DEM over the grid's bounds as a float32 .npy (NaN = no data): the runner's
    "fine" elevation file (job keys elev_fine_*), sampled at the triangle vertices. Returns the
    job keys, or None when the native cell is not finer than the model cell (the runner's rule)."""
    if native_m >= 0.999 * grid.dx:
        return None
    gdal = _gdal()
    src = gdal.Open(dem_path)
    x0, y0 = grid.x0, grid.y0
    nx = int(round(grid.nx * grid.dx / native_m))
    ny = int(round(grid.ny * grid.dx / native_m))
    if nx * ny > FINE_MAX_CELLS:
        return None                                    # over the runner's cap: model grid
    nd = src.GetRasterBand(band).GetNoDataValue()
    dst = gdal.Warp("", src, format="MEM", outputBounds=(x0, y0 - ny * native_m, x0 + nx * native_m, y0),
                    xRes=native_m, yRes=native_m, resampleAlg="bilinear", dstNodata=-9999.0, srcNodata=nd,
                    outputType=gdal.GDT_Float32)
    a = dst.GetRasterBand(1).ReadAsArray().astype(np.float32)
    a[a == -9999.0] = np.nan
    np.save(out_path, a)
    return {"elev_fine_file": os.path.basename(out_path), "elev_fine_x0": x0, "elev_fine_y0": y0,
            "elev_fine_dx": native_m}


def read_factor_on_grid(raster_path, grid, target_wkt=None, band=1):
    """A factor raster (any CRS) resampled onto the model grid (bilinear; cells without data = 1).
    Returns (array, stats)."""
    gdal = _gdal()
    src = gdal.Open(raster_path)
    if src is None:
        raise JobError("cannot open the factor raster {}".format(raster_path))
    nd = src.GetRasterBand(band).GetNoDataValue()
    dst = gdal.Warp("", src, format="MEM", dstSRS=grid.crs_wkt,
                    outputBounds=(grid.x0, grid.y0 - grid.ny * grid.dx, grid.x0 + grid.nx * grid.dx, grid.y0),
                    xRes=grid.dx, yRes=grid.dx, resampleAlg="bilinear", dstNodata=-9999.0, srcNodata=nd,
                    outputType=gdal.GDT_Float64)
    a = dst.GetRasterBand(1).ReadAsArray().astype(np.float64)
    bad = ~np.isfinite(a) | (a == -9999.0)
    n_bad = int(bad.sum())
    a[bad] = np.nan
    ok = a[~bad]
    if ok.size == 0:
        raise JobError("the factor raster does not cover the domain")
    if (ok < 0).any():
        raise JobError("the factor raster has negative values")
    st = {"cells_without_data": n_bad, "min": float(ok.min()), "max": float(ok.max()), "mean": float(ok.mean())}
    return a, st


# ------------------------------------------------------------------ the mesh spec (the runner's way)
def points_in_polygon(x, y, ring):
    """Crossing-number test of points against an (N, 2) ring."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    inside = np.zeros(x.shape, bool)
    px, py = ring[:, 0], ring[:, 1]
    j = len(ring) - 1
    for i in range(len(ring)):
        cross = ((py[i] > y) != (py[j] > y)) & (x < (px[j] - px[i]) * (y - py[i]) / (py[j] - py[i] + 1e-300) + px[i])
        inside ^= cross
        j = i
    return inside


def clip_lines_to_polygon(lines, polygon, min_len=1):
    """Pieces of the polylines inside `polygon` (vertex test): the same rule as the runner's
    anuga_model.clip_lines_to_polygon (tests/test_anuga_rain.py pins the two together)."""
    out = []
    for ln in lines:
        ln = np.asarray(ln, float)
        if len(ln) < 2:
            continue
        ins = points_in_polygon(ln[:, 0], ln[:, 1], np.asarray(polygon, float))
        run = []
        for p, ok in zip(ln, ins):
            if ok:
                run.append(p)
            else:
                if len(run) > min_len:
                    out.append(np.array(run))
                run = []
        if len(run) > min_len:
            out.append(np.array(run))
    return out


def domain_region(grid, polygon_rings):
    """Boolean model-grid mask of the cells whose centre is inside any polygon ring (DEM CRS)."""
    X, Y = np.meshgrid(grid.x_centers(), grid.y_centers())
    m = np.zeros(X.shape, bool)
    for ring in polygon_rings:
        ring = np.asarray(ring, float)
        x0, y0 = ring.min(axis=0)
        x1, y1 = ring.max(axis=0)
        sel = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        if sel.any():
            m[sel] |= points_in_polygon(X[sel], Y[sel], ring)
    return m


def outer_ring(grid, region, buffer_m=0.0, start_xy=None, simplify_m=None):
    """The outer mesh ring of the domain: the runner's anuga_model.mesh_polygons rule for `outer`
    (the region kept a tolerance away from the DEM edge and no-data, the largest piece, outline
    simplified by tol = max(min(buffer / 10, 3 dx), dx), or by ``simplify_m`` when given: a jagged basin outline at a few
    metres needs a coarser outline to pass the mesher's 20 degree gate). Returns (ring (N, 2), info)."""
    region = np.asarray(region, bool) & grid.valid()
    if buffer_m > 0:
        region = terrain.dilate(region, buffer_m, grid.dx)
    tol = max(min(buffer_m / 10.0, 3.0 * grid.dx), grid.dx)
    if simplify_m is not None:
        if simplify_m < grid.dx:
            raise JobError("the outline simplification {:g} m is below the cell size {:g} m".format(simplify_m, grid.dx))
        tol = float(simplify_m)
    valid_pad = np.pad(grid.valid(), 1, constant_values=False)
    near_bad = terrain.dilate(~valid_pad, tol + grid.dx, grid.dx)[1:-1, 1:-1]
    region = region & ~near_bad
    seed = None
    if start_xy is not None:
        r, c = grid.rc(*start_xy)
        if grid.inside(r, c) and region[r, c]:
            seed = (r, c)
    if region.sum() < 9:
        raise JobError("the domain has fewer than 9 valid model cells inside the DEM")
    region = terrain.largest_component(region, seed)
    ring = terrain.mask_outline(grid, region, simplify_m=tol)
    return ring, {"simplify_m": tol, "region_cells": int(region.sum()),
                  "region_km2": float(region.sum() * grid.dx ** 2 / 1e6)}


def flow_path(grid, outer, start_xy):
    """The runner's flow-path refinement line: steepest descent on the depression-filled DEM from
    start_xy to the domain edge, clipped to the outer ring, simplified (as anuga_model.gmsh_spec)."""
    path, length = terrain.trace_downstream(grid, start_xy, 4.0 * max(grid.nx, grid.ny) * grid.dx)
    pieces = [terrain.douglas_peucker(c, max(grid.dx, 10.0))
              for c in clip_lines_to_polygon([np.asarray(path, float)], outer)]
    return [np.asarray(c, float).tolist() for c in pieces], length


SIZING_NUMBERS = ("max_area_m2", "line_min_area_m2", "grade_dist_m")


def mesh_spec(outer, channel=None, points=None, threads=1, sizing=None):
    """The gmsh_mesher input, as anuga_model.gmsh_spec builds it: outer ring, lines (none: there is
    no breach or structure), channel (the flow path), points (its start), threads, and the
    far-field sizing keys only when set (gmsh_mesher.default_sizes otherwise, the runner's mesh).
    Bad sizing values raise JobError naming the key (gmsh_mesher.positive_number)."""
    spec = dict(outer=np.asarray(outer, float).tolist(), lines=[],
                channel=[np.asarray(c, float).tolist() for c in (channel or [])],
                points=[list(map(float, p)) for p in (points or [])], threads=int(threads or 0))
    for k in SIZING_NUMBERS:
        v = (sizing or {}).get(k)
        if v is not None:
            try:
                spec[k] = gmshmod.positive_number(k, v)
            except gmshmod.MeshError as e:
                raise JobError(str(e))
    try:                                       # the same checks build_mesh makes, before any gmsh
        g = gmshmod.default_sizes()
        g.update({k: v for k, v in spec.items() if k in g})
        gmshmod.resolve_sizing(spec, g)
    except gmshmod.MeshError as e:
        raise JobError(str(e))
    return spec


def expected_triangles(area_m2, spec):
    """Rough triangle count of an unrefined domain: area / max_area_m2 (a floor; refinement lines add)."""
    g = gmshmod.default_sizes()
    return int(area_m2 / float(spec.get("max_area_m2", g["max_area_m2"])))


# ------------------------------------------------------------------ rain
def read_rate_csv(path):
    """The ANUGA rate series damit_pmp:raingrid writes: (t_s, rate_m_per_s) arrays."""
    try:
        t, r = np.loadtxt(path, delimiter=",", skiprows=1, unpack=True, ndmin=2)
    except (OSError, ValueError) as e:
        raise JobError("cannot read the rate series {} ({}); it is the *_anuga_rate.csv from damit_pmp:raingrid "
                       "(time_s,rate_m_per_s)".format(path, e))
    t, r = np.atleast_1d(t).astype(float), np.atleast_1d(r).astype(float)
    if len(t) < 2 or not np.all(np.diff(t) >= 0) or not np.isfinite(r).all() or (r < 0).any():
        raise JobError("the rate series needs 2+ rows with increasing time and rates >= 0")
    if r.max() > 1e-4:
        raise JobError("rate {:.3g} m/s is {:.0f} mm/hr: the series must be in m/s (raingrid's anuga CSV)".format(
            r.max(), r.max() * 3.6e6))
    return t, r


def rain_depth_m(t, r):
    """Storm depth (m) of the piecewise-linear series."""
    return float(np.trapz(r, t)) if hasattr(np, "trapz") else float(np.trapezoid(r, t))


# ------------------------------------------------------------------ files
def orient_gauge(gauge, start_xy):
    """The discharge section's two ends ordered so the flow through it is POSITIVE when it runs away from `start_xy`
    (the flow-path start, i.e. downstream). ANUGA's Cross_section counts flow as positive to the RIGHT of the
    polyline direction a -> b (checked with a uniform eastward flow: a north -> south line reads -Q, south -> north +Q),
    i.e. along the normal (dy, -dx). LISFLOOD-FP's gauge in damit_pmp:lisfloodrain is positive away from the same
    point, so the two series then have the same sign. Without a start the ends are left as given."""
    if gauge is None or start_xy is None:
        return gauge
    (ax, ay), (bx, by) = gauge
    nx, ny = by - ay, -(bx - ax)                                  # the positive normal of a -> b
    away = nx * ((ax + bx) / 2.0 - start_xy[0]) + ny * ((ay + by) / 2.0 - start_xy[1])
    return [(bx, by), (ax, ay)] if away < 0 else [(ax, ay), (bx, by)]


def write_job(folder, grid, t, r, settings, sim_time_s, factor=None, fine=None, gauge=None):
    """anuga_rain_job.npz (model DEM, rain, run settings; the keys the runner's worker reads where
    it has them: dem, dem_x0, dem_y0, dem_dx, algorithm, threads, manning_n, edge_bc, sim_time,
    yieldstep, elev_fine_*) plus anuga_rain_settings.json. Returns the npz path."""
    job = dict(dem=np.where(grid.valid(), grid.data, np.nan), dem_x0=grid.x0, dem_y0=grid.y0, dem_dx=grid.dx,
               algorithm=str(settings["algorithm"]), threads=int(settings["threads"]),
               manning_n=float(settings["manning_n"]), edge_bc=str(settings["edge_bc"]),
               sim_time=float(sim_time_s), yieldstep=float(settings["yieldstep_s"]),
               rain_t=np.asarray(t, float), rain_rate=np.asarray(r, float))
    if factor is not None:
        job["factor"] = np.where(np.isfinite(factor), factor, 1.0)
    if fine:
        job.update(fine)
    if gauge is not None:                         # two points (x, y) in the DEM CRS: a discharge section
        job["gauge"] = np.asarray(gauge, float).reshape(2, 2)
    p = os.path.join(folder, JOB_NAME)
    np.savez(p, **job)
    return p


def copy_script_files(folder):
    """The generated script and the runner's files it imports, next to each other in `folder`."""
    shutil.copyfile(os.path.join(HERE, SCRIPT_TEMPLATE), os.path.join(folder, SCRIPT_NAME))
    for f in SCRIPT_FILES:
        shutil.copyfile(os.path.join(HERE, "runner_shared", f), os.path.join(folder, f))
    return [SCRIPT_NAME] + list(SCRIPT_FILES)


def mesh_arrays(npz_path):
    m = np.load(npz_path, allow_pickle=False)
    return m["mesh_points"], m["mesh_triangles"], m["mesh_boundary"], json.loads(str(m["mesh_stats"]))


def write_msh2(path, pts, tris, grid=None):
    """The mesh as a gmsh MSH 2.2 ASCII file (nodes with the ground height from the model DEM when
    given, else 0; 1-based triangles), for gmsh / QGIS / any tool that reads .msh."""
    z = np.zeros(len(pts))
    if grid is not None:
        z = np.nan_to_num(grid.sample_bilinear(pts[:, 0], pts[:, 1]), nan=0.0)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n{}\n".format(len(pts)))
        for i, (p, zz) in enumerate(zip(pts, z), 1):
            fh.write("{} {:.3f} {:.3f} {:.3f}\n".format(i, p[0], p[1], zz))
        fh.write("$EndNodes\n$Elements\n{}\n".format(len(tris)))
        for i, tri in enumerate(tris, 1):
            fh.write("{} 2 2 1 1 {} {} {}\n".format(i, tri[0] + 1, tri[1] + 1, tri[2] + 1))
        fh.write("$EndElements\n")


def write_triangles_geojson(path, pts, tris, crs_wkt=None, limit=400000):
    """The triangles as a GeoJSON polygon layer (for QGIS inspection); skipped over `limit`."""
    if len(tris) > limit:
        return False
    feats = []
    for i, t in enumerate(tris):
        ring = [[round(float(pts[k][0]), 2), round(float(pts[k][1]), 2)] for k in (t[0], t[1], t[2], t[0])]
        a = 0.5 * abs((pts[t[1]][0] - pts[t[0]][0]) * (pts[t[2]][1] - pts[t[0]][1])
                      - (pts[t[2]][0] - pts[t[0]][0]) * (pts[t[1]][1] - pts[t[0]][1]))
        feats.append({"type": "Feature", "properties": {"tri": i, "area_m2": round(float(a), 2)},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)
    return True


def write_json(path, rec):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")


def file_records(folder, names):
    out = {}
    for n in names:
        p = os.path.join(folder, n)
        if os.path.isfile(p):
            out[n] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    return out


def runner_sources():
    """sha256 of every runner_shared copy (the CI test pins them to damit_runner/core)."""
    return {f: sha256_file(os.path.join(HERE, "runner_shared", f)) for f in RUNNER_FILES}
