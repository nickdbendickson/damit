"""DamIT Core plugin shell: a library; the only menu entry is About."""
import os

MENU = "&DamIT"


class DamitCorePlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):  # noqa: N802
        try:
            from qgis.PyQt.QtGui import QIcon
            from .lib.qtcompat import QAction
            icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
            self.action = QAction(icon, "About DamIT Core\u2026", self.iface.mainWindow())
            self.action.setObjectName("DamitCoreAboutAction")
            self.action.triggered.connect(self.about)
            self.iface.addPluginToMenu(MENU, self.action)
        except Exception:                               # noqa: BLE001 - a library never blocks QGIS
            self.action = None

    def unload(self):
        try:
            if self.action is not None:
                self.iface.removePluginMenu(MENU, self.action)
        except Exception:                               # noqa: BLE001
            pass
        self.action = None

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
