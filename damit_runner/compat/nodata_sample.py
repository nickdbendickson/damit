"""NoData-receptor sampling rule (Nick, 12 Nov 2026; damit PR #67, DWR_Plugins 20 m ruling).

When the cell under a receptor (or every cell in its footprint) is NoData and a neighbour
is wet, the path depends on the depth-grid cell size (larger side, converted to metres;
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20 m, strictly greater than) and on whether the cell is
a TRUE_HOLE (true_hole_mask / nodata_true_hole):

  * coarser than 20 m, and the NoData cell is a true hole (its 4-connected non-wet
    component does not touch the raster border; it is enclosed by the wet footprint):
    the peak over wet cells in the 3x3 neighbourhood (and the footprint, if there is one)
    is used, sampling is "neighbourhood", and the receptor is flagged (nodata_neighbourhood);
  * coarser than 20 m, and the NoData cell is not a true hole (a dry flood-edge cell; the
    Runner writes every dry cell as NoData): scored dry, sampling is "centre_nodata_edge",
    flag nodata_flood_edge;
  * at 20 m or finer: the NoData cell is still scored dry (0), sampling is
    "centre_nodata_dry", and the receptor is flagged for review (nodata_dry_review).

A dry (finite 0) cell is left dry. A NoData cell with no wet neighbour is left dry and is
not flagged. Peak depth and peak velocity may come from different wet cells (option C).

Pure standard library: no QGIS, no numpy. Callers pass cell size already converted to
metres, or use cell_sides_m / cell_size_m (CRS linear units, or metres-per-degree on a
geographic CRS).
"""
import math
import os


