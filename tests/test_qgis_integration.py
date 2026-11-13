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

    def test_runner_ported_tools_are_registered(self):
        # Runner 0.4.1: until 0.4.0 the ported DamSafety tools failed to import (compat.structure_flags and
        # compat.suite_config did not exist), the provider swallowed the ImportError, and only rundam,
        # checkhandoff and hecrasexport existed. The count is pinned so a tool cannot vanish unnoticed again.
        from damit_runner import provider as RP
        self.assertIsNone(RP.ENGINE_IMPORT_ERROR)
        reg = QgsApplication.processingRegistry()
        have = sorted(a.id() for a in reg.providerById("damit_run").algorithms())
        self.assertEqual(have, ["damit_run:batch", "damit_run:cascade", "damit_run:check", "damit_run:checkhandoff",
                                "damit_run:delineate", "damit_run:estimate", "damit_run:finishanuga",
                                "damit_run:hecrasexport", "damit_run:hydrograph", "damit_run:rundam",
                                "damit_run:sensitivity"])
        for a in reg.providerById("damit_run").algorithms():
            self.assertTrue(a.parameterDefinitions(), a.id())
            self.assertTrue(a.displayName(), a.id())

    def test_runner_hydrograph_tool_runs(self):
        import processing
        out = os.path.join(self.tmp, "ported_hydrograph.csv")
        r = processing.run("damit_run:hydrograph", {"DAM_ID": "ND00009", "HEIGHT_FT": 20, "STORAGE_ACFT": 500,
                                                    "TOP_FT": 1000, "OUTPUT": out})
        self.assertTrue(os.path.isfile(r["OUTPUT"]))
        with open(r["OUTPUT"], encoding="utf-8") as fh:
            rows = [ln for ln in fh.read().splitlines() if ln.strip()]
        self.assertGreater(len(rows), 10)

    def test_runner_batch_can_hand_dams_to_workers(self):
        # Runner 0.6.0 (DamSafety Runner 3.20.0): damit_run:batch runs several dams at the same time, each in a
        # qgis_process worker. The children are doubles here: nothing is started.
        from qgis.core import QgsProcessingContext, QgsProcessingFeedback
        from damit_runner.algorithms import engine as E
        a = QgsApplication.processingRegistry().algorithmById("damit_run:batch").create()
        for name in ("WORKERS", "WORKER_TIMEOUT_MIN", "ONLY_IDS", "SUMMARY_FILE"):
            self.assertIsNotNone(a.parameterDefinition(name), name)
        self.assertEqual(a.parameterDefinition("WORKERS").defaultValue(), 1)
        self.assertIn("MODE", [o.name() for o in a.outputDefinitions()])
        self.assertEqual(E.project_only_settings(), [])          # DamIT has no per-project suite settings
        ctx, fb = QgsProcessingContext(), QgsProcessingFeedback()
        self.assertEqual(E.worker_layer_source("/data/dams.gpkg|layername=dams", ctx),
                         ("/data/dams.gpkg|layername=dams", ""))
        text, why = E.worker_layer_source(self._dams(), ctx)
        self.assertIsNone(text)
        self.assertIn("temporary layer", why)
        parent = os.path.join(self.tmp, "batch_workers")
        os.makedirs(parent, exist_ok=True)
        ran, started = [], {}
        queue = [(i, None, d, os.path.join(parent, d), dict.fromkeys(E.BATCH_FIELDS, ""), None)
                 for i, d in enumerate(("A1", "A2"))]

        def run_one(i, feat, dam_id, folder, row, fb_):
            ran.append(dam_id)
            return False

        def children(jobs, workers, **kw):
            started["jobs"], started["workers"] = jobs, workers
            return {j["key"]: (1, "ended with code 1: boom") for j in jobs}
        with mock.patch.object(E.bworkers, "find_qgis_process", lambda *x, **k: ("/usr/bin/qgis_process", "")), \
                mock.patch.object(E.bworkers, "probe", lambda *x, **k: None), \
                mock.patch.object(E.bworkers, "run_children", children):
            # a temporary layer cannot be opened by a worker: said so, and the dams run here in order
            mode = a.run_queue({"DAMS": self._dams(), "DAMS_FOLDER": parent, "F_ID": "ID"}, ctx, fb, parent,
                               queue, 2, run_one)
            self.assertTrue(mode.startswith("one dam after another"), mode)
            self.assertIn("temporary layer", mode)
            self.assertEqual(ran, ["A1", "A2"])
            self.assertNotIn("jobs", started)
            # a file layer: one worker per dam, started as `qgis_process run damit_run:batch -`
            del ran[:]
            mode = a.run_queue({"DAMS": "/data/dams.gpkg|layername=dams", "DAMS_FOLDER": parent, "F_ID": "ID",
                                "LISFLOOD_EXE": sys.executable}, ctx, fb, parent, queue, 2, run_one)
        self.assertTrue(mode.startswith("in worker processes, 2 dam(s) at a time"), mode)
        self.assertEqual(ran, [])
        self.assertEqual([j["name"] for j in started["jobs"]], ["A1", "A2"])
        self.assertEqual(started["jobs"][0]["cmd"], ["/usr/bin/qgis_process", "run", "damit_run:batch", "-"])
        sent = json.loads(started["jobs"][1]["stdin"].decode("utf-8"))["inputs"]
        self.assertEqual((sent["ONLY_IDS"], sent["WORKERS"], sent["DAMS"]),
                         ("A2", 1, "/data/dams.gpkg|layername=dams"))
        self.assertEqual(os.path.dirname(sent["SUMMARY_FILE"]), os.path.join(parent, E.bworkers.WORK_FOLDER))
        # a worker that fails is a failed row naming its log, not a lost dam
        self.assertEqual([q[4]["Status"] for q in queue], ["failed", "failed"])
        self.assertIn("boom", queue[0][4]["Message"])

    def test_no_flagged_structures_shipped(self):
        from damit_runner.compat import structure_flags as F, suite_config as SC
        self.assertEqual(F.FLAGS, ())
        self.assertEqual(F.problems(), [])
        self.assertIsNone(F.lookup("ND00597"))
        self.assertFalse(SC.in_suite_pack("/x/ND_Dam_Suite_Pack/y"))
        self.assertTrue(SC.default_dams_folder().endswith(os.path.join("DamIT", "Dams")))

    def _dams(self):
        return point_layer([{"_x": 500000.0, "_y": 5200000.0, "ID": "ND00009", "HT": 30.0, "STOR": 450.0,
                             "TOD": 1530.0, "NP": 1520.0, "PMF": 1534.0}],
                           [("ID", "s"), ("HT", "d"), ("STOR", "d"), ("TOD", "d"), ("NP", "d"), ("PMF", "d")])

    def _receptors(self):
        return point_layer([{"_x": 500100.0, "_y": 5199900.0, "id": "h1", "dam_id": "ND00009",
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
        self.assertEqual(titles["Dam ND00009 inputs"]["status"], "warn")
        self.assertIn("height_ft", titles["Dam ND00009 inputs"]["detail"])
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
        out = processing.run("damit_run:rundam", {"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs, "DRY_RUN": True})
        self.assertEqual(out["STATUS"], "prepared")
        self.assertFalse(out["MODEL_LAUNCHED"])
        with open(os.path.join(out["RUN_FOLDER"], "run_setup.json")) as fh:
            setup = json.load(fh)
        self.assertFalse(setup["model_launched"])
        self.assertEqual(setup["preset_id"], "ND")
        self.assertIn("terrain (DEM)", setup["gaps"])
        # 0.2.0: DRY_RUN is off by default and the model needs a DEM; HEC-RAS (ENGINE 3, TIER 2) is refused. None
        # of these makes a run folder.
        with self.assertRaises(QgsProcessingException):
            processing.run("damit_run:rundam", {"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs})
        for extra in ({"ENGINE": 3}, {"TIER": 2}):
            with self.assertRaises(QgsProcessingException):
                processing.run("damit_run:rundam", dict({"HANDOFF": pkg_path, "OUTPUT_FOLDER": runs}, **extra))
        self.assertEqual(len(os.listdir(os.path.join(runs, "ND00009"))), 1)

    def test_report_chain_screen_model_classify(self):
        """Crest's Report step on a synthetic valley: runchain (2D screening flood -> preliminary class), rundam
        (the model launched: Depth (Max), hmax and the flood polygons in the dam folder), damit:classify on those
        rasters. The engines are stubs (no LISFLOOD-FP, ANUGA or built-in engine runs)."""
        import processing
        from damit_runner.tests import synth
        from damit_runner.flood import lisflood as LF, screen as SC
        from damit_hazard.provider import Provider
        reg = QgsApplication.processingRegistry()
        hz = None
        if reg.providerById("damit") is None:
            hz = Provider()
            reg.addProvider(hz)
        d = os.path.join(self.tmp, "report")
        os.makedirs(d)
        dem = os.path.join(d, "dem.tif")
        site = synth.make_dem(dem)
        x, y = site["dam_xy"]
        top_ft = site["top_m"] / 0.3048
        h_ft = (site["top_m"] - site["floor_at_dam"]) / 0.3048
        work, runs = os.path.join(d, "work"), os.path.join(d, "runs")
        dams_folder = os.path.join(work, "dams")
        os.makedirs(os.path.join(dams_folder, "ND00199"))
        os.makedirs(runs)
        with open(os.path.join(dams_folder, "ND00199", "dam_line.geojson"), "w") as fh:
            json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
                "type": "LineString", "coordinates": [list(c) for c in site["line"]]}}]}, fh)
        dams = point_layer([{"_x": x, "_y": y, "ID": "ND00199", "HT": h_ft, "STOR": 500.0, "TOD": top_ft}],
                           [("ID", "s"), ("HT", "d"), ("STOR", "d"), ("TOD", "d")])
        recs = point_layer([{"_x": x, "_y": y - 200.0, "id": "h1", "dam_id": "ND00199", "receptor_type": "structure",
                             "structure_type": "home", "habitable": True}],
                           [("id", "s"), ("dam_id", "s"), ("receptor_type", "s"), ("structure_type", "s"),
                            ("habitable", "b")])
        real_sim = SC.simulate

        def sim(*a, **k):
            k["engine_factory"] = synth.FakeFV
            return real_sim(*a, **k)
        calls = []
        try:
            with mock.patch.object(SC, "simulate", sim), mock.patch.object(LF, "run", synth.stub_lisflood(LF, calls)):
                r = processing.run("damit_screen:runchain", {
                    "WORK": work, "MODE": 0, "PRESET": "ND", "DAMS": dams, "TERRAIN": dem, "RECEPTORS": recs,
                    "FIELD_MAP": "dam_id=ID,height_ft=HT,storage_acft=STOR,top_of_dam_elev_ft=TOD"})
                self.assertTrue(r["OK"])
                with open(r["HANDOFFS"][0]) as fh:
                    pkg = json.load(fh)
                self.assertEqual(pkg["screening"]["status"], "computed_preliminary")
                self.assertTrue(os.path.isfile(os.path.join(dams_folder, "ND00199", "Screening Depth (Max).tif")))
                out = processing.run("damit_run:rundam", {"HANDOFF": r["HANDOFFS"][0], "OUTPUT_FOLDER": runs,
                                                          "DAMS_FOLDER": dams_folder, "LISFLOOD_EXE": "builtin",
                                                          "MAX_RUNS": 2})
            self.assertTrue(out["MODEL_LAUNCHED"])
            self.assertEqual(out["STATUS"], "finished")
            self.assertTrue(calls)
            dam_dir = os.path.join(dams_folder, "ND00199")
            for name in ("Depth (Max).tif", "Velocity (Max).tif", "hmax_ft.tif", "Flood Polygons (Max Depth).geojson"):
                self.assertTrue(os.path.isfile(os.path.join(dam_dir, name)), name)
            before = sorted(os.listdir(dam_dir))
            from damit_hazard.engine import catalog as HC
            pids = [None] + list(HC.load()["presets"])
            st = QgsVectorLayer("Polygon?crs=EPSG:26914&field=type:string&field=occupants:integer", "s", "memory")
            f = QgsFeature(st.fields())
            f.setGeometry(QgsGeometry.fromWkt("POLYGON(({0} {1},{2} {1},{2} {3},{0} {3},{0} {1}))".format(
                x - 5, y - 205, x + 5, y - 195)))
            f.setAttribute("type", "home")
            f.setAttribute("occupants", 3)
            st.dataProvider().addFeatures([f])
            res = processing.run("damit:classify", {
                "PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0, "METRES": False,
                "DEPTH": os.path.join(dam_dir, "Depth (Max).tif"), "VELOCITY": os.path.join(dam_dir, "Velocity (Max).tif"),
                "STRUCTURES": st, "OUTPUT": os.path.join(d, "classify"), "DAM_NAME": "synthetic"})
            self.assertIn(res["CLASS"], ("Low", "Medium", "High"))
            self.assertEqual(sorted(os.listdir(dam_dir)), before)          # classify writes nothing there
        finally:
            if hz is not None:
                reg.removeProvider(hz)

    def test_runchain_refuses_on_preflight_fail(self):
        import processing
        with self.assertRaises(QgsProcessingException):
            processing.run("damit_screen:runchain", {"WORK": os.path.join(self.tmp, "x"), "MODE": 0, "PRESET": "NOPE",
                                                      "DAMS": self._dams(), "FIELD_MAP": "dam_id=ID"})


if __name__ == "__main__":
    unittest.main()
