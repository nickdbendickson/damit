"""DamIT Screener workflow (no QGIS): preflight flags, scenario-driven chain, hand-off packages."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from damit_screener.core import steps as ST       # noqa: E402
from damit_screener.core import workflow as WF    # noqa: E402
from damit_catalog import handoff as HO           # noqa: E402
from damit_catalog import catalog as C            # noqa: E402


def raw_dam(**kw):
    d = {"ID": "ND00001", "NAME": "Test Dam", "HT": 30, "STOR": 450, "TOD": 1530, "NP": 1520, "PMF": 1534,
         "_x": 500000.0, "_y": 5200000.0, "_crs": "EPSG:26914"}
    d.update(kw)
    return d


FMAP = {"dam_id": "ID", "name": "NAME", "height_ft": "HT", "storage_acft": "STOR", "top_of_dam_elev_ft": "TOD",
        "normal_pool_elev_ft": "NP", "pmf_peak_elev_ft": "PMF"}


class Preflight(unittest.TestCase):
    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.work = tempfile.mkdtemp(prefix="damit_scr_")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def codes(self, checks):
        return {(c["status"], c["title"]) for c in checks}

    def test_missing_inputs_flagged(self):
        s = dict(WF.DEFAULT_SETTINGS, preset="ND")
        checks, cat, cfg = WF.preflight(self.work, s, None)
        self.assertIn(("fail", "Dams layer"), self.codes(checks))
        self.assertFalse(WF.ready(checks))
        self.assertIn(("warn", "Terrain (DEM)"), self.codes(checks))
        self.assertIn(("warn", "Receptors"), self.codes(checks))
        dams, probs = ST.prepare([raw_dam(PMF=None, STOR=None)], FMAP)
        checks, _, _ = WF.preflight(self.work, s, dams, probs)
        miss = [c for c in checks if c["title"] == "Dam ND00001 inputs"]
        self.assertEqual(miss[0]["status"], "warn")
        self.assertIn("pmf_peak_elev_ft", miss[0]["detail"])
        self.assertIn("storage_acft|storage_curve_csv", miss[0]["detail"])

    def test_preset_errors_fail(self):
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS), [])
        self.assertIn(("fail", "Preset"), self.codes(checks))
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="XX"), [])
        self.assertIn(("fail", "Preset / method selection"), self.codes(checks))
        dams, probs = ST.prepare([raw_dam(), raw_dam(), {"ID": None}], FMAP)
        self.assertEqual(len(dams), 1)
        self.assertEqual(len(probs), 2)
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), dams, probs)
        self.assertFalse(WF.ready(checks))

    def test_usbr_and_usbr_tm11_preset_ids(self):
        dams, _ = ST.prepare([raw_dam()], FMAP)
        for pid in ("USBR", "USBR_TM11"):
            checks, _, cfg = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset=pid), dams, [])
            self.assertNotIn(("fail", "Preset / method selection"), self.codes(checks), pid)
            self.assertEqual(cfg["preset_id"], "USBR", pid)
            self.assertEqual(cfg["preset_label"], "USBR (ACER TM-11)")
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="USBR_TM12"), dams, [])
        self.assertIn(("fail", "Preset / method selection"), self.codes(checks))

    def test_dash_preset_and_receptor_fields(self):
        dams, _ = ST.prepare([raw_dam()], FMAP)
        recs = [{"id": 1, "receptor_type": "structure", "structure_type": "home"}]
        checks, _, cfg = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="TX"), dams, [], recs)
        self.assertIn(("warn", "Scenarios"), self.codes(checks))
        self.assertTrue(any(c["title"] == "Catalog flag: scenario_unconfirmed" for c in checks))
        rf = [c for c in checks if c["title"] == "Receptor fields"][0]
        self.assertEqual(rf["status"], "warn")
        self.assertIn("habitable", rf["detail"])
        self.assertIn(("warn", "Receptor hydraulics"), self.codes(checks))

    def test_scenario_pools(self):
        dams, _ = ST.prepare([raw_dam(ESP=1526)], dict(FMAP, emergency_spillway_elev_ft="ESP"))
        cat = C.load()
        cfg = cat.resolve_custom(["M13"], ["S1", "S2", "S3"])
        st = ST.storage(dams[0], cfg["scenarios"])
        self.assertEqual(st["by_scenario"]["S1"]["pool_elev_ft"], 1520)
        self.assertEqual(st["by_scenario"]["S2"]["pool_elev_ft"], 1526)
        self.assertEqual(st["by_scenario"]["S3"]["pool_elev_ft"], 1530)      # lower of top of dam and PMF
        self.assertEqual(st["by_scenario"]["S3"]["storage_acft"], 450)

    def test_storage_curve_area_integration(self):
        p = os.path.join(self.work, "curve.csv")
        with open(p, "w") as fh:
            fh.write("elev_ft,area_ac\n1500,0\n1510,10\n1530,30\n")
        rows = ST.read_curve(p)
        self.assertAlmostEqual(ST.storage_at(rows, 1510), 50.0)
        self.assertAlmostEqual(ST.storage_at(rows, 1530), 450.0)
        self.assertIsNone(ST.storage_at(rows, 1540))


class Chain(unittest.TestCase):
    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.work = tempfile.mkdtemp(prefix="damit_chain_")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_chain_writes_valid_handoff(self):
        dem = os.path.join(self.work, "dem.tif")
        open(dem, "wb").close()
        hyd = os.path.join(self.work, "hyd.csv")
        with open(hyd, "w") as fh:
            fh.write("time_hr,discharge_cfs\n0,0\n1,5000\n3,0\n")
        dams, probs = ST.prepare([raw_dam(HYD=hyd, AZ=95), raw_dam(ID="ND00002", HT=10, STOR=40)],
                                 dict(FMAP, hydrograph_csv="HYD", breach_azimuth_deg="AZ"))
        recs = [{"id": "h1", "dam_id": "ND00001", "receptor_type": "structure", "structure_type": "home",
                 "habitable": True, "depth_ground_ft": 2.6, "feature_kind": "isolated_home"},
                {"id": "r1", "dam_id": "ND00002", "receptor_type": "road", "road_class": "private",
                 "feature_kind": "township_or_county_road"}]
        s = dict(WF.DEFAULT_SETTINGS, preset="ND", terrain=dem,
                 summary={"model_dimension": "1D", "hydraulics_source": "breach_model"})
        logs = []
        summ = WF.run_chain(self.work, s, dams, probs, recs, log=logs.append)
        self.assertTrue(summ["ok"], logs)
        self.assertEqual(summ["scenarios"], ["S3", "S7"])
        r1 = summ["dams"]["ND00001"]
        self.assertEqual(r1["suggest"]["screening"]["suggested_label"], "High")
        self.assertEqual(r1["hydrograph"]["status"], "ok")
        self.assertEqual(r1["engine2d"]["status"], "not_run")
        pkg = HO.read(r1["handoff_path"])
        self.assertEqual(HO.validate(pkg, C.load(), check_paths=True), [])
        self.assertEqual(pkg["target"], {"runner_algorithm": "damit_run:rundam", "classifier_algorithm": "damit:classify"})
        self.assertEqual(pkg["preset_id"], "ND")
        self.assertEqual([x["id"] for x in pkg["scenarios"]], ["S3", "S7"])
        self.assertEqual(pkg["dam"]["scenario_pools"]["S3"]["pool_elev_ft"], 1530)
        self.assertEqual(pkg["inputs"]["terrain"], dem)
        self.assertEqual(pkg["inputs"]["hydrograph_csv"], hyd)
        self.assertEqual(pkg["screening"]["status"], "computed_preliminary")
        self.assertEqual(pkg["screening"]["driving"][0]["method"], "M2")
        pkg2 = HO.read(summ["dams"]["ND00002"]["handoff_path"])
        self.assertEqual(pkg2["screening"]["status"], "not_computed")
        self.assertIn("hydrograph", [g["step"] for g in pkg2["gaps"]])
        self.assertIn("suggest", [g["step"] for g in pkg2["gaps"]])
        self.assertTrue(os.path.exists(summ["report"]))
        with open(summ["report"]) as fh:
            rep = fh.read()
        self.assertIn("REG_05.2026", rep)
        self.assertIn("Suggested classifications only", rep)

    def test_chain_refused_on_preflight_fail(self):
        summ = WF.run_chain(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), [], [], log=lambda *_: None)
        self.assertFalse(summ["ok"])
        self.assertTrue(summ["refused"])
        self.assertFalse(os.path.exists(os.path.join(self.work, "handoff")))

    def test_custom_mode_package(self):
        dams, _ = ST.prepare([raw_dam()], FMAP)
        s = dict(WF.DEFAULT_SETTINGS, mode="custom", custom_methods=["M2", "M8a"], scenarios=["S1"])
        summ = WF.run_chain(self.work, s, dams, [], log=lambda *_: None)
        pkg = HO.read(summ["dams"]["ND00001"]["handoff_path"])
        self.assertEqual(pkg["mode"], "custom")
        self.assertIsNone(pkg["preset_id"])
        self.assertEqual(sorted(pkg["methods"]), ["M2", "M8a"])


class NidOnly(unittest.TestCase):
    """The dam inventory is the NID: a record needs an NID ID, except a new / proposed dam or a desk sample."""

    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.work = tempfile.mkdtemp(prefix="damit_nid_")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def prep(self, *recs, fmap=None):
        return ST.prepare(list(recs), dict(FMAP, **(fmap or {})))

    def test_nid_id_is_in_the_record_and_the_field_map(self):
        self.assertIn("nid_id", ST.DAM_FIELDS)
        self.assertIn("is_new", ST.DAM_FIELDS)
        dams, probs = self.prep(raw_dam(ID="ND00199"))
        self.assertEqual(probs, [])
        self.assertEqual(dams[0]["nid_id"], "ND00199")
        self.assertEqual(dams[0]["nid_step"]["status"], ST.STATUS_OK)
        dams, probs = self.prep(raw_dam(ID="Swan 12", NIDID="nd00199"), fmap={"nid_id": "NIDID"})
        self.assertEqual(probs, [])
        self.assertEqual(dams[0]["nid_id"], "ND00199")
        self.assertEqual(dams[0]["nid_step"]["status"], ST.STATUS_GAP, "dam_id = NID ID is preferred")
        # only the NID ID field mapped: dam_id becomes the NID ID
        dams, probs = self.prep(raw_dam(ID=None, NIDID="ND00199"), fmap={"nid_id": "NIDID"})
        self.assertEqual(probs, [])
        self.assertEqual((dams[0]["dam_id"], dams[0]["nid_id"]), ("ND00199", "ND00199"))
        self.assertEqual(dams[0]["nid_step"]["status"], ST.STATUS_OK)

    def test_other_inventory_and_missing_ids_fail(self):
        for rec, fmap, why in ((raw_dam(ID="DWR-2801"), None, "another inventory"),
                               (raw_dam(ID="DUG-130"), None, "another inventory"),
                               (raw_dam(ID="DWR-2801", NIDID="ND00199"), {"nid_id": "NIDID"}, "another inventory"),
                               (raw_dam(ID="Swan 12", NIDID="SAMPLE-4031"), {"nid_id": "NIDID"}, "not an NID ID"),
                               (raw_dam(ID="SAMPLE-4031"), None, "no NID ID"),
                               (raw_dam(ID="NEW"), None, "no NID ID")):
            dams, probs = self.prep(rec, fmap=fmap)
            self.assertEqual(dams, [], rec)
            self.assertEqual(len(probs), 1, rec)
            self.assertIn(why, probs[0])
        dams, probs = self.prep(raw_dam(ID="DWR-2801"))
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), dams, probs)
        self.assertFalse(WF.ready(checks))
        self.assertTrue(any(c["status"] == "fail" and "DWR-2801" in c["detail"] for c in checks))

    def test_new_dam_and_sample_pass_with_a_gap(self):
        for rec, fmap in ((raw_dam(ID="desk-new1", NEW="true"), {"is_new": "NEW"}),
                          (raw_dam(ID="proposed-a", NOE="New"), {"new_or_existing": "NOE"}),
                          (raw_dam(ID="local-sample", SMP=True), {"is_sample": "SMP"})):
            dams, probs = self.prep(rec, fmap=fmap)
            self.assertEqual(probs, [], rec)
            self.assertIsNone(dams[0]["nid_id"])
            self.assertEqual(dams[0]["nid_step"]["status"], ST.STATUS_GAP)
            checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), dams, probs)
            nid = [c for c in checks if c["title"].endswith("NID ID")]
            self.assertEqual(nid[0]["status"], "warn")
        dams, _ = self.prep(raw_dam(ID="desk-new1", NEW=1), fmap={"is_new": "NEW"})
        res = WF.run_chain(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), dams, [], log=lambda *_: None)
        r = res["dams"]["desk-new1"]
        self.assertEqual(r["prepare"]["status"], ST.STATUS_GAP)
        pkg = HO.read(r["handoff_path"])
        self.assertTrue(pkg["dam"]["is_new"])
        self.assertIsNone(pkg["dam"]["nid_id"])
        self.assertTrue(any(g["step"] == "prepare" for g in pkg["gaps"]))
        self.assertEqual(HO.validate(pkg), [])



class CatalogDecisions(unittest.TestCase):
    """The Screener's preliminary suggestion and preflight read PR #5's decisions from DamIT Catalog."""

    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.work = tempfile.mkdtemp(prefix="damit_scr_dec_")
        self.cat = C.load()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_preset_status_surfaces_in_preflight(self):
        dams, _ = ST.prepare([raw_dam()], FMAP)
        for pid in ("NRCS", "NY"):
            checks, _, cfg = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset=pid), dams, [])
            self.assertEqual(cfg["status"], self.cat.presets[pid]["status"])
            st = [c for c in checks if c["title"] == "Catalog flag: preset_status"]
            self.assertEqual(len(st), 1, pid)
            self.assertEqual(st[0]["status"], WF.WARN)
            self.assertIn("(" + self.cat.presets[pid]["status"] + ")", st[0]["detail"])
        checks, _, _ = WF.preflight(self.work, dict(WF.DEFAULT_SETTINGS, preset="ND"), dams, [])
        self.assertFalse([c for c in checks if c["title"] == "Catalog flag: preset_status"])

    def test_usbr_suggestion_m1_marks_m5_classes(self):
        cfg = self.cat.resolve_preset("USBR")
        for n, want in ((3, "Significant"), (7, "High")):
            rec = {"id": "h", "receptor_type": "structure", "structure_type": "home", "habitable": True,
                   "depth_ground_ft": 6.5, "velocity_fps": 1.0, "m1_zone": "high_danger", "occupants": n}
            st = ST.suggest(self.cat, cfg, {}, [rec], {"model_dimension": "2D"})
            self.assertEqual(st["screening"]["suggested_label"], want, n)
            self.assertEqual([d["method"] for d in st["screening"]["driving"]], ["M5"])

    def test_ny_r8_reads_existing_class(self):
        cfg = self.cat.resolve_preset("NY")
        rec = {"id": "h", "receptor_type": "structure", "structure_type": "home", "habitable": True,
               "depth_ground_ft": 0.5, "velocity_fps": 0.1, "m1_zone": "low_danger"}
        st = ST.suggest(self.cat, cfg, {"existing_class": "Class C"}, [rec], {"model_dimension": "2D"})
        self.assertEqual(st["screening"]["suggested_label"], "Class C")
        self.assertIn("R8", [m["id"] for m in st["screening"]["modifiers_applied"]])

if __name__ == "__main__":
    unittest.main()
