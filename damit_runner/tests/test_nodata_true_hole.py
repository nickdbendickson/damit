"""TRUE_HOLE NoData-receptor criterion (follow-up to #67): fill only enclosed holes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.compat import nodata_sample as NDS


class TrueHole(unittest.TestCase):
    def test_enclosed_one_cell_and_2x2_are_holes_edge_is_not(self):
        # 9x9 dry-as-NoData field; wet footprint in the middle
        nan = float("nan")
        a = [[nan] * 9 for _ in range(9)]
        for r in range(1, 8):
            for c in range(1, 8):
                a[r][c] = 1.0
        a[2][2] = nan                         # 1-cell hole
        a[4][4] = a[4][5] = a[5][4] = a[5][5] = nan   # 2x2 hole
        a[0][4] = nan                         # flood edge, open to the border
        is_nd = [[NDS.is_nodata(v) for v in row] for row in a]
        is_wt = [[NDS.is_wet(v) for v in row] for row in a]
        m = NDS.true_hole_mask(is_nd, is_wt)
        self.assertTrue(m[2][2])
        self.assertTrue(m[4][4] and m[4][5] and m[5][4] and m[5][5])
        self.assertFalse(m[0][4])
        self.assertFalse(m[1][1])             # wet
        arr = NDS.true_hole_mask_array(a)
        self.assertTrue(bool(arr[2][2]) and bool(arr[4][4]) and not bool(arr[0][4]))

    def test_finite_zero_corridor_opens_a_hole(self):
        a = [[0.0] * 5 for _ in range(5)]
        for r in range(1, 4):
            for c in range(1, 4):
                a[r][c] = 2.0
        a[2][2] = float("nan")
        is_nd = [[NDS.is_nodata(v) for v in row] for row in a]
        is_wt = [[NDS.is_wet(v) for v in row] for row in a]
        self.assertTrue(NDS.true_hole_mask(is_nd, is_wt)[2][2])
        a[2][0] = 0.0
        a[2][1] = 0.0
        is_nd = [[NDS.is_nodata(v) for v in row] for row in a]
        is_wt = [[NDS.is_wet(v) for v in row] for row in a]
        self.assertFalse(NDS.true_hole_mask(is_nd, is_wt)[2][2])

    def test_resolve_nodata_uses_physical_depth_never_raw_neighbour(self):
        pol = NDS.nodata_policy(50.0)
        self.assertTrue(pol["neighbourhood_allowed"])
        peak = (3.0, 2.0, 1)
        # no ground: dry, never the 3 ft neighbour
        nog = NDS.resolve_nodata(True, peak, pol, is_true_hole=True, has_ground=False)
        self.assertEqual(nog["sampling"], NDS.SAMPLING_CENTRE_NODATA_NO_GROUND)
        self.assertEqual(nog["flag"], NDS.FLAG_NO_GROUND)
        self.assertEqual(nog["depth"], 0.0)
        # with ground: physical 0.13, not 3.0; applies to edge and hole
        for hole in (True, False):
            filled = NDS.resolve_nodata(True, peak, pol, is_true_hole=hole,
                                        has_ground=True, physical_depth=0.13,
                                        physical_velocity=1.1)
            self.assertEqual(filled["sampling"], NDS.SAMPLING_NEIGHBOURHOOD_WSE)
            self.assertEqual(filled["flag"], NDS.FLAG_WSE_GROUND)
            self.assertEqual(filled["depth"], 0.13)
        dry = NDS.resolve_nodata(True, peak, pol, has_ground=True, physical_depth=0.0)
        self.assertEqual(dry["sampling"], NDS.SAMPLING_NEIGHBOURHOOD_WSE)
        self.assertEqual(dry["flag"], NDS.FLAG_WSE_DRY)
        self.assertEqual(dry["depth"], 0.0)
        over = NDS.resolve_nodata(True, peak, pol, is_oversize=True, has_ground=True,
                                  physical_depth=0.13)
        self.assertEqual(over["sampling"], NDS.SAMPLING_CENTRE_NODATA_OVERSIZE)
        self.assertEqual(over["depth"], 0.0)
        # 20 m rule is unchanged for a hole or an edge, even with a physical depth
        fine = NDS.nodata_policy(20.0)
        for hole in (True, False):
            d = NDS.resolve_nodata(True, peak, fine, is_true_hole=hole,
                                   has_ground=True, physical_depth=0.13)
            self.assertEqual(d["sampling"], NDS.SAMPLING_CENTRE_NODATA_DRY)
            self.assertEqual(d["flag"], NDS.FLAG_DRY_REVIEW)
            self.assertEqual(d["depth"], 0.0)

    def test_oversize_and_diagonal_and_cache(self):
        cap = NDS.TRUE_HOLE_MAX_CELLS
        import numpy as np
        n = cap + 4
        a = np.full((n + 4, n + 4), np.nan)
        a[1:n + 3, 1:n + 3] = 1.0
        a[2, 2:2 + cap + 1] = np.nan
        a[4, 4] = np.nan
        ana = NDS.analyze_nodata_array(a)
        self.assertFalse(bool(ana["hole"][2, 2]))
        self.assertTrue(bool(ana["oversize"][2, 2]))
        self.assertTrue(bool(ana["hole"][4, 4]))
        # diagonal-only link to the border: still enclosed (4-connectivity)
        b = np.full((6, 6), np.nan)
        b[1:5, 1:5] = 1.0
        b[2, 2] = np.nan
        b[1, 0] = np.nan
        self.assertTrue(bool(NDS.true_hole_mask_array(b)[2, 2]))

    def test_note_for_flag_names_physical_depth(self):
        n = NDS.note_for_flag(NDS.FLAG_WSE_GROUND, cell_m=50.0)
        self.assertIn("water surface", n.lower())
        self.assertIn("ground", n.lower())
        self.assertNotIn("have a hole", n.lower())
        g = NDS.note_for_flag(NDS.FLAG_NO_GROUND, cell_m=50.0)
        self.assertIn("raw neighbour", g.lower())


if __name__ == "__main__":
    unittest.main()
