"""DamIT Catalog access for the plugins that depend on it (declared in plugin_dependencies).

Finds the installed ``damit_catalog`` package (QGIS puts the plugins folder on sys.path), else the
``damit_catalog`` folder beside ``damit_core`` (a checkout of the damit repository, CI and tests).
"""
import os
import sys


class CatalogMissing(ImportError):
    pass


def modules():
    """(catalog, evaluate) modules of DamIT Catalog."""
    try:
        from damit_catalog import catalog, evaluate
        return catalog, evaluate
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "damit_catalog")) and here not in sys.path:
            sys.path.append(here)
            try:
                from damit_catalog import catalog, evaluate
                return catalog, evaluate
            except ImportError:
                pass
    raise CatalogMissing("DamIT Catalog is not installed. Install the 'DamIT Catalog' plugin: it holds "
                         "the presets, methods and thresholds the DamIT tools use.")


def load(folder=None):
    """The loaded catalog: ``folder``, else the ``catalog_dir`` setting, else DAMIT_CATALOG_DIR or the
    bundled data (DamIT Catalog decides)."""
    catalog, _ = modules()
    if not folder:
        try:
            from . import settings
            folder = settings.get("catalog_dir") or None
        except Exception:                                 # noqa: BLE001
            folder = None
    return catalog.load(folder or None)


def preset_choices(cat):
    """[(preset_id, label)] in catalog order."""
    return [(pid, p.get("label") or pid) for pid, p in cat.presets.items()]


def preset_for_state(cat, postal):
    """The catalog preset whose ID is the state's postal code, else None (the user then picks an
    agency preset such as FEMA333 or custom mode; DamIT never assumes a jurisdiction)."""
    code = str(postal or "").strip().upper()
    return cat.canonical_preset_id(code) if code else None


def resolve(cat, mode, preset_id="", method_ids=None, scenario_ids=None):
    if (mode or "preset").lower() == "custom":
        return cat.resolve_custom(list(method_ids or []), list(scenario_ids or []) or None)
    return cat.resolve_preset(preset_id, list(scenario_ids or []) or None)
