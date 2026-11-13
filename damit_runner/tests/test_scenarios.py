"""DamIT Runner 0.4.0: the scenario choices of damit_run:rundam (no QGIS; the engine is stubbed).

The preset is unchanged: a sunny day from the top of dam with a piping breach. START_POOL starts the sunny day at the
normal pool or a stated elevation; SCENARIO = flood routes an inflow hydrograph with a breach or with no breach, with
an optional auxiliary spillway weir."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import numpy as np
    from osgeo import gdal                                # noqa: F401
    HAVE = True
except ImportError:                                       # pragma: no cover - CI without GDAL
    HAVE = False

from damit_runner.core import rundam as RD                # noqa: E402


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


def _write_inflow(path, peak_cfs=9000.0, rise_hr=4.0, base_hr=20.0):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("time_hr,flow_cfs\n0,0\n{},{}\n{},0\n".format(rise_hr, peak_cfs, base_hr))
    return path


def _base(**kw):
    p = dict(dam_id="US00001", height_ft=30.0, storage_acft=2000.0, top_ft=1100.0, area_ac=150.0,
             crest_length_ft=600.0, method="piping")
    p.update(kw)
    return p


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
class Hydrographs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_scen_")
        self.inflow = _write_inflow(os.path.join(self.tmp, "inflow.csv"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preset_is_top_of_dam_and_piping(self):
        from damit_runner.flood import model as M
        self.assertEqual((M.DEFAULTS["scenario"], M.DEFAULTS["start_pool"], M.DEFAULTS["method"]),
                         ("sunny", "top", "piping"))
        dam, hy, fr = M.scenario_hydrograph(_base())
        self.assertIsNone(fr)
        self.assertEqual(hy.params["starting_wse_ft"], 1100.0)
        self.assertEqual(hy.params["starting_wse_rule"], "top of dam")
        self.assertEqual(M.hydrograph_for(_base())[1].peak_cfs, hy.peak_cfs)        # the two-value form
        self.assertIn("top of dam", M._hydrograph_record(hy, dam, _base())["rule"])
        self.assertNotIn("start_below_top_ft", M.BR.dam_to_dict(dam))                 # the record is as before

    def test_sunny_day_from_the_normal_pool_or_an_elevation(self):
        from damit_runner.flood import model as M
        _, top, _ = M.scenario_hydrograph(_base())
        dam, low, _ = M.scenario_hydrograph(_base(start_pool="normal", normal_pool_ft=1090.0))
        self.assertEqual(low.params["starting_wse_ft"], 1090.0)
        self.assertLess(low.peak_cfs, top.peak_cfs)
        self.assertAlmostEqual(low.params["vw_acft"], low.params["storage_at_failure_acft"], 2)
        self.assertEqual(dam.start_below_top_ft, 10.0)
        rec = M._hydrograph_record(low, dam, _base(start_pool="normal", normal_pool_ft=1090.0))
        self.assertIn("normal pool (1090.00 ft)", rec["rule"])
        self.assertEqual(rec["starting_wse_ft"], 1090.0)
        _, st, _ = M.scenario_hydrograph(_base(start_pool="stated", start_wse_ft=1095.0))
        self.assertEqual(st.params["starting_wse_ft"], 1095.0)
        for bad in (dict(start_pool="normal"), dict(start_pool="stated", start_wse_ft=1101.0)):
            with self.assertRaises(M.RunError):
                M.scenario_hydrograph(_base(**bad))

    def test_overtopping_and_the_other_methods_stay_selectable(self):
        from damit_runner.flood import model as M
        _, pip, _ = M.scenario_hydrograph(_base())
        _, ovt, _ = M.scenario_hydrograph(_base(method="overtopping"))
        self.assertEqual(ovt.params["failure_mode"], "overtopping")
        self.assertGreater(ovt.params["avg_breach_width_ft"], pip.params["avg_breach_width_ft"])
        _, low, _ = M.scenario_hydrograph(_base(method="overtopping", start_pool="normal", normal_pool_ft=1090.0))
        self.assertTrue(any("cannot overtop the dam from there" in n for n in low.notes))

    def test_flood_with_a_breach(self):
        from damit_runner.flood import model as M
        p = _base(scenario="flood", inflow_csv=self.inflow, normal_pool_ft=1090.0, trigger="wse",
                  trigger_value=1096.0)
        dam, hy, fr = M.scenario_hydrograph(p)
        self.assertTrue(fr.failed)
        self.assertGreater(hy.t_ref_s, 0.0)                         # the breach starts inside the flood record
        self.assertAlmostEqual(fr.summary["pool_at_breach_ft"], 1096.0, 0)
        self.assertGreater(fr.summary["peak_outflow_with_breach_cfs"], fr.summary["peak_outflow_no_breach_cfs"])
        rec = M._hydrograph_record(hy, dam, p)
        self.assertIn("flood inflow with a breach", rec["rule"])
        self.assertGreater(rec["breach_initiation_hr"], 0.0)
        with self.assertRaises(M.RunError):                         # a trigger the flood never reaches
            M.scenario_hydrograph(dict(p, trigger_value=1200.0))
        with self.assertRaises(M.RunError):                         # a time / elevation trigger needs its value
            M.scenario_hydrograph(dict(p, trigger_value=None))
        with self.assertRaises(M.RunError):                         # no inflow hydrograph
            M.scenario_hydrograph(dict(p, inflow_csv=None))

    def test_flood_with_no_breach_and_an_auxiliary_spillway(self):
        from damit_runner.flood import model as M
        p = _base(scenario="flood_no_breach", inflow_csv=self.inflow, normal_pool_ft=1090.0)
        dam, hy, fr = M.scenario_hydrograph(p)
        self.assertFalse(fr.failed)
        self.assertTrue(fr.summary["no_breach_scenario"])
        self.assertEqual(hy.t_ref_s, 0.0)
        self.assertLess(hy.peak_cfs, 9000.0)                         # the reservoir attenuates the inflow
        self.assertIn("NO breach", M._hydrograph_record(hy, dam, p)["rule"])
        _, _, aux = M.scenario_hydrograph(dict(p, aux_crest_ft=1094.0, aux_length_ft=200.0))
        self.assertLess(aux.summary["peak_pool_ft_no_breach"], fr.summary["peak_pool_ft_no_breach"])
        self.assertGreater(aux.summary["aux_spillway_peak_cfs"], 0)
        with self.assertRaises(M.RunError):                         # a crest with no length
            M.scenario_hydrograph(dict(p, aux_crest_ft=1094.0))

    def test_model_params_carry_the_scenario(self):
        dem = os.path.join(self.tmp, "dem.tif")
        open(dem, "w").close()
        pkg = {"dam": {"dam_id": "US00001", "height_ft": 30.0, "storage_acft": 2000.0, "top_of_dam_elev_ft": 1100.0,
                       "normal_pool_elev_ft": 1090.0}}
        p, notes = RD.model_params({"DEM": dem}, pkg)
        self.assertEqual((p["scenario"], p["start_pool"], p["trigger"], p["method"]),
                         ("sunny", "top", "peak", "piping"))
        self.assertEqual(p["normal_pool_ft"], 1090.0)                # from the dam record
        self.assertFalse(any("START_POOL" in n and "not at the top" in n for n in notes))
        p, notes = RD.model_params({"DEM": dem, "SCENARIO": 2, "INFLOW_CSV": self.inflow, "AUX_CREST_FT": 1094.0,
                                    "AUX_LENGTH_FT": 200.0, "TRIGGER": 1, "TRIGGER_VALUE": 5.0}, pkg)
        self.assertEqual((p["scenario"], p["trigger"], p["trigger_value"]), ("flood_no_breach", "time", 5.0))
        self.assertEqual((p["inflow_csv"], p["aux_crest_ft"], p["aux_length_ft"]), (self.inflow, 1094.0, 200.0))
        p, notes = RD.model_params({"DEM": dem, "START_POOL": 1}, pkg)
        self.assertEqual(p["start_pool"], "normal")
        self.assertTrue(any("normal pool" in n for n in notes))
        scen, pools, trigs = RD.scenario_labels()
        self.assertEqual((len(scen), len(pools), len(trigs)), (3, 3, 3))
        self.assertIn("top of dam", scen[0])
        self.assertIn("preset", pools[0])


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(os, "system", _no_process)
class ScenarioRuns(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        from damit_runner.flood import lisflood as LF
        self.tmp = tempfile.mkdtemp(prefix="damit_scen_run_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)
        self.calls = []
        self.patch = mock.patch.object(LF, "run", synth.stub_lisflood(LF, self.calls))
        self.patch.start()
        self.top_ft = self.site["top_m"] / 0.3048
        self.h_ft = (self.site["top_m"] - self.site["floor_at_dam"]) / 0.3048
        self.inflow = _write_inflow(os.path.join(self.tmp, "inflow.csv"), 6000.0, 3.0, 12.0)

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def params(self, **kw):
        p = dict(dem=self.dem, dam_id="US00002", height_ft=self.h_ft, storage_acft=500.0, top_ft=self.top_ft,
                 area_ac=60.0, crest_length_ft=400.0, dam_line_lonlat=self.site["line"],
                 reservoir_lonlat=self.site["reservoir"], lisflood_exe="builtin", max_runs=1)
        p.update(kw)
        return p

    def test_no_breach_run_is_recorded_as_no_failure(self):
        from damit_runner.flood import model as M
        logs = []
        rec = M.run_breach(self.params(scenario="flood_no_breach", inflow_csv=self.inflow,
                                       normal_pool_ft=self.top_ft - 6.0, aux_crest_ft=self.top_ft - 3.0,
                                       aux_length_ft=80.0), os.path.join(self.tmp, "nb"), log=logs.append)
        self.assertEqual(rec["scenario"], "flood_no_breach")
        self.assertFalse(rec["breach_occurs"])
        self.assertTrue(rec["flood"]["no_breach_scenario"])
        self.assertIn("NO breach", rec["hydrograph"]["rule"])
        self.assertTrue(any("NO breach is modelled" in w for w in rec["warnings"]))
        self.assertTrue(any(str(m).startswith("Flood outflow, no breach") for m in logs))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "nb", "outputs", "Depth (Max).tif")))

    def test_flood_breach_arrival_counts_from_breach_initiation(self):
        from damit_runner.flood import model as M
        seen = {}
        real = M.write_outputs

        def spy(folder, dem, wkt, out, p, s):
            seen["arrival"] = np.array(out["arrival_hr"], float)
            return real(folder, dem, wkt, out, p, s)
        with mock.patch.object(M, "write_outputs", spy):
            rec = M.run_breach(self.params(scenario="flood", inflow_csv=self.inflow,
                                           normal_pool_ft=self.top_ft - 6.0, trigger="time", trigger_value=2.0),
                               os.path.join(self.tmp, "fb"), log=lambda *_: None)
        self.assertEqual(rec["scenario"], "flood")
        self.assertTrue(rec["breach_occurs"])
        self.assertAlmostEqual(rec["hydrograph"]["breach_initiation_hr"], 2.0, 1)
        self.assertTrue(any("WITH the breach only" in w for w in rec["warnings"]))
        arr = seen["arrival"]
        self.assertTrue(np.isfinite(arr).any())
        self.assertGreaterEqual(float(np.nanmin(arr)), 0.0)           # never negative after the shift

    def test_preset_run_record_is_a_sunny_day_from_the_top_of_dam(self):
        from damit_runner.flood import model as M
        rec = M.run_breach(self.params(), os.path.join(self.tmp, "sd"), log=lambda *_: None)
        self.assertEqual(rec["scenario"], "sunny")
        self.assertTrue(rec["breach_occurs"])
        self.assertIsNone(rec["flood"])
        self.assertIn("top of dam", rec["hydrograph"]["rule"])
        self.assertAlmostEqual(rec["hydrograph"]["starting_wse_ft"], self.top_ft, 2)
        self.assertEqual(rec["hydrograph"]["breach_initiation_hr"], 0.0)


if __name__ == "__main__":
    unittest.main()
