"""The local DEM FOLDER DamIT Crest writes for the screener holds the chosen DEM only (2026-11-21).

damit_settings.json carried local_dem = the DEM's own folder (terrain_source 1). A DamSafety-style screener's tool 2
mosaics every raster in that folder, and the Absaraka test folder held hmax_ft.tif, vmax_fps.tif, arr_hr.tif and a
second DEM next to cass_10m_3dep.vrt. The folder is now <work>/screen_dem with the DEM alone. Nothing is run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from damit_desktop import layers  # noqa: E402

TILE_VRT = """<VRTDataset rasterXSize="2" rasterYSize="2">
  <VRTRasterBand dataType="Float32" band="1">
    <SimpleSource><SourceFilename relativeToVRT="1">tiles/a &amp; b.tif</SourceFilename></SimpleSource>
    <SimpleSource><SourceFilename relativeToVRT="0">/abs/c.tif</SourceFilename></SimpleSource>
  </VRTRasterBand>
</VRTDataset>
"""


class ScreenDemFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, dem):
        layers.write_settings(self.work, None, str(dem))
        return json.loads((self.work / layers.SETTINGS_NAME).read_text(encoding="utf-8"))

    def test_results_rasters_next_to_the_dem_are_not_in_the_local_dem_folder(self):
        dem = self.inputs / "cass_10m_3dep.vrt"
        dem.write_text('<VRTDataset><SourceFilename relativeToVRT="0">/dems/t.tif</SourceFilename></VRTDataset>')
        (self.inputs / "cass_10m_3dep.vrt.aux.xml").write_text("<PAMDataset/>")
        for other in ("hmax_ft.tif", "vmax_fps.tif", "arr_hr.tif", "absaraka_3dep_r3000m.tif"):
            (self.inputs / other).write_bytes(b"not terrain")
        s = self.settings(dem)
        folder = Path(s["local_dem"])
        self.assertEqual(folder.resolve(), (self.work / "screen_dem").resolve())
        self.assertNotEqual(folder.resolve(), self.inputs.resolve())
        self.assertEqual(sorted(x.name for x in folder.iterdir()), ["cass_10m_3dep.vrt", "cass_10m_3dep.vrt.aux.xml"])
        self.assertEqual((folder / "cass_10m_3dep.vrt").read_text(), dem.read_text())
        self.assertEqual(Path(s["terrain"]), dem.resolve(), "the screener's TERRAIN is still the DEM itself")
        self.assertEqual(s["terrain_source"], 1)
        self.assertEqual(s["larger_clips"], 2)
        self.assertEqual(sorted(x.name for x in self.inputs.iterdir()),
                         sorted(["cass_10m_3dep.vrt", "cass_10m_3dep.vrt.aux.xml", "hmax_ft.tif", "vmax_fps.tif",
                                 "arr_hr.tif", "absaraka_3dep_r3000m.tif"]), "the DEM's folder is only read")

    def test_a_vrt_with_relative_tiles_is_written_with_absolute_ones(self):
        dem = self.inputs / "mosaic.vrt"
        dem.write_text(TILE_VRT)
        folder = Path(self.settings(dem)["local_dem"])
        staged = (folder / "mosaic.vrt")
        self.assertFalse(staged.is_symlink())
        text = staged.read_text()
        tile = (self.inputs / "tiles" / "a & b.tif").resolve()
        self.assertIn(f'relativeToVRT="0">{str(tile).replace("&", "&amp;")}</SourceFilename>', text)
        self.assertIn('relativeToVRT="0">/abs/c.tif</SourceFilename>', text)
        self.assertNotIn('relativeToVRT="1"', text)

    def test_a_new_dem_replaces_the_old_one_and_a_geotiff_keeps_its_world_file(self):
        first = self.inputs / "first.vrt"
        first.write_text("<VRTDataset/>")
        self.settings(first)
        dem = self.inputs / "lidar.tif"
        dem.write_bytes(b"II*\x00")
        (self.inputs / "lidar.tfw").write_text("1\n0\n0\n-1\n0\n0\n")
        folder = Path(self.settings(dem)["local_dem"])
        self.assertEqual(sorted(x.name for x in folder.iterdir()), ["lidar.tfw", "lidar.tif"])
        self.assertEqual((folder / "lidar.tif").read_bytes(), b"II*\x00")

    def test_the_staged_dem_itself_can_be_chosen(self):
        dem = self.inputs / "d.vrt"
        dem.write_text("<VRTDataset/>")
        folder = Path(self.settings(dem)["local_dem"])
        again = Path(self.settings(folder / "d.vrt")["local_dem"])
        self.assertEqual(again.resolve(), folder.resolve())
        self.assertEqual([x.name for x in folder.iterdir()], ["d.vrt"])
        self.assertEqual((folder / "d.vrt").read_text(), "<VRTDataset/>")

    @unittest.skipIf(os.name == "nt", "a symlink needs rights on Windows; there the DEM is hard-linked or copied")
    def test_a_geotiff_is_linked_not_copied(self):
        dem = self.inputs / "big.tif"
        dem.write_bytes(b"II*\x00" * 10)
        folder = Path(self.settings(dem)["local_dem"])
        self.assertTrue((folder / "big.tif").is_symlink())
        self.assertEqual(os.path.realpath(folder / "big.tif"), str(dem.resolve()))


if __name__ == "__main__":
    unittest.main()
