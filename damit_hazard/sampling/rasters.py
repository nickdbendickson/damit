"""Hydraulics at receptors, from GDAL rasters (no QGIS).

Structures (DamSafety_Hazard's footprint, exact cell selection - fastsample.py, mode "area"):
  * an outline: every cell whose centre is inside the outline or within the edge ring
    (default 5 ft) of it;
  * a point: every cell whose centre is within point radius + edge ring (default 20 + 5 ft);
  * no cell centre in the area (grid coarser than the building): the cell under the centroid.
The depth cells come from the depth raster's grid; velocity, DV, WSE, non-breach depth and
arrival are read at those cell centres (their own grids may differ). Roads / rail: the cell
under every point of the line densified at the line step (default 10 ft).

Per receptor: depth_ft (max), velocity_fps (max over wet cells, possibly a different cell
than the peak depth), dv_ft2s (DV raster max, else the largest d x v of one cell: dv_source
"cells"), cells [(d, v)] of the wet cells, wse_ft (max), rise_ft (max of depth - non-breach
depth), arrival_h (min), in_domain (False when the receptor lies outside the depth raster).
When the cell under a point (or every cell in a footprint) is NoData and a neighbour is wet,
the path depends on the depth-grid cell size (larger side, converted to metres;
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20 m, strictly greater than):
  * coarser than 20 m: the peak over wet cells in the 3x3 neighbourhood (and the footprint,
    if there is one) is used, sampling is "neighbourhood", and the structure is flagged
    (nodata_neighbourhood);
  * at 20 m or finer: the NoData cell is still scored dry (0 ft), sampling is
    "centre_nodata_dry", and the structure is flagged for review (nodata_dry_review).
A dry (finite 0) cell is left dry. A NoData cell with no wet neighbour is left dry and is
not flagged.

The input rasters are someone else's run (often a product-of-record folder) and are opened read
only with GDAL PAM off (no_pam): nothing, not even a .aux.xml statistics sidecar, is written
beside them.
"""
import contextlib
import math

import numpy as np

from . import fastsample as FS

FT_PER_M = 3.280839895013123

# Neighbourhood fill of a NoData receptor is used only when the depth-grid cell (larger side,
# converted to metres) is strictly greater than this. At 20 m or finer, NoData still scores dry
# and is flagged for review. Nick, 12 Nov 2026 (damit PR #67).
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20.0
M_PER_DEG_LAT = 110540.0          # metres per degree of latitude (same as the Runner dam-line length)
M_PER_DEG_LON_EQ = 111320.0       # metres per degree of longitude at the equator


PAM_OPTION = "GDAL_PAM_ENABLED"


@contextlib.contextmanager
def no_pam():
    """GDAL PAM off while the block runs (process-wide GDAL config option), then the previous
    value back. A dataset whose PAM is first touched inside the block (opened, statistics
    computed) keeps PAM off until it is closed, so neither GDAL nor QGIS (layer statistics for the
    renderer) writes <raster>.aux.xml beside an input. Wrap the whole read, not just the open."""
    try:
        from osgeo import gdal
    except ImportError:          # no GDAL: nothing can write PAM either
        yield
        return
    old = gdal.GetConfigOption(PAM_OPTION)
    gdal.SetConfigOption(PAM_OPTION, "NO")
    try:
        yield
    finally:
        gdal.SetConfigOption(PAM_OPTION, old)