def _true_hole_mod():
    """Load the TRUE_HOLE helper from damit_core, or the checkout copy."""
    try:
        from damit_core.lib import true_hole as m
        return m
    except ImportError:
        pass
    import importlib.util
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                        'damit_core', 'lib', 'true_hole.py'))
    if os.path.isfile(path):
        spec = importlib.util.spec_from_file_location('damit_true_hole', path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    raise FileNotFoundError(
        "the true-hole helper was not found: expected damit_core.lib.true_hole "
        "or damit_core/lib/true_hole.py in the checkout"
    )


TH = _true_hole_mod()
TRUE_HOLE_MAX_CELLS = TH.TRUE_HOLE_MAX_CELLS
TRUE_HOLE_CONNECTIVITY = TH.TRUE_HOLE_CONNECTIVITY

# Neighbourhood fill of a NoData receptor is used only when the depth-grid cell (larger side,
# converted to metres) is strictly greater than this AND the cell is a TRUE_HOLE. At 20 m or
# finer, NoData still scores dry and is flagged for review.
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20.0
M_PER_DEG_LAT = 110540.0          # metres per degree of latitude
M_PER_DEG_LON_EQ = 111320.0       # metres per degree of longitude at the equator

SAMPLING_NEIGHBOURHOOD = "neighbourhood_wse"  # alias kept for callers; value is the 0.4.3 path
SAMPLING_NEIGHBOURHOOD_WSE = "neighbourhood_wse"
SAMPLING_CENTRE_NODATA_DRY = "centre_nodata_dry"
SAMPLING_CENTRE_NODATA_EDGE = "centre_nodata_edge"
SAMPLING_CENTRE_NODATA_NO_GROUND = "centre_nodata_no_ground"
SAMPLING_CENTRE_NODATA_OVERSIZE = "centre_nodata_oversize"
SAMPLING_CENTRE = "centre"

FLAG_NEIGHBOURHOOD = "nodata_wse_ground"      # used when physical depth > 0
FLAG_WSE_GROUND = "nodata_wse_ground"
FLAG_WSE_DRY = "nodata_wse_dry"
FLAG_NO_GROUND = "nodata_no_ground_review"
FLAG_OVERSIZE = "nodata_oversize_component"
FLAG_DRY_REVIEW = "nodata_dry_review"
FLAG_FLOOD_EDGE = "nodata_flood_edge"


def neighbourhood_from_cell(cell_m, min_m=NODATA_NEIGHBOURHOOD_MIN_CELL_M):
    """True when neighbourhood fill is used: cell size strictly greater than min_m."""
    return cell_m is not None and float(cell_m) > float(min_m)


def nodata_policy(cell_m, min_m=NODATA_NEIGHBOURHOOD_MIN_CELL_M):
    """The NoData-receptor rule for this depth raster: cell size, the 20 m threshold, and
    whether neighbourhood fill is allowed."""
    cell = None if cell_m is None else float(cell_m)
    return {"cell_m": None if cell is None else round(cell, 6),
            "nodata_neighbourhood_min_cell_m": float(min_m),
            "neighbourhood_allowed": neighbourhood_from_cell(cell, min_m),
            "true_hole_max_cells": TRUE_HOLE_MAX_CELLS,
            "true_hole_connectivity": TRUE_HOLE_CONNECTIVITY}


def cell_sides_m(dx, dy, linear_units=1.0, geographic=False, lat=None):
    """(width_m, height_m) of one cell.

    Pixel width and height (`dx`, `dy`, already absolute) are converted with the raster CRS
    linear unit (metres, international feet, US survey feet, ...). A geographic CRS is
    converted with metres-per-degree at `lat` (latitude M_PER_DEG_LAT, longitude
    M_PER_DEG_LON_EQ x cos(lat)). A missing unit is treated as metres.
    """
    dx, dy = abs(float(dx)), abs(float(dy))
    if geographic:
        phi = 0.0 if lat is None else max(-89.999, min(89.999, float(lat)))
        return (dx * M_PER_DEG_LON_EQ * math.cos(math.radians(phi)), dy * M_PER_DEG_LAT)
    factor = 1.0
    try:
        if linear_units and float(linear_units) > 0:
            factor = float(linear_units)
    except (TypeError, ValueError):
        factor = 1.0
    return dx * factor, dy * factor


def cell_size_m(dx, dy, linear_units=1.0, geographic=False, lat=None):
    """Larger side of one cell, in metres (non-square cells use the larger side)."""
    a, b = cell_sides_m(dx, dy, linear_units=linear_units, geographic=geographic, lat=lat)
    return max(a, b)


def cell_sides_m_from_wkt(dx, dy, wkt=None, mid_x=None, mid_y=None):
    """(width_m, height_m) from a WKT CRS (osgeo.osr, when available). A missing or
    unreadable CRS is treated as metres."""
    dx, dy = abs(float(dx)), abs(float(dy))
    wkt = wkt or ""
    s = None
    ok = False
    try:
        from osgeo import osr
        s = osr.SpatialReference()
        ok = bool(wkt) and s.ImportFromWkt(wkt) == 0
    except Exception:
        ok = False
    if ok and s.IsGeographic():
        lat = mid_y if mid_y is not None and abs(float(mid_y)) <= 90.0 else mid_x
        return cell_sides_m(dx, dy, geographic=True, lat=lat)
    factor = 1.0
    if ok:
        try:
            u = s.GetLinearUnits()
            if u and u > 0:
                factor = float(u)
        except Exception:
            factor = 1.0
    return cell_sides_m(dx, dy, linear_units=factor)


def cell_size_m_from_wkt(dx, dy, wkt=None, mid_x=None, mid_y=None):
    """Larger side of one cell, in metres, from a WKT CRS."""
    a, b = cell_sides_m_from_wkt(dx, dy, wkt=wkt, mid_x=mid_x, mid_y=mid_y)
    return max(a, b)


def is_nodata(value):
    """True when `value` is NoData (None or non-finite). A finite 0 is not NoData."""
    if value is None:
        return True
    try:
        x = float(value)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(x)


def is_wet(value):
    """True when `value` is a finite depth (or velocity) strictly greater than 0."""
    if value is None:
        return False
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x > 0


def peak_wet_cells(depths, vels=None):
    """(peak_depth, peak_velocity, n_wet) over wet cells (option C: the two peaks may come
    from different cells). vels is None, or a sequence aligned with depths. Returns None
    when no cell is wet."""
    dmax, vmax, n = None, None, 0
    if vels is None:
        vels = [None] * len(depths)
    for d, v in zip(depths, vels):
        if not is_wet(d):
            continue
        n += 1
        df = float(d)
        if dmax is None or df > dmax:
            dmax = df
        if v is not None:
            try:
                vf = float(v)
            except (TypeError, ValueError):
                vf = None
            if vf is not None and math.isfinite(vf) and (vmax is None or vf > vmax):
                vmax = vf
    if n == 0:
        return None
    return dmax, vmax, n


def neighbourhood_rc(row, col, nrows, ncols):
    """(r, c) of the 3x3 around (row, col), clipped to the raster."""
    out = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            r, c = int(row) + dr, int(col) + dc
            if 0 <= r < int(nrows) and 0 <= c < int(ncols):
                out.append((r, c))
    return out


def neighbourhood_centres(gt, xsize, ysize, points):
    """Unique cell centres of the 3x3 around each (x, y) in `points`, clipped to the raster.
    `gt` is a north-up or axis-aligned geotransform (gt[2] and gt[4] may be 0)."""
    g = tuple(gt)
    seen, xs, ys = set(), [], []
    dx, dy = float(g[1]), float(g[5])
    if dx == 0 or dy == 0:
        return xs, ys
    for x, y in points:
        try:
            c0 = int(math.floor((float(x) - g[0]) / dx))
            r0 = int(math.floor((float(y) - g[3]) / dy))
        except (TypeError, ValueError):
            continue
        for r, c in neighbourhood_rc(r0, c0, ysize, xsize):
            if (c, r) in seen:
                continue
            seen.add((c, r))
            xs.append(g[0] + (c + 0.5) * g[1] + (r + 0.5) * g[2])
            ys.append(g[3] + (c + 0.5) * g[4] + (r + 0.5) * g[5])
    return xs, ys


def analyze_nodata_array(depth2d, max_cells=None, cache=True):
    """Cached TRUE_HOLE / oversize analysis of a 2-d depth array."""
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    return TH.analyze_nodata(depth2d, max_cells=cap, cache=cache)


def true_hole_mask(is_nodata, is_wet, max_cells=None):
    """TRUE_HOLE mask (list of lists). Uses the shared helper, including the size cap."""
    try:
        import numpy as np
    except ImportError:
        return _true_hole_mask_lists(is_nodata, is_wet, max_cells)
    nd = np.asarray(is_nodata, dtype=bool)
    wt = np.asarray(is_wet, dtype=bool)
    a = np.zeros(nd.shape, dtype=float)
    a[wt] = 1.0
    a[nd] = np.nan
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    m = TH.true_hole_mask_from_array(a, max_cells=cap, cache=True)
    return m.tolist()


def _true_hole_mask_lists(is_nodata, is_wet, max_cells=None):
    """Stdlib fallback used only when numpy is missing (tests always have numpy)."""
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    nr = len(is_wet)
    nc = len(is_wet[0]) if nr else 0
    if nr == 0 or nc == 0:
        return [list(row) for row in is_nodata] if is_nodata else []
    # Build a numeric depth and use the shared helper via a tiny list BFS if needed.
    # Without numpy, implement cap on the original BFS.
    nonwet = [[not bool(is_wet[r][c]) for c in range(nc)] for r in range(nr)]
    exterior = [[False] * nc for _ in range(nr)]
    q = []
    def seed(r, c):
        if nonwet[r][c] and not exterior[r][c]:
            exterior[r][c] = True
            q.append((r, c))
    for c in range(nc):
        seed(0, c)
        if nr > 1:
            seed(nr - 1, c)
    for r in range(nr):
        seed(r, 0)
        if nc > 1:
            seed(r, nc - 1)
    i = 0
    while i < len(q):
        r, c = q[i]
        i += 1
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < nr and 0 <= cc < nc and nonwet[rr][cc] and not exterior[rr][cc]:
                exterior[rr][cc] = True
                q.append((rr, cc))
    # Size enclosed components
    size = [[0] * nc for _ in range(nr)]
    seen = [[False] * nc for _ in range(nr)]
    for r0 in range(nr):
        for c0 in range(nc):
            if not nonwet[r0][c0] or exterior[r0][c0] or seen[r0][c0]:
                continue
            cells, q = [(r0, c0)], [(r0, c0)]
            seen[r0][c0] = True
            i = 0
            while i < len(q):
                r, c = q[i]
                i += 1
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    rr, cc = r + dr, c + dc
                    if (0 <= rr < nr and 0 <= cc < nc and nonwet[rr][cc]
                            and not exterior[rr][cc] and not seen[rr][cc]):
                        seen[rr][cc] = True
                        q.append((rr, cc))
                        cells.append((rr, cc))
            n = len(cells)
            for r, c in cells:
                size[r][c] = n
    return [[bool(is_nodata[r][c]) and not exterior[r][c] and 0 < size[r][c] <= cap
             for c in range(nc)] for r in range(nr)]


def true_hole_mask_array(depth2d, max_cells=None, cache=True):
    """TRUE_HOLE mask of a 2-d numeric depth array (NoData is non-finite). Cached."""
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    try:
        import numpy as np
    except ImportError:
        rows = list(depth2d)
        is_nd, is_wt = [], []
        for row in rows:
            is_nd.append([is_nodata(v) for v in row])
            is_wt.append([is_wet(v) for v in row])
        return true_hole_mask(is_nd, is_wt, max_cells=cap)
    return TH.true_hole_mask_from_array(np.asarray(depth2d, dtype=float),
                                        max_cells=cap, cache=cache)


def oversize_mask_array(depth2d, max_cells=None, cache=True):
    cap = TRUE_HOLE_MAX_CELLS if max_cells is None else int(max_cells)
    return analyze_nodata_array(depth2d, max_cells=cap, cache=cache)["oversize"]


def cell_is_true_hole(is_nodata, is_wet, row, col, max_cells=None):
    """True when (row, col) is a TRUE_HOLE cell of the arrays passed to true_hole_mask."""
    if row is None or col is None:
        return False
    mask = true_hole_mask(is_nodata, is_wet, max_cells=max_cells)
    r, c = int(row), int(col)
    if r < 0 or c < 0 or r >= len(mask) or c >= len(mask[0]):
        return False
    return bool(mask[r][c])


def physical_neighbour_depth(depth2d, row, col, ground2d, wse2d, ground_value=None, vel2d=None):
    """(physical_depth, physical_velocity, has_ground, wse_used) in the array's units.

    physical_depth = max(0, neighbour WSE - receptor ground) over wet neighbours.
    Velocity is the peak among neighbours whose physical depth is > 0.
    WSE comes from wse2d, else neighbour depth + neighbour ground.
    """
    import math
    try:
        import numpy as np
        d = np.asarray(depth2d, dtype=float)
        ny, nx = d.shape
    except Exception:
        return None, None, False, None
    gnd = None if ground2d is None else np.asarray(ground2d, dtype=float)
    wse = None if wse2d is None else np.asarray(wse2d, dtype=float)
    vel = None if vel2d is None else np.asarray(vel2d, dtype=float)
    if ground_value is not None and math.isfinite(float(ground_value)):
        ground = float(ground_value)
    elif gnd is not None and 0 <= row < ny and 0 <= col < nx:
        gv = gnd[row, col]
        ground = float(gv) if np.isfinite(gv) else float("nan")
    else:
        ground = float("nan")
    has_ground = math.isfinite(ground)
    best_d, best_v, used = 0.0, None, None
    any_wet = False
    for r, c in neighbourhood_rc(row, col, ny, nx):
        dv = d[r, c]
        if not (np.isfinite(dv) and dv > 0):
            continue
        any_wet = True
        if wse is not None and np.isfinite(wse[r, c]):
            ws = float(wse[r, c])
        elif gnd is not None and np.isfinite(gnd[r, c]):
            ws = float(dv) + float(gnd[r, c])
        else:
            continue
        if not has_ground:
            continue
        phys = max(0.0, ws - ground)
        if phys > 0 and vel is not None and np.isfinite(vel[r, c]):
            vf = float(vel[r, c])
            if best_v is None or vf > best_v:
                # peak velocity over physically-wet neighbours (option C)
                pass
        if phys > best_d or (phys == best_d and used is None):
            best_d = phys
            used = ws
        if phys > 0 and vel is not None and np.isfinite(vel[r, c]):
            vf = float(vel[r, c])
            if best_v is None or vf > best_v:
                best_v = vf
    if not any_wet:
        return None, None, has_ground, used
    if not has_ground:
        return 0.0, None, False, None
    return best_d, best_v, True, used


def resolve_nodata(centre_is_nodata, neighbour_peak, policy, plain_sampling=SAMPLING_CENTRE,
                   is_true_hole=False, is_oversize=False, has_ground=False,
                   physical_depth=None, physical_velocity=None):
    """Decide the sampling path when every requested cell is NoData.

    On a coarse grid the scored depth is physical_depth (the highest
    neighbouring WSE minus ground), never the raw neighbour_peak depth.
    Without ground the receptor is scored dry. An oversize enclosed
    component is not a hole: it still gets the WSE-minus-ground test and
    is flagged nodata_oversize_component (in addition to the WSE flag).
    At the 20 m threshold or finer the 20 m rule is unchanged (NoData
    scores dry, flag nodata_dry_review). `neighbour_peak` is only used to
    detect whether a wet neighbour exists.
    """
    hole = bool(is_true_hole)
    over = bool(is_oversize)
    base = {"neighbourhood": False, "true_hole": hole, "oversize": over,
            "depth": None, "velocity": None,
            "cell_m": policy.get("cell_m"),
            "nodata_neighbourhood_min_cell_m": policy.get("nodata_neighbourhood_min_cell_m")}
    if not centre_is_nodata:
        return dict(base, sampling=plain_sampling, flag=None, flags=None)
    allowed = bool(policy.get("neighbourhood_allowed"))
    has_nb = neighbour_peak is not None

    def _with_oversize(rec):
        rec["flags"] = rec["flag"]
        if over and rec.get("flag"):
            rec["flags"] = rec["flag"] + "," + FLAG_OVERSIZE
        elif over and not rec.get("flag"):
            rec["flag"] = FLAG_OVERSIZE
            rec["flags"] = FLAG_OVERSIZE
        return rec

    if allowed and has_nb and not has_ground:
        return _with_oversize(dict(base, sampling=SAMPLING_CENTRE_NODATA_NO_GROUND,
                                   flag=FLAG_NO_GROUND, depth=0.0, velocity=None))
    if allowed and has_nb and has_ground:
        d = 0.0 if physical_depth is None else float(physical_depth)
        v = physical_velocity
        if d > 0:
            return _with_oversize(dict(base, sampling=SAMPLING_NEIGHBOURHOOD_WSE,
                                       flag=FLAG_WSE_GROUND, neighbourhood=True,
                                       depth=d, velocity=v))
        return _with_oversize(dict(base, sampling=SAMPLING_NEIGHBOURHOOD_WSE,
                                   flag=FLAG_WSE_DRY, depth=0.0, velocity=None))
    if (not allowed) and has_nb:
        return dict(base, sampling=SAMPLING_CENTRE_NODATA_DRY, flag=FLAG_DRY_REVIEW,
                    flags=FLAG_DRY_REVIEW, depth=0.0, velocity=None)
    return dict(base, sampling=plain_sampling, flag=None, flags=None, depth=0.0, velocity=None)


def note_for_flag(flag, cell_m=None, min_m=NODATA_NEIGHBOURHOOD_MIN_CELL_M):
    """A Notes / review line for a NoData-receptor flag, or None."""
    min_m = float(min_m) if min_m is not None else NODATA_NEIGHBOURHOOD_MIN_CELL_M
    cell_s = "{:g} m".format(cell_m) if cell_m is not None else "unknown"
    if flag in (FLAG_WSE_GROUND, FLAG_NEIGHBOURHOOD):
        return ("{}: centre cell was NoData; depth is max(0, the highest neighbouring "
                "water surface minus the receptor's own ground) on a depth grid of {} "
                "(coarser than NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m) - verify"
                .format(FLAG_WSE_GROUND, cell_s, min_m))
    if flag == FLAG_WSE_DRY:
        return ("{}: centre cell was NoData on a depth grid of {} (coarser than "
                "NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m); scored dry because the "
                "receptor ground is at or above every neighbouring water surface"
                .format(FLAG_WSE_DRY, cell_s, min_m))
    if flag == FLAG_NO_GROUND:
        return ("{}: centre cell was NoData on a depth grid of {} (coarser than "
                "NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m); scored dry because no "
                "run DEM / terrain was available (raw neighbour depth was not used)"
                .format(FLAG_NO_GROUND, cell_s, min_m))
    if flag == FLAG_OVERSIZE:
        return ("{}: centre cell sits in an enclosed NoData component larger than "
                "TRUE_HOLE_MAX_CELLS = {} on a depth grid of {} (not a hole; still "
                "scored with WSE-minus-ground, flagged for review)"
                .format(FLAG_OVERSIZE, TRUE_HOLE_MAX_CELLS, cell_s))
    if flag == FLAG_DRY_REVIEW:
        return ("{}: centre cell was NoData on a depth grid of {} "
                "(NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m; 20 m or finer scores NoData dry) "
                "- verify".format(FLAG_DRY_REVIEW, cell_s, min_m))
    if flag == FLAG_FLOOD_EDGE:
        return ("{}: centre cell was NoData on the flood edge on a depth grid of {} "
                "(legacy path); scored dry".format(FLAG_FLOOD_EDGE, cell_s))
    return None
