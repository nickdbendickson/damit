"""DamIT Catalog: Appendix A content, preset bundles, data-driven thresholds and combination logic."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from damit_catalog import catalog as C        # noqa: E402
from damit_catalog import evaluate as E       # noqa: E402

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS = ["M1", "M2", "M3", "M4a", "M4b", "M4c", "M5", "M6", "M7", "M8a", "M8b", "M8c", "M8d", "M8e", "M8f",
           "M8g", "M9a", "M9b", "M9c", "M10a", "M10b", "M11a", "M11b", "M11c", "M12a", "M12b", "M12c", "M12d", "M13"]
PRESETS = ["FEMA333", "USBR", "BIA", "NRCS", "ND", "NE", "NY", "VA", "TX", "ID", "CO", "RI", "AZ", "CA", "AK",
           "AL", "NC", "USACE", "TVA"]   # Appendix A.6 (15) + the Nov 2026 Summaries (AL, NC, USACE, TVA)


def home(depth, **kw):
    r = {"id": kw.pop("id", "h1"), "receptor_type": "structure", "structure_type": "home", "habitable": True,
         "depth_ground_ft": depth}
    r.update(kw)
    return r


class CatalogContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop(C.ENV_DIR, None)
        cls.cat = C.load()

    def test_ids(self):
        self.assertEqual(self.cat.method_ids(), METHODS)
        self.assertEqual(self.cat.scenario_ids(), ["S1", "S2", "S3", "S4", "S5", "S6", "S7"])
        self.assertEqual(self.cat.cutoff_ids(), ["D1", "D2"])
        self.assertEqual(self.cat.modifier_ids(), ["R{}".format(i) for i in range(1, 11)])
        self.assertEqual(sorted(self.cat.preset_ids()), sorted(PRESETS))
        self.assertEqual(self.cat.labels["ordinals"], {"0": "Minimal", "1": "Low", "2": "Significant",
                                                       "3": "High", "4": "Extremely High"})

    def test_method_records_complete(self):
        for mid, m in self.cat.methods.items():
            for k in ("name", "inputs", "params", "returns", "strength", "source", "verification"):
                self.assertIn(k, m, mid)
            self.assertIn(m["strength"], ("rule", "advisory"), mid)
        self.assertEqual(self.cat.methods["M4a"]["strength"], "advisory")
        self.assertEqual(self.cat.methods["M2"]["params"], {"depth_ft": 2.0, "comparator": ">", "datum": "ground",
                                                            "only_if_1d": False, "structure_types": [
                                                                "home", "mobile_home", "institution",
                                                                "commercial_industrial", "campground"]})
        self.assertEqual(self.cat.methods["M8a"]["params"], {"low_below_aadt": 500, "high_above_aadt": 2000})
        self.assertEqual(self.cat.domain_cutoffs["D1"]["incremental_rise_ft"], 2.0)
        self.assertEqual(self.cat.domain_cutoffs["D2"]["convergence_ft"], 1.0)
        self.assertEqual(self.cat.modifiers["R8"]["params"]["storage_acft_limit"], 200)

    def test_nd_bundle_matches_document(self):
        nd = self.cat.presets["ND"]
        self.assertEqual(nd["label"], "North Dakota (REG_05.2026)")
        self.assertEqual(nd["scenarios"], ["S3", "S7"])
        self.assertEqual(set(nd["methods"]), {"M1", "M2", "M6", "M8a", "M8b", "M9a", "M11a"})
        self.assertEqual(nd["methods"]["M1"], {"charts": ["houses_on_foundations", "mobile_homes"], "require_2d": True})
        self.assertTrue(nd["methods"]["M2"]["only_if_1d"])
        self.assertEqual(nd["methods"]["M6"], {"strength": "advisory"})
        self.assertEqual(nd["modifiers"], ["R2", "R3", "R4", "R5", "R7", "R8", "R9"])
        self.assertEqual(nd["labels"], ["Low", "Medium", "High"])
        cfg = self.cat.resolve_preset("ND")
        self.assertEqual(cfg["methods"]["M6"]["strength"], "advisory")
        self.assertEqual({r["id"]: r["strength"] for r in cfg["modifiers"]}["R4"], "advisory")
        self.assertEqual(cfg["methods"]["M2"]["params"]["depth_ft"], 2.0)
        self.assertEqual(cfg["flags"], [])

    def test_fema_and_usbr_bundles(self):
        f = self.cat.resolve_preset("FEMA333")
        self.assertEqual([s["id"] for s in f["scenarios"]], ["S1"])
        self.assertEqual(set(f["methods"]), {"M5", "M13"})
        self.assertEqual(f["methods"]["M5"]["params"]["high_min"], 1)
        self.assertIsNone(f["methods"]["M5"]["params"]["sig_min"])
        self.assertEqual([r["id"] for r in f["modifiers"]], ["R1", "R3"])
        self.assertEqual(f["labels"], ["Low", "Significant", "High"])
        u = self.cat.resolve_preset("USBR_TM11")
        self.assertEqual(u["preset_label"], "USBR (ACER TM-11)")
        self.assertEqual([s["id"] for s in u["scenarios"]], ["S1"])
        self.assertEqual([(c["id"], c["when"], c.get("verification")) for c in u["conditional_scenarios"]],
                         [("S5", "borderline dams", None)])      # Summaries F-3 states it without a mark
        self.assertEqual(len(u["methods"]["M1"]["params"]["charts"]), 5)
        self.assertEqual((u["methods"]["M5"]["params"]["sig_min"], u["methods"]["M5"]["params"]["high_min"]), (1, 7))
        self.assertEqual([r["id"] for r in u["modifiers"]], ["R1"])
        self.assertTrue(any(fl["code"] == "conditional_scenario" for fl in u["flags"]))
        self.assertFalse(any(fl["code"] == "unverified_or_secondary" for fl in u["flags"]))

    def test_all_presets_resolve(self):
        expect = {"FEMA333": (["S1"], {"M5", "M13"}), "BIA": ([], {"M5"}), "NRCS": ([], {"M13"}),
                  "NE": (["S4"], {"M3", "M4a", "M8c", "M9b", "M11b", "M12a"}),
                  "NY": (["S1", "S5"], {"M1", "M4b", "M5", "M8d", "M8f", "M9c", "M10a", "M11c", "M12b"}),
                  "VA": (["S1", "S5"], {"M13", "M8e", "M5"}), "TX": ([], {"M4c", "M13"}), "ID": ([], {"M2", "M6"}),
                  "CO": (["S2"], {"M5", "M6"}), "RI": (["S6"], {"M13", "M8g"}), "AZ": ([], {"M13", "M12d"}),
                  "CA": ([], {"M5", "M7"}), "AK": ([], {"M5", "M12c", "M13"}),
                  "AL": ([], {"M5", "M13"}), "NC": ([], {"M5", "M13"}), "USACE": ([], {"M5", "M13"}),
                  "TVA": ([], {"M5", "M13"})}
        for pid in PRESETS:
            cfg = self.cat.resolve_preset(pid)
            if pid in expect:
                self.assertEqual([s["id"] for s in cfg["scenarios"]], expect[pid][0], pid)
                self.assertEqual(set(cfg["methods"]), expect[pid][1], pid)
            if not cfg["scenarios"]:
                self.assertTrue(any(f["code"] == "scenario_unconfirmed" for f in cfg["flags"]), pid)
        self.assertEqual(self.cat.resolve_preset("NY")["label_map"], {"1": "Class A", "2": "Class B", "3": "Class C"})
        self.assertEqual([d["id"] for d in self.cat.resolve_preset("NY")["domain_cutoffs"]], ["D1"])
        self.assertEqual([d["id"] for d in self.cat.resolve_preset("VA")["domain_cutoffs"]], ["D2"])
        self.assertEqual(self.cat.resolve_preset("CA")["label_map"]["4"], "Extremely High")
        self.assertEqual(self.cat.resolve_preset("AK")["labels"], ["Class III", "Class II", "Class I"])
        self.assertEqual(self.cat.resolve_preset("BIA")["methods"]["M5"]["verification"], "secondary")

    def test_no_thresholds_in_python(self):
        for name in ("catalog.py", "evaluate.py", "handoff.py"):
            with open(os.path.join(PKG, name), encoding="utf-8") as fh:
                src = fh.read()
            for num in ("3.5", "2000", "500", "1000", "200", "400"):
                self.assertIsNone(re.search(r"(?<![\w.]){}(?![\w.])".format(re.escape(num)), src),
                                  "{} hardcodes {}".format(name, num))


class PresetAliases(unittest.TestCase):
    """USBR and USBR_TM11 are one preset: stored as USBR, USBR_TM11 accepted everywhere."""

    @classmethod
    def setUpClass(cls):
        os.environ.pop(C.ENV_DIR, None)
        cls.cat = C.load()

    def test_both_ids_resolve_to_one_preset(self):
        self.assertIn("USBR", self.cat.presets)
        self.assertNotIn("USBR_TM11", self.cat.presets)
        self.assertEqual(self.cat.preset_aliases, {"USBR_TM11": "USBR"})
        for pid in ("USBR", "USBR_TM11"):
            self.assertTrue(self.cat.has_preset(pid))
            self.assertEqual(self.cat.canonical_preset_id(pid), "USBR")
            self.assertIs(self.cat.preset(pid), self.cat.presets["USBR"])
        a, b = self.cat.resolve_preset("USBR"), self.cat.resolve_preset("USBR_TM11")
        self.assertEqual((a["preset_id"], b["preset_id"]), ("USBR", "USBR"))
        self.assertEqual((a["requested_preset_id"], b["requested_preset_id"]), ("USBR", "USBR_TM11"))
        a.pop("requested_preset_id"), b.pop("requested_preset_id")
        self.assertEqual(a, b)
        self.assertEqual(a["preset_label"], "USBR (ACER TM-11)")

    def test_unknown_preset_lists_aliases(self):
        self.assertIsNone(self.cat.canonical_preset_id("USBR_TM12"))
        with self.assertRaises(C.CatalogError) as cm:
            self.cat.resolve_preset("USBR_TM12")
        self.assertIn("USBR_TM11 = USBR", str(cm.exception))

    def test_handoff_accepts_either_id(self):
        from damit_catalog import handoff as HO
        for pid in ("USBR", "USBR_TM11"):
            pkg = {"mode": "preset", "preset_id": pid, "scenarios": [], "modifiers": [], "domain_cutoffs": []}
            self.assertNotIn("unknown preset {}".format(pid), HO.validate(pkg, self.cat))
        pkg = {"mode": "preset", "preset_id": "USBR_TM12", "scenarios": [], "modifiers": [], "domain_cutoffs": []}
        self.assertIn("unknown preset USBR_TM12", HO.validate(pkg, self.cat))

    def test_evaluation_identical(self):
        for lives, want in ((3, 2), (7, 3)):
            got = [E.evaluate(self.cat, self.cat.resolve_preset(pid), [],
                              {"lives_in_jeopardy": lives, "model_dimension": "2D"})["suggested_ordinal"]
                   for pid in ("USBR", "USBR_TM11")]
            self.assertEqual(got, [want, want])

    def test_hazard_profile_loaded_and_hashed(self):
        self.assertEqual(self.cat.hazard.get("schema"), "damit.catalog.hazard")
        self.assertTrue(self.cat.hazard.get("presets"))


class DataDriven(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_cat_")
        self.dir = os.path.join(self.tmp, "data")
        shutil.copytree(os.path.join(PKG, "data"), self.dir)

    def tearDown(self):
        os.environ.pop(C.ENV_DIR, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _edit(self, name, fn):
        p = os.path.join(self.dir, name)
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        fn(d)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)

    def test_threshold_change_without_code_release(self):
        recs = [home(2.5)]
        summ = {"model_dimension": "1D", "hydraulics_source": "breach_model"}
        base = C.load()
        r0 = E.evaluate(base, base.resolve_preset("ND"), recs, summ)
        self.assertEqual(r0["suggested_label"], "High")
        self._edit("presets.json", lambda d: d["presets"]["ND"]["methods"]["M2"].update(depth_ft=3.0))
        self._edit("presets.json", lambda d: d["presets"]["ND"]["label_map"].update({"3": "High (edited)"}))
        os.environ[C.ENV_DIR] = self.dir
        cat = C.load()
        self.assertNotEqual(cat.digest, base.digest)
        r1 = E.evaluate(cat, cat.resolve_preset("ND"), recs, summ)
        self.assertNotEqual(r1["suggested_ordinal"], 3)
        r2 = E.evaluate(cat, cat.resolve_preset("ND"), [home(3.2)], summ)
        self.assertEqual(r2["suggested_label"], "High (edited)")

    def test_dash_falls_back_to_m13(self):
        self._edit("presets.json", lambda d: d["presets"].__setitem__("ZZ", {
            "label": "Synthetic dash", "scenarios": [], "methods": {}, "modifiers": [], "labels": ["Low"],
            "label_map": {"1": "Low"}}))
        cat = C.load(self.dir)
        cfg = cat.resolve_preset("ZZ")
        self.assertEqual(list(cfg["methods"]), ["M13"])
        codes = [f["code"] for f in cfg["flags"]]
        self.assertIn("method_fallback_m13", codes)
        self.assertIn("scenario_unconfirmed", codes)

    def test_bad_alias_rejected(self):
        self._edit("presets.json", lambda d: d["aliases"].update({"ND_OLD": "NOPE"}))
        with self.assertRaises(C.CatalogError):
            C.load(self.dir)

    def test_alias_may_not_shadow_a_preset(self):
        self._edit("presets.json", lambda d: d["aliases"].update({"ND": "USBR"}))
        with self.assertRaises(C.CatalogError):
            C.load(self.dir)

    def test_hazard_profile_optional(self):
        self._edit("catalog.json", lambda d: d["files"].pop("hazard"))
        cat = C.load(self.dir)
        self.assertEqual(cat.hazard, {})
        self.assertEqual(cat.resolve_preset("USBR_TM11")["preset_id"], "USBR")

    def test_invalid_catalog_rejected(self):
        self._edit("presets.json", lambda d: d["presets"]["ND"]["methods"].__setitem__("M99", {}))
        with self.assertRaises(C.CatalogError):
            C.load(self.dir)



def inst(found, floor, dv=1.0, ground=None, **kw):
    """An institution with depths at its foundation ground line and its lowest occupied floor."""
    r = {"id": kw.pop("id", "s"), "receptor_type": "structure", "structure_type": "institution", "habitable": True,
         "depth_ground_ft": found if ground is None else ground, "depth_foundation_ft": found,
         "depth_floor_ft": floor, "dv_ft2s": dv}
    r.update(kw)
    return r


class AcceptedRecommendations(unittest.TestCase):
    """Nick's decisions on PR #5's open questions (catalog 2026.11.09.3): USBR M1 marks lives and M5 sets
    the class; M3 institutions split Significant / Low at the foundation and test High at the floor;
    preset status (NRCS unverified, NY draft) lives in presets.json; NY R2 / R8 variants are catalog data."""

    @classmethod
    def setUpClass(cls):
        os.environ.pop(C.ENV_DIR, None)
        cls.cat = C.load()

    def _m(self, r, mid):
        return [h for h in r["hits"] if h["method"] == mid]

    def test_usbr_m1_does_not_assign_high_alone(self):
        self.assertEqual(self.cat.presets["USBR"]["methods"]["M1"]["class_zones"], [])
        cfg = self.cat.resolve_preset("USBR")
        self.assertEqual(cfg["methods"]["M1"]["params"]["class_zones"], [])
        summ = {"model_dimension": "2D"}
        for n, want in ((1, 2), (6, 2), (7, 3), (12, 3)):
            r = E.evaluate(self.cat, cfg, [home(6.5, m1_zone="high_danger", occupants=n)], summ)
            self.assertEqual(r["suggested_ordinal"], want, n)
            self.assertEqual(self._m(r, "M1"), [], n)            # M1 returns no class
            self.assertEqual([h["method"] for h in r["driving"]], ["M5"], n)
        # lives spread over several high-danger structures are summed by M5
        recs = [home(6.5, id="a", m1_zone="high_danger", occupants=4), home(6.5, id="b", m1_zone="high_danger",
                                                                           occupants=3)]
        self.assertEqual(E.evaluate(self.cat, cfg, recs, summ)["suggested_ordinal"], 3)
        # judgment zone: still flagged, not counted
        r = E.evaluate(self.cat, cfg, [home(4.0, m1_zone="judgment", occupants=9)], summ)
        self.assertIn("m1_judgment_zone", [f["code"] for f in r["flags"]])
        self.assertIsNone(r["suggested_ordinal"])

    def test_m1_still_assigns_high_where_the_preset_says_so(self):
        for pid in ("ND",):
            r = E.evaluate(self.cat, self.cat.resolve_preset(pid), [home(6.5, m1_zone="high_danger")],
                           {"model_dimension": "2D", "hydraulics_source": "breach_model"})
            self.assertEqual(r["suggested_ordinal"], 3, pid)
            self.assertEqual(self._m(r, "M1")[0]["class"], 3, pid)
        cfg = self.cat.resolve_custom(["M1"], ["S1"])            # catalog default: high_danger returns High
        r = E.evaluate(self.cat, cfg, [home(6.5, m1_zone="high_danger")], {"model_dimension": "2D"})
        self.assertEqual(r["suggested_ordinal"], 3)

    def test_m3_institution_datums(self):
        m3 = self.cat.methods["M3"]
        rules = {r["label"]: json.dumps(r["when"]) for r in m3["receptor_rules"]}
        self.assertIn("depth_floor_ft", rules["institution High"])
        self.assertNotIn("depth_foundation_ft", rules["institution High"])
        self.assertIn("depth_foundation_ft", rules["institution Significant"])
        self.assertNotIn("depth_floor_ft", rules["institution Significant"])
        self.assertEqual((m3["params"]["institution_high_depth_ft"], m3["params"]["institution_high_dv"]), (2.0, 15))
        cfg = self.cat.resolve_preset("NE")

        def cls(found, floor, dv=1.0, ground=None):
            r = E.evaluate(self.cat, cfg, [inst(found, floor, dv, ground)], {})
            return max([h["class"] for h in self._m(r, "M3")] or [None])
        self.assertEqual(cls(1.0, -0.5), 2)      # water above the foundation, below the floor: Significant
        self.assertEqual(cls(0.0, -1.5, ground=0.3), 1)   # wet ground, at the foundation line: Low
        self.assertEqual(cls(3.0, 1.9), 2)       # 3 ft at the foundation but under 2 ft at the floor: not High
        self.assertEqual(cls(3.5, 2.0), 3)       # 2 ft at the floor: High
        self.assertEqual(cls(0.5, -1.0, dv=15), 3)
        r = E.evaluate(self.cat, self.cat.resolve_custom(["M10b"], ["S1"]), [inst(3.0, 1.9)], {})
        self.assertEqual(r["suggested_ordinal"], 2)               # M10b reads the same datums

    def test_preset_status_is_catalog_data(self):
        self.assertEqual(self.cat.presets["NRCS"]["status"], "unverified")
        self.assertEqual(self.cat.presets["NY"]["status"], "draft")
        self.assertEqual(self.cat.preset_status("NRCS"), "unverified")
        self.assertIsNone(self.cat.preset_status("ND"))
        for pid in ("NRCS", "NY"):
            cfg = self.cat.resolve_preset(pid)
            self.assertEqual(cfg["status"], self.cat.presets[pid]["status"])
            self.assertIn("preset_status", [f["code"] for f in cfg["flags"]], pid)
        self.assertNotIn("preset_status", [f["code"] for f in self.cat.resolve_preset("ND")["flags"]])
        with open(os.path.join(PKG, "data", "catalog.json"), encoding="utf-8") as fh:
            self.assertIn("preset_status", json.load(fh)["validation_flags"])
        # methods stay as documented: Hazard's old method-level draft / unverified marks are not restored
        marked = {mid: m["verification"] for mid, m in self.cat.methods.items() if m["verification"] != "as_documented"}
        self.assertEqual(marked, {})

    def test_ny_r2_floor_presumption_and_r8_lowering(self):
        self.assertFalse(self.cat.modifiers["R2"]["params"]["floor_presumption"])
        self.assertEqual(self.cat.modifiers["R8"]["params"]["variant"], "storage_limit")
        ny = self.cat.resolve_preset("NY")
        mods = {m["id"]: m for m in ny["modifiers"]}
        self.assertTrue(mods["R2"]["params"]["floor_presumption"])
        self.assertEqual(mods["R8"]["params"]["variant"], "lowering_from_high")
        nd = {m["id"]: m for m in self.cat.resolve_preset("ND")["modifiers"]}
        self.assertFalse(nd["R2"]["params"]["floor_presumption"])
        rec = dict(home(0.5), m1_zone="low_danger")
        r = E.evaluate(self.cat, ny, [rec], {"model_dimension": "2D"})
        self.assertIn("r2_presumption", [f["code"] for f in r["flags"]])
        cfg = self.cat.resolve_custom(["M4b"], ["S1"], ["R2"])
        r = E.evaluate(self.cat, cfg, [rec], {"model_dimension": "2D"})
        self.assertNotIn("r2_presumption", [f["code"] for f in r["flags"]])
        # R8, New York: a High dam is not lowered without TM-11 unsteady modeling
        for cur in (3, "Class C", "High"):
            r = E.evaluate(self.cat, ny, [rec], {"model_dimension": "2D", "current_class": cur,
                                                 "analysis": "breach_model"})
            self.assertEqual(r["suggested_ordinal"], 3, cur)
            self.assertIn("R8", [m["id"] for m in r["modifiers_applied"]])
        r = E.evaluate(self.cat, ny, [rec], {"model_dimension": "2D", "current_class": 3, "analysis": "unsteady_tm11"})
        self.assertNotEqual(r["suggested_ordinal"], 3)
        r = E.evaluate(self.cat, ny, [rec], {"model_dimension": "2D", "current_class": 1, "hydraulics_source":
                                             "simplified", "storage_acft": 900})
        self.assertNotEqual(r["suggested_ordinal"], 3)            # NY has no storage-limit variant


class StatusDataDriven(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_cat_st_")
        self.dir = os.path.join(self.tmp, "data")
        shutil.copytree(os.path.join(PKG, "data"), self.dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _edit(self, fn):
        p = os.path.join(self.dir, "presets.json")
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        fn(d)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)

    def test_status_read_from_data(self):
        def edit(d):
            d["presets"]["ND"]["status"] = "draft"
            d["presets"]["NY"].pop("status")
        self._edit(edit)
        cat = C.load(self.dir)
        self.assertEqual(cat.resolve_preset("ND")["status"], "draft")
        self.assertIsNone(cat.resolve_preset("NY")["status"])
        self.assertNotIn("preset_status", [f["code"] for f in cat.resolve_preset("NY")["flags"]])

    def test_unknown_status_rejected(self):
        self._edit(lambda d: d["presets"]["ND"].__setitem__("status", "rumoured"))
        with self.assertRaises(C.CatalogError):
            C.load(self.dir)

class Combination(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop(C.ENV_DIR, None)
        cls.cat = C.load()

    def test_most_severe_scenario_governs(self):
        cfg = self.cat.resolve_preset("ND")
        recs = [home(0.5, id="a", scenario="S3", sole_access=False),
                {"id": "r", "receptor_type": "road", "road_class": "interstate", "aadt": 30000, "depth_ground_ft": 1,
                 "sole_access": False, "scenario": "S7"}]
        r = E.evaluate(self.cat, cfg, recs, {"model_dimension": "1D", "hydraulics_source": "breach_model"})
        self.assertEqual(r["per_scenario"], {"S3": None, "S7": 3})
        self.assertEqual(r["suggested_label"], "High")
        self.assertEqual([(h["method"], h["receptor"], h["scenario"]) for h in r["driving"]], [("M8a", "r", "S7")])

    def test_advisory_reported_not_applied_unless_opted_in(self):
        cfg = self.cat.resolve_preset("ND")
        recs = [home(0.5)]
        summ = {"model_dimension": "1D", "hydraulics_source": "breach_model"}
        r = E.evaluate(self.cat, cfg, recs, summ)
        self.assertIsNone(r["suggested_ordinal"])
        self.assertTrue(any(h["method"] == "M6" and h["strength"] == "advisory" for h in r["advisories"]))
        self.assertIn("advisory_only_hit", [f["code"] for f in r["flags"]])
        r2 = E.evaluate(self.cat, cfg, recs, summ, apply_advisories=True)
        self.assertEqual(r2["suggested_label"], "Medium")

    def test_m1_blocked_on_1d_and_judgment_flag(self):
        cfg = self.cat.resolve_preset("ND")
        r = E.evaluate(self.cat, cfg, [home(1.0, m1_zone="judgment")], {"model_dimension": "1D",
                                                                       "hydraulics_source": "breach_model"})
        self.assertIn("one_d_run_with_2d_only_method", [f["code"] for f in r["flags"]])
        r = E.evaluate(self.cat, cfg, [home(1.0, m1_zone="judgment")], {"model_dimension": "2D",
                                                                       "hydraulics_source": "breach_model"})
        self.assertIn("m1_judgment_zone", [f["code"] for f in r["flags"]])
        r = E.evaluate(self.cat, cfg, [home(1.0, m1_zone="high_danger")], {"model_dimension": "2D",
                                                                          "hydraulics_source": "breach_model"})
        self.assertEqual(r["suggested_label"], "High")
        self.assertEqual(r["driving"][0]["method"], "M1")

    def test_missing_inputs_flagged_not_passed(self):
        cfg = self.cat.resolve_preset("NE")
        r = E.evaluate(self.cat, cfg, [{"id": "s", "receptor_type": "structure", "structure_type": "institution",
                                        "habitable": True, "depth_ground_ft": 1.0}], {})
        miss = [f for f in r["flags"] if f["code"] == "missing_input"]
        self.assertTrue(any(f["method"] == "M3" for f in miss), miss)
        self.assertEqual(r["suggested_ordinal"], 1)     # the Low row still applies; the gap is flagged

    def test_r8_simplified_analysis(self):
        cfg = self.cat.resolve_preset("ND")
        r = E.evaluate(self.cat, cfg, [], {"hydraulics_source": "simplified", "storage_acft": 250})
        self.assertEqual(r["suggested_label"], "High")
        self.assertIn("R8", [m["id"] for m in r["modifiers_applied"]])

    def test_m3_matrix_and_m5_bands(self):
        cfg = self.cat.resolve_preset("NE")
        rec = {"id": "c", "receptor_type": "structure", "structure_type": "commercial_industrial", "habitable": True,
               "depth_ground_ft": 2, "depth_foundation_ft": 1.5, "dv_ft2s": 5}
        r = E.evaluate(self.cat, cfg, [rec], {})
        self.assertEqual(r["suggested_label"], "Significant")
        u = self.cat.resolve_preset("USBR_TM11")
        self.assertEqual(E.evaluate(self.cat, u, [], {"lives_in_jeopardy": 3, "model_dimension": "2D"})["suggested_ordinal"], 2)
        self.assertEqual(E.evaluate(self.cat, u, [], {"lives_in_jeopardy": 7, "model_dimension": "2D"})["suggested_ordinal"], 3)
        f = self.cat.resolve_preset("FEMA333")
        self.assertEqual(E.evaluate(self.cat, f, [], {"lives_in_jeopardy": 1})["suggested_ordinal"], 3)

    def test_m8a_band_edges(self):
        cfg = self.cat.resolve_custom(["M8a"], ["S1"])
        road = lambda a: {"id": "r", "receptor_type": "road", "road_class": "other_public", "aadt": a, "impacted": True}  # noqa
        self.assertEqual(E.evaluate(self.cat, cfg, [road(499)], {})["suggested_ordinal"], 1)
        self.assertEqual(E.evaluate(self.cat, cfg, [road(500)], {})["suggested_ordinal"], 2)
        self.assertEqual(E.evaluate(self.cat, cfg, [road(2000)], {})["suggested_ordinal"], 2)
        self.assertEqual(E.evaluate(self.cat, cfg, [road(2001)], {})["suggested_ordinal"], 3)

    def test_custom_mode_unbranded(self):
        cfg = self.cat.resolve_custom(["M2", "M8a"], ["S1"], ["R7"], ["D1"], {"M2": {"depth_ft": 3.0}})
        self.assertEqual(cfg["mode"], "custom")
        self.assertIsNone(cfg["preset_id"])
        self.assertEqual(cfg["preset_label"], "Custom")
        for m in cfg["methods"].values():
            self.assertNotIn("source", m)
        for x in cfg["scenarios"] + cfg["modifiers"] + cfg["domain_cutoffs"]:
            self.assertNotIn("source", x)
        self.assertEqual(cfg["methods"]["M2"]["params"]["depth_ft"], 3.0)
        self.assertEqual(cfg["labels"], ["Minimal", "Low", "Significant", "High", "Extremely High"])
        r = E.evaluate(self.cat, cfg, [home(3.5)], {})
        self.assertEqual(r["suggested_label"], "High")
        self.assertTrue(r["citations"]["M2"])          # citations stay in the run report

    def test_label_clamp(self):
        cfg = self.cat.resolve_preset("ND")
        self.assertEqual(E.label_for(cfg, 0), "Low")
        self.assertEqual(E.label_for(cfg, 4), "High")
        self.assertEqual(E.label_for(cfg, None), "Not determined")


class Nov2026Summaries(unittest.TestCase):
    """Catalog 2026.11.09.4 follows the two attached documents: the Corrected Edition (Appendix A, unchanged)
    and the In-Depth Summaries (Nov. 2026): new AL / NC / USACE / TVA presets, Summaries corrections, and the
    agencies with no preset documented. Nick's M1 / M3 / status decisions stay as they were."""

    @classmethod
    def setUpClass(cls):
        os.environ.pop(C.ENV_DIR, None)
        cls.cat = C.load()

    def ev(self, pid, recs, summ=None):
        return E.evaluate(self.cat, self.cat.resolve_preset(pid), recs, summ or {})

    def feat(self, kind, rid="f1"):
        return {"id": rid, "receptor_type": "feature", "feature_kind": kind}

    def test_sources_recorded(self):
        self.assertEqual(self.cat.version, "2026.11.09.4")
        self.assertIn("Corrected Edition", self.cat.source["title"])
        sup = self.cat.source["supplements"]
        self.assertEqual(len(sup), 1)
        self.assertIn("In-Depth Summaries", sup[0]["title"])
        self.assertEqual((sup[0]["date"], sup[0]["printed"]), ("2026-11", "2026-11-09"))

    def test_new_presets_are_thin_fema_style_and_flagged(self):
        for pid, labels in (("AL", ["Low", "Significant", "High"]), ("NC", ["Class A", "Class B", "Class C"]),
                            ("USACE", ["Low", "Significant", "High"]), ("TVA", ["Low", "Significant", "High"])):
            cfg = self.cat.resolve_preset(pid)
            self.assertEqual(cfg["labels"], labels, pid)
            self.assertEqual(set(cfg["methods"]), {"M5", "M13"}, pid)
            self.assertEqual((cfg["methods"]["M5"]["params"]["sig_min"], cfg["methods"]["M5"]["params"]["high_min"]),
                             (None, 1), pid)
            codes = [f["code"] for f in cfg["flags"]]
            self.assertIn("method_fallback_m13", codes, pid)       # no jurisdiction-specific criteria in the sources
            self.assertIn("scenario_unconfirmed", codes, pid)
            self.assertEqual(cfg["scenarios"], [], pid)
            self.assertEqual(cfg["modifiers"], [], pid)
            self.assertIsNone(cfg["status"], pid)
        self.assertEqual(self.cat.resolve_preset("USACE")["methods"]["M5"]["verification"], "secondary")
        al = self.cat.presets["AL"]["notes"]
        for words in ("voluntary", "October 1, 2026", "AEMA", "secondary"):
            self.assertIn(words, al)
        self.assertIn("exemption", self.cat.presets["NC"]["notes"])
        self.assertIn(".0102", self.cat.presets["NC"]["citation"])

    def test_new_presets_classify(self):
        self.assertEqual(self.ev("AL", [], {"lives_in_jeopardy": 1})["suggested_label"], "High")
        self.assertEqual(self.ev("NC", [], {"lives_in_jeopardy": 2})["suggested_label"], "Class C")
        self.assertEqual(self.ev("NC", [self.feat("isolated_home")], {"lives_in_jeopardy": 0})["suggested_label"],
                         "Class B")
        self.assertEqual(self.ev("TVA", [self.feat("farm_building")], {"lives_in_jeopardy": 0})["suggested_label"],
                         "Low")
        self.assertEqual(self.ev("USACE", [], {"lives_in_jeopardy": 1})["suggested_ordinal"], 3)

    def test_state_postal_codes_pick_the_new_presets(self):
        self.assertEqual(self.cat.canonical_preset_id("AL"), "AL")
        self.assertEqual(self.cat.canonical_preset_id("NC"), "NC")

    def test_agencies_without_a_preset_are_documented(self):
        with open(os.path.join(PKG, "data", "presets.json"), encoding="utf-8") as fh:
            nop = json.load(fh)["no_preset"]
        self.assertEqual(set(nop), {"FERC", "USFWS", "MSHA", "OTHER_STATES"})
        for k, why in nop.items():
            self.assertFalse(self.cat.has_preset(k), k)
            self.assertIn("Summaries", why, k)

    def test_texas_economic_loss_half(self):
        cfg = self.cat.resolve_preset("TX")
        self.assertEqual(cfg["methods"]["M13"]["params"]["variant"], "texas_30TAC299.14")
        self.assertEqual(self.ev("TX", [self.feat("secondary_highway")])["suggested_ordinal"], 2)
        self.assertEqual(self.ev("TX", [self.feat("public_utility_interruption")])["suggested_ordinal"], 2)
        self.assertEqual(self.ev("TX", [self.feat("excessive_economic_loss_urban")])["suggested_ordinal"], 3)
        # M4c bands unchanged: 1-6 lives / 1-2 habitable structures Significant; 7+ / 3+ High
        self.assertEqual(self.ev("TX", [home(1.0, occupants=6)])["suggested_ordinal"], 2)
        self.assertEqual(self.ev("TX", [home(1.0, occupants=7)])["suggested_ordinal"], 3)
        recs = [home(1.0, id="h{}".format(i), occupants=1) for i in range(3)]
        self.assertEqual(self.ev("TX", recs)["suggested_ordinal"], 3)

    def test_alaska_current_wording(self):
        ak = self.cat.presets["AK"]
        self.assertEqual(ak["methods"]["M13"]["variant"], "alaska_11AAC93.157")
        self.assertIn("anadromous", ak["notes"])
        self.assertIn("superseded", ak["notes"])
        self.assertIn("Oct. 2, 2004", ak["citation"])
        for name in ("presets.json", "methods.json", "hazard.json"):
            with open(os.path.join(PKG, "data", name), encoding="utf-8") as fh:
                d = json.load(fh)
            # the superseded 'salmon spawning habitat' wording is never a rule, only named as superseded
            for pid, p in (d.get("presets") or {}).items():
                for k, v in p.items():
                    if isinstance(v, str) and "salmon" in v.lower():
                        self.assertIn("superseded", v, (name, pid, k))
        self.assertEqual(self.ev("AK", [self.feat("high_value_property")])["suggested_label"], "Class II")
        self.assertEqual(self.ev("AK", [self.feat("secondary_road")])["suggested_label"], "Class III")
        r = self.ev("AK", [{"id": "e", "receptor_type": "environment", "anadromous_waters_damage": True}])
        self.assertEqual(r["suggested_label"], "Class II")
        self.assertEqual(self.ev("AK", [], {"probable_loss_of_life": True})["suggested_label"], "Class I")

    def test_new_york_single_life(self):
        self.assertEqual(self.cat.presets["NY"]["methods"]["M5"], {"sig_min": None, "high_min": 1})
        self.assertEqual(self.ev("NY", [], {"lives_in_jeopardy": 1})["suggested_label"], "Class C")
        self.assertEqual(self.cat.preset_status("NY"), "draft")

    def test_nick_decisions_kept(self):
        u = self.cat.presets["USBR"]["methods"]
        self.assertEqual(u["M1"]["class_zones"], [])
        self.assertEqual((u["M5"]["sig_min"], u["M5"]["high_min"]), (1, 7))
        self.assertEqual(self.cat.preset_status("NRCS"), "unverified")       # kept: see status_review
        self.assertIn("Summaries", self.cat.presets["NRCS"]["status_review"])
        rules = {r["label"]: json.dumps(r["when"]) for r in self.cat.methods["M3"]["receptor_rules"]}
        self.assertIn("depth_floor_ft", rules["institution High"])
        self.assertIn("depth_foundation_ft", rules["institution Significant"])

    def test_superseded_and_corrected_notes(self):
        hz = self.cat.hazard["presets"]
        self.assertIn("superseded", hz["VA"]["notes"])
        self.assertNotIn("(unverified)", hz["VA"]["notes"])
        self.assertIn("5.1.2", self.cat.presets["ND"]["notes"])
        self.assertIn("61-03-25", self.cat.presets["ND"]["citation"])
        self.assertIn("DWEE", self.cat.presets["NE"]["notes"])
        self.assertIn("4.2.14", self.cat.presets["CO"]["notes"])
        self.assertIn("TR-60", self.cat.scenarios["S3"]["breach_assumption"])


