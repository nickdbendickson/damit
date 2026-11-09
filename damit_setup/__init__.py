"""DamIT Setup: start here (suite data folder, suite check, hand-off to DamIT Screener)."""


def classFactory(iface):  # noqa: N802
    from .plugin import DamitSetupPlugin
    return DamitSetupPlugin(iface)
