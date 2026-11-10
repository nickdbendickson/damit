"""Grid, flow-path and breach-inflow geometry for the DamIT flood models (numpy only).

Ported from the DamSafety Runner (DWR_Plugins main, core/terrain.py, core/grid.py) so DamIT Runner and DamIT
Screener place the breach inflow and lay out the model domain the same way the DamSafety Runner does:

* the breach inflow goes in at the lowest ground of the downstream toe band: from INFLOW_TOE_INNER_M (5 m) to
  H x (downstream slope + 1) downstream of the dam line along its full length (the slope H:1V from the DWR
  record, 3:1 when it is not known; never past INFLOW_MAX_FROM_DAM_M, 150 m), only cells on the downstream side
  of the segment they are nearest (the side check), widened while the band is still the dam's face;
* with no dam line (or no valid band cell) the fallback is the lowest ground clearly below the reservoir within
  the usual radius on the downstream side, never further than 150 m from the dam (find_inflow_point);
* the first domain follows the steepest-descent path from the inflow point (LENGTH_MI long, HALF_WIDTH_MI either
  side), and an edge the flood leaves deeper than the tolerance moves out by STEP_MI.

Not ported: the reservoir pool mask (DamSafety pool_at_dam), the mid-crest move and the DEM-based crest guess.
"""
import heapq
import math

import numpy as np

FT = 0.3048
MILE = 1609.344
NODATA = -9999.0
_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

INFLOW_MAX_FROM_DAM_M = 150.0      # the inflow is never further than this from the dam line
INFLOW_FAR = "CHECK THE INFLOW POINT"
NO_DOWNSTREAM = "no cell on the downstream side"
INFLOW_TOE_INNER_M = 5.0
INFLOW_TOE_DS_SLOPE_DEFAULT = 3.0  # H:1V when the DWR record has no downstream slope
INFLOW_TOE_MIN_OUTER_M = 15.0
INFLOW_TOE_BAND_M = (5.0, 30.0)    # the band when the dam height is not known
INFLOW_TOE_DROP = 0.75
INFLOW_TOE_WIDEN_M = 10.0
INFLOW_TOE_SIDE_MIN = 0.25
NO_TOE = "no toe band"


class Grid:
    """A north-up raster: data[row, col], row 0 at the top; x0 / y0 the top-left corner; dx the cell (m)."""

    def __init__(self, data, x0, y0, dx, nodata=NODATA):
        self.data = np.asarray(data, dtype=float)
        self.x0, self.y0, self.dx = float(x0), float(y0), float(dx)
        self.nodata = nodata

    @property
    def ny(self):
        return self.data.shape[0]

    @property
    def nx(self):
        return self.data.shape[1]

    @property
    def yll(self):
        return self.y0 - self.ny * self.dx

    @property
    def bounds(self):
        return (self.x0, self.yll, self.x0 + self.nx * self.dx, self.y0)

    def x_centers(self):
        return self.x0 + (np.arange(self.nx) + 0.5) * self.dx

    def y_centers(self):
        return self.y0 - (np.arange(self.ny) + 0.5) * self.dx

    def rc(self, x, y):
        return int(math.floor((self.y0 - y) / self.dx)), int(math.floor((x - self.x0) / self.dx))

    def xy(self, r, c):
        return self.x0 + (c + 0.5) * self.dx, self.y0 - (r + 0.5) * self.dx

    def inside(self, r, c):
        return 0 <= r < self.ny and 0 <= c < self.nx

    def masked(self):
        d = self.data.copy()
        d[~np.isfinite(d) | (d <= NODATA + 1)] = np.nan
        return d

    def like(self, data):
        return Grid(data, self.x0, self.y0, self.dx, self.nodata)

    def gt(self):
        return (self.x0, self.dx, 0.0, self.y0, 0.0, -self.dx)


# ---------------------------------------------------------------------- polylines and paths --
def douglas_peucker(points, tol):
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        n = np.hypot(*ab)
        seg = pts[i + 1:j]
        if n == 0:
            d = np.hypot(*(seg - a).T)
        else:
            d = np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / n
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return pts[keep]


