"""Cross-check of structure points against USA Structures (FEMA / ORNL building footprints) (0.4.0).

For each structure point (an NSI point, say): is it INSIDE a USA Structures footprint, NEAR one (within a small
tolerance, 12 m by default), or on none (a possible phantom: no building there)? The footprint's occupancy class
(OCC_CLS) and primary occupancy (PRIM_OCC) are recorded and, when the point has an NSI occtype and the footprint
gives a real class, compared: a disagreement is flagged.

ADVISORY ONLY. A match, a missing footprint or a class never makes a non-911 structure habitable or not
habitable; it feeds the engineer's review (habitable_review.py), which is the only thing that does.

Pure Python (no QGIS): the caller gives the points and the footprint rings in one projected CRS; `unit_m` is metres
per map unit. A grid index keeps it fast for tens of thousands of points.
"""
import math

USA_OCC_FIELDS = ("occ_cls", "prim_occ", "build_id")
NO_CLASS = ("", "unclassified", "unknown", "none", "null", "n/a")
# NSI class letters -> the USA Structures OCC_CLS values that agree with them (lenient: lodging and entertainment
# sit between residential / commercial / assembly in the two inventories)
EXPECTED = {"RES": ("residential", "commercial"), "COM": ("commercial", "assembly"), "IND": ("industrial",),
            "AGR": ("agriculture",), "REL": ("assembly", "religion"), "GOV": ("government", "assembly"),
            "EDU": ("education", "assembly")}
CHECK_AGREE, CHECK_DIFFERS, CHECK_NO_CLASS = "agree", "differs", "no_class"


def footprint(fid, parts, occ_cls=None, prim_occ=None, build_id=None):
    """A footprint record. parts = [[ring, ring, ...], ...]: one list of rings (outer first, then holes) per polygon
    part, each ring a list of (x, y)."""
    xs = [x for part in parts for ring in part for x, _y in ring]
    ys = [y for part in parts for ring in part for _x, y in ring]
    return {"id": fid if fid not in (None, "") else None, "parts": parts, "occ_cls": occ_cls, "prim_occ": prim_occ,
            "build_id": build_id, "bbox": (min(xs), min(ys), max(xs), max(ys)) if xs else None}


def build_index(footprints, cell):
    """Grid index: {(ix, iy): [footprint index, ...]} over each footprint's bbox, `cell` map units wide."""
    grid = {}
    for i, f in enumerate(footprints):
        if not f["bbox"]:
            continue
        x0, y0, x1, y1 = f["bbox"]
        for ix in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for iy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                grid.setdefault((ix, iy), []).append(i)
    return {"cell": cell, "grid": grid, "footprints": footprints}


def _inside(x, y, part):
    inside = False
    for ring in part:
        n = len(ring)
        for k in range(n):
            (x1, y1), (x2, y2) = ring[k], ring[(k + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def _edge_dist(x, y, part):
    best = float("inf")
    for ring in part:
        n = len(ring)
        for k in range(n):
            (x1, y1), (x2, y2) = ring[k], ring[(k + 1) % n]
            dx, dy = x2 - x1, y2 - y1
            L = dx * dx + dy * dy
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L))
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if d < best:
                best = d
    return best


def match_point(x, y, index, tol):
    """(kind, distance in map units, footprint) with kind "inside", "near" or "none"."""
    cell, grid, fps = index["cell"], index["grid"], index["footprints"]
    seen, best = set(), (None, float("inf"))
    ix0, ix1 = int(math.floor((x - tol) / cell)), int(math.floor((x + tol) / cell))
    iy0, iy1 = int(math.floor((y - tol) / cell)), int(math.floor((y + tol) / cell))
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            for i in grid.get((ix, iy), ()):
                if i in seen:
                    continue
                seen.add(i)
                f = fps[i]
                bx0, by0, bx1, by1 = f["bbox"]
                if x < bx0 - tol or x > bx1 + tol or y < by0 - tol or y > by1 + tol:
                    continue
                for part in f["parts"]:
                    if _inside(x, y, part):
                        return "inside", 0.0, f
                    d = _edge_dist(x, y, part)
                    if d < best[1]:
                        best = (f, d)
    if best[0] is not None and best[1] <= tol:
        return "near", best[1], best[0]
    return "none", None, None


def compare_class(nsi_class_letters, usa_occ_cls):
    """"agree" / "differs" / "no_class" (no NSI class, or USA Structures has no real class) for the NSI class
    letters (RES, COM ...) against a USA Structures OCC_CLS."""
    u = str(usa_occ_cls or "").strip().lower()
    if not nsi_class_letters or u in NO_CLASS:
        return CHECK_NO_CLASS
    return CHECK_AGREE if u in EXPECTED.get(nsi_class_letters, ()) else CHECK_DIFFERS


def cross_check(points, footprints, tol_m, unit_m=1.0, cell_m=60.0):
    """points: {rid: (x, y, nsi_class_letters or None)} in the footprints' CRS. Returns {rid: {"usa_struct_match":
    "inside"/"near"/"none", "usa_struct_dist_m", "usa_struct_id", "usa_occ_cls", "usa_prim_occ", "usa_occ_check"}}."""
    tol = tol_m / unit_m
    index = build_index(footprints, max(cell_m / unit_m, tol * 2, 1e-9))
    out = {}
    for rid, (x, y, letters) in points.items():
        kind, d, f = match_point(x, y, index, tol)
        e = {"usa_struct_match": kind, "usa_struct_dist_m": None if d is None else round(d * unit_m, 1),
             "usa_struct_id": None, "usa_occ_cls": None, "usa_prim_occ": None, "usa_occ_check": None}
        if f is not None:
            e.update(usa_struct_id=f["build_id"] or f["id"], usa_occ_cls=f["occ_cls"], usa_prim_occ=f["prim_occ"],
                     usa_occ_check=compare_class(letters, f["occ_cls"]) if letters else None)
        out[rid] = e
    return out
