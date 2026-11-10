import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.rundam import ALGORITHMS as _RUNDAM_ALGS

try:
    from .algorithms.engine import ALGORITHMS as _ENGINE_ALGS
except ImportError:
    _ENGINE_ALGS = []  # outside QGIS or missing dependencies

ALGORITHMS = list(_RUNDAM_ALGS) + list(_ENGINE_ALGS)

PROVIDER_ID = "damit_run"        # distinct from ndbreach, nddam and damit (DamIT Hazard)


class DamitRunProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT Runner"

    def longName(self):  # noqa: N802
        return "DamIT Runner 0.2.0"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