def priority_flood(dem):
    """Fill depressions so every cell drains to the grid edge (Barnes et al. 2014, with a tiny increment so flats
    drain). NaN cells act as outlets."""
    a = np.asarray(dem, dtype=float)
    ny, nx = a.shape
    filled = a.copy()
    closed = np.zeros(a.shape, dtype=bool)
    nan = ~np.isfinite(a)
    edge = np.zeros(a.shape, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    if nan.any():
        grown = nan.copy()
        grown[1:, :] |= nan[:-1, :]
        grown[:-1, :] |= nan[1:, :]
        grown[:, 1:] |= nan[:, :-1]
        grown[:, :-1] |= nan[:, 1:]
        edge |= grown
    edge &= ~nan
    closed[nan] = True
    heap = []
    for r, c in zip(*np.nonzero(edge)):
        heap.append((filled[r, c], int(r), int(c)))
        closed[r, c] = True
    heapq.heapify(heap)
    eps = 1e-5
    while heap:
        z, r, c = heapq.heappop(heap)
        for dr, dc in _NB:
            rr, cc = r + dr, c + dc
            if 0 <= rr < ny and 0 <= cc < nx and not closed[rr, cc]:
                closed[rr, cc] = True
                if filled[rr, cc] <= z:
                    filled[rr, cc] = z + eps
                heapq.heappush(heap, (filled[rr, cc], rr, cc))
    return filled


def trace_downstream(grid, start_xy, max_length_m):
    """Steepest-descent path on the depression-filled DEM from start_xy until max_length_m or the grid edge.
    Returns ([(x, y)], length m)."""
    filled = priority_flood(grid.masked())
    r, c = grid.rc(*start_xy)
    if not grid.inside(r, c):
        raise ValueError("the start point is outside the planning DEM")
    path = [grid.xy(r, c)]
    length = 0.0
    visited = {(r, c)}
    ny, nx = filled.shape
    while length < max_length_m:
        best, best_slope = None, 0.0
        for dr, dc in _NB:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ny and 0 <= cc < nx) or (rr, cc) in visited:
                continue
            if not np.isfinite(filled[rr, cc]):
                continue
            s = (filled[r, c] - filled[rr, cc]) / (math.hypot(dr, dc) * grid.dx)
            if s > best_slope:
                best, best_slope = (rr, cc), s
        if best is None:
            break
        length += math.hypot(best[0] - r, best[1] - c) * grid.dx
        r, c = best
        visited.add(best)
        path.append(grid.xy(r, c))
    return path, length


def path_bounds(path, buffer_m, snap=1.0):
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    b = [min(xs) - buffer_m, min(ys) - buffer_m, max(xs) + buffer_m, max(ys) + buffer_m]
    return tuple(math.floor(v / snap) * snap if i < 2 else math.ceil(v / snap) * snap for i, v in enumerate(b))


def edge_depths(depth, valid=None):
    """Largest depth on each edge row / column of the grid (m)."""
    d = np.where(np.isfinite(depth), depth, 0.0)
    if valid is not None:
        d = np.where(valid, d, 0.0)
    return {"N": float(d[0, :].max()), "S": float(d[-1, :].max()),
            "W": float(d[:, 0].max()), "E": float(d[:, -1].max())}


def expand_bounds(bounds, edges, step_m):
    xmin, ymin, xmax, ymax = bounds
    if "W" in edges:
        xmin -= step_m
    if "E" in edges:
        xmax += step_m
    if "S" in edges:
        ymin -= step_m
    if "N" in edges:
        ymax += step_m
    return (xmin, ymin, xmax, ymax)


def clip_bounds(bounds, limit):
    """`bounds` inside `limit` (both (xmin, ymin, xmax, ymax)); None when they do not overlap."""
    b = (max(bounds[0], limit[0]), max(bounds[1], limit[1]), min(bounds[2], limit[2]), min(bounds[3], limit[3]))
    return b if b[2] > b[0] and b[3] > b[1] else None


# ---------------------------------------------------------------------- downstream side --
def unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 0 else None


