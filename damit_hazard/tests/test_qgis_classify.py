"""Headless smoke of damit:classify on a real QGIS (skipped without one): register the provider,
run the ND preset and a custom configuration on synthetic rasters and layers, check the class,
the GeoPackage and the reports. Scratch profile, offscreen, no GUI.

    QT_QPA_PLATFORM=offscreen <QGIS python> damit_hazard/tests/run_tests.py qgis
"""
import json
import os
import tempfile
import unittest

from _helpers import ROOT  # noqa: F401  (puts the repo root on sys.path)

try:
    from qgis.core import QgsApplication
except Exception as e:
    raise unittest.SkipTest("QGIS not available: {}".format(e))

import numpy as np
from osgeo import gdal, osr

_APP = None


def _app():
    global _APP
    if _APP is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        prof = tempfile.mkdtemp(prefix="damit_qgis_profile_")
        _APP = QgsApplication([], False, prof)
        _APP.initQgis()
        from damit_hazard.provider import Provider
        _app.provider = Provider()           # keep a reference; the registry does not own it
        QgsApplication.processingRegistry().addProvider(_app.provider)
    return _APP


def _tif(path, arr, nodata=-9999.0):
    ds = gdal.GetDriverByName("GTiff").Create(path, arr.shape[1], arr.shape[0], 1,
                                              gdal.GDT_Float32)
    ds.SetGeoTransform((500000.0, 1.0, 0.0, 5200100.0, 0.0, -1.0))
    sr = osr.SpatialReference()
    sr.ImportFromEPSG(32614)
    ds.SetProjection(sr.ExportToWkt())
    ds.GetRasterBand(1).SetNoDataValue(nodata)
    ds.GetRasterBand(1).WriteArray(arr)
    ds = None
    return path


def _layers(d):
    from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY
    s = QgsVectorLayer("Polygon?crs=EPSG:32614&field=type:string&field=occupants:integer",
                       "structures", "memory")
    feats = []
    for x0, t, occ in ((500010.0, "home", 3), (500040.0, "home", 2), (500070.0, "barn", 0)):
        f = QgsFeature(s.fields())
        f.setGeometry(QgsGeometry.fromWkt(
            "POLYGON(({0} 5200050,{1} 5200050,{1} 5200060,{0} 5200060,{0} 5200050))".format(
                x0, x0 + 10)))
        f.setAttributes([t, occ])
        feats.append(f)
    s.dataProvider().addFeatures(feats)
    p = QgsVectorLayer("Point?crs=EPSG:32614&field=type:string", "points", "memory")
    f = QgsFeature(p.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500090.0, 5200010.0)))
    f.setAttributes(["mobile home"])
    p.dataProvider().addFeatures([f])
    r = QgsVectorLayer("LineString?crs=EPSG:32614&field=road_class:string&field=aadt:integer",
                       "roads", "memory")
    f = QgsFeature(r.fields())
    f.setGeometry(QgsGeometry.fromWkt("LINESTRING(500000 5200030,500100 5200030)"))
    f.setAttributes(["county", 500])
    r.dataProvider().addFeatures([f])
    return s, p, r


def _rasters(d):
    dep = np.zeros((100, 100), np.float32)
    vel = np.zeros((100, 100), np.float32)
    dep[38:52, 5:25] = 2.0             # house 1 (x 10-20, y 50-60): 2 m = 6.6 ft
    vel[38:52, 5:25] = 0.5
    dep[38:52, 35:55] = 0.3            # house 2: 1 ft, shallow
    vel[38:52, 35:55] = 0.3
    dep[65:75, :] = 0.2                # the road at y = 30 (row 70)
    vel[65:75, :] = 0.2
    return (_tif(os.path.join(d, "depth.tif"), dep), _tif(os.path.join(d, "vel.tif"), vel))


def _alg_run(params):
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsProject
    alg = QgsApplication.processingRegistry().algorithmById("damit:classify")
    assert alg is not None, "damit:classify not registered"
    ctx = QgsProcessingContext()
    ctx.setProject(QgsProject.instance())
    fb = QgsProcessingFeedback()
    res, ok = alg.run(params, ctx, fb)
    assert ok, "algorithm failed"
    return res


