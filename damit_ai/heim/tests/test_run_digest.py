"""Unit tests for run_digest.py: every check, on small synthetic run folders (tests/fixture_run.py).
No LLM, no network, no model. Raster tests need numpy; the GeoTIFF test needs GDAL."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, HERE)
import fixture_run as FX  # noqa: E402
from strict import StrictCase, jdump, jload, slurp, spit  # noqa: E402,F401
import run_digest as RD  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    from osgeo import gdal  # noqa: F401
    HAVE_GDAL = True
except ImportError:
    HAVE_GDAL = False


def ids(d, sev=None):
    return [f["id"] for f in d["flags"] if sev is None or f["severity"] == sev]


class Base(StrictCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="heim_digest_")
        self.addCleanup(shutil.rmtree, self.root, True)

    def digest(self, run_kw=None, **kw):
        run, dam = FX.make_run(self.root, **(run_kw or {}))
        kw.setdefault("dam_folder", dam)
        return RD.build_digest(run, **kw)


class TestVerdict(Base):
    def test_verdict_is_the_highest_flag_severity(self):
        self.assertEqual(RD.verdict_of([]), "OK")
        self.assertEqual(RD.verdict_of([{"severity": "INFO"}]), "OK")
        self.assertEqual(RD.verdict_of([{"severity": "INFO"}, {"severity": "WATCH"}]), "WATCH")
        self.assertEqual(RD.verdict_of([{"severity": "WATCH"}, {"severity": "PROBLEM"}]), "PROBLEM")

    def test_clean_run_is_ok_and_verdict_comes_from_flags_alone(self):
        d = self.digest({"streambed_ft": 1463.0, "passes": 2, "report": True})        # crest-bed 37 = height
        # passes=2 means no early/late split: no leak, so nothing to flag
        self.assertEqual(d["verdict"], "OK", [(f["id"], f["title"]) for f in d["flags"]])
        self.assertEqual(d["verdict"], RD.verdict_of(d["flags"]))
        self.assertIn("code", d["verdict_set_by"])

    def test_json_machine_flags(self):
        d = self.digest({"mass_nan": True})
        m = RD.machine_flags(d)
        self.assertEqual(m["verdict"], "PROBLEM")
        self.assertTrue(all({"id", "severity", "where", "title"} <= set(f) for f in m["flags"]))
        json.dumps(m, default=str)

    def test_text_is_20_to_40_lines(self):
        d = self.digest({"mass_nan": True, "final_leak": True}, points_path=FX.write_points(self.root))
        n = len(d["text"].splitlines())
        self.assertTrue(20 <= n <= 40, n)
        self.assertIn("VERDICT: PROBLEM", d["text"])

    def test_thresholds_are_the_documented_ones(self):
        th = RD.THRESHOLDS
        self.assertEqual((th["toe_inner_m"], th["toe_cap_m"], th["toe_default_slope"]), (5.0, 150.0, 3.0))
        self.assertEqual(th["bnsf_ko_trains_per_day"], 15.0)
        self.assertEqual(th["local_datum_max_ft"], 300.0)


class TestMass(Base):
    def test_nan_in_mass_is_a_problem(self):
        d = self.digest({"mass_nan": True})
        self.assertIn("MASS_NAN", ids(d, "PROBLEM"))

    def test_runner_number_wins_over_mass_file(self):
        d = self.digest({"mass_in_report": 2.5, "verr": 0.0})
        p = d["checks"]["passes"][-1]
        self.assertEqual((p["mass_error_pct"], p["mass_error_source"]), (2.5, "run_report"))
        self.assertIn("MASS_BALANCE", ids(d, "PROBLEM"))

    def test_mass_file_is_the_fallback_and_uses_the_runner_formula(self):
        # Qin 10 m3/s from 10 s to 3000 s = 29,900 m3 injected; interval error 100 m3 on 11 rows = 1,100 m3 = 3.679 %
        d = self.digest({"verr": 100.0})
        p = d["checks"]["passes"][-1]
        self.assertEqual(p["mass_error_source"], ".mass")
        self.assertAlmostEqual(p["mass_error_pct"], 3.679, places=2)
        self.assertIn("MASS_BALANCE", ids(d, "PROBLEM"))

    def test_between_half_and_one_percent_is_a_watch(self):
        d = self.digest({"mass_in_report": 0.7})
        self.assertEqual([f["severity"] for f in d["flags"] if f["id"] == "MASS_BALANCE"], ["WATCH"])

    def test_small_error_is_quiet(self):
        d = self.digest({"mass_in_report": 0.1})
        self.assertNotIn("MASS_BALANCE", ids(d))

    def test_read_mass_counts_nan_rows(self):
        p = os.path.join(self.root, "m.mass")
        FX.write(p, FX.mass_text(n=6, nan_row=2))
        m = RD.read_mass(p)
        self.assertEqual((m["nan_rows"], m["n"], len(m["rows"])), (1, 6, 5))

    def test_edge_inflow_and_domain_volume(self):
        run, dam = FX.make_run(self.root)
        p = os.path.join(run, "model", "run03_50m", "results", "run.mass")
        FX.write(p, FX.mass_text(qout=-1.0, vol_scale=1.5))         # water ENTERS through an edge; 1.5x held
        d = RD.build_digest(run, dam_folder=dam)
        self.assertIn("EDGE_INFLOW", ids(d, "PROBLEM"))
        self.assertIn("DOMAIN_VOLUME", ids(d, "PROBLEM"))


class TestEdges(Base):
    def test_early_pass_edge_outflow_is_flagged_as_a_watch(self):
        d = self.digest()                                   # passes 1-2 leak through N and W, 3 is clean
        early = [f for f in d["flags"] if f["id"] == "EDGE_OUTFLOW_EARLY"]
        self.assertEqual(len(early), 1)                      # passes 1 and 2 leak; one flag since 1.2.0 (see test_followups)
        self.assertEqual(early[0]["data"]["occurrences"], 2)
        self.assertTrue(all(f["severity"] == "WATCH" for f in early))
        self.assertEqual(early[0]["data"]["edges"], ["N", "W"])
        self.assertEqual(early[0]["data"]["outflow_pct"], 10.0)
        self.assertNotIn("EDGE_OUTFLOW_FINAL", ids(d))

    def test_final_pass_leak_is_a_problem(self):
        d = self.digest({"final_leak": True})
        self.assertIn("EDGE_OUTFLOW_FINAL", ids(d, "PROBLEM"))
        self.assertEqual(d["verdict"], "PROBLEM")

    def test_per_edge_depths_come_from_the_runner_record(self):
        d = self.digest()
        p1 = d["checks"]["passes"][0]
        self.assertEqual(p1["edge_source"], "run_report")
        self.assertEqual(p1["edge_depths_ft"]["W"], 0.85)

    @unittest.skipUnless(HAVE_NUMPY, "numpy")
    def test_without_a_report_edges_and_outflow_are_computed_from_the_pass_files(self):
        d = self.digest({"report": False})
        p1 = d["checks"]["passes"][0]
        self.assertEqual(p1["edge_source"], "pass raster run.max")
        self.assertGreater(p1["edge_depths_ft"]["N"], 0.7)
        self.assertAlmostEqual(p1["outflow_pct"], 10.0, places=1)           # Qout 1 / Qin 10, same duration
        self.assertNotIn("EDGE_OUTFLOW_FINAL", ids(d))                      # pass 3 is clean
        self.assertEqual(len([f for f in d["flags"] if f["id"] == "EDGE_OUTFLOW_EARLY"]), 1)

    def test_clean_edges_are_quiet(self):
        d = self.digest({"passes": 2})
        self.assertFalse([f for f in d["flags"] if f["id"].startswith("EDGE")])


class TestProgress(Base):
    def test_unfinished_pass_in_a_finished_run(self):
        d = self.digest({"unfinished": True})
        self.assertIn("PASS_UNFINISHED", ids(d, "PROBLEM"))

    def test_running_pass_with_a_stale_mass_file_is_a_stall(self):
        run, dam = FX.make_run(self.root, unfinished=True, report=False)
        mp = os.path.join(run, "model", "run03_50m", "results", "run.mass")
        t = os.path.getmtime(mp)
        d = RD.build_digest(run, dam_folder=dam, now=t + 1200, stall_s=900)
        self.assertIn("STALL", ids(d, "PROBLEM"))
        d2 = RD.build_digest(run, dam_folder=dam, now=t + 10, stall_s=900)          # still moving: no flag yet
        self.assertNotIn("STALL", ids(d2))
        self.assertNotIn("PASS_UNFINISHED", ids(d2))

    def test_run_that_stopped_while_still_moving(self):
        run, dam = FX.make_run(self.root)
        rp = os.path.join(run, "run_report.json")
        r = jload(rp)
        r["passes"][-1]["still_moving"] = True
        r["stop_reason"] = "MAX_RUNS reached"
        jdump(r, rp)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertIn("STOPPED_MOVING", ids(d, "WATCH"))

    def test_progress_fraction(self):
        d = self.digest()
        self.assertEqual(d["checks"]["passes"][0]["progress"], 1.0)         # .mass ends at 3000 s of 3000 s


class TestHeightDatumStart(Base):
    def test_37_vs_39_ft(self):
        d = self.digest()                                   # top 1500, streambed 1461: 39 ft vs inventory 37
        f = [x for x in d["flags"] if x["id"] == "HEIGHT_MISMATCH"][0]
        self.assertEqual(f["severity"], "WATCH")
        self.assertEqual(f["data"]["crest_minus_bed_ft"], 39.0)
        self.assertEqual(f["data"]["inventory_height_ft"], 37.0)
        self.assertEqual(f["data"]["diff_ft"], 2.0)
        self.assertIn("39.0 ft", f["title"])
        self.assertIn("BREACH_BOTTOM_RAISED", ids(d))       # the Runner's own note is surfaced too

    def test_matching_height_is_quiet_and_a_big_gap_is_a_problem(self):
        self.assertNotIn("HEIGHT_MISMATCH", ids(self.digest({"streambed_ft": 1463.0})))
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        self.assertIn("HEIGHT_MISMATCH", ids(self.digest({"streambed_ft": 1440.0}), "PROBLEM"))

    def test_over_5ft_is_a_problem_even_when_under_15pct(self):
        # Spec: HEIGHT_MISMATCH is PROBLEM when the gap is over 5 ft OR over 15%, not both.
        # Tall dam (50 ft), 6 ft gap: over the 5 ft bar but under 15% (7.5 ft) -> must be PROBLEM.
        d = self.digest({"top_ft": 1500.0, "streambed_ft": 1444.0, "height_ft": 50.0})
        f = [x for x in d["flags"] if x["id"] == "HEIGHT_MISMATCH"][0]
        self.assertEqual(f["severity"], "PROBLEM")
        self.assertEqual(f["data"]["diff_ft"], 6.0)

    def test_breach_bottom_is_the_fallback_for_the_streambed(self):
        run, dam = FX.make_run(self.root)
        os.remove(os.path.join(dam, "dam.json"))
        d = RD.build_digest(run, dam_folder=dam)
        h = d["checks"]["height"]
        self.assertIn("breach bottom", h["bed_label"])

    def test_navd88_ok(self):
        self.assertNotIn("DATUM", ids(self.digest()))

    def test_zero_to_300_ft_is_a_local_datum(self):
        d = self.digest({"top_ft": 120.0, "streambed_ft": 83.0})
        f = [x for x in d["flags"] if x["id"] == "DATUM"][0]
        self.assertEqual(f["severity"], "PROBLEM")
        self.assertTrue(f["data"]["local_datum"])

    def test_other_stated_datum_is_a_problem_for_dwr(self):
        d = self.digest({"datum": "NGVD29"})
        self.assertIn("DATUM", ids(d, "PROBLEM"))

    def test_start_wse_must_be_top_of_dam_max_pool(self):
        d = self.digest({"start_wse": 1495.0})
        f = [x for x in d["flags"] if x["id"] == "START_WSE"][0]
        self.assertEqual(f["severity"], "PROBLEM")
        self.assertIn("max pool", f["title"])

    def test_start_wse_at_top_of_dam_is_quiet(self):
        self.assertNotIn("START_WSE", ids(self.digest({"start_wse": 1500.0})))


class TestOutletsAndToe(Base):
    def test_extra_boundary_source_is_outlet_flow(self):
        d = self.digest({"extra_bci": "P 300.000 300.000 QVAR spillway"})
        f = [x for x in d["flags"] if x["id"] == "OUTLET_FLOW"][0]
        self.assertEqual(f["severity"], "PROBLEM")
        self.assertIn("spillway", f["detail"])

    def test_scenario_inflow_is_flagged(self):
        d = self.digest({"inflow_scenario": "100-yr"})
        self.assertIn("OUTLET_FLOW", ids(d, "PROBLEM"))

    def test_sunny_day_has_no_outlet_flag(self):
        self.assertNotIn("OUTLET_FLOW", ids(self.digest()))

    def test_toe_expected_band(self):
        lo, hi, s, dflt = RD.toe_expected(37.0, 2.5)
        self.assertEqual((lo, round(hi, 2), s, dflt), (5.0, 39.47, 2.5, False))
        lo, hi, s, dflt = RD.toe_expected(37.0, None)                # 3:1 when the slope is unknown
        self.assertEqual((round(hi, 2), s, dflt), (45.11, 3.0, True))
        self.assertEqual(RD.toe_expected(1.0, 3.0)[1], 5.0)          # 5 m minimum
        self.assertEqual(RD.toe_expected(500.0, 3.0)[1], 150.0)      # 150 m cap

    def test_toe_inflow_inside_the_band_is_quiet(self):
        d = self.digest()
        # no TOE problem or warning; the fixture has no dam_line, so the only TOE flag is the INFO source note (1.2.0)
        self.assertEqual([(f["id"], f["severity"]) for f in d["flags"] if f["id"].startswith("TOE")],
                         [("TOE_SOURCE_RUN_REPORT", "INFO")])
        t = d["checks"]["toe_inflow"]
        self.assertEqual((t["distance_m"], t["expected_outer_m"]), (39.0, 39.47))

    def test_toe_inflow_beyond_the_band_is_a_problem(self):
        d = self.digest({"toe_distance": 80})
        self.assertIn("TOE_INFLOW", ids(d, "PROBLEM"))

    def test_toe_band_that_disagrees_with_the_rule_is_flagged(self):
        d = self.digest({"toe_outer": 45.0})
        self.assertIn("TOE_BAND", ids(d, "WATCH"))


@unittest.skipUnless(HAVE_NUMPY, "numpy")
class TestReceptors(Base):
    def test_structure_in_a_nodata_pocket_next_to_wet_cells(self):
        pts = FX.write_points(self.root)
        d = self.digest(points_path=pts)
        f = [x for x in d["flags"] if x["id"] == "RECEPTOR_NODATA"][0]
        self.assertEqual(f["severity"], "WATCH")
        self.assertEqual(f["data"]["ids"], ["900000001"])
        self.assertAlmostEqual(f["data"]["neighbour_ft"]["900000001"], 6.56, places=2)

    def test_dry_cell_next_to_deep_water(self):
        d = self.digest(points_path=FX.write_points(self.root))
        f = [x for x in d["flags"] if x["id"] == "RECEPTOR_DRY_NEXT_TO_WET"][0]
        self.assertEqual(f["data"]["ids"], ["900000003"])

    def test_wet_and_far_dry_receptors_are_not_flagged(self):
        g = RD.Grid(__import__("numpy").zeros((3, 3)), 0, 150, 50)
        g.data[1, 1] = 3.0
        res = RD.receptor_check(g, [("a", 75, 75), ("b", 400, 400)])
        self.assertEqual(res["outside"], 1)
        self.assertEqual(res["nodata_next_to_wet"], [])

    def test_nodata_with_no_wet_neighbour_is_ignored(self):
        np = __import__("numpy")
        g = RD.Grid(np.zeros((3, 3)), 0, 150, 50)
        g.data[1, 1] = np.nan
        self.assertEqual(RD.receptor_check(g, [("a", 75, 75)])["nodata_next_to_wet"], [])

    def test_peaks_are_over_wet_cells(self):
        d = self.digest()
        pk = d["checks"]["peaks"]
        self.assertAlmostEqual(pk["peak_depth_ft"], 6.56, places=2)
        self.assertAlmostEqual(pk["peak_velocity_fps"], 4.92, places=2)       # 1.5 m/s
        self.assertIn("wet cells", pk["definition"])

    def test_receptors_are_sampled_without_a_points_file_only_when_a_layer_is_known(self):
        d = self.digest()
        self.assertIsNone(d["checks"]["receptors"])

    @unittest.skipUnless(HAVE_GDAL, "GDAL")
    def test_geotiff_depth_is_read_when_gdal_is_there(self):
        import numpy as np
        from osgeo import gdal
        run, dam = FX.make_run(self.root)
        os.makedirs(os.path.join(run, "outputs"))
        arr = np.zeros((FX.NROWS, FX.NCOLS), dtype="float32")
        arr[5:13, 5:13] = 6.56
        arr[FX.DRY_BESIDE_DEEP] = 0.0656          # a trace of water, as in the pass grids (0.0 would read as NoData)
        arr[FX.POCKET] = -9999
        ds = gdal.GetDriverByName("GTiff").Create(os.path.join(run, "outputs", "Depth (Max).tif"), FX.NCOLS, FX.NROWS, 1,
                                                  gdal.GDT_Float32)
        ds.SetGeoTransform((0, 50, 0, 1000, 0, -50))
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-9999)
        b.WriteArray(arr)
        ds = None
        d = RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        self.assertEqual([x for x in d["flags"] if x["id"] == "RECEPTOR_NODATA"][0]["data"]["ids"], ["900000001"])


class TestHazardDrivers(Base):
    def test_unscored_roads(self):
        d = self.digest({"hazard": True, "unscored_roads": 11})
        f = [x for x in d["flags"] if x["id"] == "ROADS_UNSCORED"][0]
        self.assertEqual((f["severity"], f["data"]["count"]), ("WATCH", 11))

    def test_bnsf_ko_lookup_with_15_is_quiet(self):
        d = self.digest({"hazard": True})
        self.assertNotIn("RAIL_TRAINS", ids(d))
        self.assertEqual(d["checks"]["hazard"]["rail_ko_trains_per_day"], 15.0)

    def test_bnsf_ko_lookup_that_is_not_15_is_flagged(self):
        d = self.digest({"hazard": True, "trains_ko": 8.0})
        f = [x for x in d["flags"] if x["id"] == "RAIL_TRAINS"][0]
        self.assertEqual(f["severity"], "WATCH")
        self.assertIn("15", f["title"])

    def test_trains_unknown_asks_for_a_lookup_row(self):
        run, dam = FX.make_run(self.root, hazard=True)
        hp = os.path.join(dam, "classify", "damit_hazard_report.json")
        h = jload(hp)
        h["flags"].append({"level": "warning", "code": "trains_unknown", "message": "x", "receptors": ["rail:1", "rail:2"]})
        h["layers"] = []
        jdump(h, hp)
        d = RD.build_digest(run, dam_folder=dam)
        f = [x for x in d["flags"] if x["id"] == "RAIL_TRAINS"][0]
        self.assertIn("BNSF KO", f["detail"])
        self.assertEqual(f["data"]["count"], 2)

    def test_judgment_zone_hits_need_review(self):
        run, dam = FX.make_run(self.root, hazard=True)
        hp = os.path.join(dam, "classify", "damit_hazard_report.json")
        h = jload(hp)
        h["flags"].append({"level": "info", "code": "judgment_zone", "message": "x", "receptors": ["structure:1"]})
        jdump(h, hp)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertIn("HAZARD_REVIEW", ids(d, "WATCH"))

    def test_no_hazard_report_yet(self):
        d = self.digest()
        self.assertIsNone(d["checks"]["hazard"])


class TestEngineAndMisc(Base):
    def test_builtin_engine_fallback(self):
        run, dam = FX.make_run(self.root)
        rp = os.path.join(run, "run_report.json")
        r = jload(rp)
        r["engine_selection"] = {"fallback": True, "warning": "no LISFLOOD-FP found"}
        jdump(r, rp)
        self.assertIn("ENGINE_FALLBACK", ids(RD.build_digest(run, dam_folder=dam), "WATCH"))

    def test_empty_folder(self):
        d = RD.build_digest(self.root)
        self.assertEqual(d["verdict"], "PROBLEM")
        self.assertIn("NO_RUN_FILES", ids(d))

    def test_never_writes_into_the_run_folder(self):
        run, dam = FX.make_run(self.root)
        before = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(run) for f in fs)
        RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        after = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(run) for f in fs)
        self.assertEqual(before, after)

    def test_cli_refuses_to_write_into_the_run_folder(self):
        run, dam = FX.make_run(self.root)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(RD.main([run, "--dam-folder", dam, "--out", os.path.join(run, "x")]), 2)
        self.assertFalse(os.path.exists(os.path.join(run, "x")))

    def test_cli_exit_code_follows_the_verdict(self):
        run, dam = FX.make_run(self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(RD.main([run, "--dam-folder", dam, "--exit-code"]), 1)       # WATCH
            self.assertEqual(RD.main([run, "--dam-folder", dam]), 0)

    def test_every_flag_id_used_is_declared(self):
        d = self.digest({"mass_nan": True, "final_leak": True, "hazard": True, "unscored_roads": 2, "start_wse": 1.0,
                         "extra_bci": "P 1 1 QVAR x", "toe_distance": 99}, points_path=FX.write_points(self.root))
        for f in d["flags"]:
            self.assertIn(f["id"], RD.KNOWN_FLAG_IDS)


if __name__ == "__main__":
    unittest.main()


class TestDamPoint(Base):

    def test_dam_point_off_the_line_is_watch(self):
        run, dam = FX.make_run(self.root)
        path = os.path.join(run, "run_report.json")
        with open(path, encoding="utf-8") as fh:
            rep = json.loads(fh.read())
        how = ("the inventory / official point is 7190 m from the dam line (threshold 68 m: "
               "100 m, or half the 136 m line when that is shorter). The model uses the dam line.")
        rep["dam_point"] = {"lonlat": [-97.42144, 46.00633], "line_distance_m": 7190.0,
                            "threshold_m": 68.0, "dam_line_length_m": 136.0, "off_line": True,
                            "how": how}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertIn("DAM_POINT_OFF_LINE", ids(d, "WATCH"))
        self.assertTrue(d["checks"]["dam_point"]["off_line"])
        f = [x for x in d["flags"] if x["id"] == "DAM_POINT_OFF_LINE"][0]
        self.assertIn("7190", f["title"])

    def test_dam_point_on_the_line_is_quiet(self):
        run, dam = FX.make_run(self.root)
        path = os.path.join(run, "run_report.json")
        with open(path, encoding="utf-8") as fh:
            rep = json.loads(fh.read())
        rep["dam_point"] = {"lonlat": [-97.5011, 45.9727], "line_distance_m": 4.0,
                            "threshold_m": 68.0, "dam_line_length_m": 136.0, "off_line": False}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertNotIn("DAM_POINT_OFF_LINE", ids(d))


if __name__ == "__main__":
    unittest.main()
