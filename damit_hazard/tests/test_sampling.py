"""Raster sampling (GDAL + numpy; skipped without GDAL) and the vendored cell selection."""
import os
import struct
import shutil
import tempfile
import unittest

from _helpers import ROOT

try:
    import numpy as np
    from osgeo import gdal, osr
except Exception as e:                       # fast CI job: no GDAL
    raise unittest.SkipTest("GDAL / numpy not available: {}".format(e))

from damit_hazard.sampling import fastsample as FS, rasters as S


def _tif(path, arr, x0=0.0, y0=100.0, cell=1.0, nodata=-9999.0,
         cell_x=None, cell_y=None, epsg=32614, wkt=None):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32)
    dx = cell if cell_x is None else cell_x
    dy = cell if cell_y is None else cell_y
    ds.SetGeoTransform((x0, dx, 0.0, y0, 0.0, -dy))
    sr = osr.SpatialReference()
    if wkt:
        sr.ImportFromWkt(wkt)
    else:
        sr.ImportFromEPSG(epsg)
    ds.SetProjection(sr.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    ds = None
    return path


US_FT_WKT = (
    'PROJCS["test_usft",GEOGCS["GCS",DATUM["D",SPHEROID["S",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",0],PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["US survey foot",0.3048006096012192]]')


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
    assert abs(out["poly"]["dv_ft2s"] - 4.5) < 1e-9
    assert out["poly"]["dv_source"] == "cells"
    assert out["poly"]["dv_cells_differ"] is False
    assert abs(out["poly"]["dv_same_cell_ft2s"] - 4.5) < 1e-9
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


def test_reader_and_no_pam_write_no_sidecar():
    """Input rasters are read with PAM off: the reader leaves nothing beside the raster, and
    statistics computed inside no_pam (as QGIS does for a layer during damit:classify) write no
    .aux.xml; no_pam puts the option back."""
    d = tempfile.mkdtemp(prefix="damit_pam_")
    path = _tif(os.path.join(d, "hmax.tif"), np.ones((10, 10), np.float32))
    old = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    r = S.Raster(path)
    assert r.values_at([0.5], [99.5])[0] == 1.0
    r.band = r.ds = None
    assert sorted(os.listdir(d)) == ["hmax.tif"], os.listdir(d)
    with S.no_pam():
        assert gdal.GetConfigOption("GDAL_PAM_ENABLED") == "NO"
        ds = gdal.Open(path)
        ds.GetRasterBand(1).ComputeStatistics(False)
        ds = None
    assert gdal.GetConfigOption("GDAL_PAM_ENABLED") == old
    assert sorted(os.listdir(d)) == ["hmax.tif"], os.listdir(d)
    # Control: outside no_pam the same statistics do write the sidecar (what classify used to do).
    if old is None:
        ds = gdal.Open(path)
        ds.GetRasterBand(1).ComputeStatistics(False)
        ds = None
        assert os.path.isfile(path + ".aux.xml")


def _nodata_grid(cell=1.0, cell_x=None, cell_y=None, wkt=None, epsg=32614, all_nodata=False,
                 dry_centre=False, dry_as_nodata=False, surround=True,
                 with_terrain=False, ground_ft=99.5, wse_ft=100.0):
    """5x5 depth grid with a point at the centre of cell (2,2).

    surround=True (default): a TRUE_HOLE at (2,2) — all 4 cardinal neighbours wet
    (east 3 ft / 1 fps, north 2 ft / 4 fps, west and south 1 ft / 0.5 fps); the
    rest of the grid is dry. surround=False: only the east and north cells are
    wet, so (2,2) is a flood-edge NoData cell with a 4-connected dry path to the
    border. dry_as_nodata writes every dry cell as NoData (the Runner convention).
    """
    dx = cell if cell_x is None else cell_x
    dy = cell if cell_y is None else cell_y
    d = tempfile.mkdtemp()
    if dry_as_nodata:
        dep = np.full((5, 5), -9999.0, np.float32)
    else:
        dep = np.zeros((5, 5), np.float32)
    vel = np.full((5, 5), 0.5, np.float32)
    if all_nodata:
        dep[:] = -9999.0
    else:
        if not dry_centre:
            dep[2, 2] = -9999.0
        elif dry_as_nodata:
            dep[2, 2] = 0.0
        dep[2, 3] = 3.0
        vel[2, 3] = 1.0
        dep[1, 2] = 2.0
        vel[1, 2] = 4.0
        if surround:
            dep[2, 1] = 1.0
            dep[3, 2] = 1.0
    y0 = 5.0 * dy
    kw = dict(x0=0.0, y0=y0, cell=cell, cell_x=dx, cell_y=dy, epsg=epsg, wkt=wkt)
    rs = S.open_rasters({"depth": _tif(os.path.join(d, "d.tif"), dep, **kw),
                         "velocity": _tif(os.path.join(d, "v.tif"), vel, **kw)})
    if with_terrain:
        # WSE only on wet cells; terrain is a constant (already in feet).
        wse = np.full((5, 5), -9999.0, np.float32)
        wet = (dep > 0) & (dep != -9999.0)
        wse[wet] = float(wse_ft)
        ter = np.full((5, 5), float(ground_ft), np.float32)
        rs["wse"] = S.Raster(_tif(os.path.join(d, "w.tif"), wse, **kw), 1.0)
        rs["terrain"] = S.Raster(_tif(os.path.join(d, "t.tif"), ter, **kw), 1.0)
        rs["terrain"].z_how = "feet (test)"
        rs["terrain"].z_scale_to_ft = 1.0
    x, y = 2.5 * dx, y0 - 2.5 * dy
    out = S.sample_structures({"hole": (_point_wkb(x, y), (x, y), 0.1 * min(dx, dy))},
                              rs, edge=0.0, point_radius=0.1 * min(dx, dy))
    return out["hole"], S.nodata_policy(rs["depth"])


def _nodata_hole(*args, **kwargs):
    """Back-compat wrapper: a true interior hole at the centre cell."""
    kwargs.setdefault("surround", True)
    return _nodata_grid(*args, **kwargs)


def test_nodata_at_10m_scores_dry_and_is_flagged_for_review():
    """At 10 m (finer than 20 m): NoData next to water stays dry, sampling=centre_nodata_dry."""
    h, pol = _nodata_hole(cell=10.0)
    assert pol["cell_m"] == 10.0 and pol["neighbourhood_allowed"] is False
    assert h["sampling"] == "centre_nodata_dry" and h.get("neighbourhood") is not True
    assert h["depth_ft"] == 0.0
    assert h["cell_m"] == 10.0
    assert h["nodata_neighbourhood_min_cell_m"] == S.NODATA_NEIGHBOURHOOD_MIN_CELL_M == 20.0
    assert h["in_domain"] is True and h["sampled"] is True


def test_nodata_at_exactly_20m_scores_dry_and_is_flagged_for_review():
    """Exactly 20 m is not coarser than the threshold: still scored dry, flagged for review."""
    h, pol = _nodata_hole(cell=20.0)
    assert pol["cell_m"] == 20.0 and pol["neighbourhood_allowed"] is False
    assert h["sampling"] == "centre_nodata_dry" and h.get("neighbourhood") is not True
    assert h["depth_ft"] == 0.0
    assert h["cell_m"] == 20.0



def test_nodata_at_30m_without_ground_scores_dry():
    """Coarser than 20 m, no DEM: score dry. Raw neighbour depth is never used."""
    h, pol = _nodata_hole(cell=30.0)
    assert pol["cell_m"] == 30.0 and pol["neighbourhood_allowed"] is True
    assert h["sampling"] == "centre_nodata_no_ground"
    assert h["depth_ft"] == 0.0
    assert h.get("nodata_path") == "no_ground"
    assert h.get("ground_source") == "none"
    assert h.get("nodata_true_hole") is True
    assert h["cell_m"] == 30.0
    assert h["nodata_neighbourhood_min_cell_m"] == 20.0

def test_finite_dry_centre_is_not_filled_from_neighbours():
    """A dry (0) cell beside water stays dry: that is RECEPTOR_DRY_NEXT_TO_WET, not neighbourhood."""
    h, _pol = _nodata_hole(cell=30.0, dry_centre=True)
    assert h.get("neighbourhood") is not True
    assert h["sampling"] not in ("neighbourhood", "centre_nodata_dry", "centre_nodata_edge")
    assert h["depth_ft"] == 0.0


def test_nodata_with_no_wet_neighbour_stays_dry():
    """No wet neighbour: left dry on both a fine and a coarse grid, and not flagged."""
    for cell in (10.0, 20.0, 30.0):
        h, _pol = _nodata_hole(cell=cell, all_nodata=True)
        assert h.get("neighbourhood") is not True
        assert h["sampling"] not in ("neighbourhood", "centre_nodata_dry", "centre_nodata_edge")
        assert h["depth_ft"] == 0.0



def test_nonsquare_cell_uses_the_larger_side():
    """15 m x 25 m (larger side 25 m > 20) uses WSE sampling; 15 m x 20 m stays dry."""
    h, pol = _nodata_hole(cell_x=15.0, cell_y=25.0, with_terrain=True, ground_ft=99.5, wse_ft=100.0)
    assert abs(pol["cell_m"] - 25.0) < 1e-6 and pol["neighbourhood_allowed"] is True
    assert h["sampling"] == "neighbourhood_wse"
    assert abs(h["depth_ft"] - 0.5) < 1e-9
    h, pol = _nodata_hole(cell_x=15.0, cell_y=20.0, with_terrain=True, ground_ft=99.5, wse_ft=100.0)
    assert abs(pol["cell_m"] - 20.0) < 1e-6 and pol["neighbourhood_allowed"] is False
    assert h["sampling"] == "centre_nodata_dry" and h["depth_ft"] == 0.0


def test_cell_size_in_us_survey_feet_is_converted_to_metres():
    """50 US-ft (~15.24 m) is at or finer than 20 m; 80 US-ft (~24.38 m) is coarser."""
    h, pol = _nodata_hole(cell=50.0, wkt=US_FT_WKT)
    assert abs(pol["cell_m"] - 50.0 * 0.3048006096012192) < 1e-6
    assert pol["neighbourhood_allowed"] is False
    assert h["sampling"] == "centre_nodata_dry" and h["depth_ft"] == 0.0
    h, pol = _nodata_hole(cell=80.0, wkt=US_FT_WKT, with_terrain=True, ground_ft=99.5, wse_ft=100.0)
    assert abs(pol["cell_m"] - 80.0 * 0.3048006096012192) < 1e-6
    assert pol["neighbourhood_allowed"] is True
    assert h["sampling"] == "neighbourhood_wse" and abs(h["depth_ft"] - 0.5) < 1e-9

def test_neighbourhood_threshold_is_strictly_greater_than_20():
    assert S.NODATA_NEIGHBOURHOOD_MIN_CELL_M == 20.0
    assert S.neighbourhood_from_cell(20.0) is False
    assert S.neighbourhood_from_cell(20.0000001) is True
    assert S.neighbourhood_from_cell(19.999) is False


def test_true_hole_mask_enclosed_and_edge():
    """Criterion TRUE_HOLE: a 1-cell hole and a 2x2 hole are inside the wet footprint;
    a flood-edge NoData cell with a dry path to the border is not."""
    a = np.full((9, 9), np.nan)              # dry-as-NoData field; wet footprint in the middle
    a[1:8, 1:8] = 1.0
    a[2, 2] = np.nan                         # 1-cell hole, all 4 (and 8) neighbours wet
    a[4, 4] = np.nan                         # 2x2 hole fully inside the wet footprint
    a[4, 5] = np.nan
    a[5, 4] = np.nan
    a[5, 5] = np.nan
    a[0, 4] = np.nan                         # flood-edge NoData, 4-connected to the border
    m = S.true_hole_mask_from_array(a)
    assert m[2, 2]
    assert m[4, 4] and m[4, 5] and m[5, 4] and m[5, 5]
    assert not m[0, 4]
    assert not m[1, 1]                       # wet cells are not holes
    # finite 0 is dry, never a hole, and it opens a path to the border
    b = np.zeros((5, 5))
    b[1:4, 1:4] = 2.0
    b[2, 2] = np.nan
    assert S.true_hole_mask_from_array(b)[2, 2]
    b[2, 0] = 0.0
    b[2, 1] = 0.0                            # dry corridor from the hole to the left border
    assert not S.true_hole_mask_from_array(b)[2, 2]


def test_dry_as_nodata_wse_depth_on_edge_and_hole():
    """Regression (DWR-2659, 50 m Runner output): dry cells are written as NoData, not 0.

    On a coarse (30 m) dry-as-NoData field, every NoData receptor (edge or hole)
    is scored with depth = max(0, neighbour WSE - own ground). Without a DEM the
    receptor is dry (never raw neighbour depth). At 20 m or finer both stay dry
    (centre_nodata_dry), even when terrain would give a positive physical depth.
    """
    # coarse, no DEM: hole and edge both dry (no raw 3 ft fill)
    h, pol = _nodata_grid(cell=30.0, dry_as_nodata=True, surround=True)
    assert pol["neighbourhood_allowed"] is True
    assert h["sampling"] == "centre_nodata_no_ground" and h["depth_ft"] == 0.0
    e, _pol = _nodata_grid(cell=30.0, dry_as_nodata=True, surround=False)
    assert e["sampling"] == "centre_nodata_no_ground" and e["depth_ft"] == 0.0
    # coarse, with DEM: physical depth 0.5 ft, not the 3 ft neighbour
    h, _pol = _nodata_grid(cell=30.0, dry_as_nodata=True, surround=True,
                           with_terrain=True, ground_ft=99.5, wse_ft=100.0)
    assert h["sampling"] == "neighbourhood_wse"
    assert abs(h["depth_ft"] - 0.5) < 1e-9
    assert abs(h["ground_ft"] - 99.5) < 1e-9
    assert abs(h["neighbour_wse_ft"] - 100.0) < 1e-9
    assert h.get("ground_source") == "source_dem_point"
    assert h.get("nodata_path") == "wse_minus_ground"
    e, _pol = _nodata_grid(cell=30.0, dry_as_nodata=True, surround=False,
                           with_terrain=True, ground_ft=99.5, wse_ft=100.0)
    assert e["sampling"] == "neighbourhood_wse" and abs(e["depth_ft"] - 0.5) < 1e-9
    # ground above every neighbouring WSE: dry
    d, _pol = _nodata_grid(cell=30.0, dry_as_nodata=True, surround=True,
                           with_terrain=True, ground_ft=100.2, wse_ft=100.0)
    assert d["sampling"] == "neighbourhood_wse" and d["depth_ft"] == 0.0
    # 20 m rule unchanged, even with terrain that would give 0.5 ft
    for surround in (True, False):
        f, _pol = _nodata_grid(cell=20.0, dry_as_nodata=True, surround=surround,
                               with_terrain=True, ground_ft=99.5, wse_ft=100.0)
        assert f["sampling"] == "centre_nodata_dry" and f["depth_ft"] == 0.0
        f, _pol = _nodata_grid(cell=10.0, dry_as_nodata=True, surround=surround,
                               with_terrain=True, ground_ft=99.5, wse_ft=100.0)
        assert f["sampling"] == "centre_nodata_dry" and f["depth_ft"] == 0.0


def test_coarse_edge_with_finite_zero_dry_is_not_filled():
    """A NoData cell next to water, with finite-0 dry cells opening a path to the
    border, is not a true hole and is not filled on a coarse grid."""
    h, pol = _nodata_grid(cell=30.0, dry_as_nodata=False, surround=False)
    assert pol["neighbourhood_allowed"] is True
    assert h["sampling"] == "centre_nodata_no_ground"
    assert h["depth_ft"] == 0.0


def test_wse_minus_ground_never_uses_raw_neighbour_depth():
    """Physical depth is 0.13 ft from WSE - ground, not the 3 ft neighbour depth."""
    h, _pol = _nodata_hole(cell=30.0, dry_as_nodata=True, with_terrain=True,
                           ground_ft=100.0, wse_ft=100.13)
    assert h["sampling"] == "neighbourhood_wse"
    assert abs(h["depth_ft"] - 0.13) < 1e-5
    assert abs(h["ground_ft"] - 100.0) < 1e-9
    assert abs(h["neighbour_wse_ft"] - 100.13) < 1e-5


def test_diagonal_only_link_to_border_is_enclosed():
    """4-connectivity: a pocket linked to the exterior only at a corner is enclosed.

    Documented on purpose: water that touches only at a corner is not an outlet.
    """
    a = np.full((6, 6), np.nan)
    a[1:5, 1:5] = 1.0
    a[2, 2] = np.nan
    a[1, 0] = np.nan          # diagonal (corner) contact from border toward the pocket
    # 4-connected, (2,2) does not reach the border through (1,0)
    m = S.true_hole_mask_from_array(a)
    assert m[2, 2]
    assert not m[1, 0]        # (1,0) touches the border (col 0)
    # A 4-connected dry corridor does connect:
    b = a.copy()
    b[2, 1] = np.nan
    b[2, 0] = np.nan
    assert not S.true_hole_mask_from_array(b)[2, 2]


def test_oversize_enclosed_component_scores_dry():
    """An enclosed component larger than TRUE_HOLE_MAX_CELLS is not a hole."""
    cap = S.TRUE_HOLE_MAX_CELLS
    n = cap + 6
    # Wet ring around an n x 1 enclosed NoData strip, plus a 1-cell hole
    a = np.full((n + 4, n + 4), np.nan)
    a[1:n + 3, 1:n + 3] = 1.0
    a[2, 2:2 + cap + 1] = np.nan          # cap+1 enclosed cells in a row
    a[4, 4] = np.nan                       # 1-cell hole
    ana = S.TH.analyze_nodata(a, max_cells=cap, cache=False)
    assert not ana["hole"][2, 2]
    assert ana["oversize"][2, 2] and ana["oversize"][2, 2 + cap]
    assert ana["hole"][4, 4] and not ana["oversize"][4, 4]
    assert ana["size"][2, 2] == cap + 1


def test_nodata_analysis_is_cached_on_the_raster():
    d = tempfile.mkdtemp()
    a = np.full((7, 7), -9999.0, np.float32)
    a[1:6, 1:6] = 1.0
    a[3, 3] = -9999.0
    dep = S.Raster(_tif(os.path.join(d, "d.tif"), a, x0=0.0, y0=7.0, cell=1.0))
    first = S.nodata_analysis(dep)
    second = S.nodata_analysis(dep)
    assert first is second
    assert first["hole"][3, 3]


def test_oversize_enclosed_rim_gets_wse_minus_ground():
    """An oversize enclosed island rim is scored like a border-touching dry rim.

    It is not a hole, but it still gets depth = max(0, highest neighbouring WSE
    minus own ground) and is flagged nodata_oversize (sampling=neighbourhood_wse).
    """
    cap = S.TRUE_HOLE_MAX_CELLS
    n = cap + 6
    d = tempfile.mkdtemp()
    dep = np.full((n + 4, n + 4), -9999.0, np.float32)
    vel = np.full(dep.shape, 3.0, np.float32)
    dep[1:n + 3, 1:n + 3] = 3.0
    dep[2, 2:2 + cap + 1] = -9999.0          # cap+1 enclosed NoData cells
    cell, ground_ft, wse_ft = 50.0, 101.5, 102.0
    y0 = dep.shape[0] * cell
    kw = dict(x0=0.0, y0=y0, cell=cell, epsg=32614)
    wse = np.full(dep.shape, -9999.0, np.float32)
    wet = dep > 0
    wse[wet] = wse_ft
    ter = np.full(dep.shape, ground_ft, np.float32)
    rs = S.open_rasters({"depth": _tif(os.path.join(d, "d.tif"), dep, **kw),
                         "velocity": _tif(os.path.join(d, "v.tif"), vel, **kw)})
    rs["wse"] = S.Raster(_tif(os.path.join(d, "w.tif"), wse, **kw), 1.0)
    rs["terrain"] = S.Raster(_tif(os.path.join(d, "t.tif"), ter, **kw), 1.0)
    rs["terrain"].z_how = "feet (test)"
    rs["terrain"].z_scale_to_ft = 1.0
    x, y = 2.5 * cell, y0 - 2.5 * cell
    h = S.sample_structures({"rim": (_point_wkb(x, y), (x, y), 0.1 * cell)},
                            rs, edge=0.0, point_radius=0.1 * cell)["rim"]
    assert h.get("nodata_oversize") is True
    assert h.get("nodata_true_hole") is not True
    assert h["sampling"] == "neighbourhood_wse"
    assert abs(h["depth_ft"] - 0.5) < 1e-5
    assert abs(h["velocity_fps"] - 3.0) < 1e-5
    assert h.get("nodata_path") == "wse_minus_ground"
    assert h.get("ground_source") == "source_dem_point"
    assert abs(h["ground_ft"] - ground_ft) < 1e-9
    assert abs(h["neighbour_wse_ft"] - wse_ft) < 1e-5


def test_hazard_imports_without_damit_core():
    """Hazard sampling imports with only damit_hazard + damit_catalog on the path."""
    import subprocess
    import sys
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    tmp = tempfile.mkdtemp(prefix="hazard_mininst_")
    try:
        plug = os.path.join(tmp, "plugins")
        os.makedirs(plug)
        for pkg in ("damit_hazard", "damit_catalog"):
            shutil.copytree(os.path.join(root, pkg), os.path.join(plug, pkg),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
        py = (
            "import os, sys\n"
            "sys.path[:0] = [os.environ['MIN_PLUGINS']]\n"
            "sys.modules.pop('damit_core', None)\n"
            "import damit_hazard.sampling.rasters as S\n"
            "assert S.TRUE_HOLE_MAX_CELLS == 25\n"
            "assert S.TRUE_HOLE_CONNECTIVITY == 4\n"
            "import numpy as np\n"
            "a = np.full((5, 5), np.nan); a[1:4, 1:4] = 1.0; a[2, 2] = np.nan\n"
            "m = S.true_hole_mask_from_array(a)\n"
            "assert bool(m[2, 2])\n"
            "print('hazard_mininst_ok')\n"
        )
        env = dict(os.environ, MIN_PLUGINS=plug, PYTHONPATH=plug)
        r = subprocess.run([sys.executable, "-c", py], capture_output=True, text=True,
                           env=env, cwd=tmp)
        assert r.returncode == 0, r.stdout + "\n" + r.stderr
        assert "hazard_mininst_ok" in r.stdout
    finally:
        shutil.rmtree(tmp, True)
