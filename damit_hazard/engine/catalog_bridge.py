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


def damit_catalog():
    """The ``damit_catalog.catalog`` module."""
    try:
        from damit_catalog import catalog          # installed plugin (plugins folder on sys.path)
        return catalog
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "damit_catalog")) and here not in sys.path:
            sys.path.append(here)                   # repository checkout / tests
            try:
                from damit_catalog import catalog
                return catalog
            except ImportError:
                pass
    raise CatalogMissing("DamIT Catalog is not installed. Install the 'DamIT Catalog' plugin: it holds "
                         "the Appendix A presets, methods and thresholds DamIT Hazard classifies with.")
