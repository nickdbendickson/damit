"""TM-11 chart data: consistent, the Core table copied verbatim (when the DWR checkout is
present), the suite's zone rule."""
import os
import sys
import unittest

from _helpers import CHARTS, tm11


def test_charts_consistent_and_five_listed():
    assert tm11.check(CHARTS) == []
    assert set(CHARTS.ids()) == {"houses", "mobile_homes", "passenger_vehicles", "adults",
                                 "children"}
    assert CHARTS.digitized("houses") and CHARTS.digitized("mobile_homes")
    assert not CHARTS.digitized("adults")


def test_zone_rule():
    lo, hi = CHARTS.thresholds("houses", 1.0)
    assert (lo, hi) == (2.916, 5.968)
    assert CHARTS.zone("houses", lo, 1.0) == tm11.JUDGMENT          # on the line: higher zone
    assert CHARTS.zone("houses", hi, 1.0) == tm11.HIGH
    assert CHARTS.zone("houses", 0.5, 30.0) == tm11.HIGH             # past the velocity axis
    assert CHARTS.zone("houses", 0.0, 30.0) == tm11.LOW              # dry
    assert CHARTS.zone("mobile_homes", 2.5, 0.0) == tm11.HIGH


def test_same_as_damsafety_core():
    root = os.environ.get("DWR_PLUGINS_ROOT")
    if not root or not os.path.isdir(os.path.join(root, "DamSafety_Core")):
        raise unittest.SkipTest("no DamSafety_Core checkout (set DWR_PLUGINS_ROOT)")
    sys.path.insert(0, root)
    from DamSafety_Core.damsuite import tm11_curves as T
    for cid, k in (("houses", "house"), ("mobile_homes", "mobile")):
        c = CHARTS.charts[cid]
        assert tuple(c["v_fts"]) == T.CURVES[k]["v"]
        assert tuple(c["low_ft"]) == T.CURVES[k]["low"]
        assert tuple(c["high_ft"]) == T.CURVES[k]["high"]
        assert (c["v_max_fts"], c["d_max_ft"]) == T.AXES[k]
        for v in [x * 0.37 for x in range(80)]:
            for d in [y * 0.13 for y in range(1, 90)]:
                assert CHARTS.zone(cid, d, v) == T.zone(k, d, v), (cid, d, v)
