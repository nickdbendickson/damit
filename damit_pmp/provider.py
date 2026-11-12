import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.anuga_algs import ALGORITHMS as ANUGA_ALGORITHMS
from .algorithms.pf_algs import ALGORITHMS

PROVIDER_ID = "damit_pmp"


def plugin_version():
    """version= from metadata.txt, so the text shown in QGIS cannot drift from the release."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.txt"), encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("version="):
                    return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return "?"


class DamitPmpProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        for cls in tuple(ALGORITHMS) + tuple(ANUGA_ALGORITHMS):
            self.addAlgorithm(cls())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT PMP (NOAA Atlas 14)"

    def longName(self):  # noqa: N802
        return "DamIT PMP {} - NOAA Atlas 14 only".format(plugin_version())

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