def downstream_from(dam_xy, crest_line=None, reservoir_xy=None, azimuth_deg=None):
    """(unit vector, how) of the downstream side: away from the reservoir point (across the dam line when there is
    one), else the breach azimuth (degrees from north, clockwise), else None."""
    if reservoir_xy is not None:
        away = (dam_xy[0] - reservoir_xy[0], dam_xy[1] - reservoir_xy[1])
        if crest_line is not None and len(crest_line) >= 2:
            a = np.asarray(crest_line, float).reshape(-1, 2)
            t = unit((a[-1, 0] - a[0, 0], a[-1, 1] - a[0, 1]))
            if t is not None:
                n = (t[1], -t[0])
                if n[0] * away[0] + n[1] * away[1] < 0:
                    n = (-n[0], -n[1])
                return n, "across the dam line, away from the reservoir point"
        u = unit(away)
        if u is not None:
            return u, "away from the reservoir point"
    if azimuth_deg is not None:
        a = math.radians(float(azimuth_deg))
        return (math.sin(a), math.cos(a)), "breach azimuth {:.0f} deg".format(float(azimuth_deg) % 360.0)
    return None, "no reservoir point and no breach azimuth"


def downstream_from_dem(grid, dam_xy, crest_line=None, probe_m=150.0):
    """Fallback: the side of the dam line (or the direction from the dam point) whose ground at probe_m is lower."""
    z = grid.masked()

    def at(x, y):
        r, c = grid.rc(x, y)
        return z[r, c] if grid.inside(r, c) and np.isfinite(z[r, c]) else np.nan

    if crest_line is not None and len(crest_line) >= 2:
        a = np.asarray(crest_line, float).reshape(-1, 2)
        t = unit((a[-1, 0] - a[0, 0], a[-1, 1] - a[0, 1]))
        if t is not None:
            n = (t[1], -t[0])
            za = at(dam_xy[0] + n[0] * probe_m, dam_xy[1] + n[1] * probe_m)
            zb = at(dam_xy[0] - n[0] * probe_m, dam_xy[1] - n[1] * probe_m)
            if np.isfinite(za) and np.isfinite(zb):
                return (n if za <= zb else (-n[0], -n[1])), "the lower side of the dam line (DEM)"
    best = None
    for k in range(16):
        ang = 2 * math.pi * k / 16
        v = (math.sin(ang), math.cos(ang))
        zz = at(dam_xy[0] + v[0] * probe_m, dam_xy[1] + v[1] * probe_m)
        if np.isfinite(zz) and (best is None or zz < best[0]):
            best = (zz, v)
    if best is None:
        return None, "no DEM around the dam"
    return best[1], "the lowest ground {:.0f} m from the dam point (DEM; check it)".format(probe_m)


# ---------------------------------------------------------------------- the breach inflow --
def dam_distance(X, Y, dam_xy, crest_line=None):
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    if crest_line is None or len(crest_line) < 2:
        return np.hypot(X - dam_xy[0], Y - dam_xy[1])
    return _line_foot(X, Y, crest_line)[0]


def toe_band_for_dam(h_m, ds_slope_h=None, inner_m=None, min_outer_m=None, cap_m=None):
    """The toe band (inner, outer) m downstream of the dam line for a dam `h_m` high with a downstream slope
    `ds_slope_h`:1 (3:1 when unknown): 5 m to H x (slope + 1), at least 15 m, never past the 150 m cap.
    Returns ((inner, outer), how, known)."""
    lo = INFLOW_TOE_INNER_M if inner_m is None else float(inner_m)
    cap = INFLOW_MAX_FROM_DAM_M if cap_m is None else float(cap_m)
    least = INFLOW_TOE_MIN_OUTER_M if min_outer_m is None else float(min_outer_m)
    try:
        h = float(h_m)
    except (TypeError, ValueError):
        h = float("nan")
    if not (h > 0 and np.isfinite(h)):
        lo, hi = INFLOW_TOE_BAND_M[0] if inner_m is None else lo, INFLOW_TOE_BAND_M[1]
        return (lo, max(min(hi, cap), lo + 1.0)), (
            "dam height not known: the default {:.0f}-{:.0f} m band".format(lo, hi)), False
    try:
        z = float(ds_slope_h)
        z_how = "{:g}:1 downstream slope".format(z)
    except (TypeError, ValueError):
        z = float("nan")
    if not (z > 0 and np.isfinite(z)):
        z = INFLOW_TOE_DS_SLOPE_DEFAULT
        z_how = "downstream slope not known, {:g}:1".format(z)
    raw = h * (z + 1.0)
    hi = min(max(raw, least, lo + 1.0), cap)
    how = "H x (slope + 1) = {:.1f} m x {:g} = {:.1f} m ({})".format(h, z + 1.0, raw, z_how)
    if hi > raw + 1e-6:
        how += ", at least {:.0f} m".format(hi)
    elif hi < raw - 1e-6:
        how += ", capped at {:.0f} m".format(hi)
    return (lo, hi), how, True


