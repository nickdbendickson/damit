"""DamIT Runner 0.7.0: LISFLOOD-FP sub-grid river channels (core/sgc.py), from DamSafety Runner 3.26.0.

DamSafety's tests/test_sgc.py with DamIT's names: the channel builder, the .par / start file, the depth above the
bank, the run key and the solver gate. Pure Python and numpy; no QGIS, no model."""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import lisflood as lf  # noqa: E402
from damit_runner.core import sgc  # noqa: E402
from damit_runner.core.breach import Hydrograph  # noqa: E402
from damit_runner.core.grid import Grid  # noqa: E402


def _valley(nr=40, nc=200, dx=20.0):
    X, Y = np.meshgrid((np.arange(nc) + 0.5) * dx, (np.arange(nr) + 0.5) * dx)
    z = 100.0 - 0.002 * X + 0.02 * np.abs(Y - nr * dx / 2)
    return Grid(z[::-1], 0.0, nr * dx, dx)


def _hy():
    return Hydrograph(np.array([0.0, 1800.0, 3600.0]), np.array([60.0, 60.0, 0.0]), "t")


class SGCTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="damit_sgc_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_identical_to_damsafety_names(self):
        self.assertEqual(sgc.BIEGER_2015_US, (2.70, 0.352, 0.30, 0.213))
        w, d = sgc.hydraulic_geometry(np.array([100.0]))
        self.assertAlmostEqual(float(w[0]), 2.70 * 100 ** 0.352)
        self.assertAlmostEqual(float(d[0]), 0.30 * 100 ** 0.213)

    def test_channels_follow_the_valley_and_take_the_dam_watershed(self):
        dem = _valley()
        rc = dem.rc(30.0, 405.0)
        ch = sgc.build(dem, inflow_rc=rc, upstream_km2=50.0, start="empty")
        self.assertTrue((ch.width[rc[0], rc[1]:] > 0).all())
        self.assertGreater(ch.info["area_at_inflow_km2"], 50.0)
        self.assertTrue(np.allclose(ch.bed[ch.mask], dem.data[ch.mask] - ch.depth[ch.mask]))
        self.assertLessEqual(ch.width.max(), dem.dx)
        small = sgc.build(dem, inflow_rc=rc, start="empty", min_area_km2=0.1)
        self.assertLess(small.width[rc[0], -1], ch.width[rc[0], -1])
        self.assertIn("was not given", sgc.describe(small.info))

    def test_par_start_file_and_acc_only(self):
        dem = _valley()
        ch = sgc.build(dem, inflow_rc=dem.rc(30.0, 405.0), upstream_km2=50.0, start="full")
        st = lf.LisfloodSettings("/no/lisflood", sim_time_s=60.0, sgc=ch)
        txt = open(lf.write_inputs(self.d, dem, (30.0, 405.0), _hy(), st), encoding="utf-8").read()
        for k in ("SGCwidth run.sgcwidth.asc", "SGCbank run.sgcbank.asc", "SGCbed run.sgcbed.asc", "SGCn 0.0350",
                  "startfile run.start"):
            self.assertIn(k, txt)
        start = Grid.read_asc(os.path.join(self.d, "run.start")).data
        self.assertTrue(np.allclose(start, ch.start_depth, atol=1e-3))
        with self.assertRaises(lf.ModelError):
            lf.LisfloodSettings("/no/lisflood", sgc=ch, solver=lf.SOLVER_FV2)

    def test_results_are_depth_above_the_bank(self):
        dem = _valley()
        ch = sgc.build(dem, inflow_rc=dem.rc(30.0, 405.0), upstream_km2=50.0, start="empty")
        os.makedirs(os.path.join(self.d, "results"))
        h = np.where(ch.mask, ch.depth + 0.5, 0.0)
        lf.local_grid(dem).like(h).write_asc(os.path.join(self.d, "results", "run.max"))
        env = lf.read_results(self.d, dem, lf.LisfloodSettings("/no/lisflood", sim_time_s=60.0, sgc=ch), _hy())
        self.assertTrue(np.allclose(env.depth.data[ch.mask], 0.5, atol=2e-3))
        self.assertEqual(env.stats["sgc"]["cells"], ch.info["cells"])

    def test_run_key_and_gate(self):
        from damit_runner.core import workflow, breach as br
        k = workflow.key_settings(workflow.RunSettings())
        self.assertFalse(any(x.startswith("sgc_") or x == "lisflood_sgc" for x in k))
        self.assertTrue(workflow.key_settings(workflow.RunSettings(lisflood_sgc=True))["lisflood_sgc"])
        with self.assertRaises(br.BreachInputError):
            workflow._check_solver(workflow.RunSettings(lisflood_sgc=True, lisflood_solver="fv2"), self.d)
        with self.assertRaises(br.BreachInputError):
            workflow._check_solver(workflow.RunSettings(lisflood_sgc=True, lisflood_exe=lf.BUILTIN_EXE), self.d)


if __name__ == "__main__":
    unittest.main()
