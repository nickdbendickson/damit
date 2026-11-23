"""Offline tests for damit_runner/core/streamstats.py on saved USGS StreamStats responses.

The fixtures are REAL server answers, captured 2026-10-29 from the post-January-2026
services (ss-delineate, ss-hydro, nssservices), the same golden captures DamSafety_PMP
tests on (DWR_Plugins DamSafety_PMP/tests/fixtures_streamstats/both_dams/). Each capture
carries a .prov.json recording the URL and response sha256 it came from.

They pin the wire contract the Runner depends on, so provider schema drift fails these
tests loudly instead of silently emptying the Runner's basin tools:
  - the live delineate answer nests the watershed as [[{name, feature}]] and carries an
    EMPTY workspace_id (the stateless new API);
  - the live basin-characteristics answer is a BARE list of parameters (both shapes are
    accepted since audit 2026-11-20; the wrapped {"parameters": [...]} kept);
  - the live flood-statistics answer uses lower-case regressionRegions/results with AEP
    codes ("PK1AEP" = 1 % AEP = Q100) - the parser previously looked for the
    decommissioned English-name shape and found nothing (fixed audit 2026-11-20).

Run:  python -m unittest damit_runner.tests.test_streamstats_golden
"""
import importlib.util
import json
import math
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
FIX = os.path.join(HERE, "fixtures_streamstats")

_spec = importlib.util.spec_from_file_location("ss_golden", os.path.join(HERE, "..", "core", "streamstats.py"))
ss = importlib.util.module_from_spec(_spec)
sys.modules["ss_golden"] = ss
_spec.loader.exec_module(ss)


