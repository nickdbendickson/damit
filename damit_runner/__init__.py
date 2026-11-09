def classFactory(iface):  # noqa: N802 (QGIS entry point)
    from .plugin import DamitRunnerPlugin
    return DamitRunnerPlugin(iface)
