"""DamIT PMP: registers provider damit_pmp (NOAA Atlas 14 only) and a menu entry."""
import os

from qgis.core import QgsApplication

MENU = "&DamIT"


class DamitPmpPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None

    def initProcessing(self):  # noqa: N802
        from .provider import DamitPmpProvider
        self.provider = DamitPmpProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from . import _deps  # noqa: F401
        from damit_core.lib.qtcompat import QAction
        icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
        self.action = QAction(icon, "NOAA Atlas 14 at a point\u2026 (DamIT PMP)", self.iface.mainWindow())
        self.action.triggered.connect(lambda: __import__("processing").execAlgorithmDialog("damit_pmp:pointpf", {}))
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
