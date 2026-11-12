"""DamIT Finder's Processing provider id (the tools are in plugin.py)."""
PROVIDER_ID = "damit_find"


def provider():
    from .plugin import Provider
    return Provider()
