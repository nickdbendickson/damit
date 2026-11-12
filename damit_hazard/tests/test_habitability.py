"""0.4.0: NSI occtype -> suggested type, ND 911 detection, the 911 / reviewed rule, the engineer's review file, the USA
Structures cross-check, and "the class is unchanged by default". Synthetic data only (no real dam, DWR or NSI data)."""
import json
import os
import tempfile

from _helpers import CAT, CHARTS, custom, home, run
from damit_hazard.engine import core, habitability, habitable_review as HR, receptors as R, usa_structures as U

HT = CAT["habitable_types"]


def test_nsi_occtype_mapping_suffixes_and_case():
    want = {"RES1": "home", "RES1-1SWB": "home", "res1-2snb": "home", " Res1-1SWB ": "home", "RES3A": "home",
            "RES3F": "home", "RES2": "mobile_home", "RES2-1SNB": "mobile_home", "RES4": "commercial",
            "RES5": "institution", "RES6": "nursing_home", "COM1": "commercial", "COM4": "commercial",
            "COM6": "hospital", "COM10": "storage", "IND2": "industrial", "AGR1": "farm_unoccupied",
            "REL1": "institution", "GOV1": "institution", "EDU1": "school", "EDU2": "institution"}
    for occ, t in want.items():
        assert R.nsi_type(occ) == t, (occ, R.nsi_type(occ))
    for occ in ("", None, "XYZ9", "RES", "RES7", "COM", "EDU3", "123"):
        assert R.nsi_type(occ) is None, occ
    assert R.nsi_class("res1-1swb") == "RES" and R.nsi_class("AGR2") == "AGR" and R.nsi_class("zz") is None
    # every type it names is a catalog type; the habitable ones are habitable, the others are not
    types = {R.nsi_type(o) for o in want.values() if False} | set(want.values())
    assert types <= set(R.TYPE_VALUES), types - set(R.TYPE_VALUES)
    assert "farm_unoccupied" not in HT and "storage" not in HT and "mobile_home" in HT and "home" in HT
    assert all(t in HT for t in ("commercial", "institution", "school", "hospital", "nursing_home", "industrial"))


def test_occtype_only_suggests_and_is_recorded_on_the_receptor():
    r = R.from_attributes("structure:1", "structure", {"occtype": "RES2-1SNB", "bid": "q9"})
    assert r["occtype"] == "RES2-1SNB" and r["suggested_type"] == "mobile_home" and r["type"] is None
    assert r["struct_key"] == "bid:q9" and r["is_911"] is False
    assert core.reviewed_status(r, HT) == (core.STATUS_UNVERIFIED, core.BASIS_UNREVIEWED)
    r2 = R.from_attributes("structure:2", "structure", {"occtype": "ZZZ", "type": "home"})
    assert r2["type"] == "home" and r2["suggested_type"] is None and r2["occtype"] == "ZZZ"
    r3 = R.from_attributes("road:1", "road", {"type": "home"})
    assert r3["type"] == "road" and "suggested_type" not in r3


def test_911_detection_from_the_layer_and_crests_hand_off():
    cases = [({"source": "nd911"}, True), ({"source": "ND_911"}, True), ({"source": "e911"}, True),
             ({"source": "usa_structures"}, False), ({"source": "crest"}, False), ({"is_911": "yes"}, True),
             ({"nd911": 1}, True), ({"placed": "911 address point"}, True), ({"placed": "building footprint"}, False),
             ({"nguid": "ND-123"}, True), ({"nguid": ""}, False), ({"occtype": "RES1"}, False), ({}, False)]
    for a, want in cases:
        assert R.from_attributes("structure:1", "structure", dict(a))["is_911"] is want, a


def test_the_review_rule():
    s = core.reviewed_status
    assert s({"is_911": True, "type": "home"}, HT) == ("yes", core.BASIS_911)
    assert s({"is_911": True}, HT) == ("yes", core.BASIS_911)                              # a 911 point needs no type
    assert s({"is_911": True, "type": "farm_unoccupied"}, HT)[0] == "no"
    assert s({"is_911": True, "habitable": False}, HT)[0] == "no"                          # Crest's flag can only remove
    assert s({"is_911": False, "habitable": True, "type": "home", "occupancy": "overnight"}, HT)[0] == "unverified"
    assert s({"is_911": False, "reviewed_habitable": True}, HT) == ("yes", core.BASIS_REVIEWED)
    assert s({"is_911": False, "reviewed_habitable": False}, HT) == ("no", core.BASIS_REVIEWED_NOT)
    assert s({"is_911": True, "reviewed_habitable": False}, HT)[0] == "no"                 # the review wins
    assert s({"is_911": True, "reviewed_habitable": True, "type": "farm_unoccupied"}, HT)[0] == "yes"


