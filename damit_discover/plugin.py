"""DamIT Discovery: provider damit_discover, menu entry Discover ponds / reservoirs..."""
import os

from qgis.core import QgsApplication

MENU = "&DamIT"


class DamitDiscoverPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.actions = []

    def initProcessing(self):  # noqa: N802
        from .provider import DamitDiscoverProvider
        self.provider = DamitDiscoverProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from damit_core.lib.qtcompat import QAction
        icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
        a = QAction(icon, "Discover ponds / reservoirs\u2026 (DamIT Discovery)", self.iface.mainWindow())
        a.triggered.connect(self.discover)
        self.iface.addPluginToMenu(MENU, a)
        self.actions.append(a)

    def unload(self):
        for a in self.actions:
            self.iface.removePluginMenu(MENU, a)
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    def discover(self):
        from qgis.processing import execAlgorithmDialog
        execAlgorithmDialog("damit_discover:candidates", {})
