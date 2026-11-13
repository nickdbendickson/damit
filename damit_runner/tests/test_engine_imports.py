"""Smoke test: every core module and compat shim imports without error.

Runs outside QGIS (no qgis.core, no PyQt5). Modules that import QGIS at
the top level are expected to fail and are listed in QGIS_ONLY. Everything
else must import cleanly — a failure here means a broken import chain in
the ported engine.
"""
import importlib
import os
import sys
import unittest

# damit_runner is found by inserting the monorepo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Modules that import QGIS at the top level (not under try/except) — these
# are expected to fail outside QGIS and are skipped.
QGIS_ONLY = {
    "damit_runner.algorithms.rundam",       # QgsProcessingAlgorithm
    "damit_runner.algorithms.engine",       # QgsProcessingAlgorithm
    "damit_runner.algorithms.qgis_io",      # qgis.core
    "damit_runner.qgis_compat",             # qgis.core
    "damit_runner.provider",                # QgsProcessingProvider
    "damit_runner.plugin",                  # QGIS plugin entry point
}


def _all_modules():
    """Discover every .py module under damit_runner/."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), os.path.dirname(root))
            mod = rel.replace(os.sep, ".").removesuffix(".py")
            yield mod


class ImportChain(unittest.TestCase):
    """Every non-QGIS module in damit_runner must import without error."""
    pass


def _make_test(mod_name):
    def test(self):
        if mod_name in QGIS_ONLY:
            self.skipTest("QGIS-only module")
        try:
            importlib.import_module(mod_name)
        except ImportError as e:
            # GDAL (osgeo) and numpy may not be installed in CI — that's OK,
            # the import *chain* is what we're testing (damsuite → compat).
            msg = str(e)
            if "osgeo" in msg or "numpy" in msg or "gdal" in msg:
                self.skipTest("optional dependency not installed: " + msg)
            raise
    test.__name__ = "test_import_" + mod_name.replace(".", "_")
    return test


for _mod in _all_modules():
    setattr(ImportChain, _make_test(_mod).__name__, _make_test(_mod))


class CompatShims(unittest.TestCase):
    """Basic contract checks on compat modules that don't need GDAL."""

    def test_keepawake_context_manager(self):
        from damit_runner.compat.keepawake import keep_awake
        with keep_awake("test"):
            pass  # should not raise

    def test_netproxy_urlopen_signature(self):
        from damit_runner.compat import netproxy
        self.assertTrue(callable(netproxy.urlopen))

    def test_services_builtin_has_3dep(self):
        from damit_runner.compat import services
        ids = [s["id"] for s in services.BUILTIN]
        self.assertIn("usgs_3dep_image", ids)

    def test_services_export_image_url(self):
        from damit_runner.compat import services
        svc = {"url": "https://example.com/arcgis/rest/services/DEM/ImageServer", "kind": "arcgis_image"}
        url = services.export_image_url(svc, (100, 200, 300, 400), (256, 256))
        self.assertIn("exportImage", url)
        self.assertIn("100", url)

    def test_suitedata_constants(self):
        from damit_runner.compat import suitedata
        self.assertEqual(suitedata.TERRAIN, "terrain")
        self.assertEqual(suitedata.DEM, "dem")

    def test_terrain_cache_snap(self):
        from damit_runner.compat import terrain_cache as TC
        box = TC.snap((100.5, 200.5, 300.5, 400.5), 1.0)
        self.assertEqual(box[0], 100.0)
        self.assertEqual(box[1], 200.0)

    def test_terrain_cache_tiles_for(self):
        from damit_runner.compat import terrain_cache as TC
        tiles = TC.tiles_for((0, 0, 2001, 2001), 1.0)
        self.assertGreater(len(tiles), 0)

    def test_gdalsafe_has_checked(self):
        from damit_runner.compat import gdalsafe
        self.assertTrue(callable(gdalsafe.checked))
        # checked(None, ...) should raise
        with self.assertRaises(RuntimeError):
            gdalsafe.checked(None, "test")


class CoreModules(unittest.TestCase):
    """Basic contract checks on core engine modules."""

    def test_units_constants(self):
        from damit_runner.core import units
        self.assertAlmostEqual(units.FT, 0.3048)
        self.assertAlmostEqual(units.ft_to_m(1), 0.3048)
        self.assertAlmostEqual(units.m_to_ft(0.3048), 1.0)
        self.assertIsNone(units.ft_to_m(None))

    def test_breach_module_loads(self):
        from damit_runner.core import breach
        self.assertTrue(hasattr(breach, "Hydrograph"))

    def test_grid_module_loads(self):
        from damit_runner.core import grid
        self.assertTrue(hasattr(grid, "Grid"))

    def test_builtin_lisflood_name(self):
        from damit_runner.core import builtin_lisflood
        self.assertIn("DamIT", builtin_lisflood.NAME)
        self.assertNotIn("ND Dam", builtin_lisflood.NAME)

    def test_rundam_version(self):
        from damit_runner.core import rundam as RD
        self.assertEqual(RD.VERSION, "0.5.0")
        self.assertEqual(RD.ENGINE_LISFLOOD, 1)
        # 0.3.0: LISFLOOD-FP and ANUGA run; HEC-RAS 2D is refused
        with self.assertRaises(RD.RunError):
            RD.refuse_engine(RD.ENGINE_HECRAS)
        RD.refuse_engine(RD.ENGINE_LISFLOOD)
        RD.refuse_engine(RD.ENGINE_ANUGA)
        # the names the damit_run:rundam algorithm reads
        for n in ("DEM_Z_LABELS", "method_labels", "refuse_engine", "run_model"):
            self.assertTrue(hasattr(RD, n), n)

    def test_workflow_version_exists(self):
        from damit_runner.core import workflow
        self.assertTrue(hasattr(workflow, "VERSION"))


if __name__ == "__main__":
    unittest.main()
