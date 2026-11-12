"""damit_core.lib: pure-Python helpers shared by the DamIT plugins (QGIS optional).

    settings       suite settings (QgsSettings group damit/ or a JSON file)
    plugins        DamIT plugin registry, metadata reading, suite / dependency check
    states         US states and territories (FIPS, bbox, download names)
    dam_record     dam field normalization onto the DamIT Screener dam fields
    catalog_access DamIT Catalog loading, preset list, preset for a state
    http           get_bytes / head / download_file (QGIS network inside QGIS, urllib outside)
    qtcompat       Qt5 / Qt6 names (QAction, exec, field types)
    display_units  the unit system the windows show and accept (US or SI; display only, 0.3.0)
    unit_widgets   SI / US number inputs for Processing tool dialogs and plugin windows (Qt)
"""
import configparser
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _version():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with open(os.path.join(HERE, "metadata.txt"), encoding="utf-8") as fh:
            cp.read_file(fh)
        return cp.get("general", "version", fallback="0.0.0")
    except (OSError, configparser.Error):
        return "0.0.0"


VERSION = _version()


def data_path(name):
    return os.path.join(HERE, "data", name)
