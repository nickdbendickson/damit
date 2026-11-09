"""DamIT PMP: NOAA Atlas 14 precipitation-frequency tools (no other precipitation source)."""


def classFactory(iface):  # noqa: N802
    from .plugin import DamitPmpPlugin
    return DamitPmpPlugin(iface)
