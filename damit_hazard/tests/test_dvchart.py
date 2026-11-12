"""The habitable-structures depth-velocity chart (engine/dvchart.py): synthetic receptors only (no real dam, DWR or
DSS-WISE data). ONLY ND 911 address points and structures an engineer reviewed habitable are plotted; every other wet
structure is an "unverified" count and worklist; the zone counts agree with the chart polygons; the empty state still
writes the chart; a missing matplotlib skips the PNG (CSV kept); the title names the source."""
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


def S(rid, type=None, depth=1.0, vel=1.0, reviewed=None, **kw):
    """A structure receptor; reviewed sets reviewed_habitable (what habitable_review.apply does)."""
    r = R.make("structure:%s" % rid, "structure", type, depth_ft=depth, velocity_fps=vel, **kw)
    if reviewed is not None:
        r["reviewed_habitable"] = reviewed
    return r


def _recs():
    return [
        S(1, "home", 6.0, 3.0, is_911=True),                                    # 911, high
        S(2, None, 3.0, 1.0, source="nd911"),                                   # 911 point, no type, MEDIUM
        S(3, "mobile_home", 0.5, 1.0, nguid="X-1"),                             # 911 (nguid), mobile-home chart, low
        S(4, "farm_unoccupied", 3.0, 3.0, is_911=True),                         # 911 but a non-habitable type
        S(5, "home", 2.0, 2.0, is_911=True, habitable=False),                   # 911 marked not habitable
        S(6, "home", 2.0, 2.0, is_911=True, reviewed=False),                    # 911, reviewed NOT habitable
        S(7, None, 4.0, 2.0, occtype="RES1-1SWB", bid="b7"),                    # NSI, not 911: unverified (suggests home)
        S(8, None, 1.0, 1.0, occtype="AGR1", bid="b8"),                         # NSI, unverified (suggests not habitable)
        S(9, None, 1.0, 1.0),                                                   # no type, no occtype, not 911: unverified
        S(10, None, 1.0, 1.0, occtype="RES2", bid="b10", reviewed=True),        # NSI RES2 reviewed habitable: mobile panel
        S(11, "home", 0.0, 0.0, is_911=True),                                   # dry
        S(12, "home", 2.0, 2.0, is_911=True, in_domain=False),
        S(13, "campground", 2.0, 2.0, is_911=True),                             # chart not digitized
        S(14, "home", 2.0, None, is_911=True),                                  # no velocity
        R.make("facility:1", "facility", "hospital", depth_ft=2.0, velocity_fps=2.0, is_911=True),
        R.make("road:1", "road", "county", depth_ft=2.0, velocity_fps=2.0),
        S(15, "home", 0.001, 0.5, is_911=True),                                 # trace depth
    ]


def _select(recs, **kw):
    return D.select(recs, CHARTS, HT, CFT, **kw)


def test_only_911_points_and_reviewed_structures_are_plotted():
    sel = _select(_recs())
    by = {p["label"]: p for p in sel["points"]}
    assert sorted(by, key=int) == ["1", "2", "3", "10", "15"] or sorted(by) == sorted(["1", "2", "3", "10", "15"]), by
    assert by["1"]["habitable_basis"] == core.BASIS_911 and by["2"]["habitable_basis"] == core.BASIS_911
    assert by["10"]["habitable_basis"] == core.BASIS_REVIEWED and by["10"]["chart"] == "mobile_homes"   # NSI RES2 suggests it
    assert by["3"]["chart"] == "mobile_homes" and by["1"]["chart"] == "houses" and by["2"]["chart"] == "houses"
    assert by["15"]["trace_depth"] and not by["1"]["trace_depth"]
    lo = sel["left_out"]
    assert lo["not_habitable"] == 3 and lo["unverified"] == 3 and lo["outside_domain"] == 1, lo
    assert lo["dry_or_unsampled"] == 1 and lo["no_chart"] == 1 and lo["no_velocity"] == 1 and lo["facilities"] == 1, lo
    unv = {e["label"]: e for e in sel["unverified"]}
    assert sorted(unv, key=int) == ["7", "8", "9"]
    assert unv["7"]["nsi_suggests"] == "habitable" and unv["8"]["nsi_suggests"] == "not habitable"
    assert unv["9"]["nsi_suggests"] == "none" and unv["7"]["struct_key"] == "bid:b7" and unv["7"]["zone"] == tm11.JUDGMENT
    u = D.unverified_summary(sel["unverified"])
    assert (u["total"], u["nsi_suggests_habitable"], u["nsi_suggests_not_habitable"], u["no_suggestion"]) == (3, 1, 1, 1)


