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

# Neighbourhood fill of a NoData receptor is used only when the depth-grid cell (larger side,
# converted to metres) is strictly greater than this AND the cell is a TRUE_HOLE. At 20 m or
# finer, NoData still scores dry and is flagged for review.
NODATA_NEIGHBOURHOOD_MIN_CELL_M = 20.0
M_PER_DEG_LAT = 110540.0          # metres per degree of latitude
M_PER_DEG_LON_EQ = 111320.0       # metres per degree of longitude at the equator

SAMPLING_NEIGHBOURHOOD = "neighbourhood"
SAMPLING_CENTRE_NODATA_DRY = "centre_nodata_dry"
SAMPLING_CENTRE_NODATA_EDGE = "centre_nodata_edge"
SAMPLING_CENTRE = "centre"

FLAG_NEIGHBOURHOOD = "nodata_neighbourhood"
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
            "neighbourhood_allowed": neighbourhood_from_cell(cell, min_m)}


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


def true_hole_mask(is_nodata, is_wet):
    """TRUE_HOLE mask: NoData cells whose 4-connected non-wet component does not
    touch the raster border (enclosed by the wet footprint).

    `is_nodata` and `is_wet` are 2-d sequences of bool of the same shape
    (nested lists, or any indexable rows). Returns a list of lists of bool.
    Finite-0 / dry cells are non-wet and never True in the result. Pure
    standard library: no numpy.
    """
    nr = len(is_wet)
    nc = len(is_wet[0]) if nr else 0
    if nr == 0 or nc == 0:
        return [list(row) for row in is_nodata] if is_nodata else []
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
        if r > 0 and nonwet[r - 1][c] and not exterior[r - 1][c]:
            exterior[r - 1][c] = True
            q.append((r - 1, c))
        if r + 1 < nr and nonwet[r + 1][c] and not exterior[r + 1][c]:
            exterior[r + 1][c] = True
            q.append((r + 1, c))
        if c > 0 and nonwet[r][c - 1] and not exterior[r][c - 1]:
            exterior[r][c - 1] = True
            q.append((r, c - 1))
        if c + 1 < nc and nonwet[r][c + 1] and not exterior[r][c + 1]:
            exterior[r][c + 1] = True
            q.append((r, c + 1))
    return [[bool(is_nodata[r][c]) and not exterior[r][c] for c in range(nc)]
            for r in range(nr)]


def true_hole_mask_array(depth2d):
    """TRUE_HOLE mask of a 2-d numeric depth array (NoData is non-finite).

    Uses numpy when it can be imported, otherwise the list form of true_hole_mask.
    Returns an object that supports [row][col] (a list of lists, or a numpy array).
    """
    try:
        import numpy as np
    except ImportError:
        rows = list(depth2d)
        is_nd, is_wt = [], []
        for row in rows:
            nd_row, wt_row = [], []
            for v in row:
                nd_row.append(is_nodata(v))
                wt_row.append(is_wet(v))
            is_nd.append(nd_row)
            is_wt.append(wt_row)
        return true_hole_mask(is_nd, is_wt)
    a = np.asarray(depth2d, dtype=float)
    if a.ndim != 2 or a.size == 0:
        return np.zeros(a.shape, dtype=bool)
    wet = np.isfinite(a) & (a > 0)
    nodata = ~np.isfinite(a)
    # Reuse the list algorithm on bool views (correctness over a micro-optimisation).
    return np.asarray(true_hole_mask(nodata.tolist(), wet.tolist()), dtype=bool)


def cell_is_true_hole(is_nodata, is_wet, row, col):
    """True when (row, col) is a TRUE_HOLE cell of the arrays passed to true_hole_mask."""
    if row is None or col is None:
        return False
    mask = true_hole_mask(is_nodata, is_wet)
    r, c = int(row), int(col)
    if r < 0 or c < 0 or r >= len(mask) or c >= len(mask[0]):
        return False
    return bool(mask[r][c])


def resolve_nodata(centre_is_nodata, neighbour_peak, policy, plain_sampling=SAMPLING_CENTRE,
                   is_true_hole=False):
    """Decide the sampling path when every requested cell is NoData.

    `neighbour_peak` is (depth, velocity, n_wet) or None (no wet neighbour).
    `is_true_hole` is True when the centre cell satisfies TRUE_HOLE (enclosed by
    the wet footprint). Neighbourhood fill on a coarse grid requires it.
    Returns a dict: sampling, flag (or None), neighbourhood (bool), true_hole,
    depth, velocity, and the policy fields. A finite-0 centre is not handled
    here (the caller leaves it dry).
    """
    hole = bool(is_true_hole)
    base = {"neighbourhood": False, "true_hole": hole,
            "depth": None, "velocity": None,
            "cell_m": policy.get("cell_m"),
            "nodata_neighbourhood_min_cell_m": policy.get("nodata_neighbourhood_min_cell_m")}
    if not centre_is_nodata:
        out = dict(base, sampling=plain_sampling, flag=None)
        return out
    allowed = bool(policy.get("neighbourhood_allowed"))
    if allowed and neighbour_peak is not None and hole:
        d, v = neighbour_peak[0], neighbour_peak[1]
        out = dict(base, sampling=SAMPLING_NEIGHBOURHOOD, flag=FLAG_NEIGHBOURHOOD,
                   neighbourhood=True, depth=d, velocity=v)
        return out
    if allowed and neighbour_peak is not None and not hole:
        out = dict(base, sampling=SAMPLING_CENTRE_NODATA_EDGE, flag=FLAG_FLOOD_EDGE,
                   depth=0.0, velocity=None)
        return out
    if (not allowed) and neighbour_peak is not None:
        out = dict(base, sampling=SAMPLING_CENTRE_NODATA_DRY, flag=FLAG_DRY_REVIEW,
                   depth=0.0, velocity=None)
        return out
    # NoData, no wet neighbour: scored dry, not flagged
    out = dict(base, sampling=plain_sampling, flag=None, depth=0.0, velocity=None)
    return out


def note_for_flag(flag, cell_m=None, min_m=NODATA_NEIGHBOURHOOD_MIN_CELL_M):
    """A Notes / review line for a nodata_neighbourhood or nodata_dry_review flag, or None."""
    min_m = float(min_m) if min_m is not None else NODATA_NEIGHBOURHOOD_MIN_CELL_M
    cell_s = "{:g} m".format(cell_m) if cell_m is not None else "unknown"
    if flag == FLAG_NEIGHBOURHOOD:
        return ("{}: centre cell was a true hole (TRUE_HOLE: NoData enclosed by the wet "
                "footprint); peak depth and velocity taken from wet cells in the 3x3 "
                "neighbourhood (depth-grid cell {} is coarser than "
                "NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m) - verify"
                .format(FLAG_NEIGHBOURHOOD, cell_s, min_m))
    if flag == FLAG_DRY_REVIEW:
        return ("{}: centre cell was NoData on a depth grid of {} "
                "(NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m; 20 m or finer scores NoData dry) "
                "- verify".format(FLAG_DRY_REVIEW, cell_s, min_m))
    if flag == FLAG_FLOOD_EDGE:
        return ("{}: centre cell was NoData on the flood edge (not a TRUE_HOLE; the Runner "
                "writes dry cells as NoData) on a depth grid of {} (coarser than "
                "NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m); scored dry"
                .format(FLAG_FLOOD_EDGE, cell_s, min_m))
    return None
