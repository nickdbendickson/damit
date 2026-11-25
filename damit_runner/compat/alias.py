"""Make one package answer under a second name (DamIT Runner 0.11.0), so there is never a second
copy of a module in one Python.

Boann (the flood engine and the terrain conditioner) is vendored once, byte-identical, at
damit_runner/boann/ (pinned by damit_runner/BOANN.lock). The Runner's old paths
damit_runner.core.metalflood and damit_runner.core.metalterrain are two-line shims that call
`install(__name__, "damit_runner.boann.hydro" | ".grid")` here: `from .metalflood import x` then
returns the very module objects of damit_runner.boann.hydro, and
`python -m damit_runner.core.metalflood.bench` still runs.

A port of DamSafety Core's alias.py (DWR_Plugins f71ac94), with DamIT's names. Plain Python 3.9+,
no Qt, no damit_core (DamIT Runner installs with only DamIT Catalog).
"""
import importlib
import importlib.abc
import importlib.machinery
import sys

_ALIASES = {}                                      # alias package name -> real package name


class _AliasLoader(importlib.abc.Loader):
    """Hands importlib the real module object instead of making a new one."""

    def __init__(self, real_name):
        self.real_name = real_name

    def create_module(self, spec):
        return importlib.import_module(self.real_name)

    def exec_module(self, module):
        pass                                       # already executed under its real name

    def get_code(self, fullname):
        """The real module's code, so `python -m <alias>.<module>` runs it."""
        real = importlib.import_module(self.real_name)
        return real.__spec__.loader.get_code(self.real_name)

    def is_package(self, fullname):
        return hasattr(importlib.import_module(self.real_name), "__path__")


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for alias, real in _ALIASES.items():
            if fullname == alias or fullname.startswith(alias + "."):
                real_name = real + fullname[len(alias):]
                try:
                    mod = importlib.import_module(real_name)
                except ImportError:
                    return None                    # not a real module: the normal error follows
                return importlib.machinery.ModuleSpec(
                    fullname, _AliasLoader(real_name),
                    origin=getattr(getattr(mod, "__spec__", None), "origin", None),
                    is_package=hasattr(mod, "__path__"))
        return None


_FINDER = _AliasFinder()


def install(alias_name, real_name):
    """Make the package `alias_name` be `real_name`, submodules included. Returns the real package.
    Call it from the alias package's own __init__.py."""
    real = importlib.import_module(real_name)
    _ALIASES[alias_name] = real_name
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)
    sys.modules[alias_name] = real
    prefix = real_name + "."
    for name, mod in list(sys.modules.items()):
        if name.startswith(prefix) and mod is not None:
            sys.modules.setdefault(alias_name + name[len(real_name):], mod)
    return real


def aliases():
    """{alias package: real package} installed so far (diagnostics and tests)."""
    return dict(_ALIASES)