def test_nd_preset_headless():
    _app()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    dep, vel = _rasters(d)
    s, p, r = _layers(d)
    from damit_hazard.engine import catalog as C
    pids = [None] + list(C.load()["presets"])
    out = os.path.join(d, "out")
    res = _alg_run({"PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0,
                    "DEPTH": dep, "VELOCITY": vel, "METRES": True, "STRUCTURES": s,
                    "FACILITIES": p, "ROADS": r, "OUTPUT": out, "DAM_NAME": "smoke"})
    assert res["CLASS"] == "High" and res["ORDINAL"] == 3, res
    rep = json.load(open(os.path.join(out, "damit_hazard_report.json"), encoding="utf-8"))
    assert rep["driving"][0]["method"] == "M1"
    assert rep["per_scenario"][0]["scenario"] == "S3"
    assert any(h["method"] == "M8a" and h["class"] == 2 for h in rep["hits"])   # AADT 500
    md = open(res["REPORT"], encoding="utf-8").read()
    assert "North Dakota (REG_05.2026)" in md and "not a regulatory determination" in md
    from qgis.core import QgsVectorLayer
    lyr = QgsVectorLayer(res["GPKG"] + "|layername=structures", "s", "ogr")
    assert lyr.isValid() and lyr.featureCount() == 3
    classes = sorted(f["class"] for f in lyr.getFeatures())
    assert classes[-1] == 3, classes
    assert os.path.isfile(os.path.join(out, "damit_hazard_report.html"))
    # 0.3.0: the depth-velocity chart of the wet habitable structures: PNG + CSV in the output folder, linked in the
    # md, embedded in the html, named for the imported raster ("depth.tif" is neither a Runner nor a Screener name)
    import csv
    pts = list(csv.DictReader(open(os.path.join(out, "damit_hazard_dv_habitable.csv"), encoding="utf-8")))
    assert sorted(p["label"] for p in pts) == ["1", "2"], pts       # the two wet homes; the barn is not habitable
    assert {p["source"] for p in pts} == {"Imported raster: depth.tif"}
    assert rep["dv_charts"][0]["counts"]["total"] == 2 and rep["dv_charts"][0]["source"] == "Imported raster: depth.tif"
    assert "damit_hazard_dv_habitable.png" in md
    try:
        import matplotlib  # noqa: F401
        have_mpl = True
    except Exception:
        have_mpl = False
    if have_mpl:
        assert os.path.getsize(os.path.join(out, "damit_hazard_dv_habitable.png")) > 5000
        assert "data:image/png;base64," in open(os.path.join(out, "damit_hazard_report.html"), encoding="utf-8").read()


def test_chart_source_label_and_runner_names():
    """SOURCE_LABEL names the source (DSS-WISE); a model run's 'Depth (Max).tif' is the Runner's."""
    _app()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    dep, vel = _rasters(d)
    s, p, r = _layers(d)
    out = os.path.join(d, "out_label")
    res = _alg_run({"PRESET": 0, "METHODS": "M1", "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep, "VELOCITY": vel,
                    "METRES": True, "STRUCTURES": s, "OUTPUT": out, "DAM_NAME": "smoke", "SOURCE_LABEL": "DSS-WISE"})
    rep = json.load(open(os.path.join(out, "damit_hazard_report.json"), encoding="utf-8"))
    assert rep["dv_charts"][0]["source"] == "DSS-WISE", rep["dv_charts"]
    run_dir = os.path.join(d, "dam")
    os.makedirs(run_dir)
    import shutil
    shutil.copy(dep, os.path.join(run_dir, "Depth (Max).tif"))
    shutil.copy(vel, os.path.join(run_dir, "Velocity (Max).tif"))
    out2 = os.path.join(d, "out_runner")
    _alg_run({"PRESET": 0, "METHODS": "M1", "RUN_SCENARIO": 3, "MODEL_DIM": 0,
              "DEPTH": os.path.join(run_dir, "Depth (Max).tif"), "VELOCITY": os.path.join(run_dir, "Velocity (Max).tif"),
              "METRES": True, "STRUCTURES": s, "OUTPUT": out2, "DAM_NAME": "smoke"})
    rep2 = json.load(open(os.path.join(out2, "damit_hazard_report.json"), encoding="utf-8"))
    assert rep2["dv_charts"][0]["source"] == "Runner", rep2["dv_charts"]
    # no velocity raster: no chart, a warning, and the classification still ran
    out3 = os.path.join(d, "out_novel")
    _alg_run({"PRESET": 0, "METHODS": "M6", "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep, "METRES": True,
              "STRUCTURES": s, "OUTPUT": out3, "DAM_NAME": "smoke"})
    rep3 = json.load(open(os.path.join(out3, "damit_hazard_report.json"), encoding="utf-8"))
    assert rep3["dv_charts"] == [] and not os.path.exists(os.path.join(out3, "damit_hazard_dv_habitable.png"))


