"""Find DamIT Catalog (a separate plugin, declared in metadata plugin_dependencies).

Same discovery as DamIT Screener / Runner: the installed ``damit_catalog`` package (QGIS puts the
plugins folder on sys.path), else the ``damit_catalog`` folder beside ``damit_hazard`` (a checkout
of the damit repository, CI and tests). The data folder is chosen by DamIT Catalog itself:
the ``DAMIT_CATALOG_DIR`` environment variable, else its bundled ``data/``.
"""
import os
import sys


class CatalogMissing(ImportError):
    pass


def _module(name):
    """``damit_catalog.<name>`` from the installed plugin, else the checkout beside ``damit_hazard``."""
    import importlib
    try:
        return importlib.import_module("damit_catalog." + name)   # installed plugin (plugins folder on sys.path)
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "damit_catalog")) and here not in sys.path:
            sys.path.append(here)                   # repository checkout / tests
            try:
                return importlib.import_module("damit_catalog." + name)
            except ImportError:
                pass
    raise CatalogMissing("DamIT Catalog is not installed. Install the 'DamIT Catalog' plugin: it holds "
                         "the Appendix A presets, methods and thresholds DamIT Hazard classifies with.")


def damit_catalog():
    """The ``damit_catalog.catalog`` module."""
    return _module("catalog")


def damit_handoff():
    """The ``damit_catalog.handoff`` module (hand-off schema and the NID-ID rule, ``nid_rule``)."""
    return _module("handoff")
