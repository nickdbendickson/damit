"""DamIT Hazard Lite: one Processing tool (damit_lite:classify)."""


def classFactory(iface):  # noqa: N802
    from .plugin import DamitHazardLitePlugin
    return DamitHazardLitePlugin(iface)
