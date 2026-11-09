"""DamIT Catalog QGIS plugin shell: no Processing provider, no GUI. It installs the catalog
data files and loader so DamIT Screener, DamIT Runner and DamIT Hazard can depend on it."""


class DamitCatalogPlugin(object):
    def __init__(self, iface):
        self.iface = iface

    def initGui(self):  # noqa: N802
        try:
            from qgis.core import Qgis, QgsMessageLog
            from . import catalog
            cat = catalog.load()
            QgsMessageLog.logMessage(
                "DamIT Catalog {} loaded from {} ({} presets, {} methods)".format(
                    cat.version, cat.folder, len(cat.presets), len(cat.methods)),
                "DamIT", Qgis.MessageLevel.Info if hasattr(Qgis, "MessageLevel") else Qgis.Info)
        except Exception as e:                                   # noqa
            try:
                from qgis.core import QgsMessageLog
                QgsMessageLog.logMessage("DamIT Catalog failed to load: {}".format(e), "DamIT")
            except Exception:                                    # noqa
                pass

    def unload(self):
        pass
