"""DamIT Runner 0.7.13: DamSafety #432 (DWR_Plugins 005aa147) - the built-in engine adds a breach's point source in
LISFLOOD-FP's order by default (the donor-cell limiter runs before the source is added), and 'physicalinflow' in
the .par keeps the earlier mass-conserving order. A tiny synthetic grid stepped directly; no model run."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import builtin_lisflood as BL  # noqa: E402
from damit_runner.flood import builtin_lisflood as FBL  # noqa: E402


def _run(mod, lf_order, steps=20, dt=0.5):
    ny = nx = 21
    z = np.tile(np.linspace(1.0, 0.0, nx), (ny, 1))           # a gentle slope to the east
    n = np.full((ny, nx), 0.035)
    rr, cc = np.array([10]), np.array([3])
    src = [(rr, cc, np.array([0.0, 1e6]), np.array([50.0, 50.0]))]   # 50 m3/s into one cell
    m = mod.Model(z, n, np.zeros((ny, nx)), 10.0, {"E"}, src, 0.0, 0.0, inflow_lf_order=lf_order)
    win = (0, ny, 0, nx)
    t = 0.0
    for _ in range(steps):
        m.step(dt, win, m.source_rate(t, win))
        t += dt
    return m


class InflowOrder(unittest.TestCase):
    def test_default_is_lisflood_order(self):
        for mod in (BL, FBL):
            m = mod.Model(np.zeros((3, 3)), np.full((3, 3), 0.035), np.zeros((3, 3)), 10.0, set(), [], 0.0, 0.0)
            self.assertTrue(m.inflow_lf_order, mod.__name__)

    def test_lisflood_order_holds_more_water_at_the_breach_cell(self):
        for mod in (BL, FBL):
            lf, phys = _run(mod, True), _run(mod, False)
            # LISFLOOD-FP order: outflow capped at the water held at step start, the source piled on after
            self.assertGreater(lf.h[10, 3], phys.h[10, 3] + 0.1, mod.__name__)
            self.assertTrue(np.isfinite(lf.h).all() and np.isfinite(phys.h).all())

    def test_physicalinflow_keyword_selects_the_old_order(self):
        import inspect
        src = inspect.getsource(BL.run_par)
        self.assertIn('inflow_lf_order="physicalinflow" not in par', src)


if __name__ == "__main__":
    unittest.main()
