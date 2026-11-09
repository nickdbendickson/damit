"""DamIT Setup plugin: Plugins > DamIT > Start here..."""
import os

MENU = "&DamIT"


class DamitSetupPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):  # noqa: N802
        from qgis.PyQt.QtGui import QIcon
        from . import _deps  # noqa: F401  (puts DamIT Core on the path)
        from damit_core.lib.qtcompat import QAction
        icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
        self.action = QAction(icon, "Start here\u2026 (DamIT Setup)", self.iface.mainWindow())
        self.action.setObjectName("DamitSetupStartAction")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None

    def run(self):
        from damit_core.lib.qtcompat import exec_dialog
        from .dialog import SetupDialog
        try:
            exec_dialog(SetupDialog(self.iface.mainWindow()))
        except Exception as e:                                   # noqa: BLE001 - tell, never silent
            self.iface.messageBar().pushWarning("DamIT Setup", str(e))
