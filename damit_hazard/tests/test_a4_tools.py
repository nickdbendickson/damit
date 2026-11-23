"""Catalog tools added in Hazard 0.4.9. No QGIS. A class is never lowered."""
import json
import os
import shutil
import tempfile

from _helpers import CAT, CHARTS, custom, home, run

from damit_hazard.engine import (batchcls, creep, dsswise, ensemble, formfill, markreviewed,
                                 modelgate, portfolio, rasimport, reproduce, series, submittal,
                                 tm11, velocity_hinge)


def test_p95_flag_does_not_change_the_class():
    # Ten slow cells and one fast cell. The worst zone is high on the fast cell. At the
    # 95th-percentile velocity the same depth is only judgment. The class stays high.
    cells = [(2.5, 0.5)] * 10 + [(2.5, 20.0)]
    rec = home("h", depth=2.5, vel=20.0, cells=cells, occupants=2)
    res = run(custom(["M1"]), [rec])
    assert res["suggested_class"] == 3
    assert res["velocity_p95_review"] and res["velocity_p95_review"][0]["less_severe"]
    assert all("95th" not in (h.get("reason") or "") for h in res["hits"])
    assert "velocity_p95_review" in [f["code"] for f in res["flags"]]


def test_p95_same_zone_is_not_flagged():
    cells = [(1.0, 1.0), (1.0, 1.1)]
    rec = {"id": "s", "kind": "structure", "type": "home", "cells": cells}
    assert velocity_hinge.hinge(CHARTS, rec, CAT) is None


def test_percentile_matches_two_points():
    # linear index 0.95 * (2-1) = 0.95, so 0.05*1 + 0.95*11
    assert abs(velocity_hinge.percentile([1.0, 11.0], 95) - 10.5) < 1e-9


def test_no_breach_is_its_own_outcome_and_cannot_lower():
    items = [
        {"id": "a", "status": "done", "suggested_class": 3, "weight": 1},
        {"id": "b", "status": "done", "suggested_class": 2, "weight": 1},
        {"id": "c", "status": "no breach", "suggested_class": 1, "weight": 1},
        {"id": "d", "status": "no breach", "weight": 1},
    ]
    agg = ensemble.aggregate(items)
    assert abs(agg["no_breach"]["p"] - 0.5) < 1e-9
    assert abs(agg["classes"][3]["p"] - 0.25) < 1e-9
    assert abs(agg["classes"][3]["p_given_breach"] - 0.5) < 1e-9
    assert 1 not in agg["classes"]          # the no-breach item's class is ignored
    assert abs(sum(b["p"] for b in agg["classes"].values()) + agg["no_breach"]["p"] - 1) < 1e-9
    assert agg["governing_class"] == 3
    assert "no breach" in ensemble.summary_line(agg)


def test_ensemble_writes_a_folder_per_run():
    folder = tempfile.mkdtemp(prefix="damit_ens_")
    try:
        runs = [{"id": "run_001", "status": "done", "suggested_class": 2, "weight": 1},
                {"id": "run_002", "status": "no breach", "suggested_class": 1, "weight": 1}]
        agg = ensemble.aggregate(runs)
        ensemble.write_distribution(folder, agg, runs)
        assert os.path.isfile(os.path.join(folder, "ensemble", "run_001", "result.json"))
        assert os.path.isfile(os.path.join(folder, "ensemble", "run_002", "result.json"))
        saved = json.load(open(os.path.join(folder, "ensemble", "run_002", "result.json"),
                               encoding="utf-8"))
        assert saved["status"] == "no breach"
        assert saved["suggested_class"] is None
        # find_runs keeps a no-breach folder and does not copy its class into the aggregate input
        run = os.path.join(folder, "Runs", "run_009")
        os.makedirs(run)
        json.dump({"status": "no breach", "weight": 2, "suggested_class": 1},
                  open(os.path.join(run, "run.json"), "w", encoding="utf-8"))
        found = ensemble.find_runs(folder)
        assert any(r["id"] == "run_009" and r["status"] == "no breach" and r["suggested_class"] is None
                   for r in found)
    finally:
        shutil.rmtree(folder)


def test_mark_reviewed_does_not_touch_a_class():
    folder = tempfile.mkdtemp(prefix="damit_mark_")
    try:
        path = os.path.join(folder, "dam.json")
        json.dump({"suggested_class": 3, "suggested_label": "High", "name": "kept"},
                  open(path, "w", encoding="utf-8"))
        res = markreviewed.mark_reviewed(folder, "A. Engineer", "Returned", open_items=0)
        assert res["class_changed"] is False
        written = json.load(open(path, encoding="utf-8"))
        assert written["suggested_class"] == 3 and written["suggested_label"] == "High"
        assert written["hazard_review"]["decision"] == "Returned"
        assert written["hazard_review"]["open_items"] == 1
        assert "class" not in written["hazard_review"]
        # chain stamp: no reviewer, still no class key added
        os.remove(path)
        markreviewed.mark_reviewed(folder)
        written = json.load(open(path, encoding="utf-8"))
        assert written["hazard_review"]["decision"] is None
        assert "suggested_class" not in written
    finally:
        shutil.rmtree(folder)


