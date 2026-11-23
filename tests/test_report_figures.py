"""B3: report-figure thresholds come from the Catalog, default acres do not move, and the class does not read them."""
import os
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Grid(object):
    def __init__(self):
        self.x0 = 0.0
        self.y0 = 100.0
        self.dx = 10.0


class ReportFigures(unittest.TestCase):
    def test_catalog_ships_the_old_defaults(self):
        from damit_catalog import catalog as C
        from damit_catalog import handoff as H
        rf = C.load().report_figures()
        self.assertEqual(rf["depth_thresholds_ft"], [0.1, 1.0, 2.0])
        self.assertEqual(rf["wet_min_depth_ft"], 0.1)
        self.assertEqual(rf["velocity_percentiles"], [95, 99])
        self.assertFalse(rf["feeds_class"])
        cfg = C.load().resolve_preset("FEMA333")
        pkg = H.build(cfg, {"dam_id": "NE00007", "nid_id": "NE00007"})
        self.assertEqual(pkg["report_figures"]["depth_thresholds_ft"], [0.1, 1.0, 2.0])
        self.assertFalse(pkg["report_figures"]["feeds_class"])
        self.assertEqual(C.load().version, "2026.11.09.4")

    def test_acres_match_the_module_defaults_and_the_list_is_stamped(self):
        from damit_runner.core import report_metrics as rm
        g = Grid()
        # 0.05 m is under 0.1 ft; 0.4 m is over 1 ft and under 2 ft; 1 m is over 2 ft
        depth = np.array([[0.02, 0.40], [1.00, np.nan]])
        vel = np.array([[0.1, 0.5], [1.2, np.nan]])
        cell_ac = 1.0
        got = rm.flood_metrics({"depth": depth, "velocity": vel}, g, cell_ac)
        direct = rm.depth_areas(depth, cell_ac, thresholds_ft=rm.DEPTH_THRESHOLDS_FT)
        direct.pop("flooded_acres")
        for k, v in direct.items():
            self.assertEqual(got[k], v, k)
        self.assertEqual(got["depth_thresholds_ft"], [0.1, 1.0, 2.0])
        self.assertEqual(got["velocity_wet_min_depth_ft"], 0.1)
        self.assertEqual(got["velocity_percentiles"], [95, 99])
        self.assertFalse(got["report_figures_feed_class"])
        lines = "\n".join(rm.report_lines(got))
        self.assertIn("not a class input", lines)
        self.assertTrue(rm.is_metric_key("depth_thresholds_ft"))

    def test_classify_does_not_read_the_thresholds(self):
        from damit_hazard.engine import catalog as HC, core, receptors as R, tm11
        cat = HC.load()
        cfg = HC.preset_config(cat, "FEMA333")
        rec = R.make("h1", "structure", "home", depth_ft=0.0, velocity_fps=0.0)
        res = core.classify(cat, cfg, [{"scenario": "S1", "model_dim": "2D", "receptors": [rec]}],
                            dam={"dam_id": "sample", "is_sample": True}, charts=tm11.load())
        self.assertEqual(res["suggested_class"], 1)
        self.assertNotIn("depth_thresholds_ft", res)
        self.assertNotIn("report_figures", res)


if __name__ == "__main__":
    unittest.main()
