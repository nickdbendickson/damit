# -*- coding: utf-8 -*-
"""One settings window for the DamIT suite (ported from DamSafety Core 1.6.0, adapted
for DamIT's key/value settings store and shared defaults file).

Until Core 0.4.0 DamIT Core only had an About entry; each tool read
damit_core.lib.settings on its own. Now there is one window, "DamIT Suite — Settings",
one per QGIS: a short file/backend row at the top and a tab for Suite folders, Catalog,
Layers, Shared defaults, and any tab a plugin registers.

A plugin registers its tab when it loads (`register_section`) with a factory that
returns {"page": QWidget, "on_show": optional callable}. Plugins > DamIT > Suite
settings… opens the window. There is no offline_pack setting: leave that empty;
this window does not add one.
"""
import os

TITLE = "DamIT Suite \u2014 Settings"
ACTION = ("Suite settings\u2026", "DamitSuiteSettings")          # (label, object name)
# built-in tabs (key -> (title, order))
BUILTIN = (("suite", "Suite", 1), ("catalog", "Catalog", 2),
           ("layers", "Layers", 3), ("defaults", "Shared defaults", 4))

# settings keys shown on each built-in tab (shared defaults are a different file)
SUITE_KEYS = ("data_folder", "work_folder", "unit_system", "defaults_file", "pfds_cache")
CATALOG_KEYS = ("catalog_dir", "state", "preset")
LAYER_KEYS = ("dams_layer", "terrain", "structures_layer", "roads_layer", "rail_layer")

_SECTIONS = {}          # key -> {"factory", "title", "order"}
_WINDOW = None          # the one live window, or None


def register_section(key, factory, title=None, order=None):
    """The tab of plugin `key`; `factory()` returns {"page": QWidget, ...}."""
    _SECTIONS[key] = {"factory": factory, "title": title or key, "order": 20 if order is None else order}
    win = _WINDOW
    if _alive(win):
        win.sync_tabs()


def unregister_section(key):
    _SECTIONS.pop(key, None)
    win = _WINDOW
    if _alive(win):
        win.drop(key)
        win.sync_tabs()


def registered():
    """{key: (title, order)} of plugin-registered sections (not the built-in tabs)."""
    return {k: (v["title"], v["order"]) for k, v in _SECTIONS.items()}


def _alive(obj):
    if obj is None:
        return False
    try:
        obj.objectName()
        return True
    except Exception:
        return False


def window(parent=None, create=True):
    global _WINDOW
    win = _WINDOW if _alive(_WINDOW) else None
    if win is None and create:
        win = SuiteSettingsWindow(parent)
        _WINDOW = win
    return win


def open_settings(key=None, factory=None, parent=None):
    """Show the one settings window, on tab `key` when given."""
    if key and factory is not None and key not in _SECTIONS:
        register_section(key, factory)
    win = window(parent)
    win.sync_tabs()
    if key:
        win.show_section(key)
    win.refresh()
    win.show()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass
    return win


