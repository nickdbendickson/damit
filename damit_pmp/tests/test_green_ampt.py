"""Green-Ampt loss against a fine-step integration, and the texture table against the two
USACE reprints of Rawls et al. (1983). No Atlas 14 fetch."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from damit_pmp import green_ampt as H


def reference(precip_incr, dt, ks, psi, dth, sub=4000):
    """Infiltration per step by explicit integration. A different route from the function under test."""
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


class GreenAmpt(unittest.TestCase):
    def test_matches_a_fine_step_and_conserves_mass(self):
        dt = 0.25
        p = np.array([0.05, 0.2, 0.5, 0.9, 0.6, 0.3, 0.1, 0.05, 0.0, 0.4]) * dt * 4
        ks, psi, dth = 0.15, 6.0, 0.30
        ex, info = H.green_ampt_excess(p, dt, ks, psi, dth)
        ref_inf = reference(p, dt, ks, psi, dth)
        self.assertTrue(np.allclose(p - ex, ref_inf, atol=2e-4))
        self.assertTrue(info["ga_ponded"])
        self.assertAlmostEqual(p.sum() - ex.sum(), info["ga_infiltrated_in"], places=9)

    def test_ponding_time_and_limits(self):
        ks, psi, dth = 0.15, 6.0, 0.30
        dt = 0.25
        p = np.array([0.05, 0.2, 0.5, 0.9, 0.6, 0.3, 0.1, 0.05, 0.0, 0.4]) * dt * 4
        ex, _info = H.green_ampt_excess(p, dt, ks, psi, dth)
        i = 1.0
        tp = ks * psi * dth / (i * (i - ks))
        fine = 1.0 / 600
        n = int(round(1.0 / fine))
        ex1, _ = H.green_ampt_excess(np.full(n, i * fine), fine, ks, psi, dth)
        first = np.argmax(ex1 > 1e-9) * fine
        self.assertLessEqual(abs(first - tp), fine + 1e-9)
        ex2, info2 = H.green_ampt_excess(np.full(40, 0.1 * 0.25), 0.25, 0.1, psi, dth)
        self.assertTrue(np.allclose(ex2, 0.0) and not info2["ga_ponded"])
        ex3, _ = H.green_ampt_excess(np.full(8, 0.2), 0.5, 0.0, psi, dth, initial_in=0.5)
        self.assertAlmostEqual(ex3.sum(), 1.6 - 0.5, places=12)
        ex4, _ = H.green_ampt_excess(p, dt, ks, psi, dth, impervious_pct=100.0)
        self.assertTrue(np.allclose(ex4, p))
        ex5, _ = H.green_ampt_excess(p, dt, ks, psi, dth, impervious_pct=50.0)
        self.assertTrue(np.allclose(ex5, 0.5 * p + 0.5 * ex))
        ex6, _ = H.green_ampt_excess(p, dt, ks, 0.0, dth)
        self.assertTrue(np.allclose(ex6, np.maximum(p - ks * dt, 0.0)))

    def test_texture_table_matches_the_usace_reprints(self):
        psi_l, ks_l, dth_l = H.ga_texture("Loam", 0.25)
        self.assertAlmostEqual(psi_l, 8.89 / 2.54, places=12)
        self.assertAlmostEqual(ks_l, 0.34 / 2.54, places=12)
        self.assertAlmostEqual(dth_l, 0.434 * 0.75, places=12)
        self.assertTrue(H.GA_TEXTURE_VERIFIED)
        ex, info = H.apply_storm([0.2, 0.5, 0.4], 0.25, texture="silt loam", initial_saturation=0.3)
        self.assertEqual(info["loss"], "green_ampt")
        self.assertEqual(info["loss_texture"], "silt loam")
        self.assertEqual(info["loss_param_status"], "PRODUCTION")
        self.assertGreater(info["excess_in"], 0)
        self.assertLess(info["excess_in"], 1.1)
        ras = {"sand": (0.437, 11.78), "loamy sand": (0.437, 2.99), "sandy loam": (0.453, 1.09),
               "loam": (0.463, 0.34), "silt loam": (0.501, 0.65), "sandy clay loam": (0.398, 0.15),
               "clay loam": (0.464, 0.10), "silty clay loam": (0.471, 0.10), "sandy clay": (0.430, 0.06),
               "silty clay": (0.479, 0.05), "clay": (0.475, 0.03)}
        hms = {"sand": (0.42, 1.9, 4.6), "loamy sand": (0.40, 2.4, 1.2), "sandy loam": (0.41, 4.3, 0.4),
               "loam": (0.43, 3.5, 0.1), "silt loam": (0.49, 6.6, 0.3), "sandy clay loam": (0.33, 8.6, 0.06),
               "clay loam": (0.31, 8.2, 0.04), "silty clay loam": (0.43, 10.7, 0.04),
               "sandy clay": (0.32, 9.4, 0.02), "silty clay": (0.42, 11.5, 0.02), "clay": (0.39, 12.5, 0.01)}
        self.assertEqual(set(H.GA_TEXTURES), set(ras))
        self.assertEqual(set(H.GA_TEXTURES), set(hms))
        for name, (psi_t, ks_t, por_t, te_t) in H.GA_TEXTURES.items():
            por_r, ks_r = ras[name]
            te_h, psi_h, ks_h = hms[name]
            self.assertEqual(por_t, por_r)
            self.assertAlmostEqual(ks_t * 2.54, ks_r, places=9)
            self.assertLessEqual(abs(te_t - te_h), 0.005 + 1e-12)
            self.assertLessEqual(abs(psi_t - psi_h), 0.05 + 1e-12)
            ks_digits = 1 if ks_h >= 0.1 else 2
            self.assertEqual(round(ks_t, ks_digits), ks_h)
        _ex, custom = H.apply_storm(p_of(), 0.25, ks_in_hr=0.15, suction_in=6.0, moisture_deficit=0.30)
        self.assertEqual(custom["loss_texture"], "custom")
        self.assertNotIn("loss_param_status", custom)
        with self.assertRaises(H.GreenAmptError):
            H.ga_texture("peat")


def p_of():
    dt = 0.25
    return np.array([0.05, 0.2, 0.5, 0.9, 0.6, 0.3, 0.1, 0.05, 0.0, 0.4]) * dt * 4


if __name__ == "__main__":
    unittest.main()
