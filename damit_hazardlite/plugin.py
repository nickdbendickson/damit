"""DamIT Hazard Lite: registers provider damit_lite (damit_lite:classify) and a menu entry."""
import os

from qgis.core import QgsApplication

MENU = "&DamIT"


class DamitHazardLitePlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None

    def initProcessing(self):  # noqa: N802
        from .provider import DamitLiteProvider
        self.provider = DamitLiteProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from . import _deps  # noqa: F401
        from damit_core.lib.qtcompat import QAction
        icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
        self.action = QAction(icon, "Suggest hazard class (lite)\u2026", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        import processing
        params = {}
        try:
            from damit_core.lib import settings
            if settings.get("preset"):
                params["PRESET"] = settings.get("preset")
        except Exception:                                        # noqa: BLE001
            pass
        processing.execAlgorithmDialog("damit_lite:classify", params)
