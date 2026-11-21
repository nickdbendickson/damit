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
than the peak depth; Nick's option C, 1 Nov 2026), dv_ft2s (DV raster max, else the largest
d x v of one wet cell: dv_source "cells", as before 0.4.3; the DV thresholds of M3 / M10b
read it), dv_same_cell_ft2s (the same value), dv_peak_ft2s (peak depth x peak velocity, for
the report), dv_cells_differ (True when the two peaks do not share a cell),
cells [(d, v)] of the wet cells, wse_ft (max), rise_ft (max of depth - non-breach
depth), arrival_h (min), in_domain (False when the receptor lies outside the depth raster).
When the cell under a point (or every cell in a footprint) is NoData and a neighbour is wet,
the path depends on the depth-grid cell size (larger side, converted to metres;
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20 m, strictly greater than):
  * at 20 m or finer: the NoData cell is scored dry (0 ft), sampling is
    "centre_nodata_dry", and the structure is flagged for review (nodata_dry_review).
  * coarser than 20 m, every NoData receptor (hole, flood edge, or oversize
    enclosed component) is scored with a physical depth: max(0, the highest
    neighbouring water surface minus the receptor's own ground)
    (sampling=neighbourhood_wse). The water surface comes from the WSE raster,
    or from neighbour depth plus neighbour ground. Ground comes from the run
    source DEM / terrain, sampled at the receptor point (ground_source=
    source_dem_point). The Runner, by contrast, uses bilinear ground from its
    interpolated model-resolution DEM (ground_source=model_dem_bilinear), so
    the two can disagree on the same house. When no ground is available the
    receptor is scored dry (sampling=centre_nodata_no_ground, flag
    nodata_no_ground_review); raw neighbour depth is never used. An enclosed
    non-wet component larger than TRUE_HOLE_MAX_CELLS is not a hole: it still
    gets the WSE-minus-ground test and is flagged nodata_oversize_component
    for review. The true-hole helper is bundled at damit_hazard/lib/true_hole.py
    (a copy of damit_core/lib/true_hole.py). The hole / oversize mask is cached
    on the Raster object, not on a plain numpy array.
A dry (finite 0) cell is left dry. A NoData cell with no wet neighbour is left dry and is
not flagged. Ground, the ground source, the highest neighbouring water surface used,
and the path are recorded per receptor.

The input rasters are someone else's run (often a product-of-record folder) and are opened read
only with GDAL PAM off (no_pam): nothing, not even a .aux.xml statistics sidecar, is written
beside them.
"""

import contextlib
import math

import numpy as np

from . import fastsample as FS

FT_PER_M = 3.280839895013123

# Neighbourhood sampling of a NoData receptor is used only when the depth-grid cell (larger
# side, converted to metres) is strictly greater than this. At 20 m or finer, NoData still
# scores dry and is flagged for review (Nick, 12 Nov 2026, damit PR #67). On a coarser grid
# the sampled depth is WSE-consistent, not raw neighbour depth (17 Nov 2026, follow-up).
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20.0
SAMPLING_NEIGHBOURHOOD = "neighbourhood"          # kept as an alias of neighbourhood_wse
SAMPLING_NEIGHBOURHOOD_WSE = "neighbourhood_wse"
SAMPLING_CENTRE_NODATA_DRY = "centre_nodata_dry"
SAMPLING_CENTRE_NODATA_EDGE = "centre_nodata_edge"  # unused on coarse grids after 0.4.3
SAMPLING_CENTRE_NODATA_NO_GROUND = "centre_nodata_no_ground"
SAMPLING_CENTRE_NODATA_OVERSIZE = "centre_nodata_oversize"
M_PER_DEG_LAT = 110540.0          # metres per degree of latitude (same as the Runner dam-line length)
M_PER_DEG_LON_EQ = 111320.0       # metres per degree of longitude at the equator


def _true_hole_mod():
    """Load the TRUE_HOLE helper: bundled copy first, then damit_core, then checkout.

    The Hazard plugin ships damit_hazard/lib/true_hole.py so it imports with only
    damit_hazard and damit_catalog installed (no damit_core).
    """
    import importlib.util
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "lib", "true_hole.py"),
        os.path.join(here, "..", "..", "damit_core", "lib", "true_hole.py"),
    ]
    for path in candidates:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location("damit_true_hole", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    try:
        from damit_core.lib import true_hole as m
        return m
    except ImportError:
        pass
    raise FileNotFoundError(
        "the true-hole helper was not found: expected damit_hazard/lib/true_hole.py "
        "inside the Hazard plugin (a bundled copy of damit_core/lib/true_hole.py), "
        "or an installed damit_core package"
    )


TH = _true_hole_mod()
TRUE_HOLE_MAX_CELLS = TH.TRUE_HOLE_MAX_CELLS
TRUE_HOLE_CONNECTIVITY = TH.TRUE_HOLE_CONNECTIVITY
true_hole_mask_from_array = TH.true_hole_mask_from_array


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

def _raster_z_info(path):
    """Band unit, vertical CRS unit and 3DEP cues for a DEM, with PAM off."""
    import os
    info = {"path": path, "z_unit": "", "z_vert": "", "z_source": "", "files": [path]}
    try:
        from osgeo import gdal, osr
    except ImportError:
        return info
    with no_pam():
        ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
    if ds is None:
        return info
    try:
        band = ds.GetRasterBand(1)
        unit = (band.GetUnitType() or "").strip()
        info["z_unit"] = unit
        wkt = ds.GetProjection() or ""
        if wkt:
            s = osr.SpatialReference()
            if s.ImportFromWkt(wkt) == 0 and s.IsCompound():
                try:
                    vert = s.GetAttrValue("VERT_CS|UNIT") or s.GetAttrValue("VERT_DATUM") or ""
                except Exception:
                    vert = ""
                u = (vert or "").strip().lower()
                if u in ("metre", "meters", "metre", "m"):
                    info["z_vert"] = "m"
                elif "survey" in u or u in ("us_ft", "us-ft"):
                    info["z_vert"] = "us_ft"
                elif "foot" in u or "feet" in u or u == "ft":
                    info["z_vert"] = "ft"
        md = ds.GetMetadata() or {}
        info["z_source"] = str(md.get("SOURCE") or md.get("source") or "")
        info["z_source_units"] = str(md.get("UNITS") or md.get("units") or "")
    finally:
        ds = None
    return info


def _unit_to_ft_scale(choice):
    """Multiplier that takes raw DEM values to international feet."""
    if choice in ("m", "metre", "metres", "meter", "meters"):
        return FT_PER_M, "metres"
    if choice in ("us_ft", "us-ft", "us_feet", "us survey feet", "us_survey_feet"):
        return (0.3048006096012192 / 0.3048), "US survey feet"
    if choice in ("ft", "foot", "feet", "international feet", "intl_ft"):
        return 1.0, "feet"
    return None, None


def _3dep_metres_reason(info):
    import os
    path = str((info or {}).get("path") or "")
    source = str((info or {}).get("z_source") or "")
    files = list((info or {}).get("files") or []) or ([path] if path else [])
    names = [os.path.basename(f) for f in files if f]
    if source.startswith("USGS 3DEP"):
        return "assumed metres: USGS 3DEP source in the file; no band unit or vertical CRS was recorded"
    real = [n for n in names if n and not n.lower().endswith((".vrt", ".aux.xml", ".ovr", ".xml"))]
    if real and all(n.upper().startswith("USGS_") for n in real):
        return "assumed metres: USGS 3DEP files (every file named USGS_*); no band unit or vertical CRS was recorded"
    blob = " ".join([path] + names).lower()
    if "3dep" in blob:
        return "assumed metres: 3DEP in the file name; no band unit or vertical CRS was recorded"
    return None


def _match_wse_scale(terrain, dep, wse, n=250):
    """Pick metres vs feet by matching terrain to (WSE - depth) on wet cells.

    Returns (scale_to_ft, how) or (None, None) when the match is not decisive.
    """
    if terrain is None or dep is None or wse is None:
        return None, None
    arr = _depth_array(dep)
    wet = np.isfinite(arr) & (arr > 0)
    if not wet.any():
        return None, None
    rows, cols = np.where(wet)
    if rows.size > n:
        pick = np.linspace(0, rows.size - 1, n).astype(int)
        rows, cols = rows[pick], cols[pick]
    xs, ys = [], []
    for r, c in zip(rows.tolist(), cols.tolist()):
        x, y = _cell_centre(dep, c, r)
        xs.append(x)
        ys.append(y)
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    d = dep.values_at(xs, ys)
    w = wse.values_at(xs, ys)
    g = terrain.values_at(xs, ys)  # already * terrain.scale; we need raw. Re-open briefly.
    # terrain.scale may already be 1 (raw). Callers pass a raw Raster (scale=1).
    model = w - d
    ok = np.isfinite(g) & np.isfinite(model)
    if int(ok.sum()) < 8:
        return None, None
    g, model = g[ok], model[ok]
    err_ft = float(np.median(np.abs(g - model)))
    err_m = float(np.median(np.abs(g * FT_PER_M - model)))
    # Decisive when one error is clearly smaller and itself small vs a 1 ft floor
    if err_m <= 1.0 and err_m * 10 < err_ft:
        return FT_PER_M, "inferred metres: terrain x 0.3048 m matches WSE minus depth (median abs {:.2f} ft vs {:.2f} ft as-is)".format(err_m, err_ft)
    if err_ft <= 1.0 and err_ft * 10 < err_m:
        return 1.0, "inferred feet: terrain matches WSE minus depth (median abs {:.2f} ft vs {:.2f} ft as metres)".format(err_ft, err_m)
    return None, None


def resolve_terrain_scale_to_ft(path, z_units="auto", depth=None, wse=None):
    """(scale_to_ft, how) for a DEM, or (None, reason) when the unit is unknown.

    Chain: explicit z_units, band unit, vertical CRS, USGS 3DEP cue, then a match of
    terrain against (WSE minus depth) on wet cells. A blank unit is not read as metres.
    """
    u = (z_units or "auto").strip().lower()
    if u and u not in ("auto", "detect", ""):
        sc, name = _unit_to_ft_scale(u)
        if sc is None:
            return None, "terrain units {!r} are not metres, feet, or US survey feet".format(z_units)
        return sc, "{} (chosen)".format(name)
    info = _raster_z_info(path)
    raw = (info.get("z_unit") or "").strip()
    if raw:
        sc, name = _unit_to_ft_scale(raw.lower())
        if sc is None:
            return None, "the DEM's band unit {!r} is not feet or metres".format(raw)
        return sc, "detected: raster unit '{}'".format(raw)
    vert = info.get("z_vert") or ""
    if vert:
        sc, name = _unit_to_ft_scale(vert)
        if sc is not None:
            return sc, "detected: vertical CRS in {}".format(name)
    assumed = _3dep_metres_reason(info)
    if assumed:
        return FT_PER_M, assumed
    # Temporary raw raster for the WSE-depth match
    if depth is not None and wse is not None:
        raw_ter = Raster(path, 1.0)
        got = _match_wse_scale(raw_ter, depth, wse)
        if got[0] is not None:
            return got
    return None, "no elevation unit is recorded on the DEM (no band unit, no vertical CRS, not a USGS 3DEP file, and no WSE-depth match)"


def open_terrain(path, z_units="auto", depth=None, wse=None):
    """Raster of the run DEM in feet, or (None, reason) when it cannot be used."""
    if not path:
        return None, "no terrain path"
    sc, how = resolve_terrain_scale_to_ft(path, z_units=z_units, depth=depth, wse=wse)
    if sc is None:
        return None, how
    ter = Raster(path, sc)
    ter.z_how = how
    ter.z_scale_to_ft = sc
    return ter, how


def discover_run_terrain(depth_path, levels=4):
    """(path, z_units or 'auto', source note) from the run folder, or (None, None, note).

    Looks beside the depth raster and up to `levels` folders above it for steps.json
    (terrain.path), run_setup.json / run_report.json / damit_handoff.json
    (inputs.terrain, parameters.dem, parameters.z_units, dem_elevation_units).
    """
    import json
    import os
    if not depth_path:
        return None, None, "no depth raster path"
    start = os.path.dirname(os.path.abspath(str(depth_path).split("|")[0]))
    dirs = []
    d = start
    for _ in range(levels + 1):
        if d in dirs or not d:
            break
        dirs.append(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    def _from_obj(obj, origin):
        path = z = None
        if not isinstance(obj, dict):
            return None, None
        ter = (obj.get("terrain") if isinstance(obj.get("terrain"), str)
               else (obj.get("terrain") or {}).get("path") if isinstance(obj.get("terrain"), dict)
               else None)
        inp = obj.get("inputs") if isinstance(obj.get("inputs"), dict) else {}
        par = obj.get("parameters") if isinstance(obj.get("parameters"), dict) else {}
        model = obj.get("model") if isinstance(obj.get("model"), dict) else {}
        settings = obj.get("settings") if isinstance(obj.get("settings"), dict) else {}
        files = settings.get("input_files") if isinstance(settings.get("input_files"), dict) else {}
        path = (ter or inp.get("terrain") or par.get("dem") or files.get("DEM")
                or (obj.get("path") if "terrain" in origin else None))
        z = (par.get("z_units") or model.get("dem_elevation_units") or obj.get("z_units")
             or obj.get("dem_elevation_units"))
        if isinstance(z, str):
            z = z.strip() or None
        if path:
            if not os.path.isabs(path):
                path = os.path.join(os.path.dirname(origin), path)
            if os.path.isfile(path):
                return path, (z or "auto")
        return None, None

    for folder in dirs:
        steps = os.path.join(folder, "steps.json")
        if os.path.isfile(steps):
            try:
                with open(steps, encoding="utf-8") as f:
                    data = json.load(f)
                block = data.get("terrain") if isinstance(data, dict) else None
                if isinstance(block, dict) and block.get("path"):
                    path = block["path"]
                    if not os.path.isabs(path):
                        path = os.path.join(folder, path)
                    if os.path.isfile(path):
                        return path, "auto", "steps.json (terrain.path)"
                path, z = _from_obj(block if isinstance(block, dict) else data, steps)
                if path:
                    return path, z or "auto", "steps.json (terrain.path)"
            except (OSError, ValueError, TypeError):
                pass
        for name in ("run_setup.json", "run_report.json", "damit_handoff.json"):
            fp = os.path.join(folder, name)
            if not os.path.isfile(fp):
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
                path, z = _from_obj(data, fp)
                if path:
                    return path, z or "auto", name
            except (OSError, ValueError, TypeError):
                pass
    return None, None, "no steps.json / run_setup terrain path found above the depth raster"


def _hyd(rs, xs, ys, d):
    """Hydraulics of one receptor from depth values d at points xs, ys.

    Peak depth and peak velocity are independent maxima over wet cells (option C).
    When there is no DV raster, dv_ft2s is the largest d x v of one wet cell
    (dv_source='cells', unchanged, so the DV thresholds score as before); dv_same_cell_ft2s
    is the same value under a plain name. dv_peak_ft2s is peak depth x peak velocity (the
    two peaks the class uses), reported only. dv_cells_differ is True when no single wet
    cell holds both peaks.
    """
    d = np.where(np.isfinite(d), d, 0.0)
    d = np.maximum(d, 0.0)
    d_peak = float(d.max()) if d.size else 0.0
    out = {"sampled": True, "in_domain": True, "depth_ft": d_peak,
           "n_cells": int(d.size), "dv_cells_differ": False,
           "dv_peak_ft2s": 0.0, "dv_same_cell_ft2s": 0.0}
    wet = d > 0
    v = None
    if "velocity" in rs:
        v = rs["velocity"].values_at(xs, ys)
        v = np.where(np.isfinite(v), np.abs(v), 0.0)
        if wet.any():
            v_peak = float(v[wet].max())
            out["velocity_fps"] = v_peak
            out["dv_peak_ft2s"] = d_peak * v_peak
            out["dv_same_cell_ft2s"] = float((d[wet] * v[wet]).max())
            out["dv_cells_differ"] = not bool(np.any(wet & (d == d_peak) & (v == v_peak)))
        else:
            out["velocity_fps"] = 0.0
    if "dv" in rs:
        dv = rs["dv"].values_at(xs, ys)
        dv = dv[np.isfinite(dv)]
        out["dv_ft2s"] = float(dv.max()) if dv.size else 0.0
        out["dv_source"] = "raster"
    elif v is not None:
        out["dv_ft2s"] = float(out["dv_same_cell_ft2s"])
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
            "neighbourhood_allowed": neighbourhood_from_cell(cell),
            "true_hole_max_cells": TRUE_HOLE_MAX_CELLS,
            "true_hole_connectivity": TRUE_HOLE_CONNECTIVITY}


def true_hole_mask_from_array(depth, max_cells=None, cache=True):
    """Boolean mask of TRUE_HOLE NoData cells (enclosed, component size <= cap)."""
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    return TH.true_hole_mask_from_array(depth, max_cells=cap, cache=cache)


def _depth_array(dep):
    """The full depth band as the Raster stores it (NoData as NaN, scaled), cached."""
    a = getattr(dep, "_depth_array", None)
    if a is None:
        a = dep.window_values(0, 0, dep.xsize, dep.ysize)
        if a is None:
            a = np.full((dep.ysize, dep.xsize), np.nan)
        dep._depth_array = a
    return a


def nodata_analysis(dep):
    """Cached TRUE_HOLE / oversize analysis of a depth Raster (one pass per classify)."""
    got = getattr(dep, "_nodata_analysis", None)
    if got is None:
        got = TH.analyze_nodata(_depth_array(dep), max_cells=TRUE_HOLE_MAX_CELLS, cache=True)
        dep._nodata_analysis = got
        dep._true_hole_mask = got["hole"]
    return got


def true_hole_mask(dep):
    """TRUE_HOLE mask of a depth Raster, cached on the raster for the classify pass."""
    return nodata_analysis(dep)["hole"]


def _cell_flags(dep, points):
    """(is_true_hole, is_oversize) for a receptor's in-domain sample points.

    True when every in-domain point sits on a hole (resp. oversize) cell.
    """
    ana = nodata_analysis(dep)
    hole, over = ana["hole"], ana["oversize"]
    holes, overs, n = [], [], 0
    for x, y in points:
        if not dep.inside(x, y):
            continue
        c, r = _cell_index(dep, x, y)
        if not (0 <= r < hole.shape[0] and 0 <= c < hole.shape[1]):
            continue
        n += 1
        holes.append(bool(hole[r, c]))
        overs.append(bool(over[r, c]))
    if n == 0:
        return False, False
    return all(holes), all(overs)


def _stamp_nodata(hyd, policy, sampling, neighbourhood=False, true_hole=False, oversize=False):
    hyd["sampling"] = sampling
    hyd["neighbourhood"] = bool(neighbourhood)
    hyd["nodata_true_hole"] = bool(true_hole)
    hyd["nodata_oversize"] = bool(oversize)
    hyd["cell_m"] = policy["cell_m"]
    hyd["nodata_neighbourhood_min_cell_m"] = policy["nodata_neighbourhood_min_cell_m"]
    hyd["true_hole_max_cells"] = TRUE_HOLE_MAX_CELLS
    hyd["true_hole_connectivity"] = TRUE_HOLE_CONNECTIVITY
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
    """Peak hydraulics over wet cells in the 3x3 (and footprint) around points, or None.

    Used only to detect whether any neighbour is wet (fine-grid review path, no-ground
    path). It is not used to score depth.
    """
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


def _sample_ground_ft(terrain, points):
    """Ground elevation in feet at the first in-range receptor point, or NaN."""
    if terrain is None or not points:
        return float("nan")
    xs = np.asarray([p[0] for p in points], float)
    ys = np.asarray([p[1] for p in points], float)
    g = terrain.values_at(xs, ys)
    ok = g[np.isfinite(g)]
    if ok.size == 0:
        return float("nan")
    return float(ok[0])  # the receptor point / centroid is first in the list we pass


def _neighbour_wse_values(rs, dep, xs, ys, terrain):
    """Water-surface elevation in feet at neighbour centres (NaN if unknown)."""
    wse = np.full(len(xs), np.nan)
    if "wse" in rs and rs["wse"] is not None:
        w = rs["wse"].values_at(xs, ys)
        wse = np.where(np.isfinite(w), w, wse)
    need = ~np.isfinite(wse)
    if need.any() and terrain is not None:
        d = dep.values_at(xs[need], ys[need])
        g = terrain.values_at(xs[need], ys[need])
        derived = d + g
        derived = np.where(np.isfinite(d) & (d > 0) & np.isfinite(g), derived, np.nan)
        wse[need] = derived
    return wse


def _from_neighbourhood_wse(rs, dep, points, terrain, ground_point):
    """WSE-consistent hydraulics for a coarse-grid NoData receptor, or None if no wet neighbour.

    depth = max(0, the highest neighbouring WSE - receptor ground) over wet
    neighbours. Velocity and option-C peaks are taken only over neighbours
    whose physical depth is > 0.
    """
    xs, ys = _neighbourhood_centres(dep, points)
    if xs is None:
        return None
    d_nb = dep.values_at(xs, ys)
    wet_nb = np.isfinite(d_nb) & (d_nb > 0)
    if not wet_nb.any():
        return None
    ground = _sample_ground_ft(terrain, [ground_point] if ground_point is not None else points)
    how = getattr(terrain, "z_how", None) if terrain is not None else None
    if not np.isfinite(ground):
        hyd = _hyd(rs, xs[:1], ys[:1], np.array([0.0]))
        hyd["depth_ft"] = 0.0
        hyd["velocity_fps"] = 0.0
        hyd["dv_ft2s"] = 0.0
        hyd["dv_peak_ft2s"] = 0.0
        hyd["dv_same_cell_ft2s"] = 0.0
        hyd["cells"] = []
        hyd["ground_ft"] = None
        hyd["neighbour_wse_ft"] = None
        hyd["ground_source"] = "none"
        hyd["terrain_z_how"] = how
        hyd["nodata_path"] = "no_ground"
        return hyd, "no_ground"
    wse_nb = _neighbour_wse_values(rs, dep, xs[wet_nb], ys[wet_nb], terrain)
    phys = np.maximum(wse_nb - ground, 0.0)
    phys = np.where(np.isfinite(phys), phys, 0.0)
    wet_phys = phys > 0
    used = float(np.nanmax(wse_nb)) if np.isfinite(wse_nb).any() else None
    if not wet_phys.any():
        hyd = _hyd(rs, xs[:1], ys[:1], np.array([0.0]))
        hyd["depth_ft"] = 0.0
        hyd["velocity_fps"] = 0.0
        hyd["dv_ft2s"] = 0.0
        hyd["dv_peak_ft2s"] = 0.0
        hyd["dv_same_cell_ft2s"] = 0.0
        hyd["cells"] = []
        hyd["ground_ft"] = float(ground)
        hyd["neighbour_wse_ft"] = used
        hyd["ground_source"] = "source_dem_point"
        hyd["terrain_z_how"] = how
        hyd["nodata_path"] = "wse_minus_ground"
        return hyd, "wse_dry"
    # Peak physical depth; option C velocity over the same physically-wet neighbours
    px, py, pd = xs[wet_nb][wet_phys], ys[wet_nb][wet_phys], phys[wet_phys]
    hyd = _hyd(rs, px, py, pd)
    # The neighbour WSE used is the one that produced the peak physical depth
    peak = float(pd.max())
    at_peak = np.isfinite(wse_nb[wet_phys]) & (np.abs(phys[wet_phys] - peak) < 1e-12)
    if at_peak.any():
        used = float(wse_nb[wet_phys][at_peak][0])
    hyd["ground_ft"] = float(ground)
    hyd["neighbour_wse_ft"] = used
    hyd["ground_source"] = "source_dem_point"
    hyd["terrain_z_how"] = how
    hyd["nodata_path"] = "wse_minus_ground"
    hyd["sampling"] = SAMPLING_NEIGHBOURHOOD_WSE
    hyd["neighbourhood"] = True
    return hyd, "wse"


def _nodata_or_plain(rs, dep, points, xs, ys, d, policy, plain_sampling,
                     ground_point=None):
    """Hydraulics when every requested cell is NoData.

    At 20 m or finer the 20 m rule is unchanged: NoData next to water is scored
    dry (centre_nodata_dry) and flagged for review, hole or edge.

    Coarser than 20 m: every NoData receptor (edge, hole, or oversize
    enclosed component) is scored with depth = max(0, the highest
    neighbouring WSE - own ground). An oversize component is not a hole
    and is flagged nodata_oversize_component, but it still gets the
    WSE-minus-ground test. With no ground, the receptor scores dry
    (never raw neighbour depth).
    """
    hole, oversize = _cell_flags(dep, points)
    terrain = rs.get("terrain")
    gpt = ground_point if ground_point is not None else (points[0] if points else None)
    if policy["neighbourhood_allowed"]:
        got = _from_neighbourhood_wse(rs, dep, points, terrain, gpt)
        if got is None:
            hyd = _hyd(rs, xs, ys, d)
            hyd["sampling"] = plain_sampling
            return hyd
        hyd, path = got
        if path == "no_ground":
            return _stamp_nodata(hyd, policy, SAMPLING_CENTRE_NODATA_NO_GROUND,
                                 False, hole, oversize)
        # wse or wse_dry
        filled = path == "wse" and float(hyd.get("depth_ft") or 0) > 0
        return _stamp_nodata(hyd, policy, SAMPLING_NEIGHBOURHOOD_WSE,
                             filled, hole, oversize)
    hyd = _hyd(rs, xs, ys, d)
    nb = _from_neighbourhood(rs, dep, points)
    if nb is not None:
        return _stamp_nodata(hyd, policy, SAMPLING_CENTRE_NODATA_DRY, False, hole, oversize)
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
                                        "cells in the footprint + edge ring",
                                        ground_point=cxy)
            continue
        x, y = cxy
        if not dep.inside(x, y):
            out[sid] = {"sampled": False, "in_domain": False, "sampling": "outside the raster"}
            continue
        xs, ys = np.array([x]), np.array([y])
        d0 = dep.values_at(xs, ys)
        if not np.isfinite(d0[0]):
            out[sid] = _nodata_or_plain(rs, dep, [(x, y)], xs, ys, d0, policy,
                                        "cell under the centre (no cell centre in the area)",
                                        ground_point=(x, y))
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
