# -*- coding: utf-8 -*-
"""DamIT Hazard window: the suite GUI grammar (info banner, CheckPanel, bold Classify beside
Check inputs, a ▸ Log fold, Close at the bottom right) over the damit:classify algorithm.

Two modes. Preset: pick a jurisdiction; the method and modifier boxes show what the preset runs
and are greyed (their tooltip says why). Custom: tick methods, modifiers and scenarios by name;
no jurisdiction appears in the list (the citations are still written to the report).
Switching to Custom keeps the last preset's ticks as a starting point. The
parameters of the ticked methods are shown as JSON and can be edited before the run.
"""
import json
import os
import traceback

from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                                 QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
                                 QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
                                 QToolButton, QVBoxLayout, QWidget)

from .engine import catalog as C
from .ui.ui_fit import _scroll as scroll_area, fit_window
from .ui.ui_widgets import CheckPanel, Collapsible, InfoBanner, WrapLabel, ERROR, OK, WARNING

VERSION = "0.1.2"
TITLE = "DamIT Hazard {}".format(VERSION)
SCENARIOS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
DIMS = ["2D", "1D", "Not known"]
RASTERS = [("DEPTH", "Maximum depth raster", True), ("VELOCITY", "Maximum velocity raster", False),
           ("DV", "Depth \u00d7 velocity raster", False), ("WSE", "Water-surface elevation raster",
                                                            False),
           ("NONBREACH", "Non-breach depth raster", False),
           ("ARRIVAL", "Arrival time raster (hours)", False)]
LAYERS = [("STRUCTURES", "structure", "Structures"), ("ROADS", "road", "Roads"),
          ("RAIL", "rail", "Railroads"), ("FACILITIES", "facility", "Critical facilities"),
          ("LIFELINES", "lifeline", "Lifelines and utilities"),
          ("ENVIRONMENT", "environment", "Environmental / cultural features"),
          ("DOMAIN", None, "Routed domain polygon")]
FILES = [("DAM_JSON", "Dam record (JSON)"), ("EXTRA_RUNS", "More runs (JSON)"),
         ("CHARTS_JSON", "Extra TM-11 charts (JSON)")]
PRESET_TIP = "Set by the preset. Choose Custom to pick methods yourself."


def _enum(cls, scope, name):
    """cls.<name> on Qt5, cls.<scope>.<name> on Qt6 (the flags are scoped there)."""
    return getattr(getattr(cls, scope, cls), name, None) or getattr(cls, name)


def _layer_filter(kind):
    """QgsMapLayerProxyModel filter, QGIS 3 or 4 spelling."""
    from qgis.core import QgsMapLayerProxyModel
    try:
        from qgis.core import Qgis
        lf = getattr(Qgis, "LayerFilter", None)
    except ImportError:
        lf = None
    name = {"raster": "RasterLayer", "vector": "VectorLayer", "polygon": "PolygonLayer"}[kind]
    if lf is not None and hasattr(lf, name):
        return getattr(lf, name)
    return getattr(getattr(QgsMapLayerProxyModel, "Filter", QgsMapLayerProxyModel), name)


def _layer_combo(kind):
    from qgis.gui import QgsMapLayerComboBox
    cb = QgsMapLayerComboBox()
    cb.setFilters(_layer_filter(kind))
    cb.setAllowEmptyLayer(True)
    cb.setLayer(None)
    return cb


class _Feedback(object):
    """A QgsProcessingFeedback that also writes to the window's log."""

    @staticmethod
    def make(log):
        from qgis.core import QgsProcessingFeedback

        class F(QgsProcessingFeedback):
            def pushInfo(self, info):
                log(info)
                super().pushInfo(info)

            def pushWarning(self, w):
                log("\u26a0 " + w)
                super().pushWarning(w)

            def reportError(self, e, fatal=False):
                log("\u2715 " + e)
                super().reportError(e, fatal)
        return F()


