"""Processing provider 'damit' (DamIT)."""
import os

from qgis.core import QgsProcessingProvider


class Provider(QgsProcessingProvider):
    def id(self):
        return "damit"

    def name(self):
        return "DamIT"

    def longName(self):
        return "DamIT dam hazard tools"

    def icon(self):
        from qgis.PyQt.QtGui import QIcon
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))

    def loadAlgorithms(self):
        from .algorithms.classify import Classify
        self.addAlgorithm(Classify())