class Raster(object):
    """One band of a GDAL raster, NoData as NaN, values scaled (m -> ft). Opened read only with
    PAM off (no_pam); it only reads pixels, so nothing is written beside the input."""
    backend = "gdal"

    def __init__(self, path, scale=1.0):
        from osgeo import gdal
        self.path = path
        with no_pam():
            self.ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        if self.ds is None:
            raise IOError("cannot open raster " + str(path))
        self.band = self.ds.GetRasterBand(1)
        self.gt = self.ds.GetGeoTransform()
        self.xsize, self.ysize = self.ds.RasterXSize, self.ds.RasterYSize
        self.nodata = self.band.GetNoDataValue()
        self.scale = float(scale)
        self.ok = True
        self.wkt = self.ds.GetProjection()

    def _clean(self, a):
        a = a.astype(np.float64)
        if self.nodata is not None:
            a[a == self.nodata] = np.nan
        a[~np.isfinite(a)] = np.nan
        return a * self.scale

    def window_values(self, c0, r0, w, h):
        c0, r0, w, h = int(c0), int(r0), int(w), int(h)
        if w <= 0 or h <= 0:
            return None
        a = self.band.ReadAsArray(c0, r0, w, h)
        return None if a is None else self._clean(a)

    def inside(self, x, y):
        g = self.gt
        c = (x - g[0]) / g[1]
        r = (y - g[3]) / g[5]
        return 0 <= c < self.xsize and 0 <= r < self.ysize

    def values_at(self, xs, ys):
        """Values at map points (NaN outside / NoData). Reads the bounding window once."""
        xs, ys = np.asarray(xs, float), np.asarray(ys, float)
        out = np.full(xs.shape, np.nan)
        if xs.size == 0:
            return out
        g = self.gt
        cc = np.floor((xs - g[0]) / g[1]).astype(np.int64)
        rr = np.floor((ys - g[3]) / g[5]).astype(np.int64)
        ok = (cc >= 0) & (cc < self.xsize) & (rr >= 0) & (rr < self.ysize)
        if not ok.any():
            return out
        c0, c1, r0, r1 = cc[ok].min(), cc[ok].max(), rr[ok].min(), rr[ok].max()
        win = self.window_values(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        if win is None:
            return out
        out[ok] = win[rr[ok] - r0, cc[ok] - c0]
        return out


def open_rasters(paths, metres=False):
    """{role: Raster} for the roles depth, velocity, dv, wse, nonbreach, arrival (None skipped).
    metres: depth / velocity / WSE / non-breach in m, m/s; DV in m2/s (scaled to ft units)."""
    scale = {"depth": FT_PER_M, "velocity": FT_PER_M, "wse": FT_PER_M, "nonbreach": FT_PER_M,
             "dv": FT_PER_M ** 2, "arrival": 1.0} if metres else {}
    return {k: Raster(p, scale.get(k, 1.0)) for k, p in (paths or {}).items() if p}


def _hyd(rs, xs, ys, d):
    """Hydraulics of one receptor from depth values d at points xs, ys."""
    d = np.where(np.isfinite(d), d, 0.0)
    d = np.maximum(d, 0.0)
    out = {"sampled": True, "in_domain": True, "depth_ft": float(d.max()) if d.size else 0.0,
           "n_cells": int(d.size)}
    wet = d > 0
    v = None
    if "velocity" in rs:
        v = rs["velocity"].values_at(xs, ys)
        v = np.where(np.isfinite(v), np.abs(v), 0.0)
        out["velocity_fps"] = float(v[wet].max()) if wet.any() else 0.0
    if "dv" in rs:
        dv = rs["dv"].values_at(xs, ys)
        dv = dv[np.isfinite(dv)]
        out["dv_ft2s"] = float(dv.max()) if dv.size else 0.0
        out["dv_source"] = "raster"
    elif v is not None:
        out["dv_ft2s"] = float((d * v).max()) if d.size else 0.0
        out["dv_source"] = "cells"
    if v is None:
        out["cells"] = [(float(a), None) for a in d[wet]]
    else:
        out["cells"] = [(float(a), float(b)) for a, b in zip(d[wet], v[wet])]
    if "wse" in rs:
        w = rs["wse"].values_at(xs, ys)
        w = w[np.isfinite(w)]
        out["wse_ft"] = float(w.max()) if w.size else None
    if "nonbreach" in rs:
        nb = rs["nonbreach"].values_at(xs, ys)
        nb = np.where(np.isfinite(nb), np.maximum(nb, 0.0), 0.0)
        out["rise_ft"] = float((d - nb).max()) if d.size else 0.0
    if "arrival" in rs:
        a = rs["arrival"].values_at(xs, ys)
        a = a[np.isfinite(a)]
        out["arrival_h"] = float(a.min()) if a.size else None
    return out


def cell_sides_m(raster):
    """(width_m, height_m) of one cell of `raster`.

    Pixel width and height come from the geotransform (|gt[1]|, |gt[5]|) and are converted
    with the raster CRS linear unit (metres, international feet, US survey feet, ...). A
    geographic CRS is converted with metres-per-degree at the raster mid-latitude (latitude
    M_PER_DEG_LAT, longitude M_PER_DEG_LON_EQ x cos(lat)). A missing or unreadable CRS is
    treated as metres.
    """
    g = raster.gt
    dx, dy = abs(float(g[1])), abs(float(g[5]))
    wkt = getattr(raster, "wkt", None) or ""
    s = None
    try:
        from osgeo import osr
        s = osr.SpatialReference()
        ok = bool(wkt) and s.ImportFromWkt(wkt) == 0
    except Exception:                                    # noqa: BLE001 - no GDAL / bad WKT
        ok = False
    if ok and s.IsGeographic():
        mid_y = g[3] + raster.ysize * g[5] / 2.0
        mid_x = g[0] + raster.xsize * g[1] / 2.0
        lat = mid_y if abs(mid_y) <= 90.0 else mid_x
        lat = max(-89.999, min(89.999, float(lat)))
        return (dx * M_PER_DEG_LON_EQ * math.cos(math.radians(lat)), dy * M_PER_DEG_LAT)
    factor = 1.0
    if ok:
        try:
            u = s.GetLinearUnits()
            if u and u > 0:
                factor = float(u)
        except Exception:                                # noqa: BLE001
            factor = 1.0
    return dx * factor, dy * factor


def cell_size_m(raster):
    """Larger side of one cell of `raster`, in metres (non-square cells use the larger side)."""
    a, b = cell_sides_m(raster)
    return max(a, b)


def neighbourhood_from_cell(cell_m, min_m=NODATA_NEIGHBOURHOOD_MIN_CELL_M):
    """True when neighbourhood fill is used: cell size strictly greater than min_m."""
    return cell_m is not None and float(cell_m) > float(min_m)


def nodata_policy(raster):
    """The NoData-receptor rule for this depth raster: cell size, the 20 m threshold, and
    whether neighbourhood fill is allowed."""
    cell = cell_size_m(raster)
    return {"cell_m": round(float(cell), 6),
            "nodata_neighbourhood_min_cell_m": NODATA_NEIGHBOURHOOD_MIN_CELL_M,
            "neighbourhood_allowed": neighbourhood_from_cell(cell)}


def _stamp_nodata(hyd, policy, sampling, neighbourhood=False):
    hyd["sampling"] = sampling
    hyd["neighbourhood"] = bool(neighbourhood)
    hyd["cell_m"] = policy["cell_m"]
    hyd["nodata_neighbourhood_min_cell_m"] = policy["nodata_neighbourhood_min_cell_m"]
    return hyd


def _cell_index(dep, x, y):
    g = dep.gt
    return int(math.floor((x - g[0]) / g[1])), int(math.floor((y - g[3]) / g[5]))


def _cell_centre(dep, col, row):
    g = dep.gt
    return g[0] + (col + 0.5) * g[1], g[3] + (row + 0.5) * g[5]


def _neighbourhood_centres(dep, points):
    """Unique cell centres of the 3x3 around each point, clipped to the raster."""
    seen, xs, ys = set(), [], []
    for x, y in points:
        c0, r0 = _cell_index(dep, x, y)
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                c, r = c0 + dc, r0 + dr
                if (c, r) in seen or not (0 <= c < dep.xsize and 0 <= r < dep.ysize):
                    continue
                seen.add((c, r))
                px, py = _cell_centre(dep, c, r)
                xs.append(px)
                ys.append(py)
    if not xs:
        return None, None
    return np.asarray(xs, float), np.asarray(ys, float)


def _from_neighbourhood(rs, dep, points):
    """Peak hydraulics over wet cells in the 3x3 (and footprint) around points, or None."""
    xs, ys = _neighbourhood_centres(dep, points)
    if xs is None:
        return None
    d = dep.values_at(xs, ys)
    wet = np.isfinite(d) & (d > 0)
    if not wet.any():
        return None
    hyd = _hyd(rs, xs[wet], ys[wet], d[wet])
    hyd["sampling"] = "neighbourhood"
    hyd["neighbourhood"] = True
    return hyd


def _nodata_or_plain(rs, dep, points, xs, ys, d, policy, plain_sampling):
    """Hydraulics when every requested cell is NoData: neighbourhood fill on a coarse grid,
    or scored dry (centre_nodata_dry) at 20 m or finer when a neighbour is wet."""
    if policy["neighbourhood_allowed"]:
        hyd = _from_neighbourhood(rs, dep, points)
        if hyd is not None:
            return _stamp_nodata(hyd, policy, "neighbourhood", True)
        hyd = _hyd(rs, xs, ys, d)
        hyd["sampling"] = plain_sampling
        return hyd
    hyd = _hyd(rs, xs, ys, d)
    nb = _from_neighbourhood(rs, dep, points)
    if nb is not None:
        return _stamp_nodata(hyd, policy, "centre_nodata_dry", False)
    hyd["sampling"] = plain_sampling
    return hyd


def sample_structures(items, rs, edge, point_radius):
    """{id: hydraulics} of structures. items: {id: (wkb bytes, centroid (x, y), radius or None)}
    in the depth raster's CRS; edge / point_radius / radius in its map units (radius: a
    point's disc radius, None = point_radius; ignored for outlines)."""
    dep = rs["depth"]
    policy = nodata_policy(dep)
    shapes, out = {}, {}
    for sid, (wkb, cxy, rad) in items.items():
        r = point_radius if rad is None else rad
        shp = FS.shape_from_wkb(wkb, r)
        if shp is None:
            continue
        reach = edge if shp.kind == "poly" else r + edge
        shapes[sid] = (shp, reach)
    got = FS.sample_cells(shapes, dep, FS.AREA, edge) if shapes else ({}, set(), set())
    cells = got[0] if got is not None else {}
    for sid, (wkb, cxy, rad) in items.items():
        if sid in cells:
            xs, ys, d = cells[sid]
            if np.isfinite(d).any():
                out[sid] = _hyd(rs, xs, ys, d)
                out[sid]["sampling"] = "cells in the footprint + edge ring"
                continue
            pts = list(zip(xs, ys)) + [cxy]
            out[sid] = _nodata_or_plain(rs, dep, pts, xs, ys, d, policy,
                                        "cells in the footprint + edge ring")
            continue
        x, y = cxy
        if not dep.inside(x, y):
            out[sid] = {"sampled": False, "in_domain": False, "sampling": "outside the raster"}
            continue
        xs, ys = np.array([x]), np.array([y])
        d0 = dep.values_at(xs, ys)
        if not np.isfinite(d0[0]):
            out[sid] = _nodata_or_plain(rs, dep, [(x, y)], xs, ys, d0, policy,
                                        "cell under the centre (no cell centre in the area)")
            continue
        out[sid] = _hyd(rs, xs, ys, d0)
        out[sid]["sampling"] = "cell under the centre (no cell centre in the area)"
    return out


def sample_lines(items, rs):
    """{id: hydraulics} of lines. items: {id: [(x, y), ...]} densified points (depth CRS)."""
    dep, out = rs["depth"], {}
    for sid, pts in items.items():
        pts = [p for p in pts if p is not None and all(map(math.isfinite, p))]
        inside = [p for p in pts if dep.inside(*p)]
        if not inside:
            out[sid] = {"sampled": False, "in_domain": False, "sampling": "outside the raster"}
            continue
        xs = np.array([p[0] for p in inside])
        ys = np.array([p[1] for p in inside])
        out[sid] = _hyd(rs, xs, ys, dep.values_at(xs, ys))
        out[sid]["sampling"] = "points every line step"
        if len(inside) < len(pts):
            out[sid]["partly_outside"] = True
    return out
