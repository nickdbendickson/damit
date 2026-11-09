"""DamIT Setup window: suite data folder, work folder, state / preset, scan and suite check,
Save, Continue in DamIT Screener."""

from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QVBoxLayout, QWidget)

from . import _deps  # noqa: F401
from . import core
from damit_core.lib import catalog_access, plugins, settings, states

CUSTOM = "(custom mode - pick methods in DamIT Screener)"


class SetupDialog(QDialog):
    def __init__(self, parent=None, suite_rows=None, open_algorithm=None):
        super(SetupDialog, self).__init__(parent)
        self.setWindowTitle("DamIT Setup - Start here")
        self.setMinimumWidth(560)
        self._suite_rows = suite_rows
        self._open_algorithm = open_algorithm      # callable(alg_id, params); default processing
        self.found = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.data = QLineEdit(settings.get("data_folder"))
        self.work = QLineEdit(settings.get("work_folder"))
        form.addRow("Suite data folder", self._with_browse(self.data))
        form.addRow("Work folder (runs)", self._with_browse(self.work))
        self.state = QComboBox()
        self.state.addItem("(no state)", "")
        for s in states.table():
            self.state.addItem("{} - {}".format(s["postal"], s["name"]), s["postal"])
        self.preset = QComboBox()
        self.cat = None
        self.catalog_note = QLabel("")
        try:
            self.cat = catalog_access.load()
            for pid, label in catalog_access.preset_choices(self.cat):
                self.preset.addItem("{} - {}".format(pid, label), pid)
            self.catalog_note.setText("DamIT Catalog {} ({} presets)".format(self.cat.version, len(self.cat.presets)))
        except Exception as e:                                   # noqa: BLE001
            self.catalog_note.setText("DamIT Catalog not available: {}".format(e))
        self.preset.addItem(CUSTOM, "")
        form.addRow("State", self.state)
        form.addRow("Preset", self.preset)
        form.addRow("", self.catalog_note)
        lay.addLayout(form)
        self.scan_label = QLabel("")
        self.scan_label.setWordWrap(True)
        self.suite_label = QLabel("")
        self.suite_label.setWordWrap(True)
        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("color: #b00020;")
        for w in (self.scan_label, self.suite_label, self.reason):
            lay.addWidget(w)
        row = QHBoxLayout()
        self.scan_btn = QPushButton("Check folder")
        self.save_btn = QPushButton("Save")
        self.next_btn = QPushButton("Continue in DamIT Screener\u2026")
        close = QPushButton("Close")
        for b in (self.scan_btn, self.save_btn, self.next_btn, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.scan_btn.clicked.connect(self.rescan)
        self.save_btn.clicked.connect(self.save)
        self.next_btn.clicked.connect(self.continue_to_screener)
        close.clicked.connect(self.reject)
        self.state.currentIndexChanged.connect(self._state_changed)
        self._select(self.state, settings.get("state"))
        if settings.get("preset"):
            self._select(self.preset, settings.get("preset"))
        self.rescan()

    def _with_browse(self, edit):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        b = QPushButton("Browse\u2026")
        b.clicked.connect(lambda: self._browse(edit))
        h.addWidget(b)
        return w

    def _browse(self, edit):
        folder = QFileDialog.getExistingDirectory(self, "Folder", edit.text())
        if folder:
            edit.setText(folder)
            self.rescan()

    @staticmethod
    def _select(combo, data):
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _state_changed(self, _i=0):
        if self.cat is None:
            return
        pid = catalog_access.preset_for_state(self.cat, self.state.currentData())
        if pid:
            self._select(self.preset, pid)

    def mode(self):
        return "custom" if not self.preset.currentData() else "preset"

    def suite_rows(self):
        return self._suite_rows if self._suite_rows is not None else plugins.check_suite()

    def rescan(self):
        folder = self.data.text().strip()
        self.found, notes = core.scan(folder) if folder else ({}, [])
        lines = []
        for status, _slot, text in core.scan_lines(self.found):
            lines.append(("\u2713 " if status == "ok" else "\u2715 ") + text)
        self.scan_label.setText("\n".join(lines + notes))
        rows = self.suite_rows()
        self.suite_label.setText("\n".join(plugins.status_line(r) for r in rows
                                           if r["present"] or r["required"]))
        why = self.problem()
        self.reason.setText(why)
        self.next_btn.setEnabled(not why)
        return self.found

    def problem(self):
        return core.problem(self.data.text().strip(), self.work.text().strip(), self.found, self.suite_rows())

    def save(self):
        written = core.fill_settings(self.data.text().strip(), self.work.text().strip(), self.found,
                                     self.state.currentData() or "", self.preset.currentData() or "")
        if self.preset.currentData() and settings.get("preset") != self.preset.currentData():
            settings.set("preset", self.preset.currentData())      # an explicit choice in this window
            written.append("preset")
        return written

    def handoff(self, field_names=None):
        """Write damit_screen_settings.json and return (alg_id, params) for the Screener."""
        from damit_core.lib import dam_record
        work = self.work.text().strip()
        dams = (self.found.get("dams") or [""])[0]
        terrain = (self.found.get("terrain") or [""])[0]
        receptors = (self.found.get("structures") or [""])[0]
        fm = dam_record.suggest_field_map(field_names or _field_names(dams))
        doc = core.screener_settings(self.preset.currentData() or "", self.mode(), terrain, fm,
                                     settings.get("catalog_dir"))
        path = core.write_screener_settings(work, doc)
        params = core.preflight_params(work, dams, terrain, receptors, self.preset.currentData() or "",
                                       self.mode(), fm, path)
        return core.handoff_target("damit_screen:preflight"), params

    def continue_to_screener(self):
        if self.problem():
            return None
        self.save()
        alg, params = self.handoff()
        opener = self._open_algorithm or _processing_dialog
        opener(alg, params)
        self.accept()
        return alg, params


def _field_names(path):
    if not path:
        return []
    try:
        from qgis.core import QgsVectorLayer
        lyr = QgsVectorLayer(path, "dams", "ogr")
        return [f.name() for f in lyr.fields()] if lyr.isValid() else []
    except Exception:                                            # noqa: BLE001
        return []


def _processing_dialog(alg_id, params):
    import processing
    from qgis.core import QgsApplication
    if QgsApplication.processingRegistry().algorithmById(alg_id) is None:
        raise RuntimeError("{} is not available: install and enable DamIT Screener.".format(alg_id))
    processing.execAlgorithmDialog(alg_id, params)
