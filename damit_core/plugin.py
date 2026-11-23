"""DamIT Core plugin shell: suite settings and About."""
import os

MENU = "&DamIT"


class DamitCorePlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.settings_action = None

    def initGui(self):  # noqa: N802
        try:
            from qgis.PyQt.QtGui import QIcon
            from .lib.qtcompat import QAction
            icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
            parent = self.iface.mainWindow()
            self.settings_action = QAction(icon, "Suite settings\u2026", parent)
            self.settings_action.setObjectName("DamitSuiteSettings")
            self.settings_action.triggered.connect(self.open_settings)
            self.iface.addPluginToMenu(MENU, self.settings_action)
            self.action = QAction(icon, "About DamIT Core\u2026", parent)
            self.action.setObjectName("DamitCoreAboutAction")
            self.action.triggered.connect(self.about)
            self.iface.addPluginToMenu(MENU, self.action)
        except Exception:                               # noqa: BLE001 - a library never blocks QGIS
            self.action = None
            self.settings_action = None

    def unload(self):
        try:
            if self.settings_action is not None:
                self.iface.removePluginMenu(MENU, self.settings_action)
            if self.action is not None:
                self.iface.removePluginMenu(MENU, self.action)
        except Exception:                               # noqa: BLE001
            pass
        self.action = None
        self.settings_action = None

    def open_settings(self):
        try:
            from .ui.suite_settings_window import open_settings
            open_settings(parent=self.iface.mainWindow())
        except Exception as e:                          # noqa: BLE001
            try:
                from qgis.PyQt.QtWidgets import QMessageBox
                QMessageBox.warning(self.iface.mainWindow(), "DamIT Core",
                                    "The suite settings window could not be opened:\n{}".format(e))
            except Exception:                           # noqa: BLE001
                pass

    def about_text(self):
        from .lib import plugins, VERSION
        lines = ["DamIT Core {} - shared library of the DamIT plugins.".format(VERSION), ""]
        for row in plugins.check_suite():
            lines.append(plugins.status_line(row))
        return "\n".join(lines)

    def about(self):
        try:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.information(self.iface.mainWindow(), "DamIT Core", self.about_text())
        except Exception:                               # noqa: BLE001
            pass
