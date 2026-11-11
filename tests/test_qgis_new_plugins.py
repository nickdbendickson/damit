"""Real-QGIS tests (offscreen, scratch profile) for DamIT Core, Setup, Data, Hazard Lite and PMP.

No network (fake HTTP clients with recorded answers), no model, no process launch."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_helper as QH  # noqa: E402

ROOT = QH.ROOT
sys.path.insert(0, os.path.join(ROOT, "damit_data", "tests"))
FIX_PMP = os.path.join(ROOT, "damit_pmp", "tests", "fixtures")

if QH.HAVE_QGIS:
    from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProcessingException, QgsProject, QgsVectorFileWriter, QgsVectorLayer)


def setUpModule():
    if QH.HAVE_QGIS:
        QH.start()


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


def mem_layer(geom_type, crs, fields, rows):
    lyr = QgsVectorLayer("{}?crs={}&{}".format(geom_type, crs, "&".join("field={}:{}".format(n, t) for n, t in fields)),
                         "l", "memory")
    feats = []
    for wkt, attrs in rows:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        f.setAttributes(attrs)
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def write_tif(path, array, x0, y0, cell, epsg, nodata=-9999.0):
    from osgeo import gdal, osr
    import numpy as np
    ny, nx = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    ds.SetProjection(s.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(np.asarray(array, dtype="float32"))
    ds = None
    return path


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class Plugins(unittest.TestCase):
    def test_plugins_load_and_unload(self):
        import importlib
        from qgis.core import QgsApplication
        reg = QgsApplication.processingRegistry()
        for folder, provider in (("damit_core", None), ("damit_setup", None), ("damit_data", "damit_data"),
                                 ("damit_hazardlite", "damit_lite"), ("damit_pmp", "damit_pmp")):
            iface = QH.FakeIface()
            mod = importlib.import_module(folder)
            p = mod.classFactory(iface)
            if provider and reg.providerById(provider) is not None:
                continue                         # registered by another test in this process
            p.initGui()
            self.assertTrue(iface.menus.get("&DamIT"), folder)
            if provider:
                self.assertIsNotNone(reg.providerById(provider), folder)
            p.unload()
            self.assertEqual(iface.menus.get("&DamIT"), [], folder)
            if provider:
                self.assertIsNone(reg.providerById(provider), folder)

    def test_core_about_lists_suite(self):
        import damit_core
        txt = damit_core.classFactory(QH.FakeIface()).about_text()
        self.assertIn("DamIT Core 0.2.0", txt)
        self.assertIn("DamIT Catalog", txt)

    def test_provider_ids_do_not_collide_with_hazard(self):
        from damit_hazard.provider import Provider as DamitProvider
        from damit_hazardlite.provider import DamitLiteProvider
        hz = QH.add_provider(DamitProvider())
        lite = QH.add_provider(DamitLiteProvider())
        self.assertEqual(hz.id(), "damit")
        self.assertEqual(lite.id(), "damit_lite")
        from qgis.core import QgsApplication
        reg = QgsApplication.processingRegistry()
        self.assertIsNotNone(reg.algorithmById("damit:classify"))
        self.assertIsNotNone(reg.algorithmById("damit_lite:classify"))


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DAMIT_SETTINGS"] = os.path.join(self.tmp, "settings.json")
        self.data = os.path.join(self.tmp, "suite_data")
        os.makedirs(os.path.join(self.data, "inventory"))
        dams = mem_layer("Point", "EPSG:26914", [("NIDID", "string"), ("DAM_NAME", "string"), ("NID_HEIGHT", "double")],
                         [("POINT(600000 5200000)", ["NE00001", "Test Dam", 30.0])])
        self.dams_path = os.path.join(self.data, "inventory", "nid_dams.gpkg")
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        res = QgsVectorFileWriter.writeAsVectorFormatV3(dams, self.dams_path, QgsProject.instance().transformContext(), opts) \
            if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3") else \
            QgsVectorFileWriter.writeAsVectorFormatV2(dams, self.dams_path, QgsProject.instance().transformContext(), opts)
        self.assertEqual(res[0], QgsVectorFileWriter.NoError)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_dialog_scan_save_and_handoff_to_real_preflight(self):
        import processing
        from damit_screener.provider import DamitScreenProvider
        from damit_setup.dialog import SetupDialog
        from damit_core.lib import settings
        QH.add_provider(DamitScreenProvider())
        work = os.path.join(self.tmp, "work")
        ran = {}

        def opener(alg, params):                     # what the Processing dialog would run
            ran["alg"] = alg
            ran["params"] = params
            p = dict(params, REPORT=os.path.join(work, "preflight.txt"))
            ran["result"] = processing.run(alg, p)
        dlg = SetupDialog(suite_rows=None, open_algorithm=opener)
        dlg.data.setText(self.data)
        dlg.work.setText(work)
        dlg._select(dlg.state, "NE")
        self.assertEqual(dlg.preset.currentData(), "NE")      # the state's catalog preset is proposed
        dlg.rescan()
        self.assertEqual(dlg.problem(), "")
        self.assertTrue(dlg.next_btn.isEnabled())
        self.assertEqual(dlg.continue_to_screener()[0], "damit_screen:preflight")
        self.assertEqual(ran["params"]["FIELD_MAP"], "dam_id=NIDID,height_ft=NID_HEIGHT,name=DAM_NAME")
        self.assertEqual(ran["params"]["PRESET"], "NE")
        self.assertTrue(os.path.exists(os.path.join(work, "damit_screen_settings.json")))
        self.assertTrue(os.path.exists(os.path.join(work, "preflight.txt")))
        self.assertEqual(settings.get("data_folder"), self.data)
        self.assertEqual(settings.get("dams_layer"), self.dams_path)

    def test_dialog_blocks_without_catalog(self):
        from damit_core.lib import plugins
        from damit_setup.dialog import SetupDialog
        rows = [dict(r, present=False) if r["folder"] == "damit_catalog" else r
                for r in plugins.check_suite(dirs=[ROOT], active=[])]
        dlg = SetupDialog(suite_rows=rows, open_algorithm=lambda a, p: self.fail("must not open"))
        dlg.data.setText(self.data)
        dlg.work.setText(os.path.join(self.tmp, "w"))
        dlg.rescan()
        self.assertIn("DamIT Catalog", dlg.reason.text())
        self.assertFalse(dlg.next_btn.isEnabled())
        self.assertIsNone(dlg.continue_to_screener())


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class Data(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DAMIT_SETTINGS"] = os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_download_nsi_extent_status_and_add_layers(self):
        import processing
        from fakehttp import FakeHttp, nsi_fixture
        from damit_data.algorithms.download import DownloadAlgorithm
        from damit_data.provider import DamitDataProvider
        import damit_data
        QH.add_provider(DamitDataProvider())
        fake = FakeHttp(json_by_url=lambda u: nsi_fixture())
        DownloadAlgorithm.http_client = fake
        try:
            root = os.path.join(self.tmp, "DamIT Data")
            r = processing.run("damit_data:download", {"STATE": 0, "EXTENT": "-96.792,-96.789,46.874,46.876 [EPSG:4326]",
                                                       "SOURCES": [0], "FOLDER": root})
            self.assertEqual(r["UPDATED"], 1)
            self.assertTrue(fake.calls[0][1].startswith("https://nsi.sec.usace.army.mil/nsiapi/structures?bbox="))
            st = processing.run("damit_data:status", {"FOLDER": root})
            self.assertEqual(st["ENTRIES"], 1)
            with self.assertRaises(QgsProcessingException):
                processing.run("damit_data:download", {"STATE": 0, "SOURCES": [1], "FOLDER": root})  # footprints need a state
            with self.assertRaises(QgsProcessingException):
                processing.run("damit_data:download", {"STATE": 1, "SOURCES": [0],
                                                       "FOLDER": os.path.join(self.tmp, "ND_Dam_Suite_Pack")})
            plug = damit_data.classFactory(QH.FakeIface())
            proj = QgsProject()
            added = plug.add_layers(root, proj)
            self.assertEqual(len(added), 1)
            self.assertEqual(added[0].featureCount(), 3)
        finally:
            DownloadAlgorithm.http_client = None


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class HazardLite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        from damit_hazardlite.provider import DamitLiteProvider
        QH.add_provider(DamitLiteProvider())
        cls.tmp = tempfile.mkdtemp()
        # 40 x 40 cells of 10 m from (500000, 5000400): depth grows to the east (0 .. 3.9 m)
        depth = np.tile(np.arange(40, dtype="float32") * 0.1, (40, 1))
        depth[:, :5] = -9999.0                                     # nodata = dry
        vel = np.full((40, 40), 1.0, dtype="float32")
        cls.depth = write_tif(os.path.join(cls.tmp, "depth.tif"), depth, 500000, 5000400, 10, 26914)
        cls.vel = write_tif(os.path.join(cls.tmp, "vel.tif"), vel, 500000, 5000400, 10, 26914)
        cls.structs = mem_layer("Polygon", "EPSG:26914", [("occtype", "string"), ("pop", "double")], [
            ("POLYGON((500300 5000300,500312 5000300,500312 5000312,500300 5000312,500300 5000300))", ["RES1-1SNB", 3]),
            ("POLYGON((500010 5000300,500020 5000300,500020 5000310,500010 5000310,500010 5000300))", ["RES1-1SNB", 2]),
            ("POLYGON((600000 5000300,600010 5000300,600010 5000310,600000 5000310,600000 5000300))", ["COM1", 0])])
        cls.roads = mem_layer("LineString", "EPSG:4326", [("highway", "string"), ("aadt", "double"), ("name", "string")], [
            ("LINESTRING(-99.0000 45.1500,-98.9999 45.1501)", ["residential", 50, "far away"])])
        cls.roads.dataProvider().addFeatures([cls._road(cls.roads)])
        cls.rail = mem_layer("LineString", "EPSG:26914", [("tpd", "double")], [
            ("LINESTRING(500350 5000050,500350 5000350)", [8])])

    @staticmethod
    def _road(lyr):
        from qgis.core import QgsCoordinateTransform
        g = QgsGeometry.fromWkt("LINESTRING(500100 5000200,500390 5000200)")
        g.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:26914"),
                                           QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()))
        f = QgsFeature(lyr.fields())
        f.setGeometry(g)
        f.setAttributes(["motorway", 30000, "I-94"])
        return f

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_lite(self, out, **kw):
        import processing
        p = {"DEPTH": self.depth, "DEPTH_UNITS": 1, "VELOCITY": self.vel, "VELOCITY_UNITS": 1,
             "STRUCTURES": self.structs, "STRUCTURE_TYPE_FIELD": "occtype", "OCCUPANTS_FIELD": "pop",
             "ROADS": self.roads, "ROAD_CLASS_FIELD": "highway", "AADT_FIELD": "aadt",
             "RAIL": self.rail, "TRAINS_FIELD": "tpd", "MODE": 0, "PRESET": "ND", "MODEL_DIMENSION": 2,
             "OUTPUT_FOLDER": os.path.join(self.tmp, out), "OUTPUT": "memory:"}
        p.update(kw)
        return processing.run("damit_lite:classify", p)

    def test_nd_preset(self):
        r = self.run_lite("nd")
        self.assertEqual(r["SUGGESTED_ORDINAL"], 3)
        with open(r["RESULT_JSON"]) as fh:
            doc = json.load(fh)
        recs = {x["id"]: x for x in doc["receptors"]}
        self.assertEqual(len(recs), 6)
        s0 = recs["structure:1"]
        self.assertTrue(s0["wet"])
        self.assertAlmostEqual(s0["depth_ground_ft"], 3.0 * 3.280839895, places=2)   # only column 30 (3.0 m) has its centre in the grown outline
        self.assertFalse(recs["structure:2"]["wet"])                                 # in the nodata band
        self.assertFalse(recs["structure:3"]["in_domain"])                           # off the raster
        self.assertEqual(recs["road:2"]["road_class"], "interstate")                 # reprojected from EPSG:4326
        self.assertTrue(recs["road:2"]["wet"])
        self.assertFalse(recs["road:1"]["in_domain"])
        self.assertIn("M8a", {h["method"] for h in doc["result"]["driving"]})
        self.assertTrue(any(f.get("method") == "M1" for f in doc["result"]["flags"]))   # no m1_zone field: flagged
        self.assertEqual(r["OUTPUT"].featureCount(), 6)
        for name in ("receptors.csv", "hazard_lite_summary.md"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "nd", name)))

    def test_other_presets_and_custom(self):
        ne = self.run_lite("ne", PRESET="NE")
        with open(ne["RESULT_JSON"]) as fh:
            self.assertEqual(json.load(fh)["result"]["preset_id"], "NE")
        usbr = self.run_lite("usbr", PRESET="USBR_TM11")
        with open(usbr["RESULT_JSON"]) as fh:
            self.assertEqual(json.load(fh)["result"]["preset_id"], "USBR")
        cu = self.run_lite("custom", MODE=1, PRESET="", METHODS="M9a")
        self.assertEqual(cu["SUGGESTED_ORDINAL"], 2)                 # active rail, 8 trains/day < 10, wet
        with self.assertRaises(QgsProcessingException):
            self.run_lite("bad", PRESET="")
        with self.assertRaises(QgsProcessingException):
            self.run_lite("bad2", PRESET="ZZ")


class FakePFDS(object):
    def __init__(self, name):
        with open(os.path.join(FIX_PMP, name), "rb") as fh:
            self.data = fh.read()
        self.urls = []

    def get_bytes(self, url, timeout=60):
        self.urls.append(url)
        return self.data


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class PMP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from damit_pmp.provider import DamitPmpProvider
        from damit_pmp.algorithms import pf_algs
        QH.add_provider(DamitPmpProvider())
        pf_algs._Base.pause_s = 0
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        from damit_pmp.algorithms import pf_algs
        pf_algs._Base.http_client = None
        pf_algs._Base.pause_s = 1.0
        shutil.rmtree(cls.tmp)

    def setUp(self):
        from damit_pmp.algorithms import pf_algs
        self.fake = FakePFDS("pfds_pds_english_fargo_nd.txt")
        pf_algs._Base.http_client = self.fake

    def test_point_projected_crs_and_hyetograph(self):
        import processing
        out = os.path.join(self.tmp, "pt")
        r = processing.run("damit_pmp:pointpf", {"POINT": "669000,5193000 [EPSG:26914]", "CACHE_DIR": os.path.join(out, "c"),
                                                 "OUTPUT_CSV": os.path.join(out, "a14.csv"),
                                                 "OUTPUT_JSON": os.path.join(out, "a14.json")})
        self.assertEqual(r["DEPTH_100YR_24HR"], 6.47)
        self.assertIn("Volume 8 Version 2", r["VOLUME"])
        self.assertRegex(self.fake.urls[0], r"lat=46\.8\d+&lon=-96\.\d+")
        with open(r["OUTPUT_JSON"]) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["sources"][0]["source"], "NOAA Atlas 14 (PFDS)")
        self.assertIn("NOAA Atlas 14 Volume 8", doc["citation"])
        h = processing.run("damit_pmp:hyetograph", {"INPUT_JSON": r["OUTPUT_JSON"], "FREQUENCY": 100,
                                                    "STEP_MIN": 30, "OUTPUT_CSV": os.path.join(out, "hyeto.csv")})
        self.assertAlmostEqual(h["TOTAL"], 6.47, places=3)
        with self.assertRaises(QgsProcessingException):
            processing.run("damit_pmp:hyetograph", {"INPUT_JSON": r["OUTPUT_JSON"], "FREQUENCY": 3,
                                                    "OUTPUT_CSV": os.path.join(out, "bad.csv")})

    def test_basin_points_and_cache(self):
        import processing
        basin = mem_layer("Polygon", "EPSG:4326", [("id", "integer")],
                          [("POLYGON((-96.9 46.8,-96.7 46.8,-96.7 46.95,-96.9 46.95,-96.9 46.8))", [1])])
        out = os.path.join(self.tmp, "basin")
        args = {"BASIN": basin, "MAX_POINTS": 5, "COMBINE": 0, "CACHE_DIR": os.path.join(out, "c"),
                "OUTPUT_CSV": os.path.join(out, "b.csv"), "OUTPUT_JSON": os.path.join(out, "b.json"), "POINTS": "memory:"}
        r = processing.run("damit_pmp:basinpf", args)
        self.assertEqual(r["POINTS"].featureCount(), 5)
        self.assertEqual(len(self.fake.urls), 5)
        self.assertEqual(r["DEPTH_100YR_24HR"], 6.47)
        r2 = processing.run("damit_pmp:basinpf", dict(args, OFFLINE=True))       # all from the cache
        self.assertEqual(len(self.fake.urls), 5)
        self.assertEqual(r2["DEPTH_100YR_24HR"], 6.47)

    def test_outside_atlas14_fails_clearly(self):
        import processing
        from damit_pmp.algorithms import pf_algs
        pf_algs._Base.http_client = FakePFDS("pfds_no_coverage_portland_or.txt")
        out = os.path.join(self.tmp, "or")
        with self.assertRaises(QgsProcessingException) as cm:
            processing.run("damit_pmp:pointpf", {"POINT": "-122.68,45.52 [EPSG:4326]", "CACHE_DIR": os.path.join(out, "c"),
                                                 "OUTPUT_CSV": os.path.join(out, "a.csv"), "OUTPUT_JSON": os.path.join(out, "a.json")})
        self.assertIn("does not cover", str(cm.exception))

    def test_gridbasin(self):
        import processing
        import numpy as np
        # an Atlas 14-style grid: geographic, thousandths of an inch
        a = np.full((20, 20), 6470, dtype="float32")
        a[:, 10:] = 7000
        grid = write_tif(os.path.join(self.tmp, "mw100yr24ha.tif"), a, -97.0, 47.0, 0.01, 4269)
        basin = mem_layer("Polygon", "EPSG:26914", [("id", "integer")], [])
        from qgis.core import QgsCoordinateTransform
        g = QgsGeometry.fromWkt("POLYGON((-96.995 46.85,-96.905 46.85,-96.905 46.95,-96.995 46.95,-96.995 46.85))")
        g.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
                                           QgsCoordinateReferenceSystem("EPSG:26914"), QgsProject.instance()))
        f = QgsFeature(basin.fields())
        f.setGeometry(g)
        f.setAttributes([1])
        basin.dataProvider().addFeatures([f])
        r = processing.run("damit_pmp:gridbasin", {"GRID": grid, "BASIN": basin,
                                                   "OUTPUT_JSON": os.path.join(self.tmp, "g.json")})
        self.assertAlmostEqual(r["MEAN"], 6.47, places=2)
        with open(r["OUTPUT_JSON"]) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["grid_name"], {"region_code": "mw", "frequency_years": 100, "duration": "24-hr",
                                            "series": "pds"})


if __name__ == "__main__":
    unittest.main()
