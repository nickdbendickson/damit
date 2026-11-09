"""DamIT suite settings: one small key/value store shared by the DamIT plugins.

Backend, first that applies:
  1. ``DAMIT_SETTINGS`` environment variable set: that JSON file (tests, portable installs);
  2. inside a running QGIS: QgsSettings group ``damit/`` (per QGIS profile);
  3. otherwise ``~/.config/damit/settings.json``.

Keys (all strings; empty = not set). Nothing here is a jurisdiction rule: the preset is only the
ID the user picked in DamIT Catalog.
"""
import json
import os
import tempfile

ENV = "DAMIT_SETTINGS"
GROUP = "damit"
KEYS = {
    "data_folder": "suite data folder (layers for the DamIT tools; DamIT Data downloads here)",
    "work_folder": "work folder for DamIT Screener / Runner runs (never inside the data folder)",
    "catalog_dir": "edited DamIT Catalog data folder (empty = the installed catalog)",
    "state": "US state / territory postal code the user works in (e.g. ND, NE)",
    "preset": "DamIT Catalog preset ID (preset mode)",
    "dams_layer": "dam points layer (path or path|layername=...)",
    "terrain": "DEM raster",
    "structures_layer": "structures / buildings layer",
    "roads_layer": "roads layer",
    "rail_layer": "railroads layer",
    "pfds_cache": "cache folder for NOAA Atlas 14 PFDS answers (DamIT PMP)",
}


def _json_path():
    p = os.environ.get(ENV)
    if p:
        return p
    return os.path.join(os.path.expanduser("~"), ".config", "damit", "settings.json")


def _qgis_settings():
    if os.environ.get(ENV):
        return None
    try:
        from qgis.core import QgsApplication, QgsSettings
    except ImportError:
        return None
    if QgsApplication.instance() is None:
        return None
    return QgsSettings()


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings_", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def backend():
    """'qgis' or the JSON file path in use."""
    return "qgis" if _qgis_settings() is not None else _json_path()


def get(key, default=""):
    _check(key)
    qs = _qgis_settings()
    if qs is not None:
        v = qs.value("{}/{}".format(GROUP, key), default)
        return "" if v is None else str(v)
    return str(_read_json(_json_path()).get(key, default) or default)


def set(key, value):  # noqa: A001 - mirrors QgsSettings
    _check(key)
    value = "" if value is None else str(value)
    qs = _qgis_settings()
    if qs is not None:
        qs.setValue("{}/{}".format(GROUP, key), value)
        return
    path = _json_path()
    d = _read_json(path)
    d[key] = value
    _write_json(path, d)


def all_settings():
    return {k: get(k) for k in KEYS}


def fill_empty(values):
    """Set each key of ``values`` only where the stored value is empty. Returns the keys set."""
    done = []
    for k, v in values.items():
        if v not in (None, "") and not get(k):
            set(k, v)
            done.append(k)
    return done


def _check(key):
    if key not in KEYS:
        raise KeyError("unknown DamIT setting {!r} (known: {})".format(key, ", ".join(sorted(KEYS))))
