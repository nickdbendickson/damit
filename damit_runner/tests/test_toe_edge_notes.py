"""Runner 0.3.3 (DWR-2645 Pheasant Lake): the toe band the inflow really came from is recorded (effective / original band and why it was
widened), and a run that ends with a wet edge says so (which edge, how deep, how much outflow, and why the domain did not grow).
Synthetic DEMs and records only; no engine runs."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np  # noqa: E402

from damit_runner.flood import geom as G  # noqa: E402
from damit_runner.flood import model as M  # noqa: E402

H, TOP = 9.0, 100.0


def valley(face_m):
    """A 2 m DEM, the dam line along y = 0 (x -60..60), downstream due south. The ground within face_m of the line is the dam's
    face (0.2 H below the crest); beyond it the ground is 0.9 H below the crest."""
    n, dx = 200, 2.0
    x0, y0 = -200.0, 200.0
    yc = y0 - (np.arange(n) + 0.5) * dx
    d = np.maximum(-yc, 0.0)[:, None] * np.ones((1, n))              # distance south of the line
    z = np.where(d < face_m, TOP - 0.2 * H, TOP - 0.9 * H)
    z = np.where(yc[:, None] > 0, TOP + 5.0, z)                       # the pool side is high ground
    return G.Grid(z, x0, y0, dx), [(-60.0, 0.0), (60.0, 0.0)], (0.0, -1.0)


class TestToeBandRecord(unittest.TestCase):
    def place(self, face_m):
        g, line, ds = valley(face_m)
        return G.place_inflow(g, (0.0, 0.0), line, ds, H, TOP, 2.0)

    def test_a_widened_band_is_recorded_with_its_reason(self):
        xy, note, band = self.place(32.0)                           # the face runs to 32 m: 27 m band widened to 37 m
        self.assertTrue(band["widened"])
        self.assertAlmostEqual(band["original_outer_m"], 27.0, 1)
        self.assertAlmostEqual(band["effective_outer_m"], 37.0, 1)
        self.assertEqual(band["effective_inner_m"], 5.0)
        self.assertIn("dam's face", band["widening_reason"])
        self.assertIn("band widened from 27 m", note)
        self.assertGreater(-xy[1], 27.0)
        self.assertLessEqual(-xy[1], band["effective_outer_m"] + 1.0)

    def test_a_band_that_was_not_widened_says_so(self):
        xy, note, band = self.place(0.0)
        self.assertFalse(band["widened"])
        self.assertIsNone(band["widening_reason"])
        self.assertEqual(band["effective_outer_m"], band["original_outer_m"])
        self.assertNotIn("widened", note)

    def test_the_fallback_has_no_effective_band(self):
        g, line, ds = valley(0.0)
        xy, note, band = G.place_inflow(g, (0.0, 0.0), None, ds, H, TOP, 2.0)          # no dam line: the fallback search
        self.assertNotIn("effective_outer_m", band)
        self.assertIn("fallback", note)

    def test_toe_band_inflow_without_info_is_as_before(self):
        g, line, ds = valley(32.0)
        a = G.toe_band_inflow(g, line, ds, H, TOP, band_m=(5.0, 27.0), max_from_dam_m=87.0, dam_xy=(0.0, 0.0))
        b = G.toe_band_inflow(g, line, ds, H, TOP, band_m=(5.0, 27.0), max_from_dam_m=87.0, dam_xy=(0.0, 0.0), info={})
        self.assertEqual(a, b)


class TestFinalEdgeNote(unittest.TestCase):
    P = {"arrival_ft": 0.1, "edge_tol_ft": 1.0, "outflow_extend_pct": 5.0}
    CAP = 96 * 3600.0

    def rec(self, s=0.0, pct=0.0, **edges):
        d = {"N": 0.0, "S": s, "E": 0.0, "W": 0.0}
        d.update(edges)
        return {"edge_depths_ft": d, "boundary_outflow_pct": pct}

    def test_the_dwr_2645_case_names_the_edge_the_depth_the_outflow_and_why_it_did_not_grow(self):
        t = M.final_edge_note(self.rec(0.94, 3.37), self.P, None, self.CAP, self.CAP)
        self.assertIn("3.4% of the breach volume left the model through its edges", t)
        self.assertIn("S 0.94 ft", t)
        self.assertIn("not grown further", t)
        self.assertIn("EDGE_TOL_FT", t)
        self.assertIn("OUTFLOW_EXTEND_PCT", t)
        self.assertIn("96 h duration cap", t)

    def test_a_stop_at_a_limit_is_named(self):
        for stop in ("duration cap", "maximum extent", "domain-run limit", "wall-clock budget"):
            t = M.final_edge_note(self.rec(1.5, 8.0), self.P, stop, self.CAP, self.CAP)
            self.assertIn("The run stopped at the " + stop, t)
            self.assertNotIn("not grown further", t)

    def test_dry_edges_and_little_outflow_say_nothing(self):
        self.assertIsNone(M.final_edge_note(self.rec(0.0, 0.0), self.P, None, 3600.0, self.CAP))
        self.assertIsNone(M.final_edge_note(self.rec(0.0, 0.5), self.P, None, 3600.0, self.CAP))
        self.assertIsNone(M.final_edge_note(self.rec(0.05, 0.5), self.P, None, 3600.0, self.CAP))       # under the arrival depth
        self.assertIsNone(M.final_edge_note(self.rec(0.5, 0.3), self.P, None, 3600.0, self.CAP))         # wet, but nothing left

    def test_a_wet_edge_over_the_tolerance_is_said_even_without_a_measured_outflow(self):
        t = M.final_edge_note(self.rec(1.4, None), self.P, "maximum extent", 3600.0, self.CAP)
        self.assertIn("an unmeasured share", t)
        self.assertIn("S 1.40 ft", t)

    def test_outflow_over_the_old_warning_threshold_still_warns_with_dry_edges(self):
        t = M.final_edge_note(self.rec(0.0, 6.0), self.P, None, 3600.0, self.CAP)
        self.assertIn("6.0% of the breach volume left the model through its edges", t)
        self.assertIn("no edge is wet at the end", t)

    def test_several_edges_are_listed(self):
        t = M.final_edge_note(self.rec(0.5, 2.0, W=0.2), self.P, None, 3600.0, self.CAP)
        self.assertIn("W 0.20 ft", t)
        self.assertIn("S 0.50 ft", t)


if __name__ == "__main__":
    unittest.main()