# ------------------------------------------------------------------ window --
class SuiteSettingsWindow(object):
    """Built in __new__ as a QDialog so the class can be imported without Qt."""

    def __new__(cls, parent=None):
        from qgis.PyQt.QtWidgets import QDialog
        inst = QDialog.__new__(QDialog)
        inst.__class__ = type("SuiteSettingsWindow", (QDialog, object), dict(cls.__dict__))
        inst._init_window(parent)
        return inst

    def _init_window(self, parent=None):
        from qgis.PyQt.QtWidgets import (
            QDialogButtonBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout,
        )
        from qgis.PyQt.QtWidgets import QDialog
        QDialog.__init__(self, parent)
        self.setWindowTitle(TITLE)
        self.setObjectName("DamitSuiteSettingsWindow")
        self.built = {}          # key -> section dict
        self.errors = {}
        self._loading = False
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        self.backend_label = QLabel()
        self.backend_label.setWordWrap(True)
        row.addWidget(self.backend_label, 1)
        root.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._tab_shown)
        root.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.close)
        # Qt6: StandardButton enum; Qt5: the same names on the class
        root.addWidget(buttons)
        self.resize(720, 520)
        self.sync_tabs()
        self.refresh()

    def sync_tabs(self):
        """Make the tab bar match the built-in tabs plus registered plugin tabs."""
        wanted = [(k, t, o) for k, t, o in BUILTIN] + [
            (k, v["title"], v["order"]) for k, v in _SECTIONS.items()
        ]
        wanted.sort(key=lambda r: (r[2], r[0]))
        have = [self.tabs.widget(i).property("damit_tab_key") for i in range(self.tabs.count())]
        want_keys = [k for k, _t, _o in wanted]
        # drop stale plugin tabs
        for i in range(self.tabs.count() - 1, -1, -1):
            key = self.tabs.widget(i).property("damit_tab_key")
            if key not in want_keys:
                self.drop(key)
        for key, title, _order in wanted:
            if key in [self.tabs.widget(i).property("damit_tab_key") for i in range(self.tabs.count())]:
                continue
            page = self._build_tab(key)
            if page is None:
                continue
            page.setProperty("damit_tab_key", key)
            self.tabs.addTab(page, title)

    def _build_tab(self, key):
        if key == "suite":
            return self._keys_page(SUITE_KEYS, "Suite folders, units and the defaults file.")
        if key == "catalog":
            return self._catalog_page()
        if key == "layers":
            return self._keys_page(LAYER_KEYS, "Default layers the DamIT tools start from. Empty is unset.")
        if key == "defaults":
            return self._defaults_page()
        sec = _SECTIONS.get(key)
        if not sec:
            return None
        try:
            info = sec["factory"]() or {}
            page = info.get("page")
            self.built[key] = info
            return page
        except Exception as e:                                   # noqa
            self.errors[key] = str(e)
            from qgis.PyQt.QtWidgets import QLabel, QWidget, QVBoxLayout
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.addWidget(QLabel("This tab could not be built:\n{}".format(e)))
            return page

    def _keys_page(self, keys, intro):
        from qgis.PyQt.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QWidget, QComboBox
        from damit_core.lib import settings
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(QLabel(intro))
        edits = {}
        for key in keys:
            if key == "unit_system":
                box = QComboBox()
                box.addItem("US customary (ft, cfs)", "us")
                box.addItem("SI (m, m\u00b3/s)", "si")
                edits[key] = box
                form.addRow(settings.KEYS[key].split("(")[0].strip().capitalize() + ":", box)
                continue
            edit = QLineEdit()
            edit.setClearButtonEnabled(True)
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            kind = "folder" if key in ("data_folder", "work_folder", "catalog_dir", "pfds_cache") else \
                "file" if key in ("defaults_file", "dams_layer", "terrain", "structures_layer",
                                  "roads_layer", "rail_layer") else None
            if kind:
                btn = QPushButton("Browse\u2026")
                btn.clicked.connect(lambda _=False, e=edit, k=kind: self._browse(e, k))
                row.addWidget(btn)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(settings.KEYS[key] + ":", wrap)
            edits[key] = edit
        page._damit_edits = edits
        page._damit_kind = "keys"
        return page

    def _catalog_page(self):
        from qgis.PyQt.QtWidgets import (QFormLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout,
                                         QWidget, QComboBox)
        from damit_core.lib import settings, states
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(QLabel("The catalog folder, the state you work in, and the Catalog preset. "
                           "DamIT never assumes a jurisdiction: leave state / preset empty until you pick one."))
        edits = {}
        folder = QLineEdit()
        folder.setClearButtonEnabled(True)
        row = QHBoxLayout()
        row.addWidget(folder, 1)
        btn = QPushButton("Browse\u2026")
        btn.clicked.connect(lambda _=False, e=folder: self._browse(e, "folder"))
        row.addWidget(btn)
        wrap = QWidget()
        wrap.setLayout(row)
        form.addRow(settings.KEYS["catalog_dir"] + ":", wrap)
        edits["catalog_dir"] = folder

        state = QComboBox()
        state.setEditable(False)
        state.addItem("(not set)", "")
        for rec in states.table():
            state.addItem("{} \u2014 {}".format(rec["postal"], rec["name"]), rec["postal"])
        form.addRow("State / territory:", state)
        edits["state"] = state

        preset = QComboBox()
        preset.setEditable(True)
        preset.setInsertPolicy(preset.NoInsert if hasattr(preset, "NoInsert") else 0)
        self._fill_presets(preset)
        form.addRow(settings.KEYS["preset"] + ":", preset)
        edits["preset"] = preset
        page._damit_edits = edits
        page._damit_kind = "keys"
        return page

    def _fill_presets(self, box):
        box.clear()
        box.addItem("(not set)", "")
        try:
            from damit_core.lib import catalog_access
            cat = catalog_access.load()
            for pid, label in catalog_access.preset_choices(cat):
                box.addItem("{} \u2014 {}".format(pid, label) if label != pid else pid, pid)
        except Exception:
            pass

    def _defaults_page(self):
        from qgis.PyQt.QtWidgets import (QFormLayout, QLabel, QComboBox, QDoubleSpinBox, QWidget)
        from damit_core.lib import shared_defaults as D
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(QLabel("Shared defaults every DamIT tool starts from. Your file "
                           "({path}) holds only the keys you change; the rest follow the shipped suite values. "
                           "Manning's n is the fallback where there is no n raster / land cover.".format(
                               path=D.user_path())))
        widgets = {}
        for key, spec in D.SCHEMA.items():
            if spec["kind"] == "choice":
                box = QComboBox()
                for cid, label in spec["choices"].items():
                    box.addItem(label, cid)
                widgets[key] = box
                form.addRow(spec["label"] + ":", box)
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(int(spec.get("decimals", 3)))
                spin.setMinimum(float(spec["minimum"]))
                spin.setMaximum(float(spec["maximum"]))
                spin.setSingleStep(10 ** (-int(spec.get("decimals", 3))))
                widgets[key] = spin
                form.addRow(spec["label"] + ":", spin)
        page._damit_defaults = widgets
        page._damit_kind = "defaults"
        return page

    def _browse(self, edit, kind):
        from qgis.PyQt.QtWidgets import QFileDialog
        start = edit.text().strip() or os.path.expanduser("~")
        if kind == "folder":
            path = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        else:
            path, _f = QFileDialog.getOpenFileName(self, "Choose file", start)
        if path:
            edit.setText(path)

    def _iter_pages(self):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            yield w.property("damit_tab_key"), w

    def refresh(self):
        """Fill every built-in tab from the current settings / defaults files."""
        from damit_core.lib import settings, display_units, shared_defaults as D
        self._loading = True
        try:
            self.backend_label.setText("Settings store: {}.".format(settings.backend()))
            for key, page in self._iter_pages():
                if getattr(page, "_damit_kind", None) == "keys":
                    self._fill_keys(page)
                elif getattr(page, "_damit_kind", None) == "defaults":
                    self._fill_defaults(page)
                info = self.built.get(key) or {}
                cb = info.get("on_show")
                if cb:
                    try:
                        cb()
                    except Exception:
                        pass
        finally:
            self._loading = False

    def _fill_keys(self, page):
        from damit_core.lib import settings, display_units
        for key, widget in page._damit_edits.items():
            val = settings.get(key)
            if key == "unit_system":
                val = display_units.normalize(val)
                idx = widget.findData(val)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            elif widget.__class__.__name__ == "QComboBox":
                idx = widget.findData(val)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                elif widget.isEditable():
                    widget.setEditText(val)
                else:
                    widget.setCurrentIndex(0)
            else:
                widget.setText(val)

    def _fill_defaults(self, page):
        from damit_core.lib import shared_defaults as D
        d = D.load()
        for key, widget in page._damit_defaults.items():
            val = d.values.get(key)
            if widget.__class__.__name__ == "QComboBox":
                idx = widget.findData(val)
                widget.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                if val is not None:
                    widget.setValue(float(val))

    def _read_keys(self, page):
        out = {}
        for key, widget in page._damit_edits.items():
            if widget.__class__.__name__ == "QComboBox":
                data = widget.currentData()
                if data is None and widget.isEditable():
                    data = widget.currentText().strip()
                out[key] = "" if data is None else str(data)
            else:
                out[key] = widget.text().strip()
        return out

    def _read_defaults(self, page):
        out = {}
        for key, widget in page._damit_defaults.items():
            if widget.__class__.__name__ == "QComboBox":
                out[key] = widget.currentData()
            else:
                out[key] = widget.value()
        return out

    def save(self):
        """Write the suite settings and the user's shared defaults. Never writes an offline_pack."""
        from damit_core.lib import settings, display_units, shared_defaults as D
        from qgis.PyQt.QtWidgets import QMessageBox
        keys, defaults = {}, None
        for _key, page in self._iter_pages():
            if getattr(page, "_damit_kind", None) == "keys":
                keys.update(self._read_keys(page))
            elif getattr(page, "_damit_kind", None) == "defaults":
                defaults = self._read_defaults(page)
        try:
            if "unit_system" in keys:
                keys["unit_system"] = display_units.normalize(keys["unit_system"])
            # never invent an offline pack path
            keys.pop("offline_pack", None)
            for k, v in keys.items():
                settings.set(k, v)
            if defaults is not None:
                D.save_user(defaults)
        except Exception as e:                                   # noqa
            QMessageBox.warning(self, TITLE, "The settings could not be saved:\n{}".format(e))
            return False
        self.refresh()
        return True

    def show_section(self, key):
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).property("damit_tab_key") == key:
                self.tabs.setCurrentIndex(i)
                return True
        return False

    def drop(self, key):
        self.built.pop(key, None)
        self.errors.pop(key, None)
        for i in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(i).property("damit_tab_key") == key:
                w = self.tabs.widget(i)
                self.tabs.removeTab(i)
                if w is not None:
                    w.deleteLater()

    def _tab_shown(self, _index):
        if self._loading:
            return
        key = self.tabs.currentWidget().property("damit_tab_key") if self.tabs.currentWidget() else None
        info = self.built.get(key) or {}
        cb = info.get("on_show")
        if cb:
            try:
                cb()
            except Exception:
                pass

    def showEvent(self, event):
        from qgis.PyQt.QtWidgets import QDialog
        QDialog.showEvent(self, event)
        self.sync_tabs()
        self.refresh()