class NidRule(unittest.TestCase):
    def test_rule(self):
        from damit_catalog import handoff as HO
        ok = lambda d: HO.nid_rule(d)  # noqa: E731
        self.assertEqual(ok({"dam_id": "ND00199"}), (None, None, "ND00199"))
        self.assertEqual(ok({"dam_id": "nd00199"})[2], "ND00199")
        e, w, n = ok({"dam_id": "Swan 12", "nid_id": "ND00199"})
        self.assertIsNone(e)
        self.assertIn("dam_id = NID ID preferred", w)
        self.assertEqual(n, "ND00199")
        for bad in ({"dam_id": "DWR-2801"}, {"dam_id": "DUG-130", "nid_id": "ND00199"}, {"dam_id": "UNK-9"},
                    {"dam_id": "x", "nid_id": "DWR-2801"}, {"dam_id": "SAMPLE-4031"}, {"dam_id": "NEW"},
                    {"dam_id": "DESK-014"}, {"dam_id": "x", "is_new": False}):
            self.assertIsNotNone(ok(bad)[0], bad)
        for good in ({"dam_id": "desk-1", "is_new": True}, {"dam_id": "desk-1", "is_new": "true"},
                     {"dam_id": "p", "new_or_existing": "new"}, {"dam_id": "local-sample", "is_sample": True}):
            e, w, n = ok(good)
            self.assertIsNone(e, good)
            self.assertIsNone(n)
            self.assertTrue(w)
        self.assertTrue(HO.is_nid_id("TX12345") and not HO.is_nid_id("ND-001") and not HO.is_nid_id(None))

    def test_rule_edges(self):
        from damit_catalog import handoff as HO
        # nid_id alone (no dam_id) is the NID ID, no warning
        self.assertEqual(HO.nid_rule({"nid_id": "nd00199"}), (None, None, "ND00199"))
        self.assertEqual(HO.nid_rule({"dam_id": "ND00199", "nid_id": "nd00199"}), (None, None, "ND00199"))
        # two different NID IDs in one record
        e, w, n = HO.nid_rule({"dam_id": "ND00001", "nid_id": "ND00002"})
        self.assertIn("one record names one NID dam", e)
        # other inventories in any spelling, even new / sample / with a valid nid_id
        for bad in ({"dam_id": "DWR2801"}, {"dam_id": "dwr_2801", "nid_id": "ND00199"}, {"dam_id": "UNK 9"},
                    {"dam_id": "DWR-2801", "is_new": True}, {"dam_id": "DUG-130", "is_sample": True}):
            self.assertIsNotNone(HO.nid_rule(bad)[0], bad)
        # a name that merely starts with the letters is not another inventory's id
        self.assertIsNone(HO.nid_rule({"dam_id": "Dugan Dam", "nid_id": "ND00199"})[0])
        self.assertIsNone(HO.nid_rule({"dam_id": "p", "new_or_existing": "Proposed"})[0])
        self.assertIsNotNone(HO.nid_rule({"dam_id": "p", "new_or_existing": "existing"})[0])
        self.assertIsNotNone(HO.nid_rule({"dam_id": "p", "is_new": "false", "is_sample": 0})[0])
        self.assertIsNotNone(HO.nid_rule(None)[0])

    def test_validate_applies_the_rule(self):
        from damit_catalog import handoff as HO
        pkg = {"dam": {"dam_id": "DWR-2801"}}
        self.assertTrue(any("another inventory" in e for e in HO.validate(pkg)))


if __name__ == "__main__":
    unittest.main()
