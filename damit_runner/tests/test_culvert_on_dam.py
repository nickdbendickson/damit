"""DamIT port of the H6-1 test of DamSafety Runner tests/test_culvert_match.py (DWR_Plugins 07ab314c):
a guessed culvert cut that crosses the dam line is marked on_dam (CSV column and the report table).
Run by unittest through damit_runner/tests/_dwr_registry.py. The test body is DamSafety's."""
from damit_runner.core.units import FT  # noqa: F401
from damit_runner.tests._dwr_registry import register

_MIN_REPORT = {
    "hydrograph": [], "policy": [], "run_finished": [], "tool": [],
    "inflow_point": {"xy": [0.0, 0.0], "how": "given"},
    "lisflood_runs": [{"run": 1, "bounds": [0.0, 0.0, 4000.0, 4000.0], "size_mi": [2.49, 2.49],
                       "cells": 10000, "dem_coverage": 1.0, "sim_time_hr": 10.0,
                       "runtime_min": 0.2, "edge_max_depth_ft": {"N": 0.0, "S": 0.0, "W": 0.0,
                                                                 "E": 0.0},
                       "edges_over_tolerance": [], "latest_arrival_hr": 9.0,
                       "stats": {"cells": 10000, "cell_size_m": 40.0, "sim_time_hr": 10.0,
                                 "max_depth_ft": 9.0, "max_velocity_fps": 11.0,
                                 "flooded_acres": 1000.0, "peak_inflow_cfs": 25000.0,
                                 "max_volume_error_pct": 0.0, "worst_interval_error_pct": 0.0,
                                 "injected_acft": 1600.0, "in_domain_acft": 1400.0,
                                 "velocity_written": True}}],
    "outputs": {"final": {"depth": "d.tif", "velocity": "v.tif", "arrival": "a.tif",
                          "wse": "w.tif"}},
    "settings": {"edge_tolerance_ft": 1.0, "expand_step_mi": 3.0},
    "summary": {"dam_id": "T1", "final_model": "LISFLOOD-FP", "peak_breach_cfs": 25000.0,
                "breach_method": "piping", "storage_at_failure_acft": 1600.0,
                "flooded_acres": 1000.0, "flooded_acres_over_arrival_depth": 900.0,
                "max_depth_ft": 9.0, "max_velocity_fps": 11.0, "latest_arrival_hr": 9.0,
                "lisflood_runs": 1, "domain_mi": [2.49, 2.49], "units": "ft"}}


@register
def culvert_guess_on_dam_marks_cut_crossing_dam_line():
    """H6-1: a guessed cut that crosses the dam line is marked on_dam (CSV column and the
    guessed-culvert report table) and counted for the warning. Mark/report only: no size,
    invert, cut geometry or structure changes."""
    import copy
    import os as _os
    import tempfile
    from damit_runner.core import culvert_guess as cg
    from damit_runner.core import workflow as W
    road = [(0.0, -500.0), (0.0, 500.0)]
    chan = [(-600.0, 0.0), (600.0, 0.0)]
    rows = cg.guess_crossings([road], [chan])            # one guess at (0, 0), cut along x
    assert len(rows) == 1 and rows[0].get("match_m") is None
    line_before = [tuple(p) for p in rows[0]["line"]]
    cut_before = cg.burn_line(rows[0])
    dam_line = [(0.0, -30.0), (0.0, 30.0)]               # crosses the along-channel cut at origin
    assert cg.mark_on_dam(rows, dam_line) == 1
    assert rows[0]["on_dam"] is True
    # mark/report only: cut geometry and the guessed structure are untouched
    assert [tuple(p) for p in rows[0]["line"]] == line_before
    assert cg.burn_line(rows[0]) == cut_before
    ss = cg.guess_structures(rows)
    assert len(ss) == 1 and abs(ss[0].width_m - 1.2) < 1e-9 and \
        abs(ss[0].height_m - 0.9) < 1e-9 and ss[0].barrels == 1
    # a dam line the cut does not reach: not marked, not counted
    far = cg.guess_crossings([road], [chan])
    assert cg.mark_on_dam(far, [(1000.0, -30.0), (1000.0, 30.0)]) == 0
    assert far[0]["on_dam"] is False
    # no dam line: nothing marked
    none = cg.guess_crossings([road], [chan])
    assert cg.mark_on_dam(none, None) == 0 and none[0]["on_dam"] is False
    # CSV carries the on_dam column as the last field
    p = _os.path.join(tempfile.mkdtemp(), "c.csv")
    cg.write_candidates_csv(p, rows)
    csv_lines = open(p).read().splitlines()
    assert csv_lines[0].split(",")[-1] == "on_dam"
    assert csv_lines[1].split(",")[-1] == "yes"
    # the guessed-culvert report table carries an On dam column
    r = copy.deepcopy(_MIN_REPORT)
    r["culvert_guesses_cut"] = [{"name": "guess: road 1 crosses channel 1", "width_m": 1.2,
                                 "height_m": 0.9, "barrels": 1, "shape": "box",
                                 "invert_up_m": 300.0 * FT, "invert_dn_m": 299.5 * FT,
                                 "on_dam": True}]
    md = W.render_report(r)
    assert "| On dam |" in md
    assert "| 300.0 / 299.5 | yes |" in md, md


from damit_runner.tests._dwr_registry import make_case  # noqa: E402

DamSafetyTests = make_case(__name__)
