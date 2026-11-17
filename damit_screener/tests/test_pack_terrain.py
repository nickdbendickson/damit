"""DamIT Screener 0.3.4: larger clips from the configured pack DEM; 3DEP when there is none, when it
does not cover the dam, or when the settings chose larger_clips themselves."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from damit_screener.core import pack_terrain as PT  # noqa: E402
from damit_screener.core import workflow as WF  # noqa: E402

DEFAULTS = {"larger_clips": 1, "local_dem": ""}


class TestPackTerrain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pack_terrain_")
        self.addCleanup(self._cleanup)
        self.env = mock.patch.dict(os.environ, {
            "NDSUITE_PACK": "", "NDSUITE_DATA": "", "DAMIT_DATA": "", "DAMIT_DATA_FOLDER": "",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self._real_config = PT._config_values
        for name, value in (("_damit_data_folder", ""), ("_config_values", [])):
            p = mock.patch.object(PT, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def _pack_with_dem(self, name="pack"):
        root = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(root, "dem"))
        dem = os.path.join(root, "dem", "mosaic.vrt")
        with open(dem, "w") as fh:
            fh.write("<VRTDataset></VRTDataset>")
        return root, dem

    def test_no_pack_keeps_3dep(self):
        notes = []
        s = PT.apply_offline_pack_terrain(dict(DEFAULTS), log=notes.append)
        self.assertEqual((s["larger_clips"], s["local_dem"]), (1, ""))
        self.assertTrue(any("USGS 3DEP" in n for n in notes), notes)

    def test_pack_dem_is_the_file_not_its_folder(self):
        folder, dem = self._pack_with_dem()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": folder}):
            s = PT.apply_offline_pack_terrain(dict(DEFAULTS))
        self.assertEqual(s["larger_clips"], 2)
        self.assertEqual(s["local_dem"], dem)             # flood/screen.py opens local_dem as a raster
        self.assertTrue(os.path.isfile(s["local_dem"]))

    def test_damit_data_folder_setting_is_read(self):
        folder, dem = self._pack_with_dem("damit")
        with mock.patch.object(PT, "_damit_data_folder", return_value=folder):
            self.assertIn(folder, PT.configured_pack_folders())

    def test_larger_clips_set_in_the_settings_is_kept(self):
        folder, _ = self._pack_with_dem()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": folder}):
            s = PT.apply_offline_pack_terrain(dict(DEFAULTS), explicit=("larger_clips",))
        self.assertEqual((s["larger_clips"], s["local_dem"]), (1, ""))

    def test_a_local_dem_folder_from_crest_becomes_its_dem_file(self):
        folder, dem = self._pack_with_dem()
        s = PT.apply_offline_pack_terrain({"larger_clips": 2, "local_dem": os.path.join(folder, "dem")})
        self.assertEqual(s["local_dem"], dem)
        s = PT.apply_offline_pack_terrain({"larger_clips": 2, "local_dem": os.path.join(folder, "dem"),
                                           "terrain": dem})
        self.assertEqual(s["local_dem"], dem)

    def test_a_raster_at_the_top_of_the_data_folder_is_not_terrain(self):
        folder = os.path.join(self.tmp, "data")
        os.makedirs(folder)
        open(os.path.join(folder, "NLCD_2021.tif"), "w").close()
        self.assertEqual(PT.pack_dem(folder), "")

    def test_settings_from_then_run_dam_checks_coverage_per_dam(self):
        """The bug in the first 0.3.4: settings_from set local_dem, and run_dam then skipped coverage."""
        folder, dem = self._pack_with_dem()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": folder}):
            s = WF.settings_from("")
        self.assertEqual(s["local_dem"], dem)
        notes = []
        per_dam = dict(s)
        with mock.patch.object(PT, "pack_covers", return_value=False):
            PT.apply_offline_pack_terrain(per_dam, xy=(-98.0, 41.0), log=notes.append,
                                          explicit=tuple(s.get("_explicit_keys") or ()))
        self.assertEqual(per_dam["larger_clips"], 1)
        self.assertTrue(any("does not cover this dam" in n for n in notes), notes)
        with mock.patch.object(PT, "pack_covers", return_value=True):
            covered = PT.apply_offline_pack_terrain(dict(s), xy=(-100.0, 47.0))
        self.assertEqual(covered["larger_clips"], 2)

    def test_dam_point_comes_from_the_prepared_record(self):
        self.assertEqual(WF._dam_xy({"x": -100.5, "y": 47.1, "crs": "EPSG:4326"}), ((-100.5, 47.1), 4326))
        self.assertEqual(WF._dam_xy({"x": 500000, "y": 5200000, "crs": "EPSG:26914"}), ((500000.0, 5200000.0), 26914))
        self.assertEqual(WF._dam_xy({"x": None, "y": None}), (None, None))

    def test_settings_json_records_which_keys_it_set(self):
        s = WF.settings_from(json.dumps({"larger_clips": 0}))
        self.assertEqual(s["_explicit_keys"], ["larger_clips"])
        self.assertEqual(s["larger_clips"], 0)

    def test_pack_path_comes_from_config_json(self):
        folder, _ = self._pack_with_dem("from_config")
        cfg = os.path.join(self.tmp, "home", ".ndsuite", "config.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w") as fh:
            json.dump({"ndsuite/data_folder": folder}, fh)
        real = os.path.expanduser
        with mock.patch.object(os.path, "expanduser", side_effect=lambda p: p.replace("~", os.path.join(self.tmp, "home")) if isinstance(p, str) and p.startswith("~") else real(p)):
            got = self._real_config((os.path.join("~", ".ndsuite", "config.json"), ("ndsuite/data_folder",)))
        self.assertEqual(got, [os.path.abspath(folder)])

    def test_turned_off(self):
        folder, _ = self._pack_with_dem()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": folder}):
            s = PT.apply_offline_pack_terrain(dict(DEFAULTS, offline_pack_terrain=False))
        self.assertEqual(s["larger_clips"], 1)


if __name__ == "__main__":
    unittest.main()
