"""DamIT Catalog: Appendix A methods / scenarios / modifiers / presets as data files.

No Processing provider. Other DamIT plugins import ``damit_catalog.catalog``,
``damit_catalog.evaluate`` and ``damit_catalog.handoff`` (pure Python).
"""


def classFactory(iface):  # noqa: N802 (QGIS entry point)
    from .plugin import DamitCatalogPlugin
    return DamitCatalogPlugin(iface)
