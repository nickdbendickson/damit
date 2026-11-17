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

    def test_resolve_nodata_fills_only_true_holes_on_a_coarse_grid(self):
        pol = NDS.nodata_policy(50.0)
        self.assertTrue(pol["neighbourhood_allowed"])
        peak = (3.0, 2.0, 1)
        filled = NDS.resolve_nodata(True, peak, pol, is_true_hole=True)
        self.assertEqual(filled["sampling"], NDS.SAMPLING_NEIGHBOURHOOD)
        self.assertEqual(filled["flag"], NDS.FLAG_NEIGHBOURHOOD)
        self.assertEqual(filled["depth"], 3.0)
        edge = NDS.resolve_nodata(True, peak, pol, is_true_hole=False)
        self.assertEqual(edge["sampling"], NDS.SAMPLING_CENTRE_NODATA_EDGE)
        self.assertEqual(edge["flag"], NDS.FLAG_FLOOD_EDGE)
        self.assertEqual(edge["depth"], 0.0)
        # 20 m rule is unchanged for a hole or an edge
        fine = NDS.nodata_policy(20.0)
        for hole in (True, False):
            d = NDS.resolve_nodata(True, peak, fine, is_true_hole=hole)
            self.assertEqual(d["sampling"], NDS.SAMPLING_CENTRE_NODATA_DRY)
            self.assertEqual(d["flag"], NDS.FLAG_DRY_REVIEW)
            self.assertEqual(d["depth"], 0.0)

    def test_note_for_flag_names_a_true_hole(self):
        n = NDS.note_for_flag(NDS.FLAG_NEIGHBOURHOOD, cell_m=50.0)
        self.assertIn("true hole", n.lower())
        self.assertIn("TRUE_HOLE", n)
        e = NDS.note_for_flag(NDS.FLAG_FLOOD_EDGE, cell_m=50.0)
        self.assertIn("flood edge", e.lower())
        self.assertNotIn("have a hole", (e or "").lower())


if __name__ == "__main__":
    unittest.main()