def _line_foot(X, Y, line):
    a = np.asarray(line, dtype=float).reshape(-1, 2)
    best = np.full(X.shape, np.inf)
    fx = np.zeros(X.shape)
    fy = np.zeros(X.shape)
    seg = np.zeros(X.shape, dtype=int)
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(a[:-1], a[1:])):
        vx, vy = x1 - x0, y1 - y0
        L2 = vx * vx + vy * vy
        t = np.clip(((X - x0) * vx + (Y - y0) * vy) / L2, 0.0, 1.0) if L2 > 0 else np.zeros(X.shape)
        px, py = x0 + t * vx, y0 + t * vy
        dd = np.hypot(px - X, py - Y)
        m = dd < best
        best = np.where(m, dd, best)
        fx = np.where(m, px, fx)
        fy = np.where(m, py, fy)
        seg = np.where(m, i, seg)
    return best, fx, fy, seg


def _segment_normals(line, downstream):
    a = np.asarray(line, dtype=float).reshape(-1, 2)
    v = np.diff(a, axis=0)
    L = np.hypot(v[:, 0], v[:, 1])
    n = np.zeros_like(v)
    ok = L > 1e-9
    n[ok, 0] = v[ok, 1] / L[ok]
    n[ok, 1] = -v[ok, 0] / L[ok]
    c = n[:, 0] * downstream[0] + n[:, 1] * downstream[1]
    n[c < 0] *= -1.0
    n[np.abs(c) < INFLOW_TOE_SIDE_MIN] = 0.0
    return n


def _toe_band_geom(grid, crest_line, downstream):
    X, Y = np.meshgrid(grid.x_centers(), grid.y_centers())
    dl, fx, fy, seg = _line_foot(X, Y, crest_line)
    n = _segment_normals(crest_line, downstream)
    with np.errstate(invalid="ignore", divide="ignore"):
        side = ((X - fx) * n[seg, 0] + (Y - fy) * n[seg, 1]) / np.where(dl > 0, dl, 1.0)
    return dl, side


def toe_band_mask(grid, crest_line, downstream, band_m=None):
    lo, hi = INFLOW_TOE_BAND_M if band_m is None else (float(band_m[0]), float(band_m[1]))
    dl, side = _toe_band_geom(grid, crest_line, downstream)
    return (dl >= lo) & (dl <= hi) & (side >= 0.5), dl


