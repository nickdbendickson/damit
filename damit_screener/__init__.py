def classFactory(iface):  # noqa: N802 (QGIS entry point)
    from .plugin import DamitScreenerPlugin
    return DamitScreenerPlugin(iface)
