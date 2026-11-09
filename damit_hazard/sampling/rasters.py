"""Hydraulics at receptors, from GDAL rasters (no QGIS).

Structures (DamSafety_Hazard's footprint, exact cell selection - fastsample.py, mode "area"):
  * an outline: every cell whose centre is inside the outline or within the edge ring
    (default 5 ft) of it;
  * a point: every cell whose centre is within point radius + edge ring (default 20 + 5 ft);
  * no cell centre in the area (grid coarser than the building): the cell under the centroid.
The depth cells come from the depth raster's grid; velocity, DV, WSE, non-breach depth and
arrival are read at those cell centres (their own grids may differ). Roads / rail: the cell
under every point of the line densified at the line step (default 10 ft).

Per receptor: depth_ft (max), velocity_fps (max over wet cells), dv_ft2s (DV raster max, else
the largest d x v of one cell: dv_source "cells"), cells [(d, v)] of the wet cells, wse_ft (max),
rise_ft (max of depth - non-breach depth), arrival_h (min), in_domain (False when the receptor
lies outside the depth raster).
"""
import math

import numpy as np

from . import fastsample as FS

FT_PER_M = 3.280839895013123


class Raster(object):
    """One band of a GDAL raster, NoData as NaN, values scaled (m -> ft)."""
    backend = "gdal"

    def __init__(self, path, scale=1.0):
        from osgeo import gdal
        self.path = path
        self.ds = gdal.Open(path)
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


def sample_structures(items, rs, edge, point_radius):
    """{id: hydraulics} of structures. items: {id: (wkb bytes, centroid (x, y), radius or None)}
    in the depth raster's CRS; edge / point_radius / radius in its map units (radius: a
    point's disc radius, None = point_radius; ignored for outlines)."""
    dep = rs["depth"]
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
            out[sid] = _hyd(rs, xs, ys, d)
            out[sid]["sampling"] = "cells in the footprint + edge ring"
            continue
        x, y = cxy
        if not dep.inside(x, y):
            out[sid] = {"sampled": False, "in_domain": False, "sampling": "outside the raster"}
            continue
        xs, ys = np.array([x]), np.array([y])
        out[sid] = _hyd(rs, xs, ys, dep.values_at(xs, ys))
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
