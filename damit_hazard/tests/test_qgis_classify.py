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
    assert dlg.windowTitle() == "DamIT Hazard 0.1.0"
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
