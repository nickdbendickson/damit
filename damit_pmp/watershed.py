"""Watershed of a dam point from a DEM: depression filling, D8 flow, accumulation, pour-point snap, upstream area.

Pure numpy / scipy (no QGIS import), so it runs the same in QGIS, in the tests and in a script. The depression
filling is the runner's own ``priority_flood`` (Barnes et al. 2014, with a tiny increment so flats drain; copied
verbatim in ``runner_shared/terrain.py``). A flat reservoir surface (3DEP lidar DEMs flatten open water) therefore
drains to its spill point instead of trapping the basin.

Method (D8, single flow direction):
  1. fill the DEM; the steepest-descent neighbour of each cell is its downstream cell;
  2. flow accumulation (cells draining through each cell) by peeling the grid from the headwaters down, one
     flow-path step per pass, vectorised;
  3. the pour point is snapped to the stream cell (accumulation within 5% of the maximum in the window) nearest to the
     point you gave, within ``snap_m`` (the dam point is usually a few cells off the stream / the pool);
  4. the basin is every cell whose flow path reaches the pour cell.
It is checked against GRASS r.watershed + r.water.outlet on the same DEM in the tests' offline cross-check
(see the plugin README): GRASS routes depressions differently, so areas agree to a few percent, not to the cell.
"""
import math

import numpy as np

from .runner_shared import terrain as _terrain
from .runner_shared.grid import Grid

M2_PER_SQMI = 2589988.110336
SNAP_FRACTION = 0.95        # a stream cell: accumulation within 5% of the largest in the snap window
NB = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


class WatershedError(ValueError):
    pass


def flow_directions(filled):
    """Flat index of each cell's steepest-descent neighbour on the filled DEM; -1 for a cell with none (an outlet at
    the grid edge or next to no-data)."""
    ny, nx = filled.shape
    z = np.where(np.isfinite(filled), filled, np.inf)
    best = np.zeros(filled.shape)
    nxt = np.full(filled.shape, -1, dtype=np.int64)
    rr, cc = np.indices(filled.shape)
    for dr, dc in NB:
        dist = math.hypot(dr, dc)
        zn = np.full(filled.shape, np.inf)
        r0, r1 = max(0, -dr), ny - max(0, dr)
        c0, c1 = max(0, -dc), nx - max(0, dc)
        zn[r0:r1, c0:c1] = z[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
        slope = (z - zn) / dist
        slope[~np.isfinite(slope)] = -1.0
        better = slope > best
        best = np.where(better, slope, best)
        nxt = np.where(better, (rr + dr) * nx + (cc + dc), nxt)
    nxt[~np.isfinite(filled)] = -1
    return nxt.ravel()


def accumulate(nxt, valid):
    """Flow accumulation (cells, the cell itself included) and the cells in the order they were peeled.
    ``order`` is a list of index arrays, headwaters first."""
    n = nxt.size
    inflow = np.bincount(nxt[(nxt >= 0) & valid], minlength=n).astype(np.int64)
    acc = np.where(valid, 1.0, 0.0)
    frontier = np.nonzero(valid & (inflow == 0))[0]
    order = []
    while frontier.size:
        order.append(frontier)
        t = nxt[frontier]
        keep = t >= 0
        t, src = t[keep], frontier[keep]
        if not t.size:
            break
        np.add.at(acc, t, acc[src])
        dec = np.bincount(t, minlength=n)
        inflow -= dec
        cand = np.unique(t)
        frontier = cand[inflow[cand] == 0]
    return acc, order


def snap_to_accumulation(acc2d, rc, radius_cells, min_cells=1.0, frac=SNAP_FRACTION):
    """Row, column of the stream cell nearest to rc within ``radius_cells``, and its accumulation: a stream cell is
    one whose accumulation is at least ``frac`` of the window's maximum. (Accumulation only grows downstream, so the
    plain maximum would always be the far edge of the window and pick up side area below the dam; the nearest cell
    on the main channel is the one that belongs to the dam.) Raises when the window holds nothing."""
    ny, nx = acc2d.shape
    r, c = rc
    r0, r1, c0, c1 = max(r - radius_cells, 0), min(r + radius_cells + 1, ny), max(c - radius_cells, 0), min(c + radius_cells + 1, nx)
    rr, cc = np.indices((r1 - r0, c1 - c0))
    rr, cc = rr + r0, cc + c0
    dist = np.hypot(rr - r, cc - c)
    win = np.where(dist <= radius_cells + 1e-9, acc2d[r0:r1, c0:c1], -1.0)
    top = win.max()
    if top < min_cells:
        raise WatershedError("no DEM cell with data within the snap radius of the point")
    ok = win >= frac * top
    k = np.argmin(np.where(ok, dist, np.inf))
    return int(rr.ravel()[k]), int(cc.ravel()[k]), float(win.ravel()[k])


def delineate(grid, x, y, snap_m=150.0, filled=None, frac=SNAP_FRACTION):
    """Delineate the basin of (x, y) on a ``Grid`` (projected, metres). Returns a dict:
    mask (bool array), pour_rc, pour_xy, snapped_from_m, acc_cells, area_m2, area_sqmi, touches_edge, cell_m,
    filled (the filled DEM, so a second point need not refill)."""
    if not grid.valid().any():
        raise WatershedError("the DEM has no data")
    r, c = grid.rc(x, y)
    if not grid.inside(r, c) or not grid.valid()[r, c]:
        raise WatershedError("the point is outside the DEM (or on no-data)")
    if filled is None:
        filled = _terrain.priority_flood(grid.masked())
    valid = np.isfinite(filled).ravel()
    nxt = flow_directions(filled)
    acc, order = accumulate(nxt, valid)
    acc2d = acc.reshape(grid.data.shape)
    rad = max(int(round(snap_m / grid.dx)), 0)
    pr, pc, top = snap_to_accumulation(acc2d, (r, c), rad, frac=frac)
    outlet = pr * grid.nx + pc
    mask = np.zeros(grid.data.size, dtype=bool)
    for idx in reversed(order):                       # downstream passes first: a cell is in the basin when its next is
        nx_ = nxt[idx]
        inside = np.zeros(idx.size, dtype=bool)
        ok = nx_ >= 0
        inside[ok] = mask[nx_[ok]]
        mask[idx] = inside | (idx == outlet)
    mask = mask.reshape(grid.data.shape)
    area = float(mask.sum()) * grid.dx * grid.dx
    edge = bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any())
    pxy = grid.xy(pr, pc)
    return {"mask": mask, "pour_rc": (pr, pc), "pour_xy": pxy, "snapped_from_m": math.hypot(pxy[0] - x, pxy[1] - y),
            "acc_cells": top, "area_m2": area, "area_sqmi": area / M2_PER_SQMI, "touches_edge": edge,
            "cell_m": grid.dx, "filled": filled, "acc": acc2d}


