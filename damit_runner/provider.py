import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.rundam import ALGORITHMS as _RUNDAM_ALGS

# The ported DamSafety tools (batch, sensitivity, cascade, hydrograph, estimate, check, finishanuga, delineate).
# 0.4.1: a failed import is no longer silent. Until 0.4.0 a missing compat module (structure_flags, suite_config)
# made this import fail, the except below emptied the list, and none of those tools was ever registered.
ENGINE_IMPORT_ERROR = None
try:
    from .algorithms.engine import ALGORITHMS as _ENGINE_ALGS
except ImportError as _e:
    _ENGINE_ALGS = []
    ENGINE_IMPORT_ERROR = "{}: {}".format(type(_e).__name__, _e)

# the handoff rundam (algorithms/rundam.py) owns damit_run:rundam; the ported engine's own rundam would collide
_RUNDAM_NAMES = {cls().name() for cls in _RUNDAM_ALGS}
ALGORITHMS = list(_RUNDAM_ALGS) + [c for c in _ENGINE_ALGS if c().name() not in _RUNDAM_NAMES]

PROVIDER_ID = "damit_run"        # distinct from ndbreach, nddam and damit (DamIT Hazard)


class DamitRunProvider(QgsProcessingProvider):
    def load(self):
        if ENGINE_IMPORT_ERROR:
            try:
                from qgis.core import Qgis, QgsMessageLog
                QgsMessageLog.logMessage(
                    "DamIT Runner: the batch, sensitivity, cascade, hydrograph and estimate tools did not load ({}). "
                    "Only 'Run breach model for one dam' is available.".format(ENGINE_IMPORT_ERROR), "DamIT",
                    Qgis.Warning)
            except Exception:                                    # noqa: BLE001 - a log line only
                pass
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
        return "DamIT Runner 0.6.0"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
