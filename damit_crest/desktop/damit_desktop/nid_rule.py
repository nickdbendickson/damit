"""DamIT Catalog's NID-ID rule, loaded from Catalog's own source file. Crest has no copy of the rule.

The rule (``nid_rule``, ``is_nid_id``, ``NID_ID_RE``, ``OTHER_INVENTORY_RE``) lives in
``damit_catalog/handoff.py``; DamIT Screener, Runner and Hazard call it there. The desk runs outside QGIS, so it
does not import the ``damit_catalog`` plugin package: it loads that one pure-Python file by path, so a rule change
in Catalog is what Crest checks. Searched, in order:

1. ``<bundle>/damit_catalog/handoff.py`` in a PyInstaller build (``damit_crest.spec`` ships the file there);
2. ``<repo>/damit_catalog/handoff.py`` in a checkout of the damit repository (INSTALL.txt: run from the repo).

No fallback copy: when the file is missing Crest stops with :class:`CatalogRuleMissing` instead of guessing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


class CatalogRuleMissing(ImportError):
    pass


def candidates() -> list[Path]:
    out = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        out.append(Path(bundle) / "damit_catalog" / "handoff.py")
    # damit_desktop -> desktop -> damit_crest -> repository root
    out.append(Path(__file__).resolve().parents[3] / "damit_catalog" / "handoff.py")
    return out


def _load():
    for path in candidates():
        if path.is_file():
            spec = importlib.util.spec_from_file_location("damit_desktop._catalog_handoff", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "nid_rule"):
                raise CatalogRuleMissing(f"{path} has no nid_rule; update the damit repository (DamIT Catalog).")
            return module, path
    raise CatalogRuleMissing(
        "DamIT Catalog's NID-ID rule (damit_catalog/handoff.py) was not found; run DamIT Crest from a checkout of "
        "the damit repository (INSTALL.txt). Looked in: " + ", ".join(str(p) for p in candidates())
    )


catalog_handoff, SOURCE = _load()

#: The rule itself, from DamIT Catalog (same objects, not copies).
nid_rule = catalog_handoff.nid_rule
is_nid_id = catalog_handoff.is_nid_id
NID_ID_RE = catalog_handoff.NID_ID_RE
OTHER_INVENTORY_RE = catalog_handoff.OTHER_INVENTORY_RE
