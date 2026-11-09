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
PRESETS = ["FEMA333", "USBR", "BIA", "NRCS", "ND", "NE", "NY", "VA", "TX", "ID", "CO", "RI", "AZ", "CA", "AK"]


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
        self.assertEqual(u["conditional_scenarios"], [{"id": "S5", "when": "borderline dams", "verification": "unverified"}])
        self.assertEqual(len(u["methods"]["M1"]["params"]["charts"]), 5)
        self.assertEqual((u["methods"]["M5"]["params"]["sig_min"], u["methods"]["M5"]["params"]["high_min"]), (1, 7))
        self.assertEqual([r["id"] for r in u["modifiers"]], ["R1"])
        self.assertTrue(any(fl["code"] == "unverified_or_secondary" for fl in u["flags"]))

    def test_all_presets_resolve(self):
        expect = {"FEMA333": (["S1"], {"M5", "M13"}), "BIA": ([], {"M5"}), "NRCS": ([], {"M13"}),
                  "NE": (["S4"], {"M3", "M4a", "M8c", "M9b", "M11b", "M12a"}),
                  "NY": (["S1", "S5"], {"M1", "M4b", "M8d", "M8f", "M9c", "M10a", "M11c", "M12b"}),
                  "VA": (["S1", "S5"], {"M13", "M8e", "M5"}), "TX": ([], {"M4c"}), "ID": ([], {"M2", "M6"}),
                  "CO": (["S2"], {"M5", "M6"}), "RI": (["S6"], {"M13", "M8g"}), "AZ": ([], {"M13", "M12d"}),
                  "CA": ([], {"M5", "M7"}), "AK": ([], {"M5", "M12c", "M13"})}
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
