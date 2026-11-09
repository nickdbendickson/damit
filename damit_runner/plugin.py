"""DamIT Runner: registers the 'damit_run' Processing provider."""
from qgis.core import QgsApplication


class DamitRunnerPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):  # noqa: N802
        from .provider import DamitRunProvider
        self.provider = DamitRunProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