def test_reproduce_never_publishes_a_lower_class():
    assert reproduce.published_class(3, 1) == 3
    low = reproduce.compare(3, 1)
    assert low["published_class"] == 3 and low["would_lower"] and low["class_lowered"] is False
    high = reproduce.compare(2, 3)
    assert high["published_class"] == 3 and high["raised"]
    assert reproduce.compare(2, 2)["published_class"] == 2


def test_batch_classifies_each_dam_on_its_own():
    folder = tempfile.mkdtemp(prefix="damit_batch_")
    try:
        wet = home("h", depth=8, vel=10, occupants=3)
        dry = home("h", depth=0, vel=0, occupants=3)
        for name, recs in (("high.json", [wet]), ("low.json", [dry])):
            json.dump({"id": name[:-5], "receptors": [recs[0]], "dam": {"is_sample": True}},
                      open(os.path.join(folder, name), "w", encoding="utf-8"))
        from damit_hazard.engine import catalog as C
        cfg = C.preset_config(CAT, "USBR")
        rows = batchcls.classify_directory(CAT, cfg, folder, charts=CHARTS)
        by = {r["id"]: r["suggested_class"] for r in rows}
        assert by["high"] > by["low"]
        assert by["low"] == run(cfg, [dry])["suggested_class"]
    finally:
        shutil.rmtree(folder)


def test_model_gate_flags_a_wet_edge_and_sets_no_class():
    import numpy as np
    depth = np.zeros((5, 5))
    depth[0, 2] = 1.5
    depth[2, 2] = 3.0
    res = modelgate.gate_arrays(depth)
    assert res["class_changed"] is False
    assert res["status"] == "WARN"
    assert any(r["check"] == "edge" and r["status"] == "WARN" for r in res["rows"])
    # a no-data gap between wet cells
    holed = np.array([[0, 0, 0], [2.0, np.nan, 2.0], [0, 0, 0]], dtype=float)
    res = modelgate.gate_arrays(holed, params={"edge_warn_ft": 10, "hole_fail_fraction": None})
    assert any(r["check"] == "holes" and r["status"] == "WARN" for r in res["rows"])
    assert "suggested_class" not in res


def test_series_portfolio_creep_form_do_not_lower():
    screened = series.screen([
        {"id": "up", "suggested_class": 3, "reaches": ["down"]},
        {"id": "down", "suggested_class": 2, "reaches": []},
    ])
    assert screened["class_changed"] is False
    by = {d["id"]: d for d in screened["dams"]}
    assert by["down"]["suggested_class"] == 2 and by["down"]["review"] and by["down"]["reached_by"] == ["up"]
    table = portfolio.rows_from_reports([
        {"dam_id": "D1", "suggested_class": 1, "suggested_label": "Low"},
        {"dam_id": "D1", "suggested_class": 3, "suggested_label": "High"},
    ])
    assert table["dams"][0]["suggested_class"] == 3 and table["dams"][0]["review"]
    change = creep.depth_change([{"id": "s", "depth_before_ft": 1, "depth_after_ft": 1.4}])
    assert change["n_increased"] == 1 and change["class_changed"] is False
    text, missing = formfill.fill("Dam {{name}} class {{suggested_class}} form {{form_no}}",
                                  {"name": "Sample"})
    assert text == "Dam Sample class {{suggested_class}} form {{form_no}}"
    assert missing == ["suggested_class", "form_no"]


def test_submittal_round_trip_and_checklist():
    folder = tempfile.mkdtemp(prefix="damit_pkg_")
    try:
        open(os.path.join(folder, "damit_hazard_report.md"), "w", encoding="utf-8").write("class 3\n")
        zpath = os.path.join(folder, "pack.zip")
        built = submittal.build_package(folder, zpath, names=["damit_hazard_report.md"])
        assert built["class_changed"] is False
        checked = submittal.verify_package(zpath)
        assert checked["ok"] and checked["class_changed"] is False
        summary = submittal.summarize_checklist(
            [{"Item": "depth units", "Answer": "yes"}, {"Item": "edge", "Answer": "no"}])
        assert summary["n_open"] == 1 and summary["class_changed"] is False
    finally:
        shutil.rmtree(folder)


def test_rasimport_names_and_dsswise_roles_have_no_state_rule():
    assert rasimport.DEPTH_BASIS_TERRAIN == "terrain"
    assert "ndbreach" not in rasimport.CELL_MIN_WARNING
    assert "ndhazard" not in rasimport.CELL_MIN_WARNING
    assert rasimport.is_plan_hdf(__file__) is False
    assert dsswise.detect_role("NA00000_FloodDepth_in_Ft.tif") == dsswise.R_DEPTH
    assert dsswise.detect_role("NA00000_FloodVelocity_in_Ft_per_Sec.tif") == dsswise.R_VEL
    # a text file is not a plan
    folder = tempfile.mkdtemp(prefix="damit_ras_")
    try:
        hdf = os.path.join(folder, "plan.p01.hdf")
        open(hdf, "wb").write(b"not hdf")
        assert rasimport.find_runner_rasters(hdf) is None
    finally:
        shutil.rmtree(folder)


def test_chart_rank_direction():
    assert tm11.RANK[tm11.HIGH] > tm11.RANK[tm11.LOW]