def test_classify_writes_nothing_beside_its_input_rasters():
    """GUI chain walk 2026-11-09: classify on read-only model rasters left <raster>.tif.aux.xml
    (QGIS layer statistics through GDAL PAM) in the product-of-record folder. The inputs sit in
    their own folder here; after the run (and after the layers are released) that folder holds
    exactly the rasters it held before, and the PAM option is back as it was."""
    _app()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    src = os.path.join(d, "source_run")
    os.makedirs(src)
    dep, vel = _rasters(src)
    before = sorted(os.listdir(src))
    s, p, r = _layers(d)
    from damit_hazard.engine import catalog as C
    pids = [None] + list(C.load()["presets"])
    old = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    out = os.path.join(d, "out")
    res = _alg_run({"PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0,
                    "DEPTH": dep, "VELOCITY": vel, "METRES": True, "STRUCTURES": s,
                    "FACILITIES": p, "ROADS": r, "OUTPUT": out})
    assert res["CLASS"] == "High", res
    import gc
    gc.collect()
    assert sorted(os.listdir(src)) == before, os.listdir(src)
    assert not [f for f in os.listdir(src) if f.endswith(".aux.xml")]
    assert os.path.isfile(os.path.join(out, "damit_hazard_report.json"))
    assert gdal.GetConfigOption("GDAL_PAM_ENABLED") == old


def _processing():
    """The QGIS Processing Python module, initialized (its plugins folder put on sys.path if needed)."""
    import sys
    try:
        import processing  # noqa: F401
    except ImportError:
        sys.path.append(os.path.join(QgsApplication.pkgDataPath(), "python", "plugins"))
    try:
        import processing
        from processing.core.Processing import Processing
    except ImportError as e:
        raise unittest.SkipTest("QGIS Processing plugin not importable: {}".format(e))
    Processing.initialize()
    return processing


def test_processing_run_writes_nothing_beside_its_input_rasters():
    """Docs & QA re-test of #13: through processing.run with file-path inputs (as the Toolbox
    does when paths are typed or browsed), QGIS loads the raster parameters while checking them,
    before processAlgorithm, and that load used to write <raster>.tif.aux.xml beside the inputs.
    checkParameterValues now runs with PAM off too. The Hazard window always passes already-loaded
    project layers; that path is outside this test."""
    _app()
    processing = _processing()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    src = os.path.join(d, "source_run")
    os.makedirs(src)
    dep, vel = _rasters(src)
    before = sorted(os.listdir(src))
    s, p, r = _layers(d)
    from damit_hazard.engine import catalog as C
    pids = [None] + list(C.load()["presets"])
    old = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    out = os.path.join(d, "out")
    res = processing.run("damit:classify", {
        "PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep,
        "VELOCITY": vel, "METRES": True, "STRUCTURES": s, "FACILITIES": p, "ROADS": r,
        "OUTPUT": out})
    assert res["CLASS"] == "High", res
    import gc
    gc.collect()
    assert sorted(os.listdir(src)) == before, os.listdir(src)
    assert not [f for f in os.listdir(src) if f.endswith(".aux.xml")]
    assert os.path.isfile(os.path.join(out, "damit_hazard_report.json"))
    assert gdal.GetConfigOption("GDAL_PAM_ENABLED") == old


