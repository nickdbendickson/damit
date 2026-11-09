"""Raster sampling (GDAL + numpy; skipped without GDAL) and the vendored cell selection."""
import os
import struct
import tempfile
import unittest

from _helpers import ROOT

try:
    import numpy as np
    from osgeo import gdal, osr
except Exception as e:                       # fast CI job: no GDAL
    raise unittest.SkipTest("GDAL / numpy not available: {}".format(e))

from damit_hazard.sampling import fastsample as FS, rasters as S


def _tif(path, arr, x0=0.0, y0=100.0, cell=1.0, nodata=-9999.0):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0.0, y0, 0.0, -cell))
    sr = osr.SpatialReference()
    sr.ImportFromEPSG(32614)
    ds.SetProjection(sr.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    ds = None
    return path


def _poly_wkb(x0, y0, x1, y1):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return struct.pack("<BIII", 1, 3, 1, len(pts)) + b"".join(struct.pack("<dd", *p)
                                                              for p in pts)


def _point_wkb(x, y):
    return struct.pack("<BIdd", 1, 1, x, y)


def test_structure_cells_and_values():
    d = tempfile.mkdtemp()
    dep = np.zeros((100, 100), np.float32)
    dep[40:60, 40:60] = 2.0                  # rows 40-59 = y 60..40
    dep[50, 50] = 3.0                        # cell centre (50.5, 49.5)
    vel = np.full((100, 100), 1.5, np.float32)
    rs = S.open_rasters({"depth": _tif(os.path.join(d, "d.tif"), dep),
                         "velocity": _tif(os.path.join(d, "v.tif"), vel)})
    items = {"poly": (_poly_wkb(48.0, 48.0, 52.0, 52.0), (50.0, 50.0), None),
             "pt": (_point_wkb(50.5, 49.5), (50.5, 49.5), None),
             "far": (_point_wkb(500.0, 500.0), (500.0, 500.0), None)}
    out = S.sample_structures(items, rs, edge=1.0, point_radius=1.0)
    assert out["poly"]["depth_ft"] == 3.0 and out["poly"]["velocity_fps"] == 1.5
    # 4 x 4 outline + 1 m ring: centres 47.5..52.5 -> 6 x 6 cells (corner centres are 0.71 m
    # from the outline corner, inside the ring)
    assert out["poly"]["n_cells"] == 36, out["poly"]["n_cells"]
    assert abs(out["poly"]["dv_ft2s"] - 4.5) < 1e-9 and out["poly"]["dv_source"] == "cells"
    assert out["pt"]["depth_ft"] == 3.0
    assert out["far"]["in_domain"] is False and out["far"]["sampled"] is False


def test_metres_and_lines():
    d = tempfile.mkdtemp()
    dep = np.zeros((10, 10), np.float32)
    dep[5, :] = 1.0                          # a 1 m deep strip at y = 94.5
    rs = S.open_rasters({"depth": _tif(os.path.join(d, "d.tif"), dep)}, metres=True)
    out = S.sample_lines({"road": [(0.5, 94.5), (5.5, 94.5)], "dry": [(0.5, 90.5)]}, rs)
    assert abs(out["road"]["depth_ft"] - 3.280839895) < 1e-6
    assert out["dry"]["depth_ft"] == 0.0 and out["road"]["cells"][0][1] is None


def test_vendored_fastsample_matches_hazard():
    """When a DamSafety_Hazard checkout is present (DWR_PLUGINS_ROOT), the vendored file is the
    Hazard file except the provenance header and the two constant imports."""
    root = os.environ.get("DWR_PLUGINS_ROOT")
    src = os.path.join(root or "", "DamSafety_Hazard", "fastsample.py")
    if not root or not os.path.isfile(src):
        raise unittest.SkipTest("no DamSafety_Hazard checkout (set DWR_PLUGINS_ROOT)")
    ours = open(os.path.join(ROOT, "damit_hazard", "sampling", "fastsample.py"),
                encoding="utf-8").read().splitlines()
    theirs = open(src, encoding="utf-8").read().splitlines()
    import difflib
    diff = [l for l in difflib.unified_diff(theirs, ours, lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    allowed = ("# ", "ONEPASS_MIN", "READ_BLOCK_TARGET_CELLS", "from .constants", "max_cells",
               "from . import constants", "try:", "from .helpers", "log_message",
               "\"edge); GEOS", "except Exception:", "pass", "# -*-")
    bad = [l for l in diff if not l[1:].strip().startswith(allowed) and l[1:].strip()]
    assert bad == [], bad


def test_fastsample_point_disc():
    gt = (0.0, 1.0, 0.0, 10.0, 0.0, -1.0)
    shp = FS.disc_shape(5.0, 5.0, 1.0)
    cs = FS.structure_cells(shp, gt, 1.5, 0.5, FS.AREA, (10, 10))
    xs, ys = cs.centres(gt)
    assert all((x - 5) ** 2 + (y - 5) ** 2 <= 1.5 ** 2 + 1e-9 for x, y in zip(xs, ys))
    assert len(xs) == 4
