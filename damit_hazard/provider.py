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
        add_algorithms(self)


def add_algorithms(provider):
    """Register every damit:* tool that is not already on `provider`.

    Another DamIT plugin may have created the shared provider id first. Each tool is added
    once, by name.
    """
    from .algorithms.classify import Classify
    from .algorithms.reviewhabitable import ReviewHabitable
    from .algorithms.catalog_tools import ALGORITHMS
    for cls in (Classify, ReviewHabitable) + tuple(ALGORITHMS):
        alg = cls()
        if provider.algorithm(alg.name()) is None:
            provider.addAlgorithm(alg)
