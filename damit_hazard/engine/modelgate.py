"""Checks of flood rasters before they are classified. The gate has no class.

Thresholds are the engineer's. A check that cannot be made is SKIP. The status is the
worst row (FAIL > WARN > PASS; only SKIP -> SKIP). Nothing here changes a hazard class.
"""

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_RANK = {SKIP: 0, PASS: 1, WARN: 2, FAIL: 3}

DEFAULTS = {
    "wet_ft": 0.0,
    "edge_warn_ft": 0.0,
    "edge_fail_ft": None,
    "hole_max_gap_cells": 3,
    "hole_fail_fraction": 0.05,
}


def _worst(rows):
    status = SKIP
    for row in rows:
        if _RANK[row["status"]] > _RANK[status]:
            status = row["status"]
    if status == SKIP and any(r["status"] == PASS for r in rows):
        status = PASS
    return status


def _holes(wet, nodata, gap):
    """Nodata runs of length <= gap with wet cells on both sides, rows and columns."""
    import numpy as np
    h, w = wet.shape
    count = np.zeros((h, w), dtype=bool)
    gap = int(gap)

    def mark(line_wet, line_na, write):
        n = line_wet.size
        i = 0
        while i < n:
            if not line_na[i]:
                i += 1
                continue
            j = i
            while j < n and line_na[j]:
                j += 1
            if j - i <= gap and i > 0 and j < n and line_wet[i - 1] and line_wet[j]:
                write(i, j)
            i = j

    for r in range(h):
        mark(wet[r], nodata[r], lambda a, b, r=r: count.__setitem__((r, slice(a, b)), True))
    for c in range(w):
        mark(wet[:, c], nodata[:, c], lambda a, b, c=c: count.__setitem__((slice(a, b), c), True))
    return int(count.sum())


def gate_arrays(depth, velocity=None, params=None):
    """`depth` is a 2-D array. Non-finite cells are no data. Returns status and rows."""
    import numpy as np
    p = dict(DEFAULTS)
    p.update(params or {})
    a = np.asarray(depth, dtype=float)
    if a.ndim != 2 or a.size == 0:
        row = {"check": "depth", "status": SKIP, "reason": "no depth array"}
        return {"status": SKIP, "rows": [row], "class_changed": False}
    nodata = ~np.isfinite(a)
    wet = np.isfinite(a) & (a > float(p["wet_ft"]))
    rows = []
    edge = np.zeros(a.shape, dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    edge_vals = a[edge & np.isfinite(a)]
    if edge_vals.size == 0:
        rows.append({"check": "edge", "status": SKIP, "reason": "no finite edge cell"})
    else:
        mx = float(edge_vals.max())
        fail_at = p.get("edge_fail_ft")
        if fail_at is not None and mx > float(fail_at):
            rows.append({"check": "edge", "status": FAIL,
                         "reason": "edge depth {:.3f} ft is above {:.3f} ft".format(mx, float(fail_at)),
                         "value": mx})
        elif mx > float(p["edge_warn_ft"]):
            rows.append({"check": "edge", "status": WARN,
                         "reason": "edge depth {:.3f} ft is above {:.3f} ft".format(
                             mx, float(p["edge_warn_ft"])),
                         "value": mx})
        else:
            rows.append({"check": "edge", "status": PASS,
                         "reason": "edge depth {:.3f} ft".format(mx), "value": mx})
    n_wet = int(wet.sum())
    if n_wet == 0:
        rows.append({"check": "holes", "status": SKIP, "reason": "no wet cell"})
    else:
        n_holes = _holes(wet, nodata, p["hole_max_gap_cells"])
        frac = n_holes / float(n_wet)
        fail_frac = p.get("hole_fail_fraction")
        if n_holes == 0:
            rows.append({"check": "holes", "status": PASS, "reason": "no interior no-data gap",
                         "value": 0})
        elif fail_frac is not None and frac > float(fail_frac):
            rows.append({"check": "holes", "status": FAIL,
                         "reason": "{} hole cell(s), {:.3f} of the wet cells".format(n_holes, frac),
                         "value": frac})
        else:
            rows.append({"check": "holes", "status": WARN,
                         "reason": "{} interior no-data cell(s) with water on both sides".format(n_holes),
                         "value": n_holes})
    if velocity is None:
        rows.append({"check": "velocity", "status": SKIP, "reason": "no velocity array"})
    else:
        v = np.asarray(velocity, dtype=float)
        if v.shape != a.shape:
            rows.append({"check": "velocity", "status": WARN, "reason": "velocity shape differs"})
        else:
            wet_v = v[wet & np.isfinite(v)]
            if wet_v.size == 0:
                rows.append({"check": "velocity", "status": WARN,
                             "reason": "wet cells have no velocity"})
            else:
                rows.append({"check": "velocity", "status": PASS,
                             "reason": "velocity on wet cells, max {:.2f} ft/s".format(float(wet_v.max())),
                             "value": float(wet_v.max())})
    return {"status": _worst(rows), "rows": rows, "class_changed": False}