def describe(res, nid_sqmi=None):
    """Plain-language lines for the log / JSON."""
    out = ["basin {:.2f} sq mi ({:.2f} km2, {} cells of {:g} m); pour point snapped {:.0f} m to a stream cell with {:,.0f} "
           "cells draining through it".format(res["area_sqmi"], res["area_m2"] / 1e6, int(res["mask"].sum()),
                                              res["cell_m"], res["snapped_from_m"], res["acc_cells"])]
    if nid_sqmi:
        out.append("NID drainage area {:g} sq mi: delineated / NID = {:.2f}".format(nid_sqmi, res["area_sqmi"] / nid_sqmi))
    if res["touches_edge"]:
        out.append("WARNING: the basin reaches the edge of the DEM, so the DEM does not cover the whole basin: use a "
                   "larger DEM")
    return out


def mask_to_polygon_wkt(mask, grid):
    """The basin outline as WKT (one polygon or multipolygon; cell edges, holes dropped) via GDAL polygonize."""
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    ogr.UseExceptions()
    rows, cols = np.nonzero(mask)
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    sub = mask[r0:r1, c0:c1].astype("uint8")
    mem = gdal.GetDriverByName("MEM").Create("", sub.shape[1], sub.shape[0], 1, gdal.GDT_Byte)
    mem.SetGeoTransform((grid.x0 + c0 * grid.dx, grid.dx, 0.0, grid.y0 - r0 * grid.dx, 0.0, -grid.dx))
    band = mem.GetRasterBand(1)
    band.WriteArray(sub)
    vds = ogr.GetDriverByName("Memory").CreateDataSource("p")
    lyr = vds.CreateLayer("p", None, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    geoms = []
    for f in lyr:
        if f.GetField("v") == 1:
            geoms.append(f.GetGeometryRef().Clone())
    if not geoms:
        raise WatershedError("the basin is empty")
    u = geoms[0]
    for g in geoms[1:]:
        u = u.Union(g)
    # drop interior rings (sinks inside the basin are part of it)
    out = ogr.Geometry(ogr.wkbMultiPolygon)
    polys = [u] if u.GetGeometryName() == "POLYGON" else [u.GetGeometryRef(i) for i in range(u.GetGeometryCount())]
    for p in polys:
        q = ogr.Geometry(ogr.wkbPolygon)
        q.AddGeometry(p.GetGeometryRef(0).Clone())
        out.AddGeometry(q)
    return out.ExportToWkt() if out.GetGeometryCount() > 1 else out.GetGeometryRef(0).ExportToWkt()