def toe_band_inflow(grid, crest_line, downstream, dam_height_m, top_m, band_m=None, max_from_dam_m=None,
                    dam_xy=None):
    """The lowest cell of the toe band downstream of the dam line along its full length (the side check: only
    cells on the downstream side of their nearest segment). Ties go to the cell nearest the line, then the dam
    point. When the band's lowest ground is not INFLOW_TOE_DROP of the dam height below the top of dam it is the
    dam's face and the outer edge moves out 10 m at a time (up to 60 m more, never past the cap).
    Returns ((x, y), note) or (None, reason starting with NO_TOE)."""
    if crest_line is None or len(crest_line) < 2:
        return None, "{}: no dam line".format(NO_TOE)
    if downstream is None:
        return None, "{}: the downstream side of the dam line is not known".format(NO_TOE)
    cap = INFLOW_MAX_FROM_DAM_M if max_from_dam_m is None else float(max_from_dam_m)
    lo, hi = (toe_band_for_dam(dam_height_m, cap_m=cap)[0] if band_m is None
              else (float(band_m[0]), float(band_m[1])))
    hi = min(hi, cap)
    if hi <= lo:
        return None, "{}: the band {:.0f}-{:.0f} m is empty".format(NO_TOE, lo, hi)
    a = np.asarray(crest_line, dtype=float).reshape(-1, 2)
    if not _segment_normals(a, downstream).any():
        return None, "{}: the dam line runs with the flow, its downstream side is not known".format(NO_TOE)
    z = grid.masked()
    X, Y = np.meshgrid(grid.x_centers(), grid.y_centers())
    dl, side = _toe_band_geom(grid, a, downstream)
    ok = np.isfinite(z) & (z < float(top_m))
    ref = dam_xy if dam_xy is not None else tuple(a.mean(axis=0))
    dref = np.hypot(X - ref[0], Y - ref[1])
    need = float(top_m) - INFLOW_TOE_DROP * float(dam_height_m)
    half = float(top_m) - 0.5 * float(dam_height_m)
    widest = min(cap, hi + 60.0)
    first = first_half = pick = None
    outer = hi
    while True:
        band = (dl >= lo) & (dl <= outer) & (side >= 0.5)
        sel = band & ok
        if sel.any():
            idx = np.flatnonzero(sel)
            k = idx[np.lexsort((dref.ravel()[idx], np.round(dl.ravel()[idx], 1), np.round(z.ravel()[idx], 2)))[0]]
            r, c = np.unravel_index(k, z.shape)
            cand = (r, c, outer)
            if first is None:
                first = cand
            if first_half is None and z[r, c] <= half:
                first_half = cand
            if z[r, c] <= need:
                pick = cand
                break
        if outer >= widest - 1e-6:
            pick = first_half if first_half is not None else first
            break
        outer = min(widest, outer + INFLOW_TOE_WIDEN_M)
    if pick is None:
        return None, ("{}: no DEM cell below the top of dam {:.0f}-{:.0f} m downstream of the dam line"
                      .format(NO_TOE, lo, widest))
    r, c, outer = pick
    d_line = float(dl[r, c])
    drop = (float(top_m) - z[r, c]) / FT
    note = ("lowest ground at the downstream toe: {:.0f}-{:.0f} m downstream of the dam line along its full length "
            "({:g} m DEM), {:.0f} m from the line, {:.1f} ft below the top of dam".format(lo, outer, grid.dx, d_line,
                                                                                         drop))
    if outer > hi + 1e-6:
        note += (" (band widened from {:.0f} m: the ground nearer is the dam's face, less than {:.0f} % of the dam "
                 "height below its top)".format(hi, 100 * INFLOW_TOE_DROP))
    if z[r, c] > half:
        note += "; less than half the dam height below the top of dam"
    elif z[r, c] > need:
        note += "; less than {:.0f} % of the dam height below the top of dam".format(100 * INFLOW_TOE_DROP)
    return (float(X[r, c]), float(Y[r, c])), note


def find_inflow_point(grid, dam_xy, dam_height_m, top_m, radius_m=None, downstream=None, crest_line=None,
                      max_from_dam_m=None):
    """Fallback (no dam line, or no toe-band cell): the lowest cell within the usual radius that is at least half
    the dam height below the top of dam, on the downstream side, never further than 150 m from the dam line (else
    the dam point); a second search out to 400 m takes the nearest qualifying cell. Returns ((x, y), note) or
    (None, reason)."""
    if radius_m is None:
        radius_m = max(90.0, 8.0 * dam_height_m)
    X, Y = np.meshgrid(grid.x_centers(), grid.y_centers())
    d = np.hypot(X - dam_xy[0], Y - dam_xy[1])
    z = grid.masked()
    need = top_m - 0.5 * dam_height_m
    ok = np.ones(z.shape, dtype=bool)
    if downstream is not None:
        ok &= ((X - dam_xy[0]) * downstream[0] + (Y - dam_xy[1]) * downstream[1]) > 0.0
    cap = INFLOW_MAX_FROM_DAM_M if max_from_dam_m is None else float(max_from_dam_m)
    dline = dam_distance(X, Y, dam_xy, crest_line)
    what = "dam line" if crest_line is not None and len(crest_line) >= 2 else "dam point"
    pt, note = _pick_inflow(X, Y, d, z, need, top_m, radius_m, ok, (dline, cap, what))
    if pt is None and downstream is not None and not note.startswith(INFLOW_FAR):
        pt, note2 = _pick_inflow(X, Y, d, z, need, top_m, radius_m, np.ones(z.shape, dtype=bool),
                                 (dline, cap, what))
        if pt is not None:
            return pt, "{}; used {} (check it)".format(NO_DOWNSTREAM, note2)
    return pt, note


