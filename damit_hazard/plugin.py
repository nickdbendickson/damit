"""QGIS side of DamIT Hazard: the 'damit' Processing provider and the DamIT Hazard window."""
import os

from qgis.core import QgsApplication

MENU = "DamIT"


class Plugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.dialog = None

    def initProcessing(self):
        from .provider import Provider
        reg = QgsApplication.processingRegistry()
        if reg.providerById("damit") is not None:
            # another DamIT plugin registered the shared provider id first: add our algorithm
            # to it instead of a second provider of the same id
            from .algorithms.classify import Classify
            prov = reg.providerById("damit")
            if prov.algorithm("classify") is None:
                prov.addAlgorithm(Classify())
            return
        self.provider = Provider()
        reg.addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        from qgis.PyQt.QtGui import QIcon
        from .compat import QAction
        self.action = QAction(QIcon(os.path.join(os.path.dirname(__file__), "icon.svg")),
                              "DamIT Hazard\u2026", self.iface.mainWindow())
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu(MENU, self.action)

    def open(self):
        from .dialog import DamitHazardDialog
        if self.dialog is None:
            from .engine import catalog as C
            try:
                C.load()
            except (C.CatalogError, ImportError) as e:      # DamIT Catalog missing or broken
                from qgis.PyQt.QtWidgets import QMessageBox
                QMessageBox.warning(self.iface.mainWindow(), "DamIT Hazard",
                                    "DamIT Hazard reads its presets and thresholds from the "
                                    "DamIT Catalog plugin, which could not be read:\n\n{}".format(e))
                return
            self.dialog = DamitHazardDialog(self.iface.mainWindow(), self.iface)
        self.dialog.show()
        self.dialog.raise_()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None
