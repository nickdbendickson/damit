"""P95 velocity review flag. The class stays on the cell velocities.

A structure is flagged when the worst depth-velocity zone of its wet cells would differ
if every wet cell were read at the 95th-percentile velocity of those cells. The flag is
not a hit and is not read by the class. A less severe shadow does not lower the class; a
more severe shadow does not raise it.
"""

from . import tm11

PCT = 95.0


def percentile(values, pct=PCT):
    """Linear percentile, the same index as numpy's default (pct/100 * (n-1))."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (float(pct) / 100.0) * (len(xs) - 1)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    t = k - lo
    return xs[lo] * (1.0 - t) + xs[hi] * t


def _chart_ids(cat, receptor):
    methods = (cat or {}).get("methods") or {}
    params = (methods.get("M1") or {}).get("params") or {}
    mapping = params.get("chart_for_type") or {"home": "houses", "mobile_home": "mobile_homes"}
    key = receptor.get("type") or "home"
    cids = mapping.get(key)
    if cids is None:
        cids = mapping.get("home") or "houses"
    if isinstance(cids, str):
        return [cids]
    return [c for c in cids if c]


def _wet(receptor):
    out = []
    for c in receptor.get("cells") or []:
        if not c or len(c) < 2 or c[0] is None or c[1] is None:
            continue
        try:
            d, v = float(c[0]), float(c[1])
        except (TypeError, ValueError):
            continue
        if d > 0 and d == d and v == v:
            out.append((d, v))
    return out


def hinge(charts, receptor, cat=None):
    """A review record when the zone would differ at P95 velocity, else None.

    The record has no class. Callers must not feed it to a hit.
    """
    wet = _wet(receptor)
    if len(wet) < 2 or charts is None:
        return None
    p95 = percentile([v for _d, v in wet], PCT)
    if p95 is None:
        return None
    shadow = [(d, p95) for d, _v in wet]
    diffs = []
    for cid in _chart_ids(cat, receptor):
        if not charts.digitized(cid):
            continue
        z_peak, _, _ = charts.worst(cid, wet)
        z_p95, _, _ = charts.worst(cid, shadow)
        if z_peak is None or z_p95 is None or z_peak == z_p95:
            continue
        diffs.append({"chart": cid, "zone_peak": z_peak, "zone_p95": z_p95,
                      "less_severe": tm11.RANK[z_p95] < tm11.RANK[z_peak]})
    if not diffs:
        return None
    bits = []
    for d in diffs:
        bits.append("{} would be {} at the 95th-percentile velocity and is {} on the "
                    "cell velocities".format(d["chart"], d["zone_p95"], d["zone_peak"]))
    return {"id": receptor.get("id"), "velocity_p95_fps": p95,
            "charts": diffs, "less_severe": any(d["less_severe"] for d in diffs),
            "message": "review flag only, class unchanged: " + "; ".join(bits)
            + " ({:.2f} ft/s)".format(p95)}


def review(runs, charts, cat=None):
    """One record per structure whose zone would differ. Does not change any class."""
    out = []
    for run in runs or []:
        scenario = run.get("scenario")
        for r in run.get("receptors") or []:
            if r.get("kind") not in (None, "structure", "facility"):
                continue
            rec = hinge(charts, r, cat)
            if rec:
                rec["scenario"] = scenario
                out.append(rec)
    return out
