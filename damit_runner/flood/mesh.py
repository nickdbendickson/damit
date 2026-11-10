# Vendored from nickdbendickson/DWR_Plugins 591f48d: DamSafety Runner core/anuga_model.py (inlet_line, mesh_polygons,
# the default ANUGA mesher) and core/terrain.py (the mask-to-polygon helpers it uses), unchanged except where marked
# "DamIT:".
"""The DamSafety Runner's ANUGA mesh: the outer polygon is the area the LISFLOOD-FP (or built-in) run flooded
(depth > 0.05 m), widened by ANUGA_BUFFER, kept a tolerance away from the DEM edge and from no-data, its largest
piece around the inflow, traced and simplified (Douglas-Peucker); the refined polygon is the flooded area within
ANUGA_NEAR_MI of the inflow, widened by min(200 m, buffer / 2) and kept away from the outer edge. ANUGA's own mesher
(create_domain_from_regions) then fills them with triangles of at most ANUGA_FINE / ANUGA_COARSE m2.

Needs numpy and scipy (scipy.ndimage), as in the DamSafety Runner; contourpy is used when it is installed, else the
built-in cell-edge tracer. Not ported: the gmsh mesher, culvert regions, embankment breaklines and the fine-terrain
bed (ANUGA_ELEVATION=fine); the bed is the model DEM."""
import numpy as np


class MeshSettings:
    """DamIT: the AnugaSettings fields mesh_polygons reads."""

    def __init__(self, buffer_m=500.0, near_field_radius_m=1609.344):
        self.buffer_m = float(buffer_m)
        self.near_field_radius_m = float(near_field_radius_m)


FLOODED_M = 0.05                 # DamSafety workflow: flooded = LISFLOOD-FP depth > 0.05 m


def flooded_mask(depth):
    """DamIT: the workflow's mask, np.isfinite(depth) & (depth > 0.05)."""
    d = np.asarray(depth, float)
    return np.isfinite(d) & (d > FLOODED_M)


def _valid(dem):
    """DamIT: core/grid.Grid.valid() for geom.Grid."""
    return np.isfinite(dem.masked())


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


def _have_contourpy():
    try:
        import contourpy  # noqa: F401
        return True
    except ImportError:
        return False


def _outline_contourpy(grid, mask):
    import contourpy
    m = np.pad(mask.astype(float), 1)
    xs = np.concatenate([[grid.x_centers()[0] - grid.dx], grid.x_centers(),
                         [grid.x_centers()[-1] + grid.dx]])
    ys = np.concatenate([[grid.y_centers()[0] + grid.dx], grid.y_centers(),
                         [grid.y_centers()[-1] - grid.dx]])
    gen = contourpy.contour_generator(xs, ys, m)
    lines = gen.lines(0.5)
    if not lines:
        raise ValueError("empty mask")
    return max(lines, key=lambda l: abs(_area(l)))


def _outline_cells(grid, mask):
    """Built-in outline (3.4.4): the cell-edge boundary of the largest region of `mask`
    (8-connected, holes filled, corner-only contacts closed so that the ring is a simple
    polygon). Used when contourpy is not installed - QGIS 3.28's Python has none (found by the
    real-QGIS smoke run on macOS, 2026-10-02). Follows cell edges where contourpy cuts corners
    at the cell-edge midpoints; after the simplification the two outlines lie within about one
    cell plus the simplification tolerance of each other (measured on blobs and a flood-shaped
    mask, 10 m cells: 9-12 m apart with a 10 m tolerance; 18 m where a corner-only contact was
    closed)."""
    m = np.asarray(mask, bool)
    if not m.any():
        raise ValueError("empty mask")
    try:
        from scipy import ndimage
        lab, n = ndimage.label(m, structure=np.ones((3, 3), bool))
        if n > 1:
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            m = lab == int(np.argmax(sizes))
        m = ndimage.binary_fill_holes(m)
    except ImportError:                  # without scipy: the largest ring of the whole mask
        pass
    m = np.pad(m, 1)
    for _ in range(50):                  # close corner-only contacts (pinch vertices)
        a, b, c, d = m[:-1, :-1], m[:-1, 1:], m[1:, :-1], m[1:, 1:]
        p1 = a & d & ~b & ~c
        p2 = b & c & ~a & ~d
        if not (p1.any() or p2.any()):
            break
        m[:-1, 1:] |= p1
        m[:-1, :-1] |= p2
    # directed boundary edges between cell corners (row, col of the padded array): every
    # vertex then has exactly one outgoing edge, so the rings follow without ambiguity
    nxt = {}
    rr, cc = np.nonzero(m)
    for r, c in zip(rr.tolist(), cc.tolist()):
        if not m[r - 1, c]:
            nxt[(r, c)] = (r, c + 1)
        if not m[r, c + 1]:
            nxt[(r, c + 1)] = (r + 1, c + 1)
        if not m[r + 1, c]:
            nxt[(r + 1, c + 1)] = (r + 1, c)
        if not m[r, c - 1]:
            nxt[(r + 1, c)] = (r, c)
    best, best_area = None, -1.0
    x_left = float(grid.x_centers()[0]) - 0.5 * grid.dx
    y_top = float(grid.y_centers()[0]) + 0.5 * grid.dx
    while nxt:
        start, _ = next(iter(nxt.items()))
        ring, v = [], start
        while v in nxt:
            ring.append(v)
            v = nxt.pop(v)
        pts = np.array([[x_left + (c - 1) * grid.dx, y_top - (r - 1) * grid.dx] for r, c in ring])
        a = abs(_area(pts)) if len(pts) >= 3 else 0.0
        if a > best_area:
            best, best_area = pts, a
    if best is None or len(best) < 3:
        raise ValueError("empty mask")
    return best


