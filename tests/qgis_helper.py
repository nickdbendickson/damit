"""One QgsApplication per test process (offscreen, scratch profile) for the DamIT QGIS tests.

Use through tests/run_tests.sh (nice -n 19, single-threaded, QT_QPA_PLATFORM=offscreen,
QGIS_CUSTOM_CONFIG_PATH = a throw-away profile). Never starts a model."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from qgis.core import QgsApplication
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False

_APP = None


def start():
    global _APP
    if not HAVE_QGIS:
        return None
    if QgsApplication.instance() is not None:
        return QgsApplication.instance()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    profile = os.environ.get("QGIS_CUSTOM_CONFIG_PATH") or tempfile.mkdtemp(prefix="damit_qgis_profile_")
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = profile
    os.environ.setdefault("DAMIT_SETTINGS", os.path.join(profile, "damit_settings.json"))
    _APP = QgsApplication([], True, profile)
    _APP.initQgis()
    plug = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
    if plug not in sys.path:
        sys.path.append(plug)
    from processing.core.Processing import Processing
    Processing.initialize()
    return _APP


_KEEP = []          # Python providers must stay referenced while registered


def add_provider(provider):
    reg = QgsApplication.processingRegistry()
    if reg.providerById(provider.id()) is None:
        _KEEP.append(provider)
        reg.addProvider(provider)
    return reg.providerById(provider.id())


class FakeIface(object):
    """The few iface calls the DamIT plugins make."""

    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow
        self.win = QMainWindow()
        self.menus = {}
        self.messages = []

    def mainWindow(self):  # noqa: N802
        return self.win

    def addPluginToMenu(self, menu, action):  # noqa: N802
        self.menus.setdefault(menu, []).append(action)

    def removePluginMenu(self, menu, action):  # noqa: N802
        self.menus.get(menu, []).remove(action)

    def messageBar(self):  # noqa: N802
        iface = self

        class Bar(object):
            def pushWarning(self, title, text):  # noqa: N802
                iface.messages.append((title, text))

            pushInfo = pushSuccess = pushCritical = pushWarning
        return Bar()
