"""DamIT Hazard: multi-jurisdiction dam hazard classification from existing flood rasters."""


def classFactory(iface):
    from .plugin import Plugin
    return Plugin(iface)
