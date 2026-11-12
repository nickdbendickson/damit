"""Depth must not collapse when a feet DEM has a blank or plural US-survey-foot unit, and the
HEC-RAS plan must not assume US units or replace a finished breach with a narrower one."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from damit_runner.core import hecras
from damit_runner.flood import rasters as R


FT = 0.3048


class ZScale(unittest.TestCase):
    def test_blank_band_is_not_metres(self):
        with self.assertRaises(R.DemZError):
            R.z_scale({"z_unit": "", "z_vert": ""})

    def test_plural_us_survey_feet_and_the_other_aliases(self):
        us = 1200.0 / 3937.0
        for name in ("us survey feet", "US survey feet", "us foot", "ft (us)", "survey foot",
                     "us survey foot"):
            self.assertAlmostEqual(R.z_scale({"z_unit": name}), us, places=9)
        self.assertAlmostEqual(R.z_scale({"z_unit": "intl foot"}), FT, places=9)
        self.assertAlmostEqual(R.z_scale({"z_unit": "", "z_vert": "feet"}), FT, places=9)
        self.assertAlmostEqual(R.z_scale({"z_unit": "m"}), 1.0, places=9)

    def test_explicit_choice(self):
        self.assertAlmostEqual(R.z_scale({}, "ft"), FT, places=9)
        self.assertAlmostEqual(R.z_scale({}, "us_ft"), 1200.0 / 3937.0, places=9)
        self.assertAlmostEqual(R.z_scale({}, "m"), 1.0, places=9)
        with self.assertRaises(R.DemZError):
            R.z_scale({}, "furlong")

    def test_fifty_foot_pool_stays_fifty_feet(self):
        """Ground stored as 1600, pool at 1650 ft. The old reader published 0 ft."""
        us = R.z_scale({"z_unit": "us survey feet"})
        depth_ft = (1650.0 * FT - 1600.0 * us) / FT
        self.assertAlmostEqual(depth_ft, 50.0, delta=0.05)
        with self.assertRaises(R.DemZError):
            ground_m = 1600.0 * R.z_scale({"z_unit": ""})
            (1650.0 * FT - ground_m) / FT

    def test_3dep_source_is_metres_when_no_band_unit(self):
        info = {"z_unit": "", "z_vert": "",
                "z_source": "USGS 3DEP ImageServer (elevation.nationalmap.gov)",
                "z_source_units": "metres", "path": "terrain_10m_epsg5070.tif"}
        self.assertEqual(R.z_scale(info), 1.0)
        factor, how = R.resolve_z(dict(info), "auto")
        self.assertEqual(factor, 1.0)
        self.assertTrue(how.startswith("assumed metres"))
        self.assertIn("USGS 3DEP", how)

    def test_usgs_star_filename_is_metres(self):
        info = {"z_unit": "", "z_vert": "", "path": "/tmp/USGS_13_n46w098_20240613.tif",
                "files": ["/tmp/USGS_13_n46w098_20240613.tif"]}
        self.assertEqual(R.z_scale(info), 1.0)

    def test_3dep_in_the_name_is_metres(self):
        self.assertEqual(R.z_scale({"z_unit": "", "path": "clip_3dep_10m.tif"}), 1.0)

    def test_explicit_feet_wins_over_a_3dep_cue(self):
        info = {"z_unit": "", "z_source": "USGS 3DEP ImageServer (elevation.nationalmap.gov)",
                "z_source_units": "metres"}
        self.assertAlmostEqual(R.z_scale(info, "ft"), FT, places=9)

    def test_unitless_without_a_3dep_cue_still_stops(self):
        with self.assertRaises(R.DemZError):
            R.z_scale({"z_unit": "", "z_vert": "", "path": "terrain_10m_epsg5070.tif"})


class FeetDem(unittest.TestCase):
    def test_read_window_scales_us_survey_feet(self):
        try:
            from osgeo import gdal, osr
        except ImportError:
            self.skipTest("GDAL not installed")
        gdal.UseExceptions()
        tmp = tempfile.mkdtemp(prefix="damit_z_")
        path = os.path.join(tmp, "dem.tif")
        try:
            ds = gdal.GetDriverByName("GTiff").Create(path, 4, 4, 1, gdal.GDT_Float32)
            ds.SetGeoTransform((500000.0, 10.0, 0.0, 5200000.0, 0.0, -10.0))
            s = osr.SpatialReference()
            s.ImportFromEPSG(26914)
            ds.SetProjection(s.ExportToWkt())
            ds.GetRasterBand(1).WriteArray(np.full((4, 4), 1600.0, np.float32))
            ds.GetRasterBand(1).SetNoDataValue(-9999)
            ds.GetRasterBand(1).SetUnitType("US survey feet")
            ds = None
            info = R.dem_info(path)
            self.assertEqual(info["z_unit"], "us survey feet")
            wkt = s.ExportToWkt()
            g = R.read_window(path, (500000.0, 5199960.0, 500040.0, 5200000.0), 10.0, wkt)
            ground_m = float(np.nanmean(g.data))
            depth_ft = (1650.0 * FT - ground_m) / FT
            self.assertAlmostEqual(depth_ft, 50.0, delta=0.05)
            # the same grid with the unit stripped must stop, not publish 0 ft
            ds = gdal.Open(path, gdal.GA_Update)
            ds.GetRasterBand(1).SetUnitType("")
            ds = None
            with self.assertRaises(R.DemZError):
                R.read_window(path, (500000.0, 5199960.0, 500040.0, 5200000.0), 10.0, wkt)
            # the same blank-unit file, tagged as USGS 3DEP, is read as metres (DWR-2659)
            ds = gdal.Open(path, gdal.GA_Update)
            ds.SetMetadataItem("SOURCE", "USGS 3DEP ImageServer (elevation.nationalmap.gov)")
            ds.SetMetadataItem("UNITS", "metres")
            ds = None
            g = R.read_window(path, (500000.0, 5199960.0, 500040.0, 5200000.0), 10.0, wkt)
            self.assertTrue(getattr(g, "z_how", "").startswith("assumed metres"))
            self.assertAlmostEqual(float(g.z_to_m), 1.0)
            # 1600 is now 1600 m, not 1600 ft: this only checks the assumption is applied
            self.assertAlmostEqual(float(__import__("numpy").nanmean(g.data)), 1600.0, delta=0.1)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class HecRasUnits(unittest.TestCase):
    def test_cms_is_si_and_cfs_is_us(self):
        self.assertEqual(hecras.parse_units("cms"), "si")
        self.assertEqual(hecras.parse_units("cfs"), "us")
        self.assertEqual(hecras.parse_units("Feet"), "us")
        self.assertEqual(hecras.parse_units("Meter"), "si")
        self.assertIsNone(hecras.parse_units(""))

    def test_low_elevation_feet_as_metres_is_fatal(self):
        elev = 40.0
        ground = np.full(20, elev / FT)          # feet numbers read as metres, then to feet
        cmin = np.full(20, elev)
        rec = hecras.datum_check(ground, cmin)
        self.assertEqual(rec["status"], "mismatch")
        self.assertTrue(rec["fatal"])

    def test_a_few_feet_of_relief_stays_a_warning(self):
        cmin = np.full(20, 1600.0)
        ground = cmin + 2.0                       # fine DEM above the cell minimum
        rec = hecras.datum_check(ground, cmin)
        self.assertEqual(rec["status"], "suspect")
        self.assertFalse(rec["fatal"])


class BreachNotReplaced(unittest.TestCase):
    def test_finished_von_thun_opening_is_kept(self):
        class Dam(object):
            top_of_dam_ft = 1800.0
            dam_height_ft = 35.0
            breach_bottom_ft = 1765.0
            storage_top_acft = 1000.0

        params = {"failure_mode": "piping",
                  "breach_parameters": "Von Thun & Gillette (1990), easily erodible",
                  "avg_breach_width_ft": 148.0, "bottom_width_ft": 130.0,
                  "side_slope_h": 0.5, "formation_time_hr": 0.5}
        rows = {r["item"]: r["value"] for r in hecras.breach_parameter_rows(Dam(), params)}
        self.assertEqual(rows["Final bottom width"], 130.0)
        self.assertEqual(rows["Left side slope"], 0.5)
        self.assertEqual(rows["Full formation time"], 0.5)
        forced = dict(params, breach_f2008="overwrite")
        wide = {r["item"]: r["value"] for r in hecras.breach_parameter_rows(Dam(), forced)}
        self.assertNotEqual(wide["Final bottom width"], 130.0)


if __name__ == "__main__":
    unittest.main()