def test_review_file_is_written_only_by_sign_off_and_read_back():
    d = tempfile.mkdtemp(prefix="hrev_")
    path = os.path.join(d, HR.REVIEW_FILE)
    assert HR.load(path) == ({}, []) and HR.find([os.path.join(d, "Depth (Max).tif")]) is None
    recs = [R.make("structure:1", "structure", None, depth_ft=1.0), R.make("structure:2", "structure", None, depth_ft=1.0)]
    recs[0]["struct_key"] = "bid:a"
    assert HR.apply(recs, {}) == 0 and recs[0]["reviewed_habitable"] is None
    for bad in (dict(keys=[], habitable=True, decided_by="E"), dict(keys=["x"], habitable=True, decided_by=" "),
                dict(keys=["x"], habitable="yes", decided_by="E"), dict(keys=["x"], habitable=True, decided_by="E",
                                                                         decided_on="12/11/2026")):
        try:
            HR.sign_off(path, **bad)
            raise AssertionError("accepted " + repr(bad))
        except ValueError:
            pass
    assert not os.path.exists(path)                                                       # nothing written by a refusal
    HR.sign_off(path, ["bid:a", "structure:2"], True, "A. Engineer", "aerial", decided_on="2026-11-12")
    HR.sign_off(path, ["structure:2"], False, "A. Engineer", "second look", decided_on="2026-11-13")
    reviews, probs = HR.load(path)
    assert probs == [] and reviews["bid:a"]["reviewed_habitable"] is True and reviews["structure:2"]["reviewed_habitable"] is False
    assert HR.find([os.path.join(d, "x", "Depth (Max).tif")]) == path                     # up the folders from a raster
    assert HR.apply(recs, reviews) == 2 and recs[0]["reviewed_habitable"] is True and recs[1]["reviewed_habitable"] is False
    assert recs[0]["review_by"] == "A. Engineer"
    data = json.load(open(path, encoding="utf-8"))
    assert data["schema"] == HR.SCHEMA and len(data["history"]) >= 2
    HR.sign_off(path, ["bid:a"], None, "A. Engineer", "undo", decided_on="2026-11-14")      # remove a review
    assert "bid:a" not in HR.load(path)[0] and len(json.load(open(path, encoding="utf-8"))["history"]) >= 3
    open(path, "w").write("{not json")
    assert HR.load(path)[0] == {} and HR.load(path)[1]
    try:
        HR.sign_off(path, ["x"], True, "E")
        raise AssertionError("overwrote a file that is not a review file")
    except (ValueError, OSError):
        pass
    open(path, "w").write(json.dumps({"schema": HR.SCHEMA, "reviews": {"k": {"reviewed_habitable": "maybe"}}}))
    assert HR.load(path)[0] == {} and "k" in HR.load(path)[1][0]


def test_review_algorithm_keys_from_text_and_csv():
    from damit_hazard.algorithms.reviewhabitable import keys_from
    d = tempfile.mkdtemp(prefix="hrev_")
    c = os.path.join(d, "w.csv")
    open(c, "w").write("id,struct_key\nstructure:1,bid:a\nstructure:2,bid:b\nstructure:3,\n")
    assert keys_from("bid:z; bid:a,\nbid:y", c) == ["bid:z", "bid:a", "bid:y", "bid:b"]
    open(c, "w").write("id\n1\n")
    try:
        keys_from("", c)
        raise AssertionError("no struct_key column")
    except ValueError:
        pass