def _load(label, kind):
    for name in os.listdir(os.path.join(FIX, label)):
        if kind in name and name.endswith(".json") and ".prov." not in name and ".request." not in name:
            with open(os.path.join(FIX, label, name), encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(kind + " for " + label)


def _no_net(*a, **k):
    raise AssertionError("network used in an offline test: {!r}".format(a[:1]))


DELIN_2801 = _load("DWR2801", "delineate")
BC_2801 = _load("DWR2801", "bchars")
SG2_2801 = _load("DWR2801", "sg2")
DELIN_4031 = _load("DWR4031", "delineate")

# Pinned at capture time against the live NSS service (DWR's test_streamstats.py):
EXPECT_2801_Q = {"Q2": 66.0, "Q5": 192.0, "Q10": 313.0, "Q25": 503.0, "Q50": 667.0,
                 "Q100": 847.0, "Q500": 1300.0}
EXPECT_2801_AREA = 16.6

POINT_2801 = (-97.39113, 46.98337)     # (lon, lat) as the API got it
POINT_4031 = (-101.4370363, 48.2985029)


def _normalized(raw, ws_id=""):
    """delineate()'s view of a capture (bcrequest.wsresp). ws_id lets a caller stand in
    the workspace the stateless new-API capture leaves empty."""
    ws = raw.get("bcrequest", {}).get("wsresp", {})
    return {"workspaceID": ws.get("workspace_id", "") or ws_id,
            "featurecollection": ws.get("featurecollection", []),
            "parameters": ws.get("parameters", []), "_raw": raw}


class DelineateNormalization(unittest.TestCase):
    def test_live_capture_normalizes_to_the_legacy_shape(self):
        b = _normalized(DELIN_2801)
        # stateless API: empty workspace id must not be mistaken for a failure
        self.assertEqual(b["workspaceID"], "")
        fc = b["featurecollection"]
        self.assertTrue(isinstance(fc, list) and fc, "featurecollection is a non-empty list")
        names = []
        for item in fc:
            for inner in (item if isinstance(item, list) else [item]):
                names.append(inner.get("name"))
        self.assertIn("globalwatershed", names)          # the basin polygon is present
        self.assertIn("globalwatershedpoint", names)     # the snapped pour point too

    def test_basin_area_from_the_live_polygon(self):
        b = _normalized(DELIN_2801)
        area = ss.basin_area_sqmi(b)
        self.assertIsNotNone(area)
        # bbox-of-ring overestimate must be above the true DRNAREA but same order
        self.assertGreater(area, EXPECT_2801_AREA)
        self.assertLess(area, EXPECT_2801_AREA * 8)

    def test_basin_area_absent_polygon_answers_none(self):
        self.assertIsNone(ss.basin_area_sqmi({"featurecollection": []}))
        self.assertIsNone(ss.basin_area_sqmi({}))

    def test_4031_polygon_present(self):
        b = _normalized(DELIN_4031)
        names = []
        for item in b["featurecollection"]:
            for inner in (item if isinstance(item, list) else [item]):
                names.append(inner.get("name"))
        self.assertIn("globalwatershed", names)


class FloodFrequencyFromGolden(unittest.TestCase):
    WS = "golden-ws"          # the stateless capture leaves workspace_id empty

    def _run(self, basin, sg2, state="ND"):
        with mock.patch.object(ss, "_get", side_effect=self._routes(sg2)):
            return ss.flood_frequency(basin, state=state)

    @staticmethod
    def _routes(sg2):
        def fake_get(url, timeout=60):
            if "flowstatistics.json" in url:
                return sg2
            raise AssertionError("unexpected URL in offline test: " + url)
        return fake_get

    def test_full_curve_from_the_live_answer(self):
        b = _normalized(DELIN_2801, self.WS)
        flows = self._run(b, SG2_2801)
        for ri, q in EXPECT_2801_Q.items():
            self.assertEqual(flows.get(ri), q, "{} should be {} (live capture)".format(ri, q))
        # area comes from the delineation's parameters list (empty here) -> None
        self.assertIsNone(flows.get("area_sqmi"))

    def test_drift_decoy_old_english_shape_still_parses(self):
        old_shape = [{"RegressionRegions": [{"Results": [
            {"Name": "Peak Flood, 100-Year Recurrence Interval", "Value": 999.0},
            {"Name": "Peak Flood, 2-Year Recurrence Interval", "Value": 111.0},
        ]}]}]
        b = _normalized(DELIN_2801, self.WS)
        flows = self._run(b, old_shape)
        self.assertEqual(flows.get("Q100"), 999.0)
        self.assertEqual(flows.get("Q2"), 111.0)

    def test_drift_decoy_unknown_codes_ignored_not_crashed(self):
        weird = [{"regressionRegions": [{"results": [
            {"code": "PK9AEP", "value": 1.0},          # not a mapped RI: skipped
            {"code": "BANKFULL", "value": 2.0},        # not a PK*AEP: ignored
            {"code": "PK1AEP", "value": None},         # null value: skipped
            {"code": "PK0_2AEP", "value": 1300.0},     # 0.2 % AEP = Q500
        ]}]}]
        b = _normalized(DELIN_2801, self.WS)
        flows = self._run(b, weird)
        self.assertEqual(flows.get("Q500"), 1300.0)
        self.assertIsNone(flows.get("Q9"))
        self.assertEqual(len([k for k in flows if k.startswith("Q")]), 1)

    def test_no_state_no_workspace_answers_valueerror(self):
        b = _normalized(DELIN_2801)                    # stateless capture: no STABBR, no ws
        with self.assertRaises(ValueError):
            self._run(b, SG2_2801, state=None)          # nothing to infer from either


class BasinCharacteristicsFromGolden(unittest.TestCase):
    def test_bare_list_shape_the_live_service_answers(self):
        with mock.patch.object(ss, "_get", return_value=BC_2801):
            b = ss.basin_characteristics("ws", "ND")
        self.assertEqual(b.get("DRNAREA"), EXPECT_2801_AREA)
        self.assertGreaterEqual(len(b), 20)              # 23 characteristics captured
        self.assertIn("BSLDEM10M", b)

    def test_wrapped_legacy_shape_still_accepted(self):
        wrapped = {"parameters": [{"code": "DRNAREA", "value": 1.5}]}
        with mock.patch.object(ss, "_get", return_value=wrapped):
            b = ss.basin_characteristics("ws", "ND")
        self.assertEqual(b.get("DRNAREA"), 1.5)

    def test_garbage_answers_empty_dict_not_crash(self):
        for bad in ([], "nope", None, {"unexpected": 1}):
            with mock.patch.object(ss, "_get", return_value=bad):
                self.assertEqual(ss.basin_characteristics("ws", "ND"), {}, repr(bad))


class GeometryGuards(unittest.TestCase):
    # dem_covers_basin was removed as unused in the 2026-11-19 dead-code sweep (1df0f5b); nothing in
    # DamIT or DamSafety calls it, so its test went too (repo audit 2026-11-23, finding 2).

    def test_pmf_inflow_volume_identity(self):
        # 1 inch over 1 sq mi = 53.33 acre-ft (the module's own identity)
        r = ss.pmf_inflow(1.0, 1.0)
        self.assertAlmostEqual(r["volume_acft"], 53.33, delta=0.06)   # rounded to 0.1
        self.assertAlmostEqual(r["peak_cfs"], 53.33 * 43560 / (0.5 * 24 * 3600), delta=6.0)
        self.assertEqual(r["time_to_peak_hr"], 12.0)

    def test_supported_states_includes_nd(self):
        self.assertIn("ND", ss.supported_states())


if __name__ == "__main__":
    unittest.main()
