import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.steps_algs import ALGORITHMS

PROVIDER_ID = "damit_screen"     # distinct from nddam, ndbreach and damit (DamIT Hazard)


class DamitScreenProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT Screener"

    def longName(self):  # noqa: N802
        return "DamIT Screener 0.1.0"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