def test_usa_structures_cross_check_inside_near_none_and_class_comparison():
    sq = lambda x, y, w: [[[(x, y), (x + w, y), (x + w, y + w), (x, y + w), (x, y)]]]          # noqa: E731
    fps = [U.footprint("f1", sq(0, 0, 10), "Residential", "Single Family Dwelling", "B1"),
           U.footprint("f2", sq(100, 0, 10), "Industrial", "Factory", None),
           U.footprint("f3", sq(200, 0, 10), "Unclassified", None, "B3")]
    pts = {"a": (5, 5, "RES"), "b": (-8, 5, "RES"), "c": (-30, 5, "RES"), "d": (105, 5, "RES"), "e": (205, 5, "COM"),
           "f": (101, 5, None)}
    out = U.cross_check(pts, fps, 12.0)
    assert out["a"]["usa_struct_match"] == "inside" and out["a"]["usa_occ_check"] == "agree"
    assert out["a"]["usa_struct_id"] == "B1" and out["a"]["usa_occ_cls"] == "Residential"
    assert out["b"]["usa_struct_match"] == "near" and out["b"]["usa_struct_dist_m"] == 8.0
    assert out["c"]["usa_struct_match"] == "none" and out["c"]["usa_occ_cls"] is None and out["c"]["usa_occ_check"] is None
    assert out["d"]["usa_occ_check"] == "differs" and out["d"]["usa_struct_id"] == "f2"
    assert out["e"]["usa_occ_check"] == "no_class"                                          # "Unclassified": no comparison
    assert out["f"]["usa_occ_check"] is None                                                # no NSI class to compare
    # a tighter tolerance; map units that are feet (0.3048 m): 8 m = 26 ft away is "near" at 30 ft, none at 20 ft
    assert U.cross_check({"b": (-8, 5, "RES")}, fps, 5.0)["b"]["usa_struct_match"] == "none"
    o = U.cross_check({"b": (-26.25, 5, "RES")}, fps, 10.0, unit_m=0.3048)["b"]
    assert o["usa_struct_match"] == "near" and 7.9 < o["usa_struct_dist_m"] < 8.1
    assert U.cross_check({"a": (1, 1, "RES")}, [], 12.0)["a"]["usa_struct_match"] == "none"   # an empty layer
    # advisory only: a match, footprint and agreeing class never make a non-911 structure habitable
    r = R.make("structure:1", "structure", None, depth_ft=2.0, velocity_fps=1.0, occtype="RES1")
    r.update(out["a"])
    assert core.reviewed_status(r, HT)[0] == core.STATUS_UNVERIFIED


def _mix():
    return [home("a", depth=2.0, is_911=True), home("b", depth=2.0, type=None, occtype="RES1", bid="b"),
            home("c", depth=2.0, is_911=True, type="farm_unoccupied")]


def test_the_class_is_unchanged_by_default_and_the_difference_is_reported():
    cfg = custom(["M6"])
    plain = run(cfg, [home("a", depth=2.0), home("b", depth=2.0, type=None), home("c", depth=2.0, type="farm_unoccupied")])
    withnew = run(cfg, _mix())
    assert withnew["habitable_rule"] == "legacy"
    assert [(h["method"], h["class"], h["receptors"]) for h in withnew["hits"]] == \
           [(h["method"], h["class"], h["receptors"]) for h in plain["hits"]]
    assert withnew["suggested_class"] == plain["suggested_class"] and any(f["code"] == "type_unknown" for f in withnew["flags"])
    # opted in: the non-911 typeless structure no longer drives M6
    rule = core.classify(CAT, cfg, [{"scenario": "S1", "model_dim": "2D", "receptors": _mix(), "label": "t"}],
                         charts=CHARTS, habitable_rule="reviewed")
    assert rule["habitable_rule"] == "reviewed"
    assert {rid for h in rule["hits"] for rid in h["receptors"]} == {"a"}
    # with only a non-911 structure the class would change: reported, never silent
    only = [home("b", depth=2.0, type=None, occtype="RES1", bid="b")]
    base = run(cfg, only)
    t = habitability.tally(only, HT)
    assert t["wet_structures"] == 1 and t["unverified"] == 1 and t["legacy_habitable"] == 1 and t["differs"] == 1
    cmp = habitability.compare(CAT, cfg, [{"scenario": "S1", "model_dim": "2D", "receptors": only, "label": "t"}],
                               CHARTS, None, None, "legacy", base)
    assert cmp["other"] == "reviewed" and cmp["class_changes"] is True and cmp["m6_receptors"] == {"applied": 1, "other": 0}
    assert only[0].get("reviewed_habitable") is None                                         # receptors were copied
    assert "habitable_rule_differs" in habitability.flag_text(t, cmp)[0] or habitability.flag_text(t, cmp)


def test_only_a_review_makes_a_non_911_structure_drive_m6_under_the_opt_in_rule():
    cfg = custom(["M6"])
    rec = home("b", depth=2.0, type=None, occtype="RES1", bid="b")
    rec["reviewed_habitable"] = True
    res = core.classify(CAT, cfg, [{"scenario": "S1", "model_dim": "2D", "receptors": [rec], "label": "t"}],
                        charts=CHARTS, habitable_rule="reviewed")
    assert {rid for h in res["hits"] for rid in h["receptors"]} == {"b"}
