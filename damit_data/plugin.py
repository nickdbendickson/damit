"""DamIT Data: provider damit_data, menu entries Download / update... and Add layers."""
import os

from qgis.core import QgsApplication

MENU = "&DamIT"


class DamitDataPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.actions = []

    def initProcessing(self):  # noqa: N802
        from .provider import DamitDataProvider
        self.provider = DamitDataProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from . import _deps  # noqa: F401
        from damit_core.lib.qtcompat import QAction
        icon = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg"))
        for text, slot in (("Download / update offline layers\u2026 (DamIT Data)", self.download),
                           ("Add DamIT Data layers to the project", self.add_layers)):
            a = QAction(icon, text, self.iface.mainWindow())
            a.triggered.connect(slot)
            self.iface.addPluginToMenu(MENU, a)
            self.actions.append(a)

    def unload(self):
        for a in self.actions:
            self.iface.removePluginMenu(MENU, a)
        self.actions = []
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def download(self):
        import processing
        processing.execAlgorithmDialog("damit_data:download", {})

    def add_layers(self, root=None, project=None):
        """Adds every downloaded layer under a 'DamIT data' group. Returns the layers added."""
        from qgis.core import QgsProject, QgsVectorLayer
        from .core import store
        try:
            root = store.root(root)
        except store.StoreError as e:
            self.iface.messageBar().pushWarning("DamIT Data", str(e))
            return []
        project = project or QgsProject.instance()
        group = project.layerTreeRoot().findGroup("DamIT data") or project.layerTreeRoot().addGroup("DamIT data")
        added = []
        for key, path in store.all_layers(root):
            lyr = QgsVectorLayer(path.rstrip("/"), "{} {}".format(key, os.path.basename(path.rstrip("/"))), "ogr")
            if lyr.isValid():
                project.addMapLayer(lyr, False)
                group.addLayer(lyr)
                added.append(lyr)
        if not added:
            self.iface.messageBar().pushWarning("DamIT Data", "No downloaded layers in {} yet.".format(root))
        return added
