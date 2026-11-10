"""Network request helper — replaces damsuite.netproxy for DamIT Runner.

The DWR version routes through QGIS's proxy settings.  DamIT Runner runs
outside QGIS, so this shim simply delegates to ``urllib.request`` with
the standard environment proxy variables (HTTP_PROXY / HTTPS_PROXY /
NO_PROXY).  The calling convention is the same: ``urlopen(req, timeout)``.
"""
import urllib.request


def urlopen(req, timeout=60, settings=None):
    """urllib.request.urlopen through the environment's proxy (same as the
    default ``ProxyHandler`` behaviour; the ``settings`` arg is accepted for
    compatibility with the QGIS version but ignored)."""
    return urllib.request.urlopen(req, timeout=timeout)