def mask_outline(grid, mask, simplify_m, backend=None):
    """Outer boundary of the largest region of `mask` as an (N, 2) array of
    x, y (open ring, counter-clockwise). contourpy when it is installed, else the built-in
    cell-edge tracer (`backend` "contourpy" / "cells" forces one; tests)."""
    use = backend or ("contourpy" if _have_contourpy() else "cells")
    ring = _outline_contourpy(grid, mask) if use == "contourpy" else _outline_cells(grid, mask)
    if np.allclose(ring[0], ring[-1]):
        ring = ring[:-1]
    ring = douglas_peucker(np.vstack([ring, ring[:1]]), simplify_m)[:-1]
    if _area(ring) < 0:
        ring = ring[::-1]
    return ring


def _area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def disk_mask(grid, center_xy, radius_m):
    X, Y = np.meshgrid(grid.x_centers(), grid.y_centers())
    return np.hypot(X - center_xy[0], Y - center_xy[1]) <= radius_m


def dilate(mask, dist_m, dx):
    from scipy.ndimage import distance_transform_edt
    if dist_m <= 0:
        return mask.copy()
    return distance_transform_edt(~mask) * dx <= dist_m


def largest_component(mask, seed_rc=None):
    from scipy.ndimage import label
    lab, n = label(mask, structure=np.ones((3, 3), bool))
    if n <= 1:
        return mask
    if seed_rc is not None and lab[seed_rc] > 0:
        return lab == lab[seed_rc]
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab == int(np.argmax(sizes))


def inlet_line(inflow_xy, direction, width_m):
    """A line across the flow, centred on the inflow point."""
    ux, uy = direction
    px, py = -uy, ux
    h = 0.5 * width_m
    x, y = inflow_xy
    return np.array([[x - px * h, y - py * h], [x + px * h, y + py * h]])


def mesh_polygons(dem, flooded, inflow_xy, st):
    """Outer mesh polygon (flooded area + buffer, inside the DEM) and the
    refined near-field polygon."""
    region = dilate(flooded, st.buffer_m, dem.dx)
    # The simplified outline can wander up to `tol` from the region edge, so keep
    # the region that far (plus a cell) away from the DEM edge and from no-data;
    # otherwise the mesh could cover terrain that was filled in, not measured.
    tol = min(st.buffer_m / 10.0, 3.0 * dem.dx)
    tol = max(tol, dem.dx)
    valid_pad = np.pad(_valid(dem), 1, constant_values=False)
    near_bad = dilate(~valid_pad, tol + dem.dx, dem.dx)[1:-1, 1:-1]
    region &= ~near_bad
    r, c = dem.rc(*inflow_xy)
    if not (dem.inside(r, c) and region[r, c]):
        # the inflow cell itself must be inside the mesh
        region |= disk_mask(dem, inflow_xy, 2.5 * dem.dx) & _valid(dem)
    region = largest_component(region, (r, c))
    outer = mask_outline(dem, region, simplify_m=tol)
    near = disk_mask(dem, inflow_xy, st.near_field_radius_m)
    fine_mask = dilate(flooded & near, min(200.0, st.buffer_m / 2.0), dem.dx) & region
    shrink = dilate(~region, max(3 * dem.dx, st.buffer_m / 4.0), dem.dx)
    fine_mask &= ~shrink
    fine = np.zeros((0, 2))
    if fine_mask.sum() > 20:
        fine_mask = largest_component(fine_mask, (r, c) if fine_mask[r, c] else None)
        fine = mask_outline(dem, fine_mask, simplify_m=max(2 * dem.dx, 20.0))
    return outer, fine
