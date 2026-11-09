"""DamIT Setup logic (pure Python)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_core.lib import plugins, settings  # noqa: E402
from damit_setup import core  # noqa: E402


def touch(*parts):
    p = os.path.join(*parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()
    return p


class SetupCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(settings.ENV)
        os.environ[settings.ENV] = os.path.join(self.tmp, "settings.json")
        self.data = os.path.join(self.tmp, "suite_data")
        touch(self.data, "inventory", "nid_dams.gpkg")
        touch(self.data, "terrain", "dem_10m.tif")
        touch(self.data, "NE", "nsi", "nsi.geojson")                 # a DamIT Data download folder
        touch(self.data, "NE", "microsoft_footprints", "Nebraska.geojson")
        touch(self.data, "transport", "roads.gpkg")
        touch(self.data, "transport", "rail_lines.shp")
        touch(self.data, "notes.txt")
        touch(self.data, "NE", "osm", ".part_abc")
        self.rows = plugins.check_suite(dirs=[ROOT], active=[])

    def tearDown(self):
        if self.old is None:
            os.environ.pop(settings.ENV, None)
        else:
            os.environ[settings.ENV] = self.old
        shutil.rmtree(self.tmp)

    def test_scan_is_jurisdiction_neutral(self):
        found, notes = core.scan(self.data)
        self.assertEqual(notes, [])
        self.assertTrue(found["dams"][0].endswith("nid_dams.gpkg"))
        self.assertTrue(found["terrain"][0].endswith("dem_10m.tif"))
        self.assertEqual(len(found["structures"]), 2)
        self.assertTrue(found["roads"][0].endswith("roads.gpkg"))
        self.assertTrue(found["rail"][0].endswith("rail_lines.shp"))
        lines = core.scan_lines(found)
        self.assertTrue(all(s == "ok" for s, _, _ in lines))

    def test_problem_order(self):
        found, _ = core.scan(self.data)
        work = os.path.join(self.tmp, "work")
        self.assertIn("Pick the suite data folder", core.problem("", work, found, self.rows))
        self.assertIn("work folder", core.problem(self.data, "", found, self.rows))
        self.assertIn("must not be inside", core.problem(self.data, os.path.join(self.data, "w"), found, self.rows))
        self.assertEqual(core.problem(self.data, work, found, self.rows), "")
        self.assertIn("No dam layer", core.problem(self.data, work, {"dams": []}, self.rows))
        no_catalog = [dict(r, present=False) if r["folder"] == "damit_catalog" else r for r in self.rows]
        self.assertIn("DamIT Catalog is not installed", core.problem(self.data, work, found, no_catalog))

    def test_fill_settings_keeps_existing(self):
        settings.set("terrain", "/mine/dem.tif")
        found, _ = core.scan(self.data)
        written = core.fill_settings(self.data, os.path.join(self.tmp, "work"), found, "NE", "NE")
        self.assertIn("data_folder", written)
        self.assertIn("dams_layer", written)
        self.assertNotIn("terrain", written)
        self.assertEqual(settings.get("terrain"), "/mine/dem.tif")
        self.assertEqual(settings.get("preset"), "NE")

    def test_handoff_params_and_settings_file(self):
        work = os.path.join(self.tmp, "work")
        doc = core.screener_settings("USBR_TM11", "preset", "/d.tif", {"dam_id": "NIDID"})
        path = core.write_screener_settings(work, doc)
        with open(path) as fh:
            self.assertEqual(json.load(fh)["preset"], "USBR_TM11")
        p = core.preflight_params(work, "/dams.gpkg", "/d.tif", "", "USBR_TM11", "preset", {"dam_id": "NIDID"}, path)
        self.assertEqual(p["MODE"], 0)
        self.assertEqual(p["FIELD_MAP"], "dam_id=NIDID")
        self.assertNotIn("RECEPTORS", p)
        self.assertEqual(core.preflight_params(work, mode="custom", preset="ND")["PRESET"], "")
        from damit_screener.core import workflow
        s = workflow.settings_from(path)                       # the Screener reads the file as is
        self.assertEqual(s["preset"], "USBR_TM11")
        self.assertEqual(set(doc) - set(workflow.DEFAULT_SETTINGS), set())

    def test_handoff_targets(self):
        self.assertEqual(core.handoff_target("damit_run:rundam"), "damit_run:rundam")
        for bad in ("nddam:preflight", "ndbreach:rundam", "ndbreach:batch"):
            with self.assertRaises(ValueError):
                core.handoff_target(bad)
        with self.assertRaises(ValueError):
            core.handoff_target("damit:classify")


if __name__ == "__main__":
    unittest.main()
