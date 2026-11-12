"""The habitable-structures depth-velocity chart (engine/dvchart.py): synthetic receptors only (no real dam,
DWR or DSS-WISE data). The habitable filter is Hazard's own rule, the zone counts agree with the chart polygons,
the empty state still writes the chart, a missing matplotlib skips the PNG (CSV kept), and the title names the
source (Runner, Screener, or the imported raster)."""
import csv
import os
import random
import sys
import tempfile
import unittest

from _helpers import CAT, CHARTS, home, preset, run
from damit_hazard.engine import core, dvchart as D, receptors as R, report, tm11

HT = CAT["habitable_types"]
CFT = CAT["methods"]["M1"]["params"]["chart_for_type"]


def _recs():
    return [
        R.make("structure:1", "structure", "home", depth_ft=6.0, velocity_fps=3.0),             # high
        R.make("structure:2", "structure", None, depth_ft=3.0, velocity_fps=1.0),               # unknown type, MEDIUM
        R.make("structure:3", "structure", "mobile_home", depth_ft=0.5, velocity_fps=1.0),      # low (mobile chart)
        R.make("structure:4", "structure", "farm_unoccupied", depth_ft=3.0, velocity_fps=3.0),  # not habitable
        R.make("structure:5", "structure", "outbuilding", depth_ft=3.0, velocity_fps=3.0),      # not habitable
        R.make("structure:6", "structure", "commercial", depth_ft=1.0, velocity_fps=1.0),       # habitable type (houses)
        R.make("structure:7", "structure", "shop_x", depth_ft=1.0, velocity_fps=1.0),           # unknown type, no occupancy
        R.make("structure:8", "structure", "shop_x", depth_ft=1.0, velocity_fps=1.0, occupancy="overnight"),
        R.make("structure:9", "structure", "home", depth_ft=0.0, velocity_fps=0.0),             # dry
        R.make("structure:10", "structure", "home", depth_ft=2.0, velocity_fps=2.0, in_domain=False),
        R.make("structure:11", "structure", "campground", depth_ft=2.0, velocity_fps=2.0),      # chart not digitized
        R.make("structure:12", "structure", "home", depth_ft=2.0),                              # no velocity
        R.make("facility:1", "facility", "hospital", depth_ft=2.0, velocity_fps=2.0),           # facilities left out
        R.make("road:1", "road", "county", depth_ft=2.0, velocity_fps=2.0),
        R.make("structure:13", "structure", "home", depth_ft=0.001, velocity_fps=0.5),          # trace depth
    ]


def _select(recs, **kw):
    return D.select(recs, CHARTS, HT, CFT, **kw)


def test_only_habitable_structures_by_hazards_rule():
    sel = _select(_recs())
    ids = sorted(p["label"] for p in sel["points"])
    assert ids == sorted(["1", "2", "3", "6", "8", "13"]), ids
    by = {p["label"]: p for p in sel["points"]}
    assert by["1"]["chart"] == "houses" and by["3"]["chart"] == "mobile_homes"
    assert by["2"]["habitable_basis"] == core.BASIS_UNKNOWN          # no type: presumed a home, said so
    assert by["6"]["habitable_basis"] == core.BASIS_TYPE and by["8"]["habitable_basis"] == core.BASIS_OCCUPANCY
    lo = sel["left_out"]
    assert lo["not_habitable"] == 3 and lo["outside_domain"] == 1 and lo["dry_or_unsampled"] == 1, lo
    assert lo["no_chart"] == 1 and lo["no_velocity"] == 1 and lo["facilities"] == 1, lo
    assert by["13"]["trace_depth"] and not by["1"]["trace_depth"]


def test_filter_is_the_engines_own_rule():
    """The chart calls core.habitable_basis, the function Ctx.habitable (M6, M1 ...) calls: same answer for every
    receptor, and the engine still flags type_unknown."""
    run_ = {"scenario": "S1", "model_dim": "2D", "receptors": [], "label": "t"}
    for r in _recs():
        flags = core.Flags()
        ctx = core.Ctx(CAT, preset("ND"), CHARTS, run_, {}, flags)
        assert ctx.habitable(r) == core.habitable_basis(r, HT)[0], r["id"]
        assert ctx.occupied(r) == core.is_occupied(r, HT), r["id"]
        assert ("type_unknown" in [f["code"] for f in flags.items]) == (r.get("type") is None), r["id"]
    res = run(preset("ND"), [home("h", depth=2.0, vel=1.0, type=None)], scenario="S3")
    assert "type_unknown" in set(f["code"] for f in res["flags"])