def _pick_inflow(X, Y, d, z, need, top_m, radius_m, ok, lim):
    dline, cap, what = lim
    radii = [radius_m]
    wider = max(radius_m, 400.0)
    if wider > radius_m + 1.0:
        radii.append(wider)
    last_drop, last_r = 0.0, radius_m
    for rad in radii:
        near = (d <= rad) & np.isfinite(z) & ok
        if not near.any():
            last_r = rad
            continue
        last_drop = (top_m - float(np.nanmin(z[near]))) / FT
        last_r = rad
        sel = near & (z <= need)
        if not sel.any():
            continue
        if not (sel & (dline <= cap)).any():
            far = float(dline[sel].min())
            cand = (dline <= cap) & np.isfinite(z) & ok & (z < top_m)
            if not cand.any():
                return None, ("{}: the nearest ground at least half the dam height below the top of dam is {:.0f} m "
                              "from the {} (limit {:.0f} m); give the inflow point below the dam"
                              .format(INFLOW_FAR, far, what, cap))
            idx = np.flatnonzero(cand)
            k = idx[np.lexsort((dline.ravel()[idx], np.round(z.ravel()[idx], 3)))[0]]
            r, c = np.unravel_index(k, z.shape)
            return (float(X[r, c]), float(Y[r, c])), (
                "{}: used the lowest ground within {:.0f} m of the {}, {:.1f} ft below the top of dam".format(
                    INFLOW_FAR, cap, what, (top_m - z[r, c]) / FT))
        sel &= dline <= cap
        idx = np.flatnonzero(sel)
        if rad > radius_m + 1.0:
            k = idx[np.lexsort((z.ravel()[idx], d.ravel()[idx]))[0]]
        else:
            k = idx[np.lexsort((d.ravel()[idx], np.round(z.ravel()[idx], 3)))[0]]
        r, c = np.unravel_index(k, z.shape)
        drop = (top_m - z[r, c]) / FT
        if rad > radius_m + 1.0:
            note = ("toe is outside the usual {:.0f} m search; nearest ground {:.0f} m from the dam point, {:.1f} ft "
                    "below the top of dam".format(radius_m, d[r, c], drop))
        else:
            note = "lowest ground within {:.0f} m of the dam point, {:.1f} ft below the top of dam".format(rad, drop)
        return (float(X[r, c]), float(Y[r, c])), note
    return None, ("the lowest ground within {:.0f} m of the dam point is only {:.1f} ft below the top of dam; give "
                  "the inflow point below the dam".format(last_r, last_drop))


def place_inflow(fine, dam_xy, crest_line, downstream, h_m, top_m, ds_slope_h=None):
    """The breach inflow (x, y) and how it was found: the toe band on the fine DEM, else the fallback search.
    Returns (xy or None, note, band dict)."""
    (lo, hi), how, known = toe_band_for_dam(h_m, ds_slope_h)
    band = {"inner_m": lo, "outer_m": hi, "rule": how, "height_known": known,
            "cap_m": INFLOW_MAX_FROM_DAM_M}
    if crest_line is not None and len(crest_line) >= 2 and downstream is not None and h_m:
        xy, note = toe_band_inflow(fine, crest_line, downstream, h_m, top_m, band_m=(lo, hi),
                                   max_from_dam_m=min(INFLOW_MAX_FROM_DAM_M, hi + 60.0), dam_xy=dam_xy)
        if xy is not None:
            return xy, note, band
        band["toe_band_failed"] = note
    xy, note = find_inflow_point(fine, dam_xy, h_m or 3.0, top_m, downstream=downstream, crest_line=crest_line)
    if xy is not None:
        note = "fallback (no toe-band cell): " + note
    return xy, note, band
