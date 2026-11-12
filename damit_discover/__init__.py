"""DamIT Discovery: optional non-NID pond / reservoir / dam candidate finder."""


def classFactory(iface):  # noqa: N802
    from .plugin import DamitDiscoverPlugin
    return DamitDiscoverPlugin(iface)
