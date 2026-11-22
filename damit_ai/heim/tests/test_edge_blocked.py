"""run_digest 1.4.0: EDGE_OUTFLOW_BLOCKED, water standing at a FREE edge with next to no outflow.

Why this exists: Boann sub-grid FV (Runner <= 3.42.0) walled the east and south edges of any grid that was not a
multiple of r. Lake Delhi's lower valley ponded 17 ft too high for days while roughness, conveyance and the
boundary condition were blamed; the .mass file showed 0 outflow the whole time. No model, no rasters.
"""
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("run_digest_blocked", os.path.join(os.path.dirname(HERE), "tools",
                                                                                 "run_digest.py"))
RD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RD)


def a_pass(n, edges, outflow, rise=None, over=()):
    return {"pass": n, "edge_depths_ft": edges, "outflow_pct": outflow, "over": list(over), "over_outflow": [],
            "volume_tail_rise_pct": rise}


class EdgeBlockedTest(unittest.TestCase):
    def ids(self, passes, in_progress=False):
        fl = RD.Flags()
        RD.check_edges(passes, fl, in_progress=in_progress)
        return [(f["id"], f["severity"]) for f in fl.items], fl.items

    def test_deep_edge_with_no_outflow_in_the_final_pass_is_a_problem(self):
        got, items = self.ids([a_pass(1, {"N": 0.0, "S": 6.2, "W": 0.0, "E": 4.1}, 0.0, rise=12.5)])
        self.assertEqual(got, [("EDGE_OUTFLOW_BLOCKED", RD.PROBLEM)])
        self.assertEqual(items[0]["data"]["edges"], ["E", "S"])
        self.assertIn("rose 12.5%", items[0]["detail"])
        self.assertIn(".mass Qout", items[0]["detail"])

    def test_while_the_run_goes_on_it_is_a_watch(self):
        got, _ = self.ids([a_pass(1, {"S": 3.0}, 0.02)], in_progress=True)
        self.assertEqual(got, [("EDGE_OUTFLOW_BLOCKED", RD.WATCH)])

    def test_a_draining_edge_is_not_blocked(self):
        got, _ = self.ids([a_pass(1, {"S": 3.0}, 40.0, over=["S"])])
        self.assertEqual([g[0] for g in got], ["EDGE_OUTFLOW_FINAL"])

    def test_a_shallow_wet_edge_or_unknown_outflow_says_nothing_new(self):
        self.assertEqual(self.ids([a_pass(1, {"S": 0.4}, 0.0)])[0], [])
        self.assertEqual(self.ids([a_pass(1, {"S": 5.0}, None)])[0], [])

    def test_mass_balance_gives_the_tail_rise(self):
        rows = [[t * 600.0, v, 10.0, 0.0, 0.0] for t, v in enumerate([0, 6000, 12000, 18000, 24000, 30000, 36000,
                                                                          42000, 48000, 54000, 60000])]
        mb = RD.mass_balance({"rows": rows})
        self.assertEqual(mb["outflow_pct"], 0.0)
        self.assertGreater(mb["volume_tail_rise_pct"], 0.0)

    def test_the_flag_is_known_and_documented(self):
        self.assertIn("EDGE_OUTFLOW_BLOCKED", RD.KNOWN_FLAG_IDS)
        with open(os.path.join(os.path.dirname(HERE), "knowledge", "WATCHER-DIGEST.md"), encoding="utf-8") as f:
            self.assertIn("`EDGE_OUTFLOW_BLOCKED`", f.read())


if __name__ == "__main__":
    unittest.main()
