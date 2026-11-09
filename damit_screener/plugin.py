"""DamIT Screener: registers the 'damit_screen' Processing provider."""
from qgis.core import QgsApplication


class DamitScreenerPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):  # noqa: N802
        from .provider import DamitScreenProvider
        self.provider = DamitScreenProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
