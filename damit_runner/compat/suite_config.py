"""Suite settings as the ported DamSafety Runner tools read them (DamSafety Core damsuite/suite_config.py).

DamIT keeps its settings in DamIT Core (damit_core/lib/settings.py: QGIS settings group 'damit', or the JSON file
DAMIT_SETTINGS names). This module answers the DamSafety keys from there:

    data_folder     DamIT 'data_folder'
    dams_folder     DamIT 'work_folder' (where DamIT Screener / Runner write), else ~/DamIT/Dams
    lisflood_exe    env DAMIT_RUN_LISFLOOD_EXE, then NDBREACH_LISFLOOD (the provider setting is read by the tools)
    anuga_python    env DAMIT_RUN_ANUGA_PYTHON, then NDBREACH_ANUGA_PYTHON
    unit_system     DamIT 'unit_system'

DamIT has no read-only data pack, so in_suite_pack() is always False. Never raises: a missing DamIT Core or an
unknown key gives ''. Pure Python (QGIS is only touched through DamIT Core)."""
import os

_DAMIT_KEY = {"data_folder": "data_folder", "dams_folder": "work_folder", "unit_system": "unit_system"}
ENV = {"lisflood_exe": ("DAMIT_RUN_LISFLOOD_EXE", "NDBREACH_LISFLOOD"),
       "anuga_python": ("DAMIT_RUN_ANUGA_PYTHON", "NDBREACH_ANUGA_PYTHON"),
       "data_folder": ("DAMIT_DATA_FOLDER",), "dams_folder": ("DAMIT_DAMS_FOLDER",)}


def _core_settings():
    try:
        from damit_core.lib import settings as S
        return S
    except Exception:                                             # noqa: BLE001 - no DamIT Core: env only
        return None


def get(key, project=None):
    """The setting, '' when unset. `project` is accepted for the DamSafety signature and not used."""
    mine = _DAMIT_KEY.get(key)
    S = _core_settings()
    if mine and S is not None:
        try:
            v = S.get(mine)
            if v not in (None, ""):
                return str(v)
        except Exception:                                         # noqa: BLE001 - a settings read never fails a run
            pass
    for name in ENV.get(key, ()):
        v = os.environ.get(name, "")
        if v:
            return v
    return ""


def default_dams_folder():
    return os.path.join(os.path.expanduser("~"), "DamIT", "Dams")


def dams_folder():
    return get("dams_folder") or default_dams_folder()


def data_folder():
    return get("data_folder") or ""


def in_suite_pack(path):
    """DamIT has no read-only pack folder: always False."""
    return False


def safe_dams_folder(candidate=""):
    return str(candidate or "").strip() or dams_folder()
