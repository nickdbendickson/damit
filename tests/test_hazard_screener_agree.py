"""DamIT Hazard (damit:classify engine) and DamIT Screener's preliminary suggestion (DamIT Catalog's
evaluator) give the same class for the rules decided on PR #5's open questions: USBR M1 / M5, M3
institution datums, and New York's R2 floor presumption and R8 lowering-from-High. Both read these
rules from DamIT Catalog (presets.json / modifiers.json), not from a Hazard-only override.

No QGIS needed:  python3 -m unittest -v tests.test_hazard_screener_agree
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from damit_catalog import catalog as DC                    # noqa: E402
from damit_hazard.engine import catalog as HC, core, receptors as R, tm11   # noqa: E402
from damit_screener.core import catalog_bridge as CB, steps as ST       # noqa: E402

ZONE = {tm11.HIGH: "high_danger", tm11.JUDGMENT: "judgment", tm11.LOW: "low_danger"}


class Agree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop(DC.ENV_DIR, None)
        cls.src = DC.load()
        cls.hcat = HC.load()
        cls.charts = tm11.load()
        cls.base = int(cls.src.hazard["general"]["base_class"])

    # -- the two engines on one set of receptors
    def hazard(self, pid, recs, scenario, dam=None):
        cfg = HC.preset_config(self.hcat, pid)
        res = core.classify(self.hcat, cfg, [{"scenario": scenario, "model_dim": "2D", "receptors": recs}],
                            dam=dam, charts=self.charts)
        return res["suggested_class"]

    def screener(self, pid, recs, dam=None, summary=None):
        cfg = CB.resolve(self.src, {"mode": "preset", "preset": pid})
        st = ST.suggest(self.src, cfg, dict(dam or {}), recs, dict({"model_dimension": "2D"}, **(summary or {})))
        o = st["screening"]["suggested_ordinal"]
        return self.base if o is None else max(o, self.base)    # Hazard reports its base class on no hit

    def home_pair(self, rid, depth, vel, occupants=None):
        h = R.make(rid, "structure", "home", depth_ft=depth, velocity_fps=vel, occupants=occupants)
        z = self.charts.zone("houses", depth, vel)
        c = {"id": rid, "receptor_type": "structure", "structure_type": "home", "habitable": True,
             "occupancy": "overnight", "depth_ground_ft": depth, "depth_foundation_ft": depth,
             "velocity_fps": vel, "dv_ft2s": depth * vel, "m1_zone": ZONE[z]}
        if occupants is not None:
            c["occupants"] = occupants
        return h, c

    def test_usbr_m1_m5(self):
        cases = [((6.5, 1.0, 1),), ((6.5, 1.0, 6),), ((6.5, 1.0, 7),), ((4.0, 1.0, 9),), ((0.5, 0.5, 3),),
                 ((6.5, 1.0, 4), (6.5, 1.0, 3)), ((6.5, 1.0, 3), (4.0, 1.0, 5))]
        got = []
        for case in cases:
            pairs = [self.home_pair("h{}".format(i), *c) for i, c in enumerate(case)]
            hz = self.hazard("USBR", [p[0] for p in pairs], "S1")
            sc = self.screener("USBR", [p[1] for p in pairs])
            self.assertEqual(hz, sc, case)
            got.append(hz)
        self.assertEqual(got, [2, 2, 3, 1, 1, 3, 2])            # M5: 1-6 Significant, 7+ High; M1 alone never

    def test_m3_institutions(self):
        def pair(found, floor, ground=None, dv=1.0):
            g = found if ground is None else ground
            wse = 100.0 + g
            h = R.make("s", "structure", "school", depth_ft=g, velocity_fps=0.1, dv_ft2s=dv, wse_ft=wse,
                       ground_elev=100.0, foundation_elev=wse - found, floor_elev=wse - floor)
            c = {"id": "s", "receptor_type": "structure", "structure_type": "institution", "habitable": True,
                 "depth_ground_ft": g, "depth_foundation_ft": found, "depth_floor_ft": floor, "dv_ft2s": dv}
            return h, c
        cases = [(1.0, -0.5), (0.0, -1.5, 0.3), (3.0, 1.9), (3.5, 2.0), (0.5, -1.0, None, 15.0), (1.9, 0.5)]
        got = []
        for case in cases:
            h, c = pair(*case)
            hz = self.hazard("NE", [h], "S4")
            sc = self.screener("NE", [c])
            self.assertEqual(hz, sc, case)
            got.append(hz)
        self.assertEqual(got, [2, 1, 2, 3, 3, 2])

    def test_ny_r2_and_r8(self):
        h, c = self.home_pair("h", 0.5, 0.1)
        for cur, analysis, want in ((3, "breach_model", 3), (3, "unsteady_tm11", None), (1, "breach_model", None)):
            hz = self.hazard("NY", [dict(h)], "S1", dam={"current_class": cur, "analysis": analysis})
            label = self.src.presets["NY"]["label_map"][str(cur)]
            sc = self.screener("NY", [dict(c)], dam={"existing_class": label}, summary={"analysis": analysis})
            self.assertEqual(hz, sc, (cur, analysis))
            if want is not None:
                self.assertEqual(hz, want)
            else:
                self.assertLess(hz, 3)

    def test_nd_m1_still_high(self):
        h, c = self.home_pair("h", 6.5, 1.0)
        self.assertEqual(self.hazard("ND", [h], "S3"), 3)
        self.assertEqual(self.screener("ND", [c], summary={"hydraulics_source": "breach_model"}), 3)

    def test_summaries_presets_agree(self):
        """Catalog 2026.11.09.4 (Nov 2026 Summaries): AL, NC, USACE, TVA and New York's M5 (High at 1+ life)
        give the same class in both engines."""
        cases = [(6.5, 1.0, 1), (6.5, 1.0, 3), (0.5, 0.5, 2)]
        for pid in ("AL", "NC", "USACE", "TVA", "NY"):
            got = []
            for case in cases:
                h, c = self.home_pair("h", *case)
                hz = self.hazard(pid, [h], "S1")
                sc = self.screener(pid, [c])
                self.assertEqual(hz, sc, (pid, case))
                got.append(hz)
            self.assertEqual(got[:2], [3, 3], pid)          # one life in jeopardy -> High / Class C


if __name__ == "__main__":
    unittest.main()
