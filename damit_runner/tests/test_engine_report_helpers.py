"""engine_sources() helpers: _suite_source_label and _why_not_a_file (repo audit 2026-11-23, finding 1).

The port of DamSafety_Runner/algorithms.py dropped both, so engine_sources() raised NameError instead of
writing its "problems" line when a set engine path was not a file. engine.py imports QGIS at the top, so
the two functions are lifted out of its source and run on their own; a static check also confirms that
every name engine_sources() calls is defined in the module."""
import ast
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
ENGINE = os.path.join(ROOT, "damit_runner", "algorithms", "engine.py")


def _tree():
    with open(ENGINE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _load(*names):
    """The named top-level functions of engine.py, compiled into a namespace that resolves
    `from ..compat import x` against damit_runner.compat."""
    tree = _tree()
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    mod = ast.Module(body=body, type_ignores=[])
    ns = {"os": os, "__name__": "damit_runner.algorithms.engine", "__package__": "damit_runner.algorithms"}
    exec(compile(mod, ENGINE, "exec"), ns)
    return ns


class WhyNotAFile(unittest.TestCase):
    def setUp(self):
        self.f = _load("_why_not_a_file")["_why_not_a_file"]
        self.tmp = tempfile.mkdtemp()

    def test_missing(self):
        self.assertEqual(self.f(os.path.join(self.tmp, "nope")), "does not exist")

    def test_folder(self):
        self.assertEqual(self.f(self.tmp), "is a folder, not a program")

    def test_dangling_link(self):
        link = os.path.join(self.tmp, "lf")
        os.symlink(os.path.join(self.tmp, "gone"), link)
        self.assertIn("which does not exist", self.f(link))


class SuiteSourceLabel(unittest.TestCase):
    def setUp(self):
        self.f = _load("_suite_source_label")["_suite_source_label"]

    def test_env_variable_named(self):
        with mock.patch.dict(os.environ, {"NDBREACH_LISFLOOD": "/x/lisflood"}, clear=False):
            os.environ.pop("DAMIT_RUN_LISFLOOD_EXE", None)
            self.assertEqual(self.f("lisflood_exe"), "environment variable NDBREACH_LISFLOOD")

    def test_first_env_variable_wins(self):
        with mock.patch.dict(os.environ, {"DAMIT_RUN_LISFLOOD_EXE": "/a", "NDBREACH_LISFLOOD": "/b"}):
            self.assertEqual(self.f("lisflood_exe"), "environment variable DAMIT_RUN_LISFLOOD_EXE")

    def test_unset_falls_back_to_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.f("lisflood_exe"), "suite setting lisflood_exe")


class EngineNamesDefined(unittest.TestCase):
    def test_engine_sources_calls_only_defined_names(self):
        tree = _tree()
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == "engine_sources":
                called = {c.func.id for c in ast.walk(n)
                          if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id.startswith("_")}
                self.assertTrue(called, "engine_sources not found")
                self.assertEqual(called - defined, set())
                return
        self.fail("engine_sources not found")


if __name__ == "__main__":
    unittest.main()