def test_preset_id_and_alias_headless():
    """PRESET_ID takes a preset ID or alias (USBR or USBR_TM11) and wins over the PRESET list;
    the list shows 'ID: label'; an unknown ID fails with the known ones listed."""
    _app()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    dep, vel = _rasters(d)
    s, p, r = _layers(d)
    alg = QgsApplication.processingRegistry().algorithmById("damit:classify")
    opts = alg.parameterDefinition("PRESET").options()
    assert "USBR: USBR (ACER TM-11)" in opts and opts[0].startswith("Custom"), opts
    reps = []
    for pid in ("USBR", "USBR_TM11"):
        out = os.path.join(d, "out_" + pid)
        res = _alg_run({"PRESET": 0, "PRESET_ID": pid, "RUN_SCENARIO": 1, "MODEL_DIM": 0,
                        "DEPTH": dep, "VELOCITY": vel, "METRES": True, "STRUCTURES": s,
                        "FACILITIES": p, "ROADS": r, "OUTPUT": out})
        rep = json.load(open(os.path.join(out, "damit_hazard_report.json"), encoding="utf-8"))
        assert rep["config"]["preset"] == "USBR"
        reps.append((res["ORDINAL"], res["CLASS"], sorted(h["method"] for h in rep["hits"])))
    assert reps[0] == reps[1], reps
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback
    ok = True
    try:
        _r, ok = alg.run({"PRESET": 0, "PRESET_ID": "USBR_TM12", "DEPTH": dep,
                          "OUTPUT": os.path.join(d, "bad")}, QgsProcessingContext(),
                         QgsProcessingFeedback())
    except Exception as e:                      # some QGIS versions raise instead of returning
        ok = "USBR_TM11" not in str(e)
    assert not ok


