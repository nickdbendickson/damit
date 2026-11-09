"""DamIT Hazard Lite engine (pure Python): records and catalog-driven classes."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_core.lib import catalog_access  # noqa: E402
from damit_hazardlite import engine as E  # noqa: E402

CAT = catalog_access.load()
PROF = E.profile(CAT)
VOCAB = E.load_vocab()
SF = {"type": "occ", "habitable": None, "occupants": "pop", "m1_zone": None}
RF = {"road_class": "cls", "aadt": "aadt"}
LF = {"active": None, "trains_per_day": "tpd", "passenger": None}


def struct(rid, depth, vel=None, occ="RES1-1SNB", pop=3):
    cells = E.reduce_cells([depth], [vel], PROF["wet_min_depth_ft"])
    return E.structure_record(rid, cells, {"occ": occ, "pop": pop}, PROF, VOCAB, SF)


def road(rid, depth, cls="local", aadt=100):
    return E.road_record(rid, E.reduce_cells([0.0, depth], None, PROF["wet_min_depth_ft"]),
                         {"cls": cls, "aadt": aadt}, VOCAB, RF)


def rail(rid, depth, tpd=2):
    return E.rail_record(rid, E.reduce_cells([depth], None, PROF["wet_min_depth_ft"]), {"tpd": tpd}, VOCAB, LF)


def run(preset, records, summary=None, mode="preset", methods=None):
    cfg = E.resolve(CAT, mode, preset, methods)
    return E.classify(CAT, cfg, records, summary or {"model_dimension": "2D", "hydraulics_source": "breach_model"},
                      prof=PROF)


class Cells(unittest.TestCase):
    def test_reduce(self):
        r = E.reduce_cells([0.0, 1.5, 3.0, float("nan")], [9.0, 2.0, 1.0, None], 0.0)
        self.assertEqual((r["depth_ground_ft"], r["velocity_fps"], r["dv_ft2s"]), (3.0, 2.0, 3.0))
        self.assertEqual(r["wet_cells"], 2)                       # a dry cell's velocity is never used
        dry = E.reduce_cells([0.0, None], None, 0.0)
        self.assertFalse(dry["wet"])
        self.assertTrue(E.reduce_cells([1.0], None, 0.0)["velocity_unknown"])

    def test_vocab(self):
        self.assertEqual(E.structure_type("RES1-1SNB", VOCAB), "home")
        self.assertEqual(E.structure_type("RES2", VOCAB), "mobile_home")
        self.assertEqual(E.structure_type("COM6", VOCAB), "hospital")
        self.assertEqual(E.structure_type("COM1", VOCAB), "commercial")
        self.assertEqual(E.structure_type("Mobile Home", VOCAB), "mobile_home")
        s = struct("s1", 1.0, occ="School")
        self.assertEqual((s["hazard_type"], s["structure_type"], s["habitable"]), ("school", "institution", True))
        self.assertFalse(struct("b1", 1.0, occ="barn")["habitable"])
        self.assertEqual(road("r", 1.0, cls="motorway")["road_class"], "interstate")

    def test_profile_from_catalog(self):
        g = CAT.hazard["general"]
        self.assertEqual(PROF["wet_min_depth_ft"], g["wet_min_depth_ft"])
        self.assertEqual(PROF["base_class"], g["base_class"])


class Classes(unittest.TestCase):
    def test_nd_interstate_high(self):
        res = run("ND", [struct("s1", 0.5), road("r1", 0.4, "interstate")])
        self.assertEqual(res["suggested_ordinal"], 3)
        self.assertIn("M8a", {h["method"] for h in res["driving"]})
        self.assertEqual(res["preset_id"], "ND")

    def test_nd_m2_is_1d_only(self):
        deep = [struct("s1", 4.0)]
        one_d = run("ND", deep, {"model_dimension": "1D", "hydraulics_source": "breach_model"})
        self.assertEqual(one_d["suggested_ordinal"], 3)                   # M2 > 2 ft at a home, 1D
        two_d = run("ND", deep, {"model_dimension": "2D", "hydraulics_source": "breach_model"})
        self.assertNotIn("M2", {h["method"] for h in two_d["hits"]})
        self.assertTrue(any(f["code"] == "missing_input" and f.get("method") == "M1" for f in two_d["flags"]))

    def test_usbr_alias_and_nebraska_rail(self):
        self.assertEqual(run("USBR_TM11", [struct("s1", 1.0)])["preset_id"], "USBR")
        res = run("NE", [rail("k1", 2.5, tpd=8)])
        self.assertEqual(res["suggested_ordinal"], 3)                    # M9b main line >= depth
        self.assertIn("M9b", {h["method"] for h in res["driving"]})

    def test_same_receptors_differ_by_preset(self):
        recs = [road("r1", 0.3, "local", aadt=1200)]
        self.assertEqual(run("ND", recs)["suggested_ordinal"], 2)        # M8a AADT band
        self.assertNotEqual(run("FEMA333", recs)["suggested_ordinal"], 2)

    def test_dry_gives_base_class(self):
        res = run("ND", [struct("s1", 0.0), road("r1", 0.0, "interstate")])
        self.assertTrue(res["base_class_applied"])
        self.assertEqual(res["suggested_ordinal"], PROF["base_class"])

    def test_custom_mode_and_not_screened(self):
        res = run("", [road("r1", 1.0, "interstate")], mode="custom", methods=["M8a", "M12b"])
        self.assertEqual(res["mode"], "custom")
        self.assertEqual(res["suggested_ordinal"], 3)
        self.assertIn("M12b", res["not_screened"])
        md = E.summary_markdown(res, [], {"mode": "custom"}, {"depth": "d.tif"})
        self.assertIn("Suggested class", md)
        self.assertIn("M12b", md)


class NoThresholdsInCode(unittest.TestCase):
    def test_engine_has_no_jurisdiction_numbers(self):
        with open(os.path.join(ROOT, "damit_hazardlite", "engine.py"), encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(ln.split("#")[0] for ln in src.splitlines() if not ln.strip().startswith(('"', "'")))
        nums = set(re.findall(r"(?<![\w.])\d+\.?\d*(?![\w.])", code))
        self.assertTrue(nums <= {"0", "1", "4", "8", "0.0", "3.280839895", "12"}, nums)
        for word in ("REG_05", "North Dakota", "TM-11", "2000", "500"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
