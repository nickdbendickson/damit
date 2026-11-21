"""The GPU flood engine (core/metalflood) as a separate engine choice in DamIT, through the live
flood launcher that damit_run:rundam and DamIT Screener use (flood/lisflood.py) and the screener's
engine list. The deck is the LISFLOOD-FP ACC deck the launcher writes; the CPU build of the same
kernels runs it here (no Metal GPU off a Mac)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import numpy as np                                      # noqa: F401
    HAVE = True
except ImportError:                                         # pragma: no cover
    HAVE = False


@unittest.skipUnless(HAVE, "numpy needed")
class GpuEngineChoice(unittest.TestCase):
    def test_find_exe_and_is_gpu_recognise_the_word(self):
        from damit_runner.flood import lisflood as LF
        self.assertTrue(LF.is_gpu("gpu"))
        self.assertTrue(LF.is_gpu("metal"))
        self.assertFalse(LF.is_gpu("builtin"))
        self.assertEqual(LF.find_exe("gpu")["exe"], LF.GPU)
        self.assertEqual(LF.resolve_exe("metal"), LF.GPU)

    def test_screen_choose_engine_offers_gpu(self):
        from damit_runner.flood import screen as SC
        self.assertIn("gpu", SC.ENGINES)
        kind, exe, how, warn = SC.choose_engine("gpu")
        self.assertEqual(kind, "gpu")
        self.assertEqual(exe, "gpu")
        self.assertIsNone(warn)

    def test_screener_engine2d_lists_gpu(self):
        from damit_screener.core import steps as ST
        self.assertIn("gpu", ST.ENGINES)

    def test_live_launcher_runs_the_acc_deck_on_the_gpu_engine(self):
        from damit_runner.flood import lisflood as LF
        from damit_runner.core import metalflood as MF
        from damit_runner.core.metalflood import cases
        if not (MF.metal_available()[0] or MF.find_compiler()):   # metal_available() is (ok, why)
            self.skipTest("no Metal GPU and no C++ compiler for the CPU build")
        os.environ["DAMIT_MF_BACKEND"] = "cpu"              # the CPU build of the same kernels
        try:
            with tempfile.TemporaryDirectory() as d:
                par = cases.valley_deck(d, ny=40, nx=60, dx=20.0, sim_s=1800.0)
                log = []
                info = LF.run(d, par, "gpu", max_wall_s=600.0, log=log.append)
                self.assertIn("GPU", info["engine"].upper())
                with open(os.path.join(d, "lisflood.log"), encoding="utf-8") as fh:
                    logtxt = fh.read()
                self.assertIn("GPU flood engine", logtxt)
                # the ACC run wrote its maxima: the valley got wet
                mx = os.path.join(d, "results", "run.max")
                self.assertTrue(os.path.isfile(mx))
                a = cases.read_asc(mx)
                self.assertGreater(np.nansum(a > 0.001), 0)
        finally:
            os.environ.pop("DAMIT_MF_BACKEND", None)


class MetalfloodProvenance(unittest.TestCase):
    """core/metalflood is the DWR_Plugins #399 copy (commit 51d72917). The parity pin has no metalflood
    folder, so the gate skips it; METALFLOOD_SOURCE.json records the commit and each file's sha256."""

    def test_files_match_the_recorded_source(self):
        import hashlib
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "METALFLOOD_SOURCE.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        folder = os.path.join(root, "core", "metalflood")
        have = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
        self.assertEqual(have, sorted(rec["sha256"]), "core/metalflood files differ from METALFLOOD_SOURCE.json")
        for name, want in rec["sha256"].items():
            with open(os.path.join(folder, name), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), want, name)
        self.assertEqual(len(rec["source_commit"]), 40)


if __name__ == "__main__":
    unittest.main()
