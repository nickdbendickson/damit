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
try:      # import scipy now: numpy 2's numpy.testing may run `lscpu` on first import, inside a test that bans processes
    import scipy.ndimage  # noqa: F401
except ImportError:                                            # pragma: no cover - the ANUGA tests need it
    pass

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


def _slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


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


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class PMPGrids(unittest.TestCase):
    """damit_pmp 0.3.0 tools: fetchgrid, gridbasin (fetch route) and raingrid with a fake PFDS and a fake NOAA download."""

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
        pf_algs._GridChoice.grid_downloader = None
        shutil.rmtree(cls.tmp)

    def setUp(self):
        from damit_pmp.algorithms import pf_algs
        from damit_pmp.tests.test_gis_rain import fake_noaa_zip
        self.pfds = FakePFDS("pfds_pds_english_fargo_nd.txt")
        pf_algs._Base.http_client = self.pfds
        self.urls = []
        self.cache = tempfile.mkdtemp(dir=self.tmp)

        def dl(url, dest):
            self.urls.append(url)
            # 3 x 3 cells of 0.01 deg over lon -97.0..-96.97, lat 46.9..46.93 (thousandths of an inch)
            fake_noaa_zip(dest, [[6300, 6310, 6320], [6342, 6350, 6360], [6400, 6410, -9]], x0=-97.0, y0=46.9, cell=0.01)
        pf_algs._GridChoice.grid_downloader = dl

    def fetch(self, name, **kw):
        import processing
        out = os.path.join(self.tmp, name)
        args = {"POINT": "-96.985,46.915 [EPSG:4326]", "BUFFER_KM": 0.5, "FREQUENCY": 100, "DURATION": 9,
                "CACHE_DIR": self.cache, "OUTPUT": out + ".tif"}
        args.update(kw)
        return processing.run("damit_pmp:fetchgrid", args), out

    def test_fetchgrid_inches_sidecar_and_cache(self):
        r, out = self.fetch("g1")
        self.assertEqual(self.urls, ["https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw100yr24ha.zip"])   # region mw from PFDS
        self.assertIn("lat=46.9150&lon=-96.9850", self.pfds.urls[0])
        self.assertAlmostEqual(r["POINT_VALUE"], 6.35, places=3)                                       # cell holding the point
        with open(out + ".tif.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["units"], doc["value_scale"], doc["frequency_years"], doc["duration"], doc["bound"]),
                         ("in", 1.0, 100, "24-hr", "estimate"))
        self.assertEqual(doc["url"], self.urls[0])
        self.assertIn("NOAA Atlas 14 Volume 8", doc["citation"])
        self.assertEqual(doc["grid_metadata"]["pubdate"], "20130415")
        self.assertEqual(len(doc["sha256"]), 64)
        r2, _ = self.fetch("g2")                                       # second call: cached zip and PFDS answer
        self.assertEqual(len(self.urls), 1)
        self.assertEqual(len(self.pfds.urls), 1)
        r3, _ = self.fetch("g3", OFFLINE=True)
        self.assertAlmostEqual(r3["MEAN"], r["MEAN"])

    def test_fetchgrid_choices_change_the_file(self):
        self.fetch("c1", FREQUENCY=500, DURATION=7, BOUND=2, REGION=2)
        self.fetch("c2", SERIES=1, FREQUENCY=10, DURATION=10, REGION=2)
        self.assertEqual([u.rsplit("/", 1)[1] for u in self.urls], ["mw500yr06hau.zip", "mw10yr48ha_ams.zip"])

    def test_fetchgrid_extent_and_basin_mask(self):
        r, _ = self.fetch("e1", POINT=None, EXTENT="-97.0,-96.99,46.9,46.91 [EPSG:4326]")
        self.assertGreater(r["MEAN"], 6.29)
        self.assertLess(r["MEAN"], 6.42)
        basin = mem_layer("Polygon", "EPSG:4326", [("id", "integer")],
                          [("POLYGON((-97.0 46.92,-96.99 46.92,-96.99 46.93,-97.0 46.93,-97.0 46.92))", [1])])
        r2, _ = self.fetch("e2", POINT=None, BASIN=basin, MASK_TO_BASIN=True, REGION=2)
        self.assertAlmostEqual(r2["MEAN"], 6.3, places=3)               # the top-left cell only

    def test_fetchgrid_errors(self):
        import processing
        from damit_pmp.algorithms import pf_algs
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x1", FREQUENCY=3)
        self.assertIn("not an Atlas 14 PDS frequency", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x2", SERIES=1, FREQUENCY=1)
        self.assertIn("AMS", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x3", POINT=None)                                # nothing to find the region from
        self.assertIn("so the Atlas 14 region can be found", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x4", CACHE_DIR=os.path.join(self.tmp, "empty"), OFFLINE=True, REGION=2, FREQUENCY=25)
        self.assertIn("offline", str(cm.exception))
        from damit_core.lib.http import HttpError

        def nf(url, dest):
            raise HttpError(url, 404, "Not Found")
        pf_algs._GridChoice.grid_downloader = nf
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x5", REGION=2, FREQUENCY=2, DURATION=0)
        self.assertIn("has not published mw2yr05ma.zip", str(cm.exception))

        def down(url, dest):
            raise HttpError(url, None, "network is unreachable")
        pf_algs._GridChoice.grid_downloader = down
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x6", REGION=2, FREQUENCY=5, DURATION=0)
        self.assertIn("download failed", str(cm.exception))
        pf_algs._Base.http_client = FakePFDS("pfds_no_coverage_portland_or.txt")
        with self.assertRaises(QgsProcessingException) as cm:
            self.fetch("x7", POINT="-122.68,45.52 [EPSG:4326]")
        self.assertIn("does not cover", str(cm.exception))

    def test_gridbasin_fetch_route_and_fetchgrid_tif(self):
        import processing
        basin = mem_layer("Polygon", "EPSG:4326", [("id", "integer")],
                          [("POLYGON((-97.0 46.9,-96.97 46.9,-96.97 46.93,-97.0 46.93,-97.0 46.9))", [1])])
        r = processing.run("damit_pmp:gridbasin", {"BASIN": basin, "FREQUENCY": 100, "DURATION": 9,
                                                   "CACHE_DIR": self.cache,
                                                   "OUTPUT_JSON": os.path.join(self.tmp, "gb.json")})
        self.assertAlmostEqual(r["MEAN"], sum([6.3, 6.31, 6.32, 6.342, 6.35, 6.36, 6.4, 6.41]) / 8, places=3)
        with open(r["OUTPUT_JSON"]) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["grid_name"]["duration"], "24-hr")
        self.assertEqual(doc["fetch"]["url"], "https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw100yr24ha.zip")
        # the fetchgrid GeoTIFF is in inches: gridbasin must not apply 0.001 again
        g, out = self.fetch("gb_in", POINT=None, EXTENT="-97.0,-96.97,46.9,46.93 [EPSG:4326]", REGION=2)
        r2 = processing.run("damit_pmp:gridbasin", {"GRID": g["OUTPUT"], "BASIN": basin,
                                                    "OUTPUT_JSON": os.path.join(self.tmp, "gb2.json")})
        self.assertAlmostEqual(r2["MEAN"], r["MEAN"], places=3)

    def test_same_duration_index_in_every_tool(self):
        """STORM (hyetograph, raingrid) and DURATION (fetchgrid, gridbasin) are one list: index i = same duration."""
        import processing
        from qgis.core import QgsApplication, QgsProcessingException
        from damit_pmp import atlas14 as A
        reg = QgsApplication.processingRegistry()
        for alg, name in (("hyetograph", "STORM"), ("raingrid", "STORM"), ("fetchgrid", "DURATION"), ("gridbasin", "DURATION")):
            p = reg.algorithmById("damit_pmp:" + alg).parameterDefinition(name)
            self.assertEqual(list(p.options()), A.DURATION_LABELS, alg)
            self.assertEqual(p.defaultValue(), 9, alg)
            self.assertEqual(A.DURATION_LABELS[p.defaultValue()], "24-hr")
        pt = processing.run("damit_pmp:pointpf", {"POINT": "-96.985,46.915 [EPSG:4326]", "CACHE_DIR": self.cache,
                                                  "OUTPUT_CSV": os.path.join(self.tmp, "ip.csv"),
                                                  "OUTPUT_JSON": os.path.join(self.tmp, "ip.json")})
        for idx, label in ((9, "24-hr"), (7, "6-hr"), (6, "3-hr")):
            h = processing.run("damit_pmp:hyetograph", {"INPUT_JSON": pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": idx,
                                                        "STEP_MIN": 30, "OUTPUT_CSV": os.path.join(self.tmp, "i%d.csv" % idx)})
            with open(os.path.join(self.tmp, "i%d.csv" % idx)) as fh:
                self.assertIn("storm_min={}".format(A.duration_minutes(label)), fh.read())
            r = processing.run("damit_pmp:raingrid", {"INPUT_JSON": pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": idx,
                                                      "STEP_MIN": 30, "OUTPUT_RAIN": os.path.join(self.tmp, "i%d.rain" % idx),
                                                      "OUTPUT_ANUGA": os.path.join(self.tmp, "i%d_a.csv" % idx),
                                                      "OUTPUT_JSON": os.path.join(self.tmp, "i%d_r.json" % idx)})
            self.assertAlmostEqual(r["TOTAL_MM"], h["TOTAL"] * 25.4, places=2, msg=label)
        self.fetch("same_idx", DURATION=7, FREQUENCY=100)                    # 6-hr
        self.assertTrue(self.urls[-1].endswith("mw100yr06ha.zip"), self.urls[-1])

    def test_storms_that_cannot_be_built_say_why(self):
        import processing
        from qgis.core import QgsProcessingException
        pt = processing.run("damit_pmp:pointpf", {"POINT": "-96.985,46.915 [EPSG:4326]", "CACHE_DIR": self.cache,
                                                  "OUTPUT_CSV": os.path.join(self.tmp, "jp.csv"),
                                                  "OUTPUT_JSON": os.path.join(self.tmp, "jp.json")})
        for alg, extra in (("hyetograph", {"OUTPUT_CSV": os.path.join(self.tmp, "x.csv")}),
                           ("raingrid", {"OUTPUT_RAIN": os.path.join(self.tmp, "x.rain"),
                                         "OUTPUT_ANUGA": os.path.join(self.tmp, "x_a.csv"),
                                         "OUTPUT_JSON": os.path.join(self.tmp, "x.json")})):
            base = dict({"INPUT_JSON": pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": 0, "STEP_MIN": 60}, **extra)
            with self.assertRaises(QgsProcessingException) as cm:             # 5-min storm, 60-min step
                processing.run("damit_pmp:" + alg, base)
            self.assertIn("5-min (5 min) is shorter than the time step of 60 min", str(cm.exception))
            ok = processing.run("damit_pmp:" + alg, dict(base, STEP_MIN=5))   # the same storm with a fitting step
            self.assertTrue(ok)

    # ---- damit_pmp:anugarain (the runner's gmsh mesh for ANUGA rain-on-grid); nothing is launched here ----
    def _anuga_inputs(self, name):
        import numpy as np
        from damit_pmp.tests.test_anuga_rain import make_dem
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        dem = os.path.join(d, "dem.tif")
        make_dem(dem)
        rate = os.path.join(d, "rate.csv")
        with open(rate, "w") as fh:
            fh.write("time_s,rate_m_per_s\n0,2.0e-7\n3599,2.0e-7\n3600,0\n7200,0\n")
        return d, dem, rate, np

    def test_anugarain_writes_the_job_and_launches_nothing(self):
        import processing
        d, dem, rate, np = self._anuga_inputs("anuga1")
        out = os.path.join(d, "job")
        r = processing.run("damit_pmp:anugarain", {
            "DEM": dem, "EXTENT": "501000,503000,5196800,5198800 [EPSG:26914]", "RATE_CSV": rate, "CELL_M": 30,
            "FLOW_PATH_START": "501500,5198300 [EPSG:26914]", "MAX_AREA_M2": 40000, "OUTPUT_DIR": out})
        self.assertEqual(r["MESH"], "")                                     # no ANUGA Python: no mesh, no launch
        self.assertEqual(r["TRIANGLES"], 0)
        for f in ("run_anuga_rain.py", "gmsh_mesher.py", "anuga_worker.py", "omp_probe.py", "anuga_dtdiag.py",
                  "gmsh_mesh_in.json", "anuga_rain_job.npz", "rain_rate_m_per_s.csv", "run_manifest.json"):
            self.assertTrue(os.path.exists(os.path.join(out, f)), f)
        self.assertFalse(os.path.exists(os.path.join(out, "gmsh_mesh.npz")))
        with open(os.path.join(out, "run_manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["launched"], {"anuga": False, "gmsh_mesher": False, "result": None})
        self.assertEqual((m["settings"]["algorithm"], m["settings"]["edge_bc"], m["settings"]["manning_n"]),
                         ("DE0", "outflow", 0.06))
        self.assertAlmostEqual(m["rain"]["depth_mm"], 2.0e-7 * 3599.5 * 1000, places=3)
        from damit_pmp import anugarain as AR
        self.assertEqual(m["runner_shared_sha256"], AR.runner_sources())
        self.assertEqual(m["files"]["gmsh_mesher.py"]["sha256"], AR.runner_sources()["gmsh_mesher.py"])
        with open(os.path.join(out, "gmsh_mesh_in.json")) as fh:
            spec = json.load(fh)
        self.assertEqual(spec["max_area_m2"], 40000.0)
        self.assertEqual(len(spec["channel"]), 1)                           # the flow path
        self.assertEqual(spec["lines"], [])
        job = np.load(os.path.join(out, "anuga_rain_job.npz"))
        self.assertEqual(float(job["sim_time"]), 7200.0 + 6 * 3600.0)       # rain series end + 6 h

    def test_anugarain_basin_and_factor_raster(self):
        import processing
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorFileWriter, QgsVectorLayer, QgsCoordinateTransformContext
        d, dem, rate, np = self._anuga_inputs("anuga2")
        shp = os.path.join(d, "basin.gpkg")
        lyr = QgsVectorLayer("Polygon?crs=EPSG:26914", "b", "memory")
        f = QgsFeature()
        cx, cy = 502500.0, 5198500.0
        a = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(cx + 900 * np.cos(t), cy + 900 * np.sin(t)) for t in a]]))
        lyr.dataProvider().addFeatures([f])
        QgsVectorFileWriter.writeAsVectorFormatV3(lyr, shp, QgsCoordinateTransformContext(), QgsVectorFileWriter.SaveVectorOptions())
        fac = os.path.join(d, "factor.tif")
        from osgeo import gdal, osr
        ds = gdal.GetDriverByName("GTiff").Create(fac, 20, 20, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((501000.0, 150.0, 0, 5200000.0, 0, -150.0))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(26914)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.full((20, 20), 1.2, dtype="float32"))
        ds.FlushCache()
        ds = None
        out = os.path.join(d, "job")
        processing.run("damit_pmp:anugarain", {"DEM": dem, "BASIN": shp, "RATE_CSV": rate, "FACTOR_RASTER": fac, "CELL_M": 30,
                                               "EDGE_BC": 1, "SIM_TIME_H": 3.0, "OUTPUT_DIR": out})
        with open(os.path.join(out, "run_manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["settings"]["edge_bc"], "transmissive")
        self.assertEqual(m["settings"]["sim_time_s"], 10800.0)
        self.assertIn("factor", m["rain"]["spatial"])
        self.assertAlmostEqual(m["inputs"]["factor_raster"]["stats_on_model_grid"]["mean"], 1.2, places=3)
        self.assertAlmostEqual(m["domain"]["area_km2"], np.pi * 0.9 ** 2, delta=0.25)
        import numpy
        job = numpy.load(os.path.join(out, "anuga_rain_job.npz"))
        self.assertAlmostEqual(float(numpy.nanmean(job["factor"])), 1.2, places=3)

    def test_anugarain_refusals(self):
        import processing
        from qgis.core import QgsProcessingException
        d, dem, rate, np = self._anuga_inputs("anuga3")
        base = {"DEM": dem, "EXTENT": "501000,503000,5196800,5198800 [EPSG:26914]", "RATE_CSV": rate, "CELL_M": 30,
                "OUTPUT_DIR": os.path.join(d, "o")}
        with self.assertRaises(QgsProcessingException) as cm:               # no basin and no extent
            processing.run("damit_pmp:anugarain", {k: v for k, v in base.items() if k != "EXTENT"})
        self.assertIn("basin polygon or an extent", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:               # running needs an interpreter
            processing.run("damit_pmp:anugarain", dict(base, RUN_ANUGA=True))
        self.assertIn("RUN_ANUGA needs the ANUGA Python", str(cm.exception))
        with self.assertRaises(QgsProcessingException):                     # an interpreter that does not exist
            processing.run("damit_pmp:anugarain", dict(base, ANUGA_PYTHON="/no/such/python"))
        with self.assertRaises(QgsProcessingException) as cm:               # mm/hr instead of m/s
            bad = os.path.join(d, "bad.csv")
            with open(bad, "w") as fh:
                fh.write("time_s,rate\n0,60\n3600,0\n")
            processing.run("damit_pmp:anugarain", dict(base, RATE_CSV=bad))
        self.assertIn("m/s", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:               # bad mesher sizing: the mesher's message
            processing.run("damit_pmp:anugarain", dict(base, GRADE_DIST_M=10.0))
        self.assertIn("grade_dist_m", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(d, "o", "gmsh_mesh.npz")))

    def test_raingrid_files_units_and_scaling(self):
        import processing
        out = os.path.join(self.tmp, "rain")
        os.makedirs(out, exist_ok=True)
        # build a hyetograph with the real tool from the Fargo answer
        pt = processing.run("damit_pmp:pointpf", {"POINT": "-96.8,46.9 [EPSG:4326]", "CACHE_DIR": os.path.join(out, "c"),
                                                  "OUTPUT_CSV": os.path.join(out, "a.csv"),
                                                  "OUTPUT_JSON": os.path.join(out, "a.json")})
        h = processing.run("damit_pmp:hyetograph", {"INPUT_JSON": pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": 9,
                                                    "STEP_MIN": 60, "OUTPUT_CSV": os.path.join(out, "h.csv")})
        self.assertAlmostEqual(h["TOTAL"], 6.47, places=3)
        args = {"INPUT_CSV": os.path.join(out, "h.csv"), "OUTPUT_RAIN": os.path.join(out, "s.rain"),
                "OUTPUT_ANUGA": os.path.join(out, "s_anuga.csv"), "OUTPUT_JSON": os.path.join(out, "s.json")}
        r = processing.run("damit_pmp:raingrid", args)
        self.assertAlmostEqual(r["TOTAL_MM"], 6.47 * 25.4, places=2)
        lines = _slurp(args["OUTPUT_RAIN"]).splitlines()
        self.assertTrue(lines[0].startswith("#"))
        self.assertEqual(lines[1], "49 seconds")                # 24 blocks x 2 points + the 0 mm/hr end
        self.assertEqual(len(lines), 51)
        rec = json.loads(_slurp(args["OUTPUT_JSON"]))
        self.assertLess(abs(rec["series_depth_error_pct"]), 0.01)
        self.assertEqual(rec["hyetograph"]["frequency_years"], "100")
        self.assertIn("anuga.Rate_operator", _slurp(os.path.join(out, "s_anuga_README.txt")))
        # the JSON route gives the same storm
        r_js = processing.run("damit_pmp:raingrid", dict(args, INPUT_CSV="", INPUT_JSON=pt["OUTPUT_JSON"], FREQUENCY=100,
                                                         STORM=9, STEP_MIN=60, OUTPUT_RAIN=os.path.join(out, "j.rain")))
        self.assertAlmostEqual(r_js["TOTAL_MM"], r["TOTAL_MM"], places=3)
        self.assertEqual(_slurp(os.path.join(out, "j.rain")).splitlines()[1:], lines[1:])
        # rescale to an Atlas 14 grid at a point, hours, SIM_TIME and a factor raster
        g, _ = self.fetch("rg", POINT="-96.985,46.915 [EPSG:4326]", BUFFER_KM=1.0)
        r3 = processing.run("damit_pmp:raingrid", dict(
            args, SCALE_GRID=g["OUTPUT"], SCALE_POINT="-96.985,46.915 [EPSG:4326]", TIME_UNIT=1, SIM_TIME_H=30,
            OUTPUT_RAIN=os.path.join(out, "g.rain"), FACTOR_RASTER=os.path.join(out, "f.tif")))
        self.assertAlmostEqual(r3["TOTAL_MM"], 6.35 * 25.4, places=2)
        txt = _slurp(os.path.join(out, "g.rain")).splitlines()
        self.assertTrue(txt[1].endswith(" hours"))
        self.assertTrue(txt[-1].startswith("0.00000 30"))
        from osgeo import gdal
        fds = gdal.Open(os.path.join(out, "f.tif"))
        fa = fds.GetRasterBand(1).ReadAsArray()
        self.assertAlmostEqual(float(fa.max()), 6.41 / 6.35, places=3)
        # a grid for another duration is refused
        g2, _ = self.fetch("rg2", DURATION=7)
        with self.assertRaises(QgsProcessingException) as cm:
            processing.run("damit_pmp:raingrid", dict(args, SCALE_GRID=g2["OUTPUT"], SCALE_POINT="-96.985,46.915 [EPSG:4326]"))
        self.assertIn("scale grid is for the 6-hr duration", str(cm.exception))


@unittest.skipUnless(QH.HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class PMPPatternsLossesWatershedLisflood(unittest.TestCase):
    """damit_pmp 0.4.0: temporal patterns and losses in hyetograph / raingrid, damit_pmp:watershed and
    damit_pmp:lisfloodrain, with a fake PFDS, a fake HDSC download and a fake 3DEP service. Nothing is launched."""

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
        from damit_pmp import demfetch
        pf_algs._Base.http_client = None
        pf_algs._Base.temporal_downloader = None
        demfetch.OPENER = None
        shutil.rmtree(cls.tmp)

    def setUp(self):
        import processing
        from damit_pmp.algorithms import pf_algs
        pf_algs._Base.http_client = FakePFDS("pfds_pds_english_fargo_nd.txt")
        self.urls = []

        def dl(url, dest):
            self.urls.append(url)
            shutil.copyfile(os.path.join(FIX_PMP, "mw_2_24h_temporal.csv"), dest)
        pf_algs._Base.temporal_downloader = dl
        self.cache = tempfile.mkdtemp(dir=self.tmp)
        self.pt = processing.run("damit_pmp:pointpf", {"POINT": "-96.985,46.915 [EPSG:4326]", "CACHE_DIR": self.cache,
                                                       "OUTPUT_CSV": os.path.join(self.cache, "p.csv"),
                                                       "OUTPUT_JSON": os.path.join(self.cache, "p.json")})

    def hyeto(self, name, **kw):
        import processing
        out = os.path.join(self.cache, name + ".csv")
        args = {"INPUT_JSON": self.pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": 9, "STEP_MIN": 60, "OUTPUT_CSV": out,
                "CACHE_DIR": os.path.join(self.cache, "tc")}
        args.update(kw)
        r = processing.run("damit_pmp:hyetograph", args)
        with open(out) as fh:
            return r, fh.read()

    def test_default_hyetograph_has_no_loss_columns(self):
        r, txt = self.hyeto("d0")
        self.assertEqual(r["TOTAL"], r["EXCESS"])
        self.assertNotIn("loss_", txt)
        self.assertEqual(self.urls, [])

    def test_nrcs_type_ii_keeps_the_atlas_14_depth(self):
        r0, _ = self.hyeto("a0")
        r, txt = self.hyeto("n2", PATTERN=4, OUTPUT_JSON=os.path.join(self.cache, "n2.json"))
        self.assertAlmostEqual(r["TOTAL"], r0["TOTAL"], places=3)
        with open(os.path.join(self.cache, "n2.json")) as fh:
            j = json.load(fh)
        self.assertEqual(j["pattern"], "nrcs2")
        self.assertIn("shape option only", json.dumps(j))
        self.assertEqual(self.urls, [])                                     # NRCS needs no download

    def test_atlas_14_temporal_distribution_is_fetched_cited_and_recorded(self):
        r, txt = self.hyeto("t1", PATTERN=1, TDA=2, OUTPUT_JSON=os.path.join(self.cache, "t1.json"))
        self.assertEqual(self.urls, ["https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw_2_24h_temporal.csv"])
        with open(os.path.join(self.cache, "t1.json")) as fh:
            j = json.load(fh)
        rec = j["temporal"] if "temporal" in j else j["record"]
        self.assertEqual((rec["area"], rec["quartile"], rec["percent_of_occurrence"]), (2, "second", 50))
        self.assertEqual(len(rec["file"]["sha256"]), 64)
        self.assertIn("Shape only", rec["note"])
        self.assertIn("hdsc.nws.noaa.gov", txt)
        r2, _ = self.hyeto("t2", PATTERN=1, TDA=2, OFFLINE=True)             # now from the cache
        self.assertEqual(len(self.urls), 1)
        self.assertAlmostEqual(r2["TOTAL"], r["TOTAL"])

    def test_pattern_that_does_not_fit_the_storm_says_why(self):
        with self.assertRaises(QgsProcessingException) as cm:
            self.hyeto("bad1", STORM=6, PATTERN=1, TDA=2)                    # 3-hr
        self.assertIn("6-, 12-, 24- and 96-hour", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:
            self.hyeto("bad2", STORM=7, PATTERN=4)                           # 6-hr, NRCS 24 h
        self.assertIn("24-hour curve", str(cm.exception))

    def test_losses_in_inches_and_mm(self):
        r0, _ = self.hyeto("l0")
        r, txt = self.hyeto("l1", INITIAL_LOSS=0.5, CONSTANT_LOSS=0.05, LOSS_UNITS=0)
        self.assertAlmostEqual(r["TOTAL"], r0["TOTAL"], places=3)
        self.assertLess(r["EXCESS"], r0["TOTAL"] - 0.5)                    # at least the initial loss
        self.assertGreater(r["EXCESS"], r0["TOTAL"] - 0.5 - 0.05 * 24)     # at most the constant loss every hour
        self.assertIn("excess_in", txt)
        rm, txtm = self.hyeto("l2", INITIAL_LOSS=12.7, CONSTANT_LOSS=1.27, LOSS_UNITS=1)
        self.assertAlmostEqual(rm["EXCESS"], r["EXCESS"], delta=0.02)                      # the same losses given in mm
        self.assertIn("excess_in", txtm)                                                    # the table stays in the Atlas 14 unit

    def test_raingrid_pattern_and_losses_feed_both_solvers(self):
        import processing
        out = os.path.join(self.cache, "rg")
        args = {"INPUT_JSON": self.pt["OUTPUT_JSON"], "FREQUENCY": 100, "STORM": 9, "STEP_MIN": 30, "PATTERN": 4,
                "INITIAL_LOSS": 10, "CONSTANT_LOSS": 1, "LOSS_UNITS": 1, "OUTPUT_RAIN": out + ".rain",
                "OUTPUT_ANUGA": out + "_a.csv", "OUTPUT_JSON": out + ".json"}
        r = processing.run("damit_pmp:raingrid", args)
        self.assertGreater(r["GROSS_MM"], r["TOTAL_MM"])
        with open(out + ".json") as fh:
            j = json.load(fh)
        self.assertEqual(j["temporal_pattern"]["pattern"], "nrcs2")
        self.assertIn("losses", j)
        import numpy as np
        t, rate = np.loadtxt(out + "_a.csv", delimiter=",", skiprows=1, unpack=True)
        vol = float(getattr(np, "trapezoid", None) and np.trapezoid(rate, t) or np.trapz(rate, t)) * 1000.0
        self.assertAlmostEqual(vol, r["TOTAL_MM"], delta=0.05 * r["TOTAL_MM"])
        with self.assertRaises(QgsProcessingException):                     # nothing silently ignored: bad pattern for 3-hr
            processing.run("damit_pmp:raingrid", dict(args, STORM=6, OUTPUT_RAIN=out + "x.rain", OUTPUT_ANUGA=out + "x_a.csv",
                                                      OUTPUT_JSON=out + "x.json"))

    # ---- damit_pmp:watershed ----
    def _valley_dem(self, name, nx=90, ny=70, cell=30.0):
        import numpy as np
        rows, cols = np.indices((ny, nx))
        z = 300.0 + 0.9 * np.abs(rows - ny // 2) + 0.15 * cols
        path = os.path.join(self.cache, name)
        write_tif(path, z, 500000.0, 5200000.0, cell, 26914)
        return path, ny // 2, cell

    def test_watershed_from_a_dem(self):
        import processing
        from qgis.core import QgsVectorLayer
        from damit_pmp import demfetch
        dem, rc, cell = self._valley_dem("v.tif")
        demfetch.OPENER = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the network must not be used with a DEM"))
        x, y = 500000.0 + 4.5 * cell, 5200000.0 - (rc + 0.5) * cell
        out = os.path.join(self.cache, "ws")
        os.makedirs(out)
        r = processing.run("damit_pmp:watershed", {"POINT": "{},{} [EPSG:26914]".format(x, y + 40), "DEM": dem, "SNAP_M": 120,
                                                   "NID_AREA_SQMI": 1.5, "OUTPUT_BASIN": os.path.join(out, "b.gpkg"),
                                                   "OUTPUT_POUR": os.path.join(out, "p.gpkg"),
                                                   "OUTPUT_MASK": os.path.join(out, "m.tif"),
                                                   "OUTPUT_JSON": os.path.join(out, "w.json")})
        with open(os.path.join(out, "w.json")) as fh:
            j = json.load(fh)
        self.assertEqual(j["schema"], "damit.pmp.watershed")
        self.assertAlmostEqual(r["AREA_SQMI"], j["area"]["sqmi"], places=3)
        self.assertGreater(r["AREA_SQMI"], 0.5)
        self.assertAlmostEqual(j["ratio_to_nid"], r["AREA_SQMI"] / 1.5, places=2)
        self.assertEqual((j["nid_area_sqmi"], j["touches_dem_edge"]), (1.5, True))                  # the valley runs off the east edge: flagged
        lyr = QgsVectorLayer(os.path.join(out, "b.gpkg"), "b", "ogr")
        self.assertEqual(lyr.featureCount(), 1)
        self.assertAlmostEqual(next(lyr.getFeatures()).geometry().area() / 2589988.110336, r["AREA_SQMI"], delta=0.01)
        pour = next(QgsVectorLayer(os.path.join(out, "p.gpkg"), "p", "ogr").getFeatures()).geometry().asPoint()
        self.assertAlmostEqual(pour.y(), y, delta=cell)                     # snapped onto the channel row
        self.assertTrue(os.path.exists(os.path.join(out, "m.tif")))

    def test_watershed_fetches_3dep_and_widens_when_the_basin_touches_the_edge(self):
        import processing
        import numpy as np
        from urllib.parse import parse_qs, urlparse
        from damit_pmp import demfetch
        from damit_pmp.tests.test_watershed import tiff_bytes, _Resp
        calls = []

        def opener(url, timeout=None):
            q = parse_qs(urlparse(url).query)
            calls.append(url)
            w, h = (int(v) for v in q["size"][0].split(","))
            bbox = tuple(float(v) for v in q["bbox"][0].split(","))
            return _Resp(tiff_bytes(w, h, bbox, 5070, 300.0))
        demfetch.OPENER = opener
        out = os.path.join(self.cache, "wf")
        os.makedirs(out)
        r = processing.run("damit_pmp:watershed", {"POINT": "-97.3911392,46.9833779 [EPSG:4326]", "FETCH_RADIUS_KM": 1.0,
                                                   "FETCH_CELL_M": 30, "SNAP_M": 60, "WORK_DIR": out,
                                                   "OUTPUT_BASIN": os.path.join(out, "b.gpkg"),
                                                   "OUTPUT_JSON": os.path.join(out, "w.json")})
        self.assertTrue(calls)
        self.assertTrue(all("elevation.nationalmap.gov" in u for u in calls))
        with open(os.path.join(out, "w.json")) as fh:
            j = json.load(fh)
        self.assertIn("3DEP", j["dem"]["source"])
        self.assertIn("touches_dem_edge", j)
        self.assertIn("3D Elevation Program", j["dem"]["citation"])
        self.assertTrue(os.path.basename(j["dem"]["path"]).startswith("dem_3dep_30m_5070"))
        self.assertTrue(os.path.exists(j["dem"]["path"]))
        self.assertTrue(os.path.abspath(j["dem"]["path"]).startswith(os.path.abspath(out)))

    # ---- damit_pmp:lisfloodrain: writes the job, launches nothing by default ----
    def _lisflood_job(self, name, **kw):
        import processing
        from damit_pmp.tests.test_anuga_rain import make_dem
        d = os.path.join(self.cache, name)
        os.makedirs(d)
        dem = os.path.join(d, "dem.tif")
        make_dem(dem)
        rate = os.path.join(d, "rate.csv")
        with open(rate, "w") as fh:
            fh.write("time_s,rate_m_per_s\n0,2.0e-7\n3599,2.0e-7\n3600,0\n7200,0\n")
        args = {"DEM": dem, "EXTENT": "501000,503000,5196800,5198800 [EPSG:26914]", "RATE_CSV": rate, "CELL_M": 30,
                "SIM_TIME_H": 3, "GAUGE_A": "502000,5197700 [EPSG:26914]", "GAUGE_B": "502000,5197500 [EPSG:26914]",
                "FLOW_PATH_START": "501500,5198300 [EPSG:26914]", "OUTPUT_DIR": os.path.join(d, "job")}
        args.update(kw)
        return processing.run("damit_pmp:lisfloodrain", args), os.path.join(d, "job")

    def test_lisfloodrain_writes_the_job_and_launches_nothing(self):
        from qgis.core import QgsApplication
        p = QgsApplication.processingRegistry().algorithmById("damit_pmp:lisfloodrain").parameterDefinition("RUN_LISFLOOD")
        self.assertFalse(p.defaultValue())
        r, out = self._lisflood_job("lf1")
        for f in ("Model Terrain (LISFLOOD).tif", "rain.dem.asc", "rain.bci", "rain.rain", "rain.par", "rain.gauge",
                  "rain_rate_m_per_s.csv", "run_manifest.json"):
            self.assertTrue(os.path.exists(os.path.join(out, f)), f)
        self.assertFalse(os.path.exists(os.path.join(out, "results")))
        with open(os.path.join(out, "run_manifest.json")) as fh:
            m = json.load(fh)
        self.assertFalse(m["lisflood"]["launched"])
        self.assertIsNone(m["results"])
        self.assertEqual(m["settings"]["solver"], "acceleration")
        self.assertIn("rainfall rain.rain", m["settings"]["par_lines"])
        self.assertAlmostEqual(m["rain"]["depth_mm"], 2.0e-7 * 3599.5 * 1000, places=3)
        from damit_pmp import lisfloodrain as LR
        self.assertEqual(m["runner_shared_sha256"], LR.runner_sources())
        self.assertEqual(r["CELLS"], m["domain"]["valid_cells"])
        with open(os.path.join(out, "rain.par")) as fh:
            par = fh.read()
        self.assertIn("sim_time 10800", par)
        self.assertIn("acceleration", par)

    def test_lisfloodrain_fv2_is_written_with_the_cuda_warning(self):
        r, out = self._lisflood_job("lf2", SOLVER=1)
        with open(os.path.join(out, "run_manifest.json")) as fh:
            m = json.load(fh)
        self.assertEqual(m["settings"]["solver"], "fv2")
        self.assertIn("limitslopes", m["settings"]["par_lines"])
        self.assertIn("CUDA", m["settings"]["cuda_note"])

    def test_lisfloodrain_run_needs_an_executable(self):
        with self.assertRaises(QgsProcessingException) as cm:
            self._lisflood_job("lf3", RUN_LISFLOOD=True, LISFLOOD_EXE=os.path.join(self.cache, "nope"))
        self.assertIn("not a file", str(cm.exception))
        with self.assertRaises(QgsProcessingException) as cm:
            self._lisflood_job("lf4", GAUGE_B="")
        self.assertIn("both GAUGE_A and GAUGE_B", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