def _pip(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def test_zone_counts_agree_with_the_chart_polygons():
    random.seed(7)
    for cid, ctype in (("houses", "home"), ("mobile_homes", "mobile_home")):
        c = CHARTS.charts[cid]
        recs = [R.make("structure:%d" % i, "structure", ctype, depth_ft=random.uniform(0.05, c["d_max_ft"] * 1.2),
                       velocity_fps=random.uniform(0.0, c["v_max_fts"] * 1.2)) for i in range(400)]
        pts = _select(recs)["points"]
        poly = D.zone_polygons(CHARTS, cid)
        want = {"high": 0, "judgment": 0, "low": 0}
        for p in pts:
            xy = (p["velocity_fps"], p["depth_ft"])
            z = "low" if _pip(xy, poly["low"]) else ("judgment" if _pip(xy, poly["judgment"]) else "high")
            want[z] += 1
            assert p["zone"] == z, (cid, xy, p["zone"], z)
        got = D.counts(pts)
        assert (got["high"], got["judgment"], got["low"]) == (want["high"], want["judgment"], want["low"])
        assert got["total"] == 400 and want["high"] and want["judgment"] and want["low"]


def _build(recs, tmp, **meta):
    m = {"dam_id": "ND00000", "dam_name": "Synthetic Dam", "source": "Runner", "run_date": "2026-11-12"}
    m.update(meta)
    return D.build(recs, CHARTS, m, tmp, habitable_types=HT, chart_for_type=CFT)


def _have_mpl():
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def test_png_csv_title_and_counts_text():
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build(_recs(), tmp)
    assert os.path.isfile(res["csv"])
    rows = list(csv.DictReader(open(res["csv"], encoding="utf-8")))
    assert len(rows) == 6 and tuple(rows[0].keys()) == D.CSV_COLUMNS
    assert [r["zone"] for r in rows][0] == "high" and {r["zone"] for r in rows} == {"high", "MEDIUM", "low"}
    c = res["counts"]
    assert res["text"] == "6 wet habitable structure(s): {} high, {} MEDIUM (judgment), {} low".format(
        c["high"], c["judgment"], c["low"])
    assert "ND00000 Synthetic Dam - Runner - run 2026-11-12" in res["title"]
    assert c["unknown_type"] == 1 and "mobile_homes" in c["by_chart"]
    if _have_mpl():
        assert res["status"] == "ok" and os.path.getsize(res["png"]) > 5000
        assert open(res["png"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_empty_state_still_writes_the_chart():
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build([R.make("structure:1", "structure", "farm_unoccupied", depth_ft=3.0, velocity_fps=2.0),
                  R.make("structure:2", "structure", "home", depth_ft=0.0, velocity_fps=0.0)], tmp)
    assert res["counts"]["total"] == 0 and "0 wet habitable" in res["text"]
    assert "no wet habitable structures" in res["note"]
    rows = list(csv.reader(open(res["csv"], encoding="utf-8")))
    assert len(rows) == 1                                           # the header only
    if _have_mpl():
        assert res["status"] == "ok" and os.path.isfile(res["png"])


def test_mobile_home_panel_only_when_there_are_mobile_homes():
    if not _have_mpl():
        return
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    seen = []
    real = plt.subplots

    def spy(*a, **k):
        fig, axs = real(*a, **k)
        seen.append(len(axs) if hasattr(axs, "__len__") else 1)
        return fig, axs
    plt.subplots = spy
    try:
        tmp = tempfile.mkdtemp(prefix="dvchart_")
        _build([R.make("structure:1", "structure", "home", depth_ft=2.0, velocity_fps=1.0)], tmp)
        _build(_recs(), tempfile.mkdtemp(prefix="dvchart_"))
    finally:
        plt.subplots = real
    assert seen == [2, 3], seen                                     # full + zoom; then the mobile-home panel too


def test_missing_matplotlib_skips_the_png_with_a_note():
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    saved = {k: sys.modules.get(k) for k in ("matplotlib", "matplotlib.pyplot")}
    sys.modules["matplotlib"] = None                                # import raises ImportError
    sys.modules["matplotlib.pyplot"] = None
    logs = []
    try:
        res = D.build(_recs(), CHARTS, {"dam_id": "ND00000", "source": "Runner", "run_date": "2026-11-12"}, tmp,
                      habitable_types=HT, chart_for_type=CFT, log=logs.append)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    assert res["status"] == "csv_only" and res["png"] is None
    assert "matplotlib is not available" in res["note"] and logs and "skipped" in logs[0]
    assert "csv" in res["note"].lower()
    assert os.path.isfile(res["csv"]) and not os.path.exists(os.path.join(tmp, D.CHART_NAME + ".png"))


def test_source_label_runner_screener_or_the_imported_raster():
    assert D.detect_source("/x/ND00001/Depth (Max).tif") == ("Runner", "runner")
    assert D.detect_source("/x/ND00001/Screening Depth (Max).tif") == ("Screener", "screener")
    assert D.detect_source("/x/dsswise_run7_depth.tif") == ("Imported raster: dsswise_run7_depth.tif", "imported")
    assert D.detect_source("/x/dsswise_run7_depth.tif|layername=a") [0] == "Imported raster: dsswise_run7_depth.tif"
    assert D.detect_source("/x/depth.tif", "DSS-WISE") == ("DSS-WISE", "given")
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build(_recs(), tmp, source=D.detect_source("/x/dsswise_run7_depth.tif")[0])
    assert "Imported raster: dsswise_run7_depth.tif" in res["title"]
    if _have_mpl():
        assert os.path.getsize(res["png"]) > 5000
    assert {r["source"] for r in csv.DictReader(open(res["csv"], encoding="utf-8"))} == {
        "Imported raster: dsswise_run7_depth.tif"}


def test_screener_receptors_become_point_sample_chart_points():
    recs = D.from_screener([
        {"id": "a", "receptor_type": "structure", "structure_type": "home", "depth_ground_ft": 3.0, "velocity_fps": 2.0},
        {"id": "b", "receptor_type": "structure", "structure_type": "mobile_home", "depth_ground_ft": 1.0,
         "velocity_fps": 1.0},
        {"id": "c", "receptor_type": "structure", "structure_type": "barn", "depth_ground_ft": 3.0, "velocity_fps": 1.0},
        {"id": "d", "receptor_type": "road", "depth_ground_ft": 3.0, "velocity_fps": 1.0},
        {"id": "e", "receptor_type": "structure", "structure_type": "home", "depth_ground_ft": 0.0, "velocity_fps": 0.0},
        {"id": "f", "receptor_type": "structure", "structure_type": "home", "in_domain": False}])
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = D.build(recs, CHARTS, {"dam_id": "ND00000", "source": "Screener", "run_date": "2026-11-12",
                                 "sampling": D.SAMPLING_POINT}, tmp, habitable_types=HT, chart_for_type=CFT)
    assert sorted(r["label"] for r in csv.DictReader(open(res["csv"], encoding="utf-8"))) == ["a", "b"]
    assert {r["sampling"] for r in csv.DictReader(open(res["csv"], encoding="utf-8"))} == {D.SAMPLING_POINT}
    assert "point sample" in D.title_lines({"sampling": D.SAMPLING_POINT}, res["counts"])[2]


def test_report_links_and_embeds_the_chart():
    if not _have_mpl():
        return
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    recs = _recs()
    res = run(preset("ND"), recs, scenario="S3")
    ch = D.build(recs, CHARTS, {"dam_id": "ND00000", "dam_name": "Synthetic Dam", "source": "Runner",
                                "run_date": "2026-11-12"}, tmp, habitable_types=HT, chart_for_type=CFT)
    ch["png"], ch["csv"] = os.path.basename(ch["png"]), os.path.basename(ch["csv"])
    res["dv_charts"] = [ch]
    md = report.markdown(res, CAT)
    assert report.DV_SECTION in md and "![" in md and D.CHART_NAME + ".png" in md and D.CHART_NAME + ".csv" in md
    html = report.html_report(res, CAT, base_dir=tmp)
    assert "<img" in html and "data:image/png;base64," in html
    assert "src='" + D.CHART_NAME + ".png'" not in html                  # embedded, not linked
    res.pop("dv_charts")
    assert report.DV_SECTION not in report.markdown(res, CAT)


if __name__ == "__main__":
    unittest.main()