def test_dam_json_needs_an_nid_id():
    _app()
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsProject
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    try:
        dep, vel = _rasters(d)
        s, p, r = _layers(d)
        from damit_hazard.engine import catalog as C
        pids = [None] + list(C.load()["presets"])
        alg = QgsApplication.processingRegistry().algorithmById("damit:classify")

        def go(dam, name):
            path = os.path.join(d, name + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dam, f)
            ctx = QgsProcessingContext()
            ctx.setProject(QgsProject.instance())
            return alg.run({"PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep,
                            "VELOCITY": vel, "METRES": True, "STRUCTURES": s, "DAM_JSON": path,
                            "OUTPUT": os.path.join(d, name)}, ctx, QgsProcessingFeedback())

        res, ok = go({"dam_id": "ND00199", "storage_acft": 300}, "nid")
        assert ok, res
        rep = json.load(open(os.path.join(d, "nid", "damit_hazard_report.json"), encoding="utf-8"))
        assert rep["nid_id"] == "ND00199"
        for name, dam in (("dwr", {"dam_id": "DWR-2801"}), ("sample_id", {"dam_id": "SAMPLE-4031"})):
            _res, ok = go(dam, name)
            assert not ok, name
            assert not os.path.isfile(os.path.join(d, name, "damit_hazard_report.json")), name
        _res, ok = go({"dam_id": "desk-new1", "is_new": True}, "new")
        assert ok
        _res, ok = go({"dam_id": "local-sample", "is_sample": True}, "sample")
        assert ok
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_dam_record_nested_and_found_without_dam_json():
    """0.2.1: a dam.json with nested "fields" is read as it is; with no DAM_JSON the dam.json beside the rasters is used
    (or the run watcher's flat copy); a found record with no usable NID ID is left out with a warning, not an error."""
    _app()
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsProject
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    try:
        dep, vel = _rasters(d)
        s, p, r = _layers(d)
        from damit_hazard.engine import catalog as C
        pids = [None] + list(C.load()["presets"])
        alg = QgsApplication.processingRegistry().algorithmById("damit:classify")
        nested = {"format": "nd_dam_suite/dam_record", "fields": {"dam_id": "ND00199", "storage_acft": 300},
                  "sources": {}, "status": []}

        def go(name, dam_json=None):
            ctx = QgsProcessingContext()
            ctx.setProject(QgsProject.instance())
            fb = QgsProcessingFeedback()
            prm = {"PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep, "VELOCITY": vel,
                   "METRES": True, "STRUCTURES": s, "OUTPUT": os.path.join(d, name)}
            if dam_json:
                prm["DAM_JSON"] = dam_json
            res, ok = alg.run(prm, ctx, fb)
            rep = None
            if ok:
                rep = json.load(open(os.path.join(d, name, "damit_hazard_report.json"), encoding="utf-8"))
            return res, ok, rep

        def record_layer(rep):
            return [x for x in rep["layers"] if x["role"] == "dam record"]

        npath = os.path.join(d, "nested_given.json")
        json.dump(nested, open(npath, "w", encoding="utf-8"))
        _res, ok, rep = go("given", npath)                      # explicit and nested
        assert ok and rep["nid_id"] == "ND00199"
        assert "found automatically" not in record_layer(rep)[0]["note"]
        _res, ok, rep = go("none")                              # nothing to find: as before
        assert ok and not record_layer(rep) and rep["nid_id"] is None
        dam_json = os.path.join(d, "dam.json")                  # beside the rasters
        json.dump(nested, open(dam_json, "w", encoding="utf-8"))
        _res, ok, rep = go("found")
        assert ok and rep["nid_id"] == "ND00199", rep.get("nid_id")
        assert "found automatically" in record_layer(rep)[0]["note"]
        assert record_layer(rep)[0]["source"] == dam_json
        json.dump({"fields": {"dam_id": "DWR-2801"}}, open(dam_json, "w", encoding="utf-8"))
        _res, ok, rep = go("found_bad")                         # found, but not an NID id: left out, no failure
        assert ok and not record_layer(rep) and rep["nid_id"] is None
        _res, ok, _rep = go("given_bad", dam_json)              # the same file given on purpose still fails
        assert not ok
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_dam_folder_raster_finds_the_watcher_copy_and_the_inputs_line_says_so():
    """0.2.2, the DWR-2824 shape: classify on <Dams>/<dam id>/Depth (Max).tif with the run watcher's copy in
    <watch>/<dam id>_run_<timestamp>/dam_record_hazard.json and no DAM_JSON."""
    _app()
    import shutil
    from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsProject
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    old = os.environ.get("DAMIT_WATCH_DIR")
    try:
        dep0, vel0 = _rasters(d)
        dam_dir = os.path.join(d, "work", "dams", "ND00199")
        os.makedirs(dam_dir)
        dep, vel = (shutil.copy(x, os.path.join(dam_dir, n)) for x, n in ((dep0, "Depth (Max).tif"), (vel0, "Velocity (Max).tif")))
        s, p, r = _layers(d)
        watch = os.path.join(d, "home", "local-ai", "watch")
        os.environ["DAMIT_WATCH_DIR"] = watch
        from damit_hazard.engine import catalog as C
        pids = [None] + list(C.load()["presets"])
        alg = QgsApplication.processingRegistry().algorithmById("damit:classify")

        def go(name, **extra):
            ctx = QgsProcessingContext()
            ctx.setProject(QgsProject.instance())
            prm = {"PRESET": pids.index("ND"), "RUN_SCENARIO": 3, "MODEL_DIM": 0, "DEPTH": dep, "VELOCITY": vel,
                   "METRES": True, "STRUCTURES": s, "OUTPUT": os.path.join(d, name), "DAM_NAME": "Square Butte Creek Dam 2"}
            prm.update(extra)
            res, ok = alg.run(prm, ctx, QgsProcessingFeedback())
            assert ok, res
            md = open(os.path.join(d, name, "damit_hazard_report.md"), encoding="utf-8").read()
            return json.load(open(os.path.join(d, name, "damit_hazard_report.json"), encoding="utf-8")), md

        rep, md = go("none")                                       # nothing to find: the line says so, no {"name": ...}
        line = [l for l in md.splitlines() if l.startswith("- Dam record:")][0]
        assert line.startswith("- Dam record: none given or found (DAM_JSON was empty"), line
        assert "only the name was given: Square Butte Creek Dam 2" in line and '{"name"' not in md
        assert "dam record search:" not in md and rep["nid_id"] is None
        flat = os.path.join(watch, "ND00199_run_20261111_221952", "dam_record_hazard.json")
        os.makedirs(os.path.dirname(flat))
        json.dump({"dam_id": "ND00199", "nid_id": "ND00199", "name": "Watcher Name", "storage_acft": 300},
                  open(flat, "w", encoding="utf-8"))
        rep, md = go("found")
        assert rep["nid_id"] == "ND00199"
        rec = [x for x in rep["layers"] if x["role"] == "dam record"]
        assert rec and rec[0]["source"] == flat and "found automatically" in rec[0]["note"]
        line = [l for l in md.splitlines() if l.startswith("- Dam record:")][0]
        assert "ND00199" in line and "storage_acft = 300" in line and '{"' not in line, line
    finally:
        if old is None:
            os.environ.pop("DAMIT_WATCH_DIR", None)
        else:
            os.environ["DAMIT_WATCH_DIR"] = old
        shutil.rmtree(d, ignore_errors=True)


