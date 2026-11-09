import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.classify import ClassifyLite

PROVIDER_ID = "damit_lite"      # distinct from damit (DamIT Hazard, damit:classify), nddam and ndbreach


class DamitLiteProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        self.addAlgorithm(ClassifyLite())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT Hazard Lite"

    def longName(self):  # noqa: N802
        return "DamIT Hazard Lite 0.1.0"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
