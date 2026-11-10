import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.rundam import ALGORITHMS

PROVIDER_ID = "damit_run"        # distinct from ndbreach, nddam and damit (DamIT Hazard)


class DamitRunProvider(QgsProcessingProvider):
    def load(self):
        # 0.3.0: where an empty LISFLOOD_EXE looks first (flood/lisflood.find_exe), as the old ND Breach Runner's
        # provider settings; optional - the parameters can carry the path
        try:
            from processing.core.ProcessingConfig import ProcessingConfig, Setting
            from .flood import lisflood as LF
            ProcessingConfig.addSetting(Setting(
                self.name(), LF.SETTING_DAMIT, "LISFLOOD-FP executable (empty = PATH or a usual install place, else "
                "the built-in engine with a warning; 'builtin' = the built-in engine)", "", valuetype=Setting.FILE))
            ProcessingConfig.addSetting(Setting(
                self.name(), LF.SETTING_USE_BUILTIN, "Use the built-in flood engine instead of LISFLOOD-FP (no "
                "install; slower; a screening approximation)", False))
            ProcessingConfig.readSettings()
        except Exception:                                        # noqa: BLE001 - settings are optional
            pass
        self.refreshAlgorithms()
        return True

    def unload(self):
        try:
            from processing.core.ProcessingConfig import ProcessingConfig
            from .flood import lisflood as LF
            for k in (LF.SETTING_DAMIT, LF.SETTING_USE_BUILTIN):
                ProcessingConfig.removeSetting(k)
        except Exception:                                        # noqa: BLE001
            pass

    def loadAlgorithms(self):  # noqa: N802
        for cls in ALGORITHMS:
            self.addAlgorithm(cls())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "DamIT Runner"

    def longName(self):  # noqa: N802
        return "DamIT Runner 0.3.0"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