def test_nothing_but_911_or_a_review_makes_a_structure_habitable():
    """An NSI occtype, a habitable type, an occupancy, a Crest habitable flag and a USA Structures match never do."""
    r = S(1, "home", 3.0, 1.0, occtype="RES1", bid="x", habitable=True, occupancy="overnight", usa_struct_match="inside")
    r["usa_struct_match"], r["usa_occ_check"] = "inside", "agree"
    assert core.reviewed_status(r, HT) == (core.STATUS_UNVERIFIED, core.BASIS_UNREVIEWED)
    assert D.select([r], CHARTS, HT, CFT)["points"] == []
    r["reviewed_habitable"] = True
    assert core.reviewed_status(r, HT) == (core.STATUS_YES, core.BASIS_REVIEWED)
    r["reviewed_habitable"] = False
    assert core.reviewed_status(dict(r, is_911=True), HT)[0] == core.STATUS_NO          # the review wins over a 911 point
    assert core.reviewed_status(S(2, None, is_911=True), HT) == (core.STATUS_YES, core.BASIS_911)


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
        recs = [S(i, ctype, random.uniform(0.05, c["d_max_ft"] * 1.2), random.uniform(0.0, c["v_max_fts"] * 1.2),
                  is_911=True) for i in range(400)]
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
        import matplotlib.pyplot  # noqa: F401
        return True
    except Exception:
        return False


def _rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


