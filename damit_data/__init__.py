"""DamIT Data: offline structure / footprint / OSM layers for any US state."""


def classFactory(iface):  # noqa: N802
    from .plugin import DamitDataPlugin
    return DamitDataPlugin(iface)
