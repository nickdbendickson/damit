"""DamIT Runner 0.11.0 (Boann extraction plan, phase 2): Boann is vendored once, byte-identical, at
damit_runner/boann/ and pinned by damit_runner/BOANN.lock to DWR_Plugins' DamSafety_Core/boann/ at
one commit. These tests hold the pin and the plumbing around it without a DWR checkout; the
upstream half (the lock equals DWR at that commit) is .github/workflows/engine_parity.yml's
boann-lock job (scripts/boann_sync.py --check --dwr).

- the vendored files are exactly the locked ones, and DWR's own FILES.json agrees with the lock;
- core/metalflood and core/metalterrain are only the alias shims, and resolve to the vendored modules;
- the Runner lends Boann its channel builder (DamIT's sgc, Bieger 2015 by default) and fill oracle;
- the engine "executables" point into the vendored copy, and a pre-0.11.0 core/metalflood path
  still resolves;
- damit_runner/damsuite holds only the redirect the vendored condition.py needs;
- LISFLOOD-FP stays the default engine and Bieger 2015 the default channel curve."""
import importlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import boann_sync  # noqa: E402


class BoannLock(unittest.TestCase):
    def test_vendored_copy_matches_the_lock(self):
        lock = boann_sync.load_lock()
        self.assertEqual(boann_sync.check_vendored(lock), [])
        self.assertEqual(len(lock["commit"]), 40)
        self.assertEqual(lock["source_repo"], "nickdbendickson/DWR_Plugins")
        self.assertEqual(lock["source_path"], "DamSafety_Core/boann")
        from damit_runner.boann.hydro.version import BOANN_VERSION
        self.assertEqual(BOANN_VERSION, lock["boann_version"])

    def test_lock_file_is_canonical(self):
        with open(boann_sync.LOCK, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, boann_sync.lock_text(json.loads(text)), "BOANN.lock was edited by hand")

    def test_old_folders_are_only_shims(self):
        for name, real in (("metalflood", "hydro"), ("metalterrain", "grid")):
            folder = os.path.join(ROOT, "damit_runner", "core", name)
            self.assertEqual(sorted(f for f in os.listdir(folder) if f != "__pycache__"), ["__init__.py"], name)
            with open(os.path.join(folder, "__init__.py"), encoding="utf-8") as fh:
                self.assertIn('"damit_runner.boann.{}"'.format(real), fh.read())

    def test_shims_are_the_vendored_modules(self):
        from damit_runner.core.metalflood import engine as a
        from damit_runner.boann.hydro import engine as b
        self.assertIs(a, b)
        from damit_runner.core.metalterrain import fill as c
        from damit_runner.boann.grid import fill as d
        self.assertIs(c, d)
        self.assertIs(importlib.import_module("damit_runner.core.metalflood"),
                      importlib.import_module("damit_runner.boann.hydro"))

    def test_runner_lends_boann_its_host_functions(self):
        import damit_runner.core  # noqa: F401  (registers the hooks)
        from damit_runner.boann.hydro import host
        self.assertIsNotNone(host.get("channel_builder"))
        self.assertIsNotNone(host.get("priority_flood"))

    def test_engine_paths_point_into_the_vendored_copy(self):
        from damit_runner.core import lisflood as lf
        from damit_runner.core import solve_gate as sg
        hydro = os.path.join(ROOT, "damit_runner", "boann", "hydro")
        self.assertEqual(os.path.realpath(lf.BOANN_DIR), os.path.realpath(hydro))
        for e in (lf.GPU_EXE, lf.GPU_FV_EXE, lf.GPU_FV2_EXE, lf.GPU_DG2_EXE, lf.GPU_SGC_EXE,
                  lf.GPU_SUBFV_EXE, lf.GPU_SUBLI_EXE):
            self.assertTrue(os.path.isfile(e), e)
            self.assertTrue(sg.is_inprocess_engine(e), e)
        old = os.path.join(ROOT, "damit_runner", "core", "metalflood", "engine_fv2.py")
        self.assertEqual(lf.resolve_exe(old), lf.GPU_FV2_EXE)
        self.assertEqual(lf.resolve_exe("C:\\x\\damit_runner\\core\\metalflood\\engine.py"), lf.GPU_EXE)
        self.assertIsNone(lf._legacy_boann("/x/core/metalflood/not_an_engine.py"))

    def test_damsuite_is_only_the_gdalsafe_redirect(self):
        folder = os.path.join(ROOT, "damit_runner", "damsuite")
        self.assertEqual(sorted(f for f in os.listdir(folder) if f.endswith(".py")),
                         ["__init__.py", "gdalsafe.py"])
        from damit_runner.damsuite import gdalsafe as a
        from damit_runner.compat import gdalsafe as b
        self.assertIs(a, b)

    def test_damit_defaults_are_unchanged(self):
        from damit_runner.core import sgc
        self.assertEqual(sgc.DEFAULT_CURVE, sgc.BIEGER_2015_US)
        self.assertEqual(sgc.SGC_CURVES["nd_usgs_2026"], sgc.ND_USGS_2026)


if __name__ == "__main__":
    unittest.main()
