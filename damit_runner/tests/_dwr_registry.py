"""Run DamSafety Runner test modules, ported with DamIT's names, under unittest.

DamSafety's tests register plain functions with `@test` (tests/registry.py) and raise `Skip` when
an optional dependency is missing. A ported module imports `test`, `Skip` and `need_osgeo` from
here instead and ends with `DamSafetyTests = make_case(__name__)`, which turns each registered
function of that module into a unittest method (Skip -> skipTest). Nothing is weakened: the test
bodies are DamSafety's, with only the import paths and DamIT's own names changed."""
import functools
import unittest

_TESTS = []


class Skip(Exception):
    """Raised inside a test that cannot run here (a missing optional dependency)."""


def need_osgeo():
    try:
        from osgeo import gdal  # noqa: F401
    except ImportError:
        raise Skip("no GDAL (osgeo) in this Python")


def test(fn):
    _TESTS.append(fn)
    return fn


register = test
test.__test__ = False


def make_case(module_name):
    def _wrap(fn):
        @functools.wraps(fn)
        def method(self):
            try:
                fn()
            except Skip as exc:
                self.skipTest(str(exc))
        return method

    attrs = {"test_" + fn.__name__: _wrap(fn) for fn in _TESTS if fn.__module__ == module_name}
    return type("DamSafetyTests", (unittest.TestCase,), attrs)
