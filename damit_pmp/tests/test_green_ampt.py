"""Green-Ampt loss (damit_pmp/green_ampt.py, ported from DamSafety PMP 0.7.0-0.7.3)
against an independent fine-step integration of the Green-Ampt rate law
f = min(i, Ks (1 + psi*dtheta / F)), plus mass balance, the limits (no ponding below Ks,
Ks = 0, all impervious, initial loss), the PRODUCTION / PROVISIONAL stamp of the texture
table and the table itself against two USACE reprints. No QGIS, no data files.

    python3 -m unittest -v damit_pmp.tests.test_green_ampt
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError:                                          # pragma: no cover
    np = None

from damit_pmp import green_ampt as GA  # noqa: E402


def reference(precip_incr, dt, ks, psi, dth, sub=4000):
    """Cumulative infiltration per step by explicit integration with `sub` substeps per step: a
    separate route from the ponding-time + implicit-equation scheme under test."""
    pd = psi * dth
    F, out = 0.0, []
    for p in precip_incr:
        i = p / dt
        h = dt / sub
        F0 = F
        for _ in range(sub):
            cap = np.inf if F <= 0 else ks * (1.0 + pd / F)
            F += min(i, cap) * h
        out.append(F - F0)
    return np.array(out)


@unittest.skipUnless(np is not None, "numpy is required")
class GreenAmpt(unittest.TestCase):
    def setUp(self):
        self.dt = 0.25
        # in per step; a storm that ponds part way through
        self.p = np.array([0.05, 0.2, 0.5, 0.9, 0.6, 0.3, 0.1, 0.05, 0.0, 0.4]) * self.dt * 4
        self.ks, self.psi, self.dth = 0.15, 6.0, 0.30

    def test_matches_fine_step_integration_and_mass_balance(self):
        ex, info = GA.green_ampt_excess(self.p, self.dt, self.ks, self.psi, self.dth)
        ref_inf = reference(self.p, self.dt, self.ks, self.psi, self.dth)
        self.assertTrue(np.allclose(self.p - ex, ref_inf, atol=2e-4), (self.p - ex, ref_inf))
        self.assertTrue(info["ga_ponded"])
        self.assertLess(abs(self.p.sum() - ex.sum() - info["ga_infiltrated_in"]), 1e-9)

    def test_analytic_ponding_time(self):
        # Chow et al. eq. 4.4.3: tp = Ks psi dth / (i (i - Ks)) for steady rain i > Ks
        i = 1.0
        tp = self.ks * self.psi * self.dth / (i * (i - self.ks))
        fine = 1.0 / 600
        n = int(round(1.0 / fine))
        ex1, _ = GA.green_ampt_excess(np.full(n, i * fine), fine, self.ks, self.psi, self.dth)
        first = np.argmax(ex1 > 1e-9) * fine
        self.assertLessEqual(abs(first - tp), fine + 1e-9, (first, tp))

    def test_rain_no_faster_than_ks_never_ponds(self):
        ex2, info2 = GA.green_ampt_excess(np.full(40, 0.1 * 0.25), 0.25, 0.1, self.psi, self.dth)
        self.assertTrue(np.allclose(ex2, 0.0) and not info2["ga_ponded"])

    def test_ks_zero_and_all_impervious(self):
        ex3, _ = GA.green_ampt_excess(np.full(8, 0.2), 0.5, 0.0, self.psi, self.dth, initial_in=0.5)
        self.assertLess(abs(ex3.sum() - (1.6 - 0.5)), 1e-12)
        self.assertLess(abs(ex3[0]), 1e-12)
        self.assertLess(abs(ex3[2] - 0.1), 1e-12)
        ex4, _ = GA.green_ampt_excess(self.p, self.dt, self.ks, self.psi, self.dth, impervious_pct=100.0)
        self.assertTrue(np.allclose(ex4, self.p))

    def test_half_impervious_is_the_mean(self):
        ex, _ = GA.green_ampt_excess(self.p, self.dt, self.ks, self.psi, self.dth)
        ex5, _ = GA.green_ampt_excess(self.p, self.dt, self.ks, self.psi, self.dth, impervious_pct=50.0)
        self.assertTrue(np.allclose(ex5, 0.5 * self.p + 0.5 * ex))

    def test_no_suction_is_constant_loss_at_ks(self):
        ex6, _ = GA.green_ampt_excess(self.p, self.dt, self.ks, 0.0, self.dth)
        self.assertTrue(np.allclose(ex6, np.maximum(self.p - self.ks * self.dt, 0.0)))

    def test_texture_preset_and_production_stamp(self):
        psi_l, ks_l, dth_l = GA.ga_texture("Loam", 0.25)
        self.assertLess(abs(psi_l - 8.89 / 2.54), 1e-12)
        self.assertLess(abs(ks_l - 0.34 / 2.54), 1e-12)
        self.assertLess(abs(dth_l - 0.434 * 0.75), 1e-12)
        ks, psi, dth, name, status = GA.resolve_params(texture="silt loam", initial_saturation=0.3)
        self.assertEqual(name, "silt loam")
        self.assertEqual(status, "PRODUCTION" if GA.GA_TEXTURE_VERIFIED else "PROVISIONAL")
        self.assertIs(GA.GA_TEXTURE_VERIFIED, True)
        self.assertEqual(GA.texture_status(), "PRODUCTION")
        custom = GA.resolve_params(ks_in_hr=self.ks, suction_in=self.psi, moisture_deficit=self.dth)
        self.assertEqual(custom[3], "custom")
        self.assertIsNone(custom[4])

    def test_table_against_usace_reprints(self):
        # HEC-RAS 1D Technical Reference, "Green-Ampt": total porosity, Ks (cm/hr), to the printed digits
        RAS = {"sand": (0.437, 11.78), "loamy sand": (0.437, 2.99), "sandy loam": (0.453, 1.09),
               "loam": (0.463, 0.34), "silt loam": (0.501, 0.65), "sandy clay loam": (0.398, 0.15),
               "clay loam": (0.464, 0.10), "silty clay loam": (0.471, 0.10), "sandy clay": (0.430, 0.06),
               "silty clay": (0.479, 0.05), "clay": (0.475, 0.03)}
        # HEC-HMS guide, "Applying the Green and Ampt Loss Method": effective porosity, suction (in),
        # Ks (in/hr), rounded
        HMS = {"sand": (0.42, 1.9, 4.6), "loamy sand": (0.40, 2.4, 1.2), "sandy loam": (0.41, 4.3, 0.4),
               "loam": (0.43, 3.5, 0.1), "silt loam": (0.49, 6.6, 0.3), "sandy clay loam": (0.33, 8.6, 0.06),
               "clay loam": (0.31, 8.2, 0.04), "silty clay loam": (0.43, 10.7, 0.04),
               "sandy clay": (0.32, 9.4, 0.02), "silty clay": (0.42, 11.5, 0.02), "clay": (0.39, 12.5, 0.01)}
        self.assertEqual(set(GA.GA_TEXTURES), set(RAS))
        self.assertEqual(set(GA.GA_TEXTURES), set(HMS))
        for name, (psi_t, ks_t, por_t, te_t) in GA.GA_TEXTURES.items():
            por_r, ks_r = RAS[name]
            te_h, psi_h, ks_h = HMS[name]
            self.assertEqual(por_t, por_r, name)
            self.assertLess(abs(ks_t * 2.54 - ks_r), 1e-9, name)
            self.assertLessEqual(abs(te_t - te_h), 0.005 + 1e-12, name)
            self.assertLessEqual(abs(psi_t - psi_h), 0.05 + 1e-12, name)
            ks_digits = 1 if ks_h >= 0.1 else 2
            self.assertEqual(round(ks_t, ks_digits), ks_h, name)

    def test_unknown_texture_is_refused(self):
        with self.assertRaises(GA.GreenAmptError):
            GA.ga_texture("peat")

    def test_apply_to_rows_matches_excess_and_mm_round_trip(self):
        from damit_pmp import storm as S
        rows, c = [], 0.0
        t = 0.0
        for inc in self.p:
            t += self.dt * 60.0
            c += inc
            rows.append((t, inc, c))
        table, info = GA.apply_to_rows(rows, self.ks, self.psi, self.dth, unit="in")
        ex, info2 = GA.green_ampt_excess(self.p, self.dt, self.ks, self.psi, self.dth)
        self.assertTrue(np.allclose([r[3] for r in table], ex, atol=5e-4))
        self.assertEqual(info["ga_ponded"], info2["ga_ponded"])
        # mm rows: convert, apply, convert back; excess matches within rounding
        rows_mm = [(t_end, inc * S.MM_PER_IN, cum * S.MM_PER_IN) for t_end, inc, cum in rows]
        table_mm, _ = GA.apply_to_rows(rows_mm, self.ks, self.psi, self.dth, unit="mm")
        ex_mm = [r[3] / S.MM_PER_IN for r in table_mm]
        self.assertTrue(np.allclose(ex_mm, ex, atol=1e-3))

    def test_shared_storm_module_is_untouched(self):
        """Green-Ampt must not be added to the five byte-identical Atlas 14 files."""
        path = os.path.join(ROOT, "damit_pmp", "storm.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("green_ampt", text.lower())
        self.assertNotIn("Green-Ampt", text)


if __name__ == "__main__":
    unittest.main()

