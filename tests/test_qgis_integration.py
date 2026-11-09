"""Real-QGIS integration (offscreen, scratch profile): providers, algorithms, preflight, chain ->
hand-off -> rundam round trip, engine refusal. Skipped when qgis is not importable.

Run through tests/run_tests.sh (nice -n 19, single-threaded, QT_QPA_PLATFORM=offscreen,
QGIS_CUSTOM_CONFIG_PATH = a temporary scratch profile). Never starts a model."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from qgis.core import (QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProcessingException,
                           QgsVectorLayer)
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False

APP = None


def setUpModule():
    global APP
    if not HAVE_QGIS:
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    profile = os.environ.get("QGIS_CUSTOM_CONFIG_PATH") or tempfile.mkdtemp(prefix="damit_qgis_profile_")
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = profile
    APP = QgsApplication([], False, profile)
    APP.initQgis()
    plug = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
    if plug not in sys.path:
        sys.path.append(plug)
    from processing.core.Processing import Processing
    Processing.initialize()


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


def point_layer(rows, fields):
    lyr = QgsVectorLayer("Point?crs=EPSG:26914", "dams", "memory")
    pr = lyr.dataProvider()
    from qgis.core import QgsFields
    fs = QgsFields()
    for name, kind in fields:
        fs.append(_field(name, kind))
    pr.addAttributes(fs.toList())
    lyr.updateFields()
    feats = []
    for r in rows:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r.pop("_x"), r.pop("_y"))))
        for k, v in r.items():
            f.setAttribute(k, v)
        feats.append(f)
    pr.addFeatures(feats)
    return lyr


def _field(name, kind):
    try:
        from qgis.PyQt.QtCore import QMetaType
        t = {"s": QMetaType.Type.QString, "d": QMetaType.Type.Double, "b": QMetaType.Type.Bool}[kind]
        return QgsField(name, t)
    except (TypeError, AttributeError):
        from qgis.PyQt.QtCore import QVariant as V  # QGIS < 3.38 needs the QVariant constructor
        return QgsField(name, {"s": V.String, "d": V.Double, "b": V.Bool}[kind])


@unittest.skipUnless(HAVE_QGIS, "qgis not importable")
@mock.patch.object(subprocess, "Popen", _no_process)
class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import damit_catalog
        import damit_runner
        import damit_screener
        reg = QgsApplication.processingRegistry()
        before = {p.id() for p in reg.providers()}
        cls.catalog_plugin = damit_catalog.classFactory(None)
        cls.catalog_plugin.initGui()
        cls.catalog_providers = {p.id() for p in reg.providers()} - before
        cls.screener = damit_screener.classFactory(None)
        cls.screener.initProcessing()
        cls.runner = damit_runner.classFactory(None)
        cls.runner.initProcessing()
        cls.tmp = tempfile.mkdtemp(prefix="damit_qgis_")

    @classmethod
    def tearDownClass(cls):
        cls.screener.unload()
        cls.runner.unload()
        cls.catalog_plugin.unload()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_providers_and_algorithms(self):
        reg = QgsApplication.processingRegistry()
        self.assertEqual(self.catalog_providers, set())
        self.assertIsNotNone(reg.providerById("damit_screen"))
        self.assertIsNotNone(reg.providerById("damit_run"))
        for pid in ("damit", "nddam", "ndbreach"):
            p = reg.providerById(pid)
            if p is not None:                      # another plugin may be installed; it is not ours
                self.assertNotIn(type(p).__module__.split(".")[0], ("damit_screener", "damit_runner", "damit_catalog"))
        for alg in ("damit_screen:preflight", "damit_screen:runchain", "damit_screen:handoff",
                    "damit_screen:prepare", "damit_screen:terrain", "damit_screen:storage",
                    "damit_screen:breachdirection", "damit_screen:hydrograph", "damit_screen:triage",
                    "damit_screen:engine2d", "damit_screen:suggest", "damit_screen:report",
                    "damit_run:rundam", "damit_run:checkhandoff"):
            a = reg.algorithmById(alg)
            self.assertIsNotNone(a, alg)
            self.assertTrue(a.shortHelpString())
        self.assertIsNone(reg.algorithmById("damit_screen:classify"))
        self.assertIsNone(reg.algorithmById("damit_run:classify"))

    def _dams(self):
        return point_layer([{"_x": 500000.0, "_y": 5200000.0, "ID": "ND-9", "HT": 30.0, "STOR": 450.0,
                             "TOD": 1530.0, "NP": 1520.0, "PMF": 1534.0}],
                           [("ID", "s"), ("HT", "d"), ("STOR", "d"), ("TOD", "d"), ("NP", "d"), ("PMF", "d")])

    def _receptors(self):
        return point_layer([{"_x": 500100.0, "_y": 5199900.0, "id": "h1", "dam_id": "ND-9",
                             "receptor_type": "structure", "structure_type": "home", "habitable": True,
                             "depth_ground_ft": 2.6, "feature_kind": "isolated_home"}],
                           [("id", "s"), ("dam_id", "s"), ("receptor_type", "s"), ("structure_type", "s"),
                            ("habitable", "b"), ("depth_ground_ft", "d"), ("feature_kind", "s")])

    FMAP = "dam_id=ID,height_ft=HT,storage_acft=STOR,top_of_dam_elev_ft=TOD,normal_pool_elev_ft=NP,pmf_peak_elev_ft=PMF"

    def test_preflight_flags_missing_inputs(self):
        import processing
        work = os.path.join(self.tmp, "pf")
        r = processing.run("damit_screen:preflight", {"WORK": work, "MODE": 0, "PRESET": "ND"})
        self.assertFalse(r["READY"])                       # no dams layer
        self.assertGreaterEqual(r["FAILS"], 1)
        r = processing.run("damit_screen:preflight", {"WORK": work, "MODE": 0, "PRESET": "ND",
                                                       "DAMS": self._dams(), "FIELD_MAP": "dam_id=ID"})
        self.assertTrue(r["READY"])
        titles = {c["title"]: c for c in r["CHECKS"]}
        self.assertEqual(titles["Dam ND-9 inputs"]["status"], "warn")
        self.assertIn("height_ft", titles["Dam ND-9 inputs"]["detail"])
        self.assertEqual(titles["Receptors"]["status"], "warn")

    def test_chain_handoff_rundam_round_trip(self):
        import processing
        work = os.path.join(self.tmp, "chain")
        runs = os.path.join(self.tmp, "runs")
        os.makedirs(runs, exist_ok=True)
        r = processing.run("damit_screen:runchain", {
            "WORK": work, "MODE": 0, "PRESET": "ND", "DAMS": self._dams(), "FIELD_MAP": self.FMAP,
            "RECEPTORS": self._receptors(),
            "SETTINGS": json.dumps({"summary": {"model_dimension": "1D", "hydraulics_source": "breach_model"}})})
        self.assertTrue(r["OK"])
        self.assertEqual(r["DAMS"], 1)
        pkg_path = r["HANDOFFS"][0]
        with open(pkg_path) as fh:
            pkg = json.load(fh)
        self.assertEqual(pkg["screening"]["suggested_label"], "High")
        self.assertEqual(pkg["dam"]["crs"], "EPSG:26914")
        chk = processing.run("damit_run:checkhandoff", {"HANDOFF": pkg_path})
        self.assertTrue(chk["VALID"])
        out = processing.run("damit_run:rundam", {"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs})
        self.assertEqual(out["STATUS"], "prepared")
        with open(os.path.join(out["RUN_FOLDER"], "run_setup.json")) as fh:
            setup = json.load(fh)
        self.assertFalse(setup["model_launched"])
        self.assertEqual(setup["preset_id"], "ND")
        self.assertIn("terrain (DEM)", setup["gaps"])
        for engine in (1, 2, 3):
            with self.assertRaises(QgsProcessingException):
                processing.run("damit_run:rundam", {"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs, "ENGINE": engine})
        with self.assertRaises(QgsProcessingException):
            processing.run("damit_run:rundam", {"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs, "DRY_RUN": False})
        self.assertEqual(len(os.listdir(os.path.join(runs, "ND-9"))), 1)

    def test_runchain_refuses_on_preflight_fail(self):
        import processing
        with self.assertRaises(QgsProcessingException):
            processing.run("damit_screen:runchain", {"WORK": os.path.join(self.tmp, "x"), "MODE": 0, "PRESET": "NOPE",
                                                      "DAMS": self._dams(), "FIELD_MAP": "dam_id=ID"})


if __name__ == "__main__":
    unittest.main()
