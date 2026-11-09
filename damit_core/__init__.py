"""DamIT Core: the shared library of the DamIT plugins (``damit_core.lib``).

Importing it has no side effects. As a QGIS plugin it adds one About entry under the DamIT menu.
"""


def classFactory(iface):  # noqa: N802 (QGIS entry point)
    from .plugin import DamitCorePlugin
    return DamitCorePlugin(iface)