class DamitHazardDialog(QDialog):
    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.cat = C.load()
        self.setWindowTitle(TITLE)
        self.preset_ids = [p for p, _l in C.preset_choices(self.cat)]
        root = QVBoxLayout(self)
        root.addWidget(InfoBanner(self.cat.get("disclaimer", "")))

        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(0, 0, 0, 0)

        # -- mode ------------------------------------------------------------------------
        mode = QGroupBox("Classification method")
        mg = QGridLayout(mode)
        mg.setColumnStretch(1, 1)
        self.r_preset = QRadioButton("Jurisdiction preset")
        self.r_custom = QRadioButton("Custom (pick methods by name)")
        self.r_preset.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_preset)
        grp.addButton(self.r_custom)
        self.preset = QComboBox()
        for _pid, label in C.preset_choices(self.cat):
            self.preset.addItem(label)
        self.preset.setCurrentIndex(self.preset_ids.index("FEMA333"))
        mg.addWidget(self.r_preset, 0, 0)
        mg.addWidget(self.preset, 0, 1)
        mg.addWidget(self.r_custom, 1, 0, 1, 2)
        self.preset_note = WrapLabel("")
        mg.addWidget(self.preset_note, 2, 0, 1, 2)
        body.addWidget(mode)

        # -- methods, modifiers, scenarios ------------------------------------------------
        self.m_boxes = self._boxes(self.cat["methods"], C.EVAL_ORDER, 2)
        self.r_boxes = self._boxes(self.cat["modifiers"], list(self.cat["modifiers"]), 2)
        sd = dict(self.cat["scenarios"])
        sd.update(self.cat.get("domains", {}))
        self.s_boxes = self._boxes(sd, list(sd), 2)
        body.addWidget(Collapsible("Methods", self.m_boxes[0]))
        body.addWidget(Collapsible("Modifiers", self.r_boxes[0]))
        body.addWidget(Collapsible("Scenarios and domain cutoffs expected", self.s_boxes[0]))

        self.params = QPlainTextEdit()
        self.params.setMinimumHeight(140)
        reset = QPushButton("Reset parameters")
        reset.clicked.connect(self._fill_params)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(WrapLabel("Parameters of the ticked methods and modifiers (JSON). Edits "
                               "are passed to the run as overrides."))
        pl.addWidget(self.params)
        pl.addWidget(reset)
        body.addWidget(Collapsible("Parameters", pw))

        # -- inputs ----------------------------------------------------------------------
        inp = QGroupBox("Flood run and receptors")
        g = QGridLayout(inp)
        g.setColumnStretch(1, 1)
        r = 0
        self.scenario = QComboBox()
        self.scenario.addItems(["{} {}".format(s, self.cat["scenarios"][s]["name"])
                                for s in SCENARIOS])
        g.addWidget(QLabel("Scenario of these rasters"), r, 0)
        g.addWidget(self.scenario, r, 1)
        r += 1
        self.dim = QComboBox()
        self.dim.addItems(DIMS)
        g.addWidget(QLabel("Model dimensionality"), r, 0)
        g.addWidget(self.dim, r, 1)
        r += 1
        self.rasters = {}
        for key, label, _req in RASTERS:
            self.rasters[key] = _layer_combo("raster")
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(self.rasters[key], r, 1)
            r += 1
        self.metres = QCheckBox("Rasters are in metres (m, m/s, m\u00b2/s)")
        g.addWidget(self.metres, r, 0, 1, 2)
        r += 1
        self.layers = {}
        for key, _kind, label in LAYERS:
            self.layers[key] = _layer_combo("polygon" if key == "DOMAIN" else "vector")
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(self.layers[key], r, 1)
            r += 1
        self.files = {}
        for key, label in FILES:
            self.files[key] = QLineEdit()
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(self.files[key], r, 1)
            g.addWidget(self._browse(self.files[key], "json"), r, 2)
            r += 1
        self.dam = QLineEdit()
        g.addWidget(QLabel("Dam name"), r, 0)
        g.addWidget(self.dam, r, 1)
        r += 1
        self.out = QLineEdit()
        g.addWidget(QLabel("Output folder"), r, 0)
        g.addWidget(self.out, r, 1)
        g.addWidget(self._browse(self.out, "dir"), r, 2)
        r += 1
        self.advisory = QCheckBox("Apply advisory results to the suggested class")
        g.addWidget(self.advisory, r, 0, 1, 2)
        body.addWidget(inp)
        self.result = WrapLabel("")
        body.addWidget(self.result)
        body.addStretch(1)
        root.addWidget(scroll_area(page), 1)

        # -- footer: checks, log, action bar ---------------------------------------------
        self.check_btn = QPushButton("Check inputs")
        self.classify_btn = QPushButton("Classify")
        f = self.classify_btn.font()
        f.setBold(True)
        self.classify_btn.setFont(f)
        self.check_panel = CheckPanel(self.check_btn, self.classify_btn, action="classifying")
        root.addWidget(self.check_panel)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(Collapsible("Log", self.log))

        bar = QHBoxLayout()
        self.gear = QToolButton()
        self.gear.setText("\u2699")
        self.gear.setPopupMode(_enum(QToolButton, "ToolButtonPopupMode", "InstantPopup"))
        menu = QMenu(self.gear)
        menu.addAction("About DamIT Hazard\u2026", self._about)
        self.gear.setMenu(menu)
        bar.addWidget(self.gear)
        bar.addStretch(1)
        bar.addWidget(self.check_btn)
        bar.addWidget(self.classify_btn)
        self.close_btn = QPushButton("Close")
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

        self.r_preset.toggled.connect(self._mode_changed)
        self.preset.currentIndexChanged.connect(self._mode_changed)
        for boxes in (self.m_boxes[1], self.r_boxes[1], self.s_boxes[1]):
            for cb in boxes.values():
                cb.toggled.connect(self._ticks_changed)
        self.check_btn.clicked.connect(lambda: self.check_panel.set_results(self._problems()))
        self.classify_btn.clicked.connect(self._run)
        self.close_btn.clicked.connect(self.reject)
        self._mode_changed()
        fit_window(self, prefer=(760, 720), key="DamitHazard/size")

    # -- building blocks -------------------------------------------------------------------
    def _boxes(self, records, order, cols):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        out = {}
        for i, rid in enumerate(order):
            rec = records[rid]
            cb = QCheckBox("{}  {}".format(rid, rec["name"]))
            out[rid] = cb
            g.addWidget(cb, i // cols, i % cols)
        return w, out

    def _browse(self, line, kind):
        b = QPushButton("Browse\u2026")
        if kind == "dir":
            b.clicked.connect(lambda: self._pick(line, QFileDialog.getExistingDirectory(
                self, "Output folder")))
        else:
            b.clicked.connect(lambda: self._pick(line, QFileDialog.getOpenFileName(
                self, "JSON file", "", "JSON (*.json)")[0]))
        return b

    @staticmethod
    def _pick(line, value):
        if value:
            line.setText(value)

    def _pid(self):
        return None if self.r_custom.isChecked() else self.preset_ids[self.preset.currentIndex()]

    def _ticked(self, boxes):
        return [k for k, cb in boxes[1].items() if cb.isChecked()]

    def _config(self, overrides=None):
        pid = self._pid()
        adv = self.advisory.isChecked()
        if pid:
            return C.preset_config(self.cat, pid, overrides=overrides, apply_advisory=adv)
        sd = self._ticked(self.s_boxes)
        return C.custom_config(self.cat, self._ticked(self.m_boxes), self._ticked(self.r_boxes),
                               [s for s in sd if s.startswith("S")],
                               [s for s in sd if s.startswith("D")], overrides,
                               apply_advisory=adv)

    # -- state -----------------------------------------------------------------------------
    def _mode_changed(self, *a):
        pid = self._pid()
        self.preset.setEnabled(pid is not None)
        self.preset.setToolTip("" if pid else "Choose Jurisdiction preset to use one.")
        if pid:
            p = self.cat["presets"][pid]
            sc = set(p["scenarios"]) | set(p.get("optional_scenarios", {})) | \
                set(p.get("scenarios_any_of", [])) | set(p.get("domains", []))
            ticks = (set(p["methods"]), set(p["modifiers"]), sc)
            ver = p.get("verification", "verified")
            note = p.get("notes", "")
            self.preset_note.setText(("" if ver == "verified" else
                                      "Verification: {}. ".format(ver)) + note)
        else:
            self.preset_note.setText("Custom mode uses generic class labels (Minimal, Low, "
                                     "Significant, High, Extremely High). The report still "
                                     "cites each method's source.")
        for i, boxes in enumerate((self.m_boxes, self.r_boxes, self.s_boxes)):
            for k, cb in boxes[1].items():
                cb.blockSignals(True)
                if pid:
                    cb.setChecked(k in ticks[i])
                cb.setEnabled(pid is None)
                cb.setToolTip(PRESET_TIP if pid else self._tip(k))
                cb.blockSignals(False)
        self._fill_params()

    def _tip(self, rid):
        rec = self.cat["methods"].get(rid) or self.cat["modifiers"].get(rid) or \
            self.cat["scenarios"].get(rid) or self.cat.get("domains", {}).get(rid) or {}
        return rec.get("rule") or rec.get("condition") or ""

    def _ticks_changed(self, *a):
        self.check_panel.clear()
        self._fill_params()

    def _fill_params(self, *a):
        try:
            cfg = self._config()
        except C.CatalogError as e:
            self.params.setPlainText("")
            self.log.appendPlainText(str(e))
            return
        out = {}
        for rid, e in list(cfg["methods"].items()) + list(cfg["modifiers"].items()):
            if e.get("params"):
                out[rid] = e["params"]
        for d, prm in cfg.get("domains", {}).items():
            out[d] = prm
        self.params.setPlainText(json.dumps(out, indent=2, ensure_ascii=False))

    def _overrides(self):
        text = self.params.toPlainText().strip()
        return json.loads(text) if text else {}

    # -- checks ----------------------------------------------------------------------------
    def _problems(self):
        res = []
        if self.rasters["DEPTH"].currentLayer() is None:
            res.append((ERROR, "Maximum depth raster is required"))
        if not self.out.text().strip():
            res.append((ERROR, "Output folder is required"))
        try:
            ov = self._overrides()
            if not isinstance(ov, dict):
                raise ValueError("the parameters must be a JSON object")
        except ValueError as e:
            res.append((ERROR, "Parameters are not valid JSON: {}".format(e)))
            ov = None
        pid = self._pid()
        if pid is None and not self._ticked(self.m_boxes):
            res.append((ERROR, "Custom mode: tick at least one method"))
        for key, label in FILES:
            path = self.files[key].text().strip()
            if path and not os.path.isfile(path):
                res.append((ERROR, "{} not found: {}".format(label, path)))
        if pid:
            ver = self.cat["presets"][pid].get("verification", "verified")
            if ver != "verified":
                res.append((WARNING, "Preset is {}: check it against the current rule".format(
                    ver)))
        have = {kind for key, kind, _l in LAYERS
                if kind and self.layers[key].currentLayer() is not None}
        try:
            methods = self._config(ov if isinstance(ov, dict) else None)["methods"]
        except C.CatalogError:
            methods = {}
        for mid in methods:
            kinds = self.cat["methods"][mid]["receptor_kinds"]
            if not have.intersection(kinds):
                res.append((WARNING, "{} has no {} layer: it will be reported as not "
                                     "evaluated".format(mid, " or ".join(kinds))))
        if self.rasters["VELOCITY"].currentLayer() is None and \
                self.rasters["DV"].currentLayer() is None and \
                any(m in methods for m in ("M1", "M3", "M10b")):
            res.append((WARNING, "No velocity or DV raster: depth-velocity methods are flagged "
                                 "as missing input"))
        if not [x for x in res if x[0] == ERROR]:
            res.append((OK, "Inputs and output folder are set"))
        return res

    # -- run -------------------------------------------------------------------------------
    def params_dict(self):
        """The damit:classify parameters this window would run (also used by the tests)."""
        pid = self._pid()
        sd = self._ticked(self.s_boxes)
        p = {"PRESET": 0 if pid is None else 1 + self.preset_ids.index(pid),
             "METHODS": ",".join(self._ticked(self.m_boxes)) if pid is None else "",
             "MODIFIERS": ",".join(self._ticked(self.r_boxes)) if pid is None else "",
             "SCENARIOS": ",".join(sd) if pid is None else "",
             "OVERRIDES": json.dumps(self._overrides()),
             "APPLY_ADVISORY": self.advisory.isChecked(),
             "RUN_SCENARIO": 1 + self.scenario.currentIndex(),
             "MODEL_DIM": self.dim.currentIndex(), "METRES": self.metres.isChecked(),
             "DAM_NAME": self.dam.text().strip(), "OUTPUT": self.out.text().strip()}
        for key, _l, _r in RASTERS:
            lyr = self.rasters[key].currentLayer()
            if lyr is not None:
                p[key] = lyr
        for key, _k, _l in LAYERS:
            lyr = self.layers[key].currentLayer()
            if lyr is not None:
                p[key] = lyr
        for key, _l in FILES:
            if self.files[key].text().strip():
                p[key] = self.files[key].text().strip()
        return p

    def _run(self):
        self.check_panel.set_results(self._problems())
        if self.check_panel.blocked:
            return
        self.log.clear()
        self.result.setText("")
        try:
            import processing
            res = processing.run("damit:classify", self.params_dict(),
                                 feedback=_Feedback.make(self.log.appendPlainText))
        except Exception as e:                                                # noqa
            self.log.appendPlainText(traceback.format_exc())
            QMessageBox.critical(self, TITLE, "The run failed: {}".format(e))
            return
        self.result.setText("Suggested class: {}. Report: {}".format(res.get("CLASS"),
                                                                    res.get("REPORT")))
        if self.iface is not None and res.get("GPKG"):
            from qgis.core import QgsVectorLayer
            for key, _k, _l in LAYERS:
                name = key.lower()
                lyr = QgsVectorLayer("{}|layername={}".format(res["GPKG"], name),
                                     "DamIT {}".format(name), "ogr")
                if lyr.isValid():
                    from . import styles
                    styles.apply(lyr, C.labels_for(self.cat, self._pid()))
                    from qgis.core import QgsProject
                    QgsProject.instance().addMapLayer(lyr)

    def _about(self):
        QMessageBox.information(self, TITLE, self.cat.get("disclaimer", "") +
                                "\n\nOne Processing tool (damit:classify) and this window. "
                                "Catalog {}.".format(self.cat.get("catalog_version")))
