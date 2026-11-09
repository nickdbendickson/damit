import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.pf_algs import ALGORITHMS

PROVIDER_ID = "damit_pmp"


class DamitPmpProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT PMP (NOAA Atlas 14)"

    def longName(self):  # noqa: N802
        return "DamIT PMP 0.1.0 - NOAA Atlas 14 only"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