def test_png_csv_worklist_title_and_counts_text():
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build(_recs(), tmp)
    rows = _rows(res["csv"])
    assert len(rows) == 5 and tuple(rows[0].keys()) == D.CSV_COLUMNS
    assert rows[0]["zone"] == "high" and {r["zone"] for r in rows} == {"high", "MEDIUM", "low"}
    assert {r["habitable_basis"] for r in rows} == {core.BASIS_911, core.BASIS_REVIEWED}
    c = res["counts"]
    assert res["text"] == "5 wet habitable structure(s): {} high, {} MEDIUM (judgment), {} low".format(
        c["high"], c["judgment"], c["low"])
    assert "ND00000 Synthetic Dam - Runner - run 2026-11-12" in res["title"]
    assert c["n_911"] == 4 and c["n_reviewed"] == 1 and "mobile_homes" in c["by_chart"]
    wl = _rows(res["unverified_csv"])
    assert tuple(wl[0].keys()) == D.UNVERIFIED_COLUMNS and wl[0]["id"] == "structure:7"
    assert {w["struct_key"] for w in wl} >= {"bid:b7", "bid:b8"}
    assert "3 wet unverified" in res["note"] and res["unverified"]["total"] == 3
    if _have_mpl():
        assert res["status"] == "ok" and os.path.getsize(res["png"]) > 5000
        assert open(res["png"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_empty_state_still_writes_the_chart_and_the_worklist():
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build([S(1, "home", 3.0, 2.0, occtype="RES1", bid="a"), S(2, "home", 0.0, 0.0, is_911=True),
                  S(3, "farm_unoccupied", 3.0, 2.0, is_911=True)], tmp)
    assert res["counts"]["total"] == 0 and "0 wet habitable" in res["text"]
    assert "no wet habitable structures" in res["note"] and "1 wet unverified" in res["note"]
    assert len(list(csv.reader(open(res["csv"], encoding="utf-8")))) == 1                   # the header only
    assert len(_rows(res["unverified_csv"])) == 1
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
        _build([S(1, "home", 2.0, 1.0, is_911=True)], tempfile.mkdtemp(prefix="dvchart_"))
        _build([S(1, "home", 2.0, 1.0, is_911=True), S(2, None, 1.0, 1.0, occtype="RES2", bid="m", reviewed=True)],
               tempfile.mkdtemp(prefix="dvchart_"))
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
    assert "csv" in res["note"].lower() and "unverified" in res["note"]
    assert os.path.isfile(res["csv"]) and os.path.isfile(res["unverified_csv"])
    assert not os.path.exists(os.path.join(tmp, D.CHART_NAME + ".png"))


def test_source_label_runner_screener_or_the_imported_raster():
    assert D.detect_source("/x/ND00001/Depth (Max).tif") == ("Runner", "runner")
    assert D.detect_source("/x/ND00001/Screening Depth (Max).tif") == ("Screener", "screener")
    assert D.detect_source("/x/dsswise_run7_depth.tif") == ("Imported raster: dsswise_run7_depth.tif", "imported")
    assert D.detect_source("/x/dsswise_run7_depth.tif|layername=a")[0] == "Imported raster: dsswise_run7_depth.tif"
    assert D.detect_source("/x/depth.tif", "DSS-WISE") == ("DSS-WISE", "given")
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = _build(_recs(), tmp, source=D.detect_source("/x/dsswise_run7_depth.tif")[0])
    assert "Imported raster: dsswise_run7_depth.tif" in res["title"]
    if _have_mpl():
        assert os.path.getsize(res["png"]) > 5000
    assert {r["source"] for r in _rows(res["csv"])} == {"Imported raster: dsswise_run7_depth.tif"}


def test_screener_receptors_911_points_and_reviews():
    recs = D.from_screener([
        {"id": "a", "receptor_type": "structure", "structure_type": "home", "depth_ground_ft": 3.0, "velocity_fps": 2.0,
         "source": "nd911"},
        {"id": "b", "receptor_type": "structure", "structure_type": "mobile_home", "depth_ground_ft": 1.0,
         "velocity_fps": 1.0, "source": "nd911"},
        {"id": "c", "receptor_type": "structure", "structure_type": "home", "depth_ground_ft": 3.0, "velocity_fps": 1.0,
         "source": "crest", "crest_id": "c1"},                                   # not 911: unverified until reviewed
        {"id": "d", "receptor_type": "road", "depth_ground_ft": 3.0, "velocity_fps": 1.0},
        {"id": "e", "receptor_type": "structure", "structure_type": "home", "depth_ground_ft": 0.0, "velocity_fps": 0.0,
         "source": "nd911"},
        {"id": "f", "receptor_type": "structure", "structure_type": "home", "source": "nd911", "in_domain": False}],
        reviews={"crest_id:c1": {"reviewed_habitable": True, "decided_by": "E", "decided_on": "2026-11-12"}})
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    res = D.build(recs, CHARTS, {"dam_id": "ND00000", "source": "Screener", "run_date": "2026-11-12",
                                 "sampling": D.SAMPLING_POINT}, tmp, habitable_types=HT, chart_for_type=CFT)
    rows = _rows(res["csv"])
    assert sorted(r["label"] for r in rows) == ["a", "b", "c"]
    assert {r["habitable_basis"] for r in rows if r["label"] == "c"} == {core.BASIS_REVIEWED}
    assert {r["sampling"] for r in rows} == {D.SAMPLING_POINT}
    assert "point sample" in D.title_lines({"sampling": D.SAMPLING_POINT}, res["counts"])[2]
    no_review = D.select(D.from_screener([{"id": "c", "receptor_type": "structure", "structure_type": "home",
                                           "depth_ground_ft": 3.0, "velocity_fps": 1.0, "source": "crest"}]),
                         CHARTS, HT, CFT)
    assert no_review["points"] == [] and len(no_review["unverified"]) == 1


def test_report_links_and_embeds_the_chart_and_says_unverified():
    if not _have_mpl():
        return
    tmp = tempfile.mkdtemp(prefix="dvchart_")
    recs = _recs()
    res = run(preset("ND"), recs, scenario="S3")
    ch = D.build(recs, CHARTS, {"dam_id": "ND00000", "dam_name": "Synthetic Dam", "source": "Runner",
                                "run_date": "2026-11-12"}, tmp, habitable_types=HT, chart_for_type=CFT)
    for k in ("png", "csv", "unverified_csv"):
        ch[k] = os.path.basename(ch[k])
    res["dv_charts"] = [ch]
    md = report.markdown(res, CAT)
    assert report.DV_SECTION in md and "![" in md and D.CHART_NAME + ".png" in md and D.CHART_NAME + ".csv" in md
    assert D.CHART_NAME + "_unverified.csv" in md and "Unverified wet structures, not plotted: 3" in md
    html = report.html_report(res, CAT, base_dir=tmp)
    assert "<img" in html and "data:image/png;base64," in html
    assert "src='" + D.CHART_NAME + ".png'" not in html                  # embedded, not linked
    res.pop("dv_charts")
    assert report.DV_SECTION not in report.markdown(res, CAT)


if __name__ == "__main__":
    unittest.main()
