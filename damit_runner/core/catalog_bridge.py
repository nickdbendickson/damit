"""Import DamIT Catalog (a separate plugin, declared in metadata plugin_dependencies)."""
import os
import sys


class CatalogMissing(ImportError):
    pass


def _import():
    try:
        from damit_catalog import catalog, evaluate, handoff   # installed plugin (plugins dir on sys.path)
        return catalog, evaluate, handoff
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "damit_catalog")) and here not in sys.path:
            sys.path.append(here)                              # monorepo checkout / tests
            try:
                from damit_catalog import catalog, evaluate, handoff
                return catalog, evaluate, handoff
            except ImportError:
                pass
        raise CatalogMissing("DamIT Catalog is not installed. Install the 'DamIT Catalog' plugin "
                             "(it holds the Appendix A presets and the hand-off schema).")


def modules():
    return _import()


def load_catalog(folder=None):
    catalog, _, _ = _import()
    return catalog.load(folder or None)


def resolve(cat, settings):
    """Resolved config from screener settings: mode preset/custom."""
    mode = (settings.get("mode") or "preset").lower()
    scen = [s for s in (settings.get("scenarios") or []) if s]
    if mode == "custom":
        return cat.resolve_custom(settings.get("custom_methods") or [], scen,
                                  settings.get("custom_modifiers") or [], settings.get("custom_cutoffs") or [],
                                  settings.get("custom_params") or {})
    return cat.resolve_preset(settings.get("preset") or "", scen or None, settings.get("method_overrides") or {})
