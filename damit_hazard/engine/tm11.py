"""USBR ACER TM-11 depth-velocity danger charts, read from data/tm11_charts.json.

The houses and mobile-homes tables are the DamSafety suite's digitized REG_05.2026 Figs 5.1 / 5.2
(= TM-11 Figs 2 / 3), copied from DamSafety_Core/damsuite/tm11_curves.py (see the file's
provenance). TM-11 Figs 4-6 (passenger vehicles, adults, children) are not digitized: zone()
raises ChartNotDigitized for them unless the caller supplies a curve (load(extra=...)).

Rule (the suite's): linear between tabulated velocities; a velocity above the chart's axis or a
depth above its axis is HIGH; a negative velocity reads at 0; a depth ON a boundary takes the
higher zone; a depth of 0 or less is LOW (DamSafety_Core's zone() would call a dry point
faster than the axis HIGH; the engine only passes wet cells, so the two agree on every wet cell).
"""
import json
import os

LOW, JUDGMENT, HIGH = "low", "judgment", "high"
RANK = {LOW: 0, JUDGMENT: 1, HIGH: 2}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(HERE, "data", "tm11_charts.json")


class ChartNotDigitized(KeyError):
    pass


def _interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + t * (ys[hi] - ys[lo])


class Charts(object):
    """The chart set. charts[id] = {title, status, v_fts, low_ft, high_ft, v_max_fts, d_max_ft}."""

    def __init__(self, data):
        self.data = data
        self.charts = data.get("charts", {})

    def ids(self):
        return list(self.charts)

    def digitized(self, cid):
        c = self.charts.get(cid)
        return bool(c) and c.get("status") == "digitized" and bool(c.get("v_fts"))

    def title(self, cid):
        return (self.charts.get(cid) or {}).get("title", cid)

    def thresholds(self, cid, v):
        """(low line ft, high line ft) at velocity v ft/s."""
        if not self.digitized(cid):
            raise ChartNotDigitized(cid)
        c = self.charts[cid]
        v = max(0.0, float(v))
        return _interp(v, c["v_fts"], c["low_ft"]), _interp(v, c["v_fts"], c["high_ft"])

    def zone(self, cid, d, v):
        if not self.digitized(cid):
            raise ChartNotDigitized(cid)
        c = self.charts[cid]
        d, v = float(d), float(v)
        if d <= 0:
            return LOW                       # a dry point is not in danger whatever the velocity
        if v > c["v_max_fts"] or d > c["d_max_ft"]:
            return HIGH
        lo, hi = self.thresholds(cid, v)
        if d >= hi:
            return HIGH
        if d >= lo and d > 0:
            return JUDGMENT
        return LOW

    def worst(self, cid, pairs):
        """(zone, (d, v), margin_ft) of the worst cell: margin = high line - d at that cell (how
        far below the high-danger line it is; <= 0 when high)."""
        best, at, margin = None, None, None
        for d, v in pairs:
            if d is None or v is None or d != d or v != v:
                continue
            z = self.zone(cid, d, v)
            try:
                m = self.thresholds(cid, v)[1] - d
            except ChartNotDigitized:
                m = None
            if best is None or RANK[z] > RANK[best] or (RANK[z] == RANK[best] and m is not None
                                                        and (margin is None or m < margin)):
                best, at, margin = z, (d, v), m
        return best, at, margin


def load(path=None, extra=None):
    """Charts from path (default data/tm11_charts.json), with `extra` (a dict of the same form,
    or a path to one) overriding / adding charts, e.g. a user-digitized TM-11 Fig. 4."""
    with open(path or DEFAULT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if extra:
        if isinstance(extra, str):
            with open(extra, encoding="utf-8") as f:
                extra = json.load(f)
        for cid, c in (extra.get("charts", extra) or {}).items():
            c = dict(c)
            c.setdefault("status", "digitized")
            c.setdefault("title", cid + " (user-supplied curve)")
            data.setdefault("charts", {})[cid] = c
    return Charts(data)


def check(charts):
    """Problems of a chart set ([] = consistent)."""
    out = []
    for cid in charts.ids():
        if not charts.digitized(cid):
            continue
        c = charts.charts[cid]
        v, lo, hi = c["v_fts"], c["low_ft"], c["high_ft"]
        if not (len(v) == len(lo) == len(hi)) or len(v) < 2:
            out.append("{}: columns of different length".format(cid))
            continue
        if any(b <= a for a, b in zip(v, v[1:])):
            out.append("{}: velocities not increasing".format(cid))
        if any(a > b for a, b in zip(lo, hi)):
            out.append("{}: low line above the high line".format(cid))
    return out