def test_custom_mode_headless():
    _app()
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    dep, vel = _rasters(d)
    s, p, r = _layers(d)
    out = os.path.join(d, "out")
    res = _alg_run({"PRESET": 0, "METHODS": "M3,M8c", "MODIFIERS": "R2", "SCENARIOS": "S1",
                    "RUN_SCENARIO": 1, "MODEL_DIM": 0, "DEPTH": dep, "VELOCITY": vel,
                    "METRES": True, "STRUCTURES": s, "ROADS": r, "OUTPUT": out})
    assert res["CLASS"] == "High" and res["ORDINAL"] == 3     # M3 home row: 6.6 ft >= 3.5 ft
    md = open(res["REPORT"], encoding="utf-8").read()
    assert "Custom mode" in md and "Nebraska" in md.split("## Citations")[1]
    meth = md.split("## Methods")[1].split("## Modifiers")[0]
    assert "Nebraska" not in meth


def test_dialog_grammar_and_params():
    _app()
    import re
    from qgis.PyQt.QtWidgets import QAbstractButton, QCheckBox
    from damit_hazard import dialog as D
    src = open(D.__file__, encoding="utf-8").read()
    assert not re.search(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])", src)
    dlg = D.DamitHazardDialog()
    assert dlg.windowTitle() == "DamIT Hazard 0.1.2"
    assert dlg.minimumSizeHint().width() <= 800 and dlg.minimumSizeHint().height() <= 1000
    for b in dlg.findChildren(QAbstractButton):
        assert "..." not in b.text() and not b.text().startswith("\u25b6"), b.text()
    assert dlg.classify_btn.font().bold() and not dlg.check_btn.font().bold()
    # preset mode: boxes follow the preset and are greyed with a reason
    dlg.preset.setCurrentIndex(dlg.preset_ids.index("ND"))
    ticked = dlg._ticked(dlg.m_boxes)
    assert ticked and all(not cb.isEnabled() and cb.toolTip() for cb in dlg.m_boxes[1].values())
    # custom mode: no jurisdiction name in any method / modifier / scenario box
    dlg.r_custom.setChecked(True)
    names = ("FEMA", "USBR", "Reclamation", "BIA", "NRCS", "North Dakota", "Nebraska",
             "New York", "Virginia", "Texas", "Idaho", "Colorado", "Rhode Island", "Arizona",
             "California", "Alaska")
    for cb in dlg.findChildren(QCheckBox):
        assert cb.isEnabled() or cb in (dlg.metres, dlg.advisory)
        assert not any(n in cb.text() for n in names), cb.text()
    assert dlg._ticked(dlg.m_boxes) == ticked          # custom starts from the last preset
    for cb in dlg.m_boxes[1].values():
        cb.setChecked(False)
    probs = dlg._problems()
    assert any("tick at least one method" in t for k, t in probs)
    dlg.m_boxes[1]["M3"].setChecked(True)
    assert "M3" in json.loads(dlg.params.toPlainText())
    p = dlg.params_dict()
    assert p["PRESET"] == 0 and p["METHODS"] == "M3"
    # the window's parameters run the algorithm
    d = tempfile.mkdtemp(prefix="damit_smoke_")
    dep, vel = _rasters(d)
    s, _pt, _r = _layers(d)
    p.update({"DEPTH": dep, "VELOCITY": vel, "METRES": True, "STRUCTURES": s,
              "OUTPUT": os.path.join(d, "out")})
    res = _alg_run(p)
    assert res["ORDINAL"] == 3
    dlg.deleteLater()


def test_plugin_load_unload_shares_provider():
    _app()
    from qgis.PyQt.QtWidgets import QMainWindow
    from damit_hazard import classFactory

    class Iface(object):
        def __init__(self):
            self.win, self.menu = QMainWindow(), []

        def mainWindow(self):
            return self.win

        def addPluginToMenu(self, m, a):
            self.menu.append((m, a))

        def removePluginMenu(self, m, a):
            self.menu.remove((m, a))

    iface = Iface()
    plug = classFactory(iface)
    plug.initGui()                       # 'damit' already registered by _app(): reuse it
    assert iface.menu and iface.menu[0][0] == "DamIT" and plug.provider is None
    assert QgsApplication.processingRegistry().algorithmById("damit:classify") is not None
    plug.unload()
    assert iface.menu == []
