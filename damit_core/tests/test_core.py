"""DamIT Core (pure Python; no QGIS needed)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_core.lib import VERSION, catalog_access, dam_record, plugins, settings, states  # noqa: E402


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(settings.ENV)
        os.environ[settings.ENV] = os.path.join(self.tmp, "s.json")

    def tearDown(self):
        if self.old is None:
            os.environ.pop(settings.ENV, None)
        else:
            os.environ[settings.ENV] = self.old
        shutil.rmtree(self.tmp)

    def test_round_trip_and_json_backend(self):
        self.assertEqual(settings.get("data_folder"), "")
        settings.set("data_folder", "/x")
        self.assertEqual(settings.get("data_folder"), "/x")
        self.assertEqual(settings.backend(), os.environ[settings.ENV])
        with open(os.environ[settings.ENV]) as fh:
            self.assertEqual(json.load(fh)["data_folder"], "/x")

    def test_fill_empty_keeps_values(self):
        settings.set("state", "NE")
        done = settings.fill_empty({"state": "ND", "terrain": "/dem.tif", "roads_layer": ""})
        self.assertEqual(done, ["terrain"])
        self.assertEqual(settings.get("state"), "NE")

    def test_unknown_key(self):
        with self.assertRaises(KeyError):
            settings.get("pack_path")


class Plugins(unittest.TestCase):
    def test_repo_checkout_suite(self):
        rows = {r["folder"]: r for r in plugins.check_suite(dirs=[ROOT], active=[])}
        self.assertTrue(rows["damit_core"]["present"])
        self.assertEqual(rows["damit_core"]["version"], VERSION)
        self.assertTrue(rows["damit_catalog"]["present"])
        for r in rows.values():
            self.assertEqual(r["foreign_deps"], [], r["folder"])

    def test_missing_and_foreign_deps(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "damit_data"))
            with open(os.path.join(tmp, "damit_data", "metadata.txt"), "w") as fh:
                fh.write("[general]\nname=DamIT Data\nversion=0.1.0\n"
                         "plugin_dependencies=DamIT Core==0.2.0,DamSafety Core\n")
            rows = plugins.check_suite(dirs=[tmp], active=["damit_data"])
            probs = plugins.problems(rows)
            self.assertTrue(any("DamIT Core is not installed" in p for p in probs))
            self.assertTrue(any("needs DamIT Core >= 0.2.0" in p for p in probs))
            self.assertTrue(any("DamSafety Core (not part of DamIT)" in p for p in probs))
        finally:
            shutil.rmtree(tmp)

    def test_providers_and_foreign_ids(self):
        provs = [r[2] for r in plugins.SUITE if r[2]]
        self.assertEqual(len(provs), len(set(provs)))
        self.assertNotIn("nddam", provs)
        self.assertTrue(plugins.is_foreign_algorithm("ndbreach:rundam"))
        self.assertTrue(plugins.is_foreign_algorithm("NDDAM:preflight"))
        self.assertFalse(plugins.is_foreign_algorithm("damit_screen:preflight"))
        self.assertEqual(plugins.parse_version("0.10.2"), (0, 10, 2))


class States(unittest.TestCase):
    def test_table(self):
        t = states.table()
        self.assertEqual(len(t), 52)                       # 50 states, DC, PR
        nd = states.get("nd")
        self.assertEqual((nd["fips"], nd["name"]), ("38", "North Dakota"))
        self.assertEqual(states.get("38")["postal"], "ND")
        self.assertEqual(states.get("New York")["microsoft"], "NewYork")
        self.assertIn("NE", states.states_for_bbox((-100.0, 41.0, -99.0, 42.0)))
        self.assertIn("ND", states.state_for_point(-96.79, 46.88))
        with self.assertRaises(KeyError):
            states.get("XX")


class DamRecord(unittest.TestCase):
    def test_nid_fields(self):
        fm = dam_record.suggest_field_map(["NIDID", "DAM_NAME", "NID_HEIGHT", "NID_STORAGE",
                                           "HAZARD_POTENTIAL", "STATE"])
        self.assertEqual(fm, {"dam_id": "NIDID", "name": "DAM_NAME", "height_ft": "NID_HEIGHT",
                              "storage_acft": "NID_STORAGE", "existing_class": "HAZARD_POTENTIAL"})
        self.assertIn("dam_id=NIDID", dam_record.field_map_string(fm))
        rec = dam_record.normalize({"NIDID": " ND00001 ", "DAM_NAME": "A", "NID_HEIGHT": 25, "NID_STORAGE": ""}, fm)
        self.assertEqual(rec, {"dam_id": "ND00001", "name": "A", "height_ft": 25, "storage_acft": None})

    def test_exact_names_win(self):
        fm = dam_record.suggest_field_map(["id", "dam_id", "height_ft"])
        self.assertEqual(fm["dam_id"], "dam_id")
        self.assertEqual(dam_record.field_map_string(fm), "")


class CatalogAccess(unittest.TestCase):
    def test_presets(self):
        cat = catalog_access.load()
        ids = [p for p, _ in catalog_access.preset_choices(cat)]
        self.assertIn("FEMA333", ids)
        self.assertEqual(catalog_access.preset_for_state(cat, "nd"), "ND")
        self.assertIsNone(catalog_access.preset_for_state(cat, "MN"))   # no MN preset: user picks
        self.assertEqual(catalog_access.preset_for_state(cat, "al"), "AL")    # Nov 2026 Summaries S-1
        self.assertEqual(catalog_access.preset_for_state(cat, "NC"), "NC")    # Nov 2026 Summaries S-12
        cfg = catalog_access.resolve(cat, "preset", "USBR_TM11")
        self.assertEqual(cfg["preset_id"], "USBR")


if __name__ == "__main__":
    unittest.main()
