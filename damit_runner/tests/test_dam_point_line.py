"""Official / inventory point vs dam line (DWR-2659): threshold and distance, no model run."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.flood import geom as G


class OffLine(unittest.TestCase):
    def test_threshold_is_100_m_or_half_the_line(self):
        self.assertEqual(G.off_line_threshold_m(None), 100.0)
        self.assertEqual(G.off_line_threshold_m(2000.0), 100.0)     # long dam: 100 m
        self.assertEqual(G.off_line_threshold_m(136.0), 68.0)       # 2659 pack line ~136 m
        self.assertEqual(G.off_line_threshold_m(20.0), 25.0)        # short dam: 25 m floor

    def test_distance_to_a_segment(self):
        line = [(0.0, 0.0), (100.0, 0.0)]
        self.assertAlmostEqual(G.distance_to_polyline_m((50.0, 12.0), line), 12.0)
        self.assertAlmostEqual(G.distance_to_polyline_m((50.0, 0.0), line), 0.0)
        self.assertAlmostEqual(G.distance_to_polyline_m((-10.0, 0.0), line), 10.0)
        self.assertAlmostEqual(G.polyline_length_m(line), 100.0)

    def test_tewaukon_scale_offset_is_off_the_line(self):
        # pack line ~136 m; official point 4.47 mi (~7.2 km) away
        line = [(0.0, 0.0), (136.0, 0.0)]
        dist = G.distance_to_polyline_m((7200.0, 100.0), line)
        self.assertGreater(dist, G.off_line_threshold_m(G.polyline_length_m(line)))
        self.assertGreater(dist, 7000.0)


if __name__ == "__main__":
    unittest.main()
