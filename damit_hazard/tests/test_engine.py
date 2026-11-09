"""QGIS-free tests of the combination logic, the presets and the method evaluators.

    python3 damit_hazard/tests/run_tests.py      (or: python3 -m pytest damit_hazard/tests)
"""
from _helpers import (CAT, C, R, core, report, run, preset, custom, home, road, rail, codes,
                      methods_hit)


# ---------------------------------------------------------------- combination logic --------
def test_highest_rule_wins_and_advisory_is_opt_in():
    cfg = custom(["M4a", "M6"], overrides={"M4a": {"min_count": 1}})
    recs = [home("a", depth=3.0, vel=0.5)]
    res = run(cfg, recs)
    # M4a is advisory in the catalog (High); M6 a rule (Significant)
    assert res["suggested_class"] == 2
    assert "M4a" in methods_hit(res, 3, "advisory")
    assert res["class_with_advisory"] == 3 and "advisory_only" in codes(res)
    assert [h["method"] for h in res["driving"]] == ["M6"]
    res2 = run(custom(["M4a", "M6"], overrides={"M4a": {"min_count": 1}}, apply_advisory=True),
               [home("a", depth=3.0, vel=0.5)])
    assert res2["suggested_class"] == 3 and res2["driving"][0]["method"] == "M4a"


def test_most_severe_scenario_governs_and_driving_reported():
    cfg = preset("ND")
    s3 = {"scenario": "S3", "model_dim": "2D", "label": "a", "breach_location": "left",
          "receptors": [home("h1", depth=1.0, vel=1.0)]}
    s7 = {"scenario": "S7", "model_dim": "2D", "label": "b", "breach_location": "right",
          "receptors": [home("h1", depth=6.5, vel=1.0)]}
    res = core.classify(CAT, cfg, [s3, s7])
    assert [p["class"] for p in res["per_scenario"]] == [1, 3]
    assert res["suggested_class"] == 3 and res["suggested_label"] == "High"
    d = res["driving"][0]
    assert d["method"] == "M1" and d["receptors"] == ["h1"] and d["scenario"] == "S7"


def test_no_hit_gives_base_class_with_flag():
    res = run(custom(["M2"]), [home("dry", depth=0.0)])
    assert res["suggested_class"] == 1 and "no_rule_hit" in codes(res)


# ---------------------------------------------------------------- North Dakota -------------
def test_nd_m1_high_danger_is_high():
    res = run(preset("ND"), [home("h", depth=6.5, vel=1.0)], scenario="S3")
    assert res["suggested_class"] == 3 and res["suggested_label"] == "High"
    assert "M1" in methods_hit(res, 3, "rule")


def test_nd_judgment_flagged_not_promoted():
    res = run(preset("ND"), [home("h", depth=4.0, vel=1.0)], scenario="S3")
    assert "judgment_zone" in codes(res, "warning")
    assert "M1" not in methods_hit(res, 3)
    # M6 (advisory in ND) is the only other result: not applied by default
    assert res["suggested_class"] == 1 and res["suggested_label"] == "Low"
    assert "M6" in methods_hit(res, 2, "advisory")


def test_nd_r7_options_promote_judgment():
    res = run(preset("ND", overrides={"R7": {"judgment_zone_to_high": True}}),
              [home("h", depth=4.0, vel=1.0)], scenario="S3")
    assert res["suggested_class"] == 3
    res = run(preset("ND", overrides={"R7": {"near_margin_ft": 0.5}}),
              [home("h", depth=5.6, vel=1.0)], scenario="S3")      # high line 5.968 at 1 ft/s
    assert res["suggested_class"] == 3
    res = run(preset("ND", overrides={"R7": {"near_margin_ft": 0.5}}),
              [home("h", depth=4.0, vel=1.0)], scenario="S3")
    assert res["suggested_class"] == 1


def test_nd_m2_only_when_1d_and_m1_blocked_on_1d():
    rec = [home("h", depth=2.5, vel=0.5)]
    r2d = run(preset("ND"), rec, scenario="S3", dim="2D")
    assert "M2" not in methods_hit(r2d) and "m2_not_1d" in codes(r2d)
    r1d = run(preset("ND"), [home("h", depth=2.5, vel=0.5)], scenario="S3", dim="1D")
    assert "M2" in methods_hit(r1d, 3) and r1d["suggested_class"] == 3
    assert "m1_blocked_1d" in codes(r1d, "error") and "M1" not in methods_hit(r1d)
    # exactly 2 ft is not "greater than 2 ft"
    r = run(preset("ND"), [home("h", depth=2.0, vel=0.5)], scenario="S3", dim="1D")
    assert "M2" not in methods_hit(r)
    unk = run(preset("ND"), [home("h", depth=2.5)], scenario="S3", dim=None)
    assert "dim_unknown" in codes(unk, "error")


def test_nd_m6_advisory_not_applied_by_default():
    res = run(preset("ND"), [home("h", depth=0.5, vel=0.5)], scenario="S3")
    assert "M6" in methods_hit(res, 2, "advisory")
    assert res["suggested_class"] == 1
    res = run(preset("ND", apply_advisory=True), [home("h", depth=0.5, vel=0.5)], scenario="S3")
    assert res["suggested_class"] == 2 and res["suggested_label"] == "Medium"


def test_nd_m8a_aadt_bands():
    def cls(**kw):
        res = run(preset("ND"), [road("r", **kw)], scenario="S3")
        return [h["class"] for h in res["hits"] if h["method"] == "M8a"][0]
    assert cls(aadt=499) == 1
    assert cls(aadt=500) == 2           # exactly 500 is Significant
    assert cls(aadt=2000) == 2
    assert cls(aadt=2001) == 3
    assert cls(cls="interstate", aadt=100) == 3
    assert cls(cls="us_state") == 2
    assert cls(cls="private", aadt=100) == 1
    res = run(preset("ND"), [road("r")], scenario="S3")
    assert "m8a_unknown" in codes(res, "warning")


def test_nd_m8b_m9a_m11a_and_labels():
    recs = [road("r", cls="county", aadt=50, sole_access=True),
            rail("x", trains_per_day=3), rail("y", trains_per_day=12), rail("z", passenger=True),
            R.make("p", "lifeline", "power_line", depth_ft=0.3)]
    res = run(preset("ND"), recs, scenario="S3")
    assert "M8b" in methods_hit(res, 2)
    m9 = {h["receptors"][0]: h["class"] for h in res["hits"] if h["method"] == "M9a"}
    assert m9 == {"x": 2, "y": 3, "z": 3}
    assert "M11a" in methods_hit(res, 2)
    cfg = preset("ND")
    assert [cfg["labels"][i] for i in (1, 2, 3)] == ["Low", "Medium", "High"]


def test_nd_r8_simplified_storage_limit():
    dam = {"analysis": "simplified", "storage_acft": 250}
    res = run(preset("ND"), [home("h", depth=0.2)], scenario="S3", dam=dam)
    assert res["suggested_class"] == 3 and "r8_storage" in codes(res, "error")
    dam = {"analysis": "simplified", "storage_acft": 150}
    assert run(preset("ND"), [home("h", depth=0.2)], scenario="S3",
               dam=dam)["suggested_class"] == 1


def test_nd_r4_dams_in_series_is_advisory():
    res = run(preset("ND"), [home("h", depth=0.0)], scenario="S3",
              dam={"downstream_dam_classes": ["High"]})
    assert res["suggested_class"] == 1 and res["class_with_advisory"] == 3
    res = run(preset("NE"), [home("h", depth=0.0)], scenario="S4",
              dam={"downstream_dam_classes": ["High"]})
    assert res["suggested_class"] == 3            # Nebraska: rule


# ---------------------------------------------------------------- FEMA / USBR / BIA --------
def test_fema_m5_high_min_1():
    res = run(preset("FEMA333"), [home("h", depth=6.5, vel=1.0, occupants=1)])
    assert res["suggested_class"] == 3 and "M5" in methods_hit(res, 3)


def test_fema_r1_transients_do_not_force_high():
    recs = [R.make("c", "structure", "campground", depth_ft=6.5, velocity_fps=1.0,
                   occupancy="day_use", occupants=5)]
    res = run(preset("FEMA333"), recs)
    assert "M5" not in methods_hit(res, 3) and "r1_excluded" in codes(res)
    # without R1 the same people would count
    res = run(custom(["M5"]), [R.make("c", "structure", "home", depth_ft=6.5,
                                      velocity_fps=1.0, occupancy="day_use", occupants=5)])
    assert res["suggested_class"] == 3


def test_usbr_m5_bands_and_all_five_charts():
    def at(n_people):
        recs = [home("h", depth=6.5, vel=1.0, occupants=n_people)]
        return run(preset("USBR"), recs)["suggested_class"]
    assert at(1) == 2 and at(6) == 2 and at(7) == 3
    # M1 by itself does not set High in this preset (TM-11's lives count does)
    res = run(preset("USBR"), [home("h", depth=6.5, vel=1.0, occupants=3)])
    assert "M1" not in methods_hit(res, 3) and "M5" in methods_hit(res, 2)
    # all five charts callable: two digitized, three flagged; a supplied curve is read
    from damit_hazard.engine import tm11
    ch = tm11.load()
    assert ch.zone("houses", 6.5, 1.0) == "high" and ch.zone("mobile_homes", 1.0, 1.0) == "low"
    for cid in ("passenger_vehicles", "adults", "children"):
        try:
            ch.zone(cid, 1.0, 1.0)
            raise AssertionError("should not be digitized")
        except tm11.ChartNotDigitized:
            pass
    recs = [R.make("car", "road", "us_state", depth_ft=1.0, velocity_fps=2.0),
            R.make("camp", "structure", "campground", depth_ft=1.0, velocity_fps=2.0)]
    res = run(preset("USBR"), recs)
    nd = [f for f in res["flags"] if f["code"] == "chart_not_digitized"]
    assert {r for f in nd for r in f["receptors"]} == {"car", "camp"}
    synth = {"adults": {"v_fts": [0, 10], "low_ft": [0.5, 0.1], "high_ft": [1.0, 0.2],
                        "v_max_fts": 10, "d_max_ft": 5}}
    ch2 = tm11.load(extra=synth)
    assert ch2.zone("adults", 1.5, 0.0) == "high" and ch2.zone("adults", 0.7, 0.0) == "judgment"


def test_bia_is_secondary():
    assert CAT["presets"]["BIA"]["verification"] == "secondary"
    assert any("(secondary)" in lab for pid, lab in C.preset_choices(CAT) if pid == "BIA")


# ---------------------------------------------------------------- other methods ------------
def test_m3_nebraska_matrix():
    def c(t, d, v=0.0, **kw):
        res = run(preset("NE"), [R.make("s", "structure", t, depth_ft=d, velocity_fps=v,
                                        **kw)], scenario="S4")
        return max([h["class"] for h in res["hits"] if h["method"] == "M3"] or [None])
    assert c("home", 3.4, 1.0) == 2 and c("home", 3.5, 0.1) == 3 and c("home", 1.0, 20.0) == 3
    assert c("school", 1.9, 1.0, floor_height_ft=0.0) == 2
    assert c("school", 2.0, 0.1, floor_height_ft=0.0) == 3
    assert c("hospital", 1.0, 15.0, floor_height_ft=0.0) == 3
    assert c("commercial", 0.9, 1.0) == 1 and c("commercial", 1.0, 1.0) == 2
    assert c("industrial", 3.5, 0.1) == 3
    assert c("campground", 0.9, 1.0, nights_per_year=60) == 1
    assert c("campground", 1.0, 8.0, nights_per_year=60) == 3
    assert c("barn", 2.0, 1.0) == 1
    # walkout option
    cfg = preset("NE", overrides={"M3": {"walkout_option": True}})
    res = run(cfg, [R.make("w", "structure", "home", depth_ft=4.0, velocity_fps=1.0,
                           walkout=True)], scenario="S4")
    assert max(h["class"] for h in res["hits"] if h["method"] == "M3") == 2
    # missing floor elevation: institutions fall back to ground depth with a warning
    res = run(preset("NE"), [R.make("s", "structure", "school", depth_ft=1.0,
                                    velocity_fps=1.0)], scenario="S4")
    assert "floor_fallback" in codes(res, "warning")


def test_m4c_texas():
    def c(recs, dam=None):
        return run(preset("TX"), recs, dam=dam)["suggested_class"]
    assert c([home("a", depth=0.2, occupants=2)]) == 2
    assert c([home("a", depth=0.2, occupants=2), home("b", depth=0.2, occupants=2)]) == 2
    assert c([home(x, depth=0.2, occupants=1) for x in "abc"]) == 3
    assert c([home("a", depth=0.2, occupants=7)]) == 3
    assert c([home("a", depth=0.2, occupants=6)]) == 2
    # R5 for Texas: existing development only
    assert c([home("f", depth=0.2, occupants=9, future=True)]) == 1


def test_m7_california_extremely_high():
    recs = [home("h", depth=6.5, vel=1.0, occupants=2)]
    assert run(preset("CA"), recs)["suggested_class"] == 3
    res = run(preset("CA"), [home("h", depth=6.5, vel=1.0, occupants=2)],
              dam={"population_inundation": 1500})
    assert res["suggested_class"] == 4 and res["suggested_label"] == "Extremely High"
    recs = [home("h", depth=6.5, vel=1.0, occupants=2),
            R.make("hosp", "facility", "hospital", depth_ft=0.5, public_safety_threat=True)]
    assert run(preset("CA"), recs)["suggested_class"] == 4
    recs = [home("h", depth=0.5, vel=1.0, occupants=2)]          # no life loss
    assert run(preset("CA"), recs, dam={"population_inundation": 5000})["suggested_class"] < 4


def test_m8_m9_key_bands():
    cfg = custom(["M8c", "M9b", "M8d"])
    recs = [road("i", cls="interstate", depth=1.0), road("i2", cls="interstate", depth=2.0),
            road("s", cls="us_state", depth=1.9, lanes=2), road("s2", cls="us_state", depth=2.0,
                                                                lanes=2),
            road("loc", cls="other_public", depth=3.0, func_class="local"),
            rail("m", depth=1.0, trains_per_day=5), rail("m2", depth=2.0, trains_per_day=5),
            rail("n", depth=1.0, trains_per_day=4), rail("n2", depth=2.5, trains_per_day=4)]
    res = run(cfg, recs)
    got = {(h["method"], h["receptors"][0]): h["class"] for h in res["hits"]}
    assert got[("M8c", "i")] == 2 and got[("M8c", "i2")] == 3
    assert got[("M8c", "s")] == 1 and got[("M8c", "s2")] == 2 and got[("M8c", "loc")] == 1
    assert got[("M9b", "m")] == 2 and got[("M9b", "m2")] == 3
    assert got[("M9b", "n")] == 1 and got[("M9b", "n2")] == 2
    assert got[("M8d", "loc")] == 1
    res = run(custom(["M8d"]), [road("a", func_class="interstate", aadt=399)])
    assert res["hits"][0]["class"] == 1                     # AADT 400 or less: minor road
    res = run(custom(["M9c"]), [rail("a", freight_class="Class 1"), rail("b", line_category=
                                                                         "tourist")])
    got = {h["receptors"][0]: h["class"] for h in res["hits"]}
    assert got == {"a": 3, "b": 2}


def test_m4b_new_york_table():
    def ny(recs):
        return run(preset("NY"), recs, extra_runs=[])["suggested_class"]
    assert ny([home("a", depth=0.5, vel=0.5, floor_height_ft=0.0)]) == 1
    assert ny([home("a", depth=1.5, vel=0.5, floor_height_ft=0.0)]) == 2
    assert ny([home(str(i), depth=0.5, vel=0.5, floor_height_ft=0.0) for i in range(11)]) == 2
    assert ny([home(str(i), depth=0.2, vel=0.5, floor_height_ft=0.0) for i in range(100)]) == 3
    assert ny([home("a", depth=4.0, vel=1.0, floor_height_ft=0.0)]) == 3      # above Low Danger


def test_virginia_low_volume_and_wording():
    recs = [road("a", cls="other_public", aadt=150), road("b", cls="other_public", aadt=200)]
    res = run(preset("VA"), recs)
    assert res["suggested_class"] == 1 and "M8e" in methods_hit(res, 1)
    recs = [road("a", cls="other_public", aadt=300), road("b", cls="other_public", aadt=200)]
    res = run(preset("VA"), recs)
    assert "m8e_sum" in codes(res) and "M13" in methods_hit(res, 2)
    res = run(preset("VA"), [home("h", depth=0.3, descriptor="residence")])
    assert res["suggested_class"] == 3


def test_missing_inputs_are_flagged():
    # no velocity: M1 cannot be scored
    res = run(preset("ND"), [R.make("h", "structure", "home", depth_ft=5.0)], scenario="S3")
    assert "no_velocity" in codes(res, "error")
    # no road layer for a road method
    res = run(preset("ND"), [home("h", depth=0.0)], scenario="S3")
    assert "no_layer" in codes(res, "warning")
    # scenario missing / S7 needs several locations
    assert {"scenario_missing", "s7_locations"} <= codes(res)
    # a receptor without hydraulics
    res = run(custom(["M6"]), [R.make("x", "structure", "home")])
    assert "no_hydraulics" in codes(res)
    # receptor outside the routed domain
    res = run(custom(["M6"]), [home("o", depth=1.0, in_domain=False)])
    assert "outside_domain" in codes(res) and res["suggested_class"] == 1
    # M12d is never a silent pass
    res = run(preset("AZ"), [R.make("e", "environment", "wetland", depth_ft=1.0,
                                    agency_identified=True)])
    assert "m12d_intangible" in codes(res)
    # Colorado M6 variant needs a damage state
    res = run(preset("CO"), [home("h", depth=0.5)], scenario="S2")
    assert "m6_damage_unknown" in codes(res)


def test_every_method_runs_without_error():
    recs = [home("h", depth=3.0, vel=2.0, occupants=3), road("r", cls="us_state", aadt=900),
            rail("t", trains_per_day=6),
            R.make("f", "facility", "hospital", depth_ft=1.5, isolated=True),
            R.make("l", "lifeline", "wastewater", depth_ft=1.0, ww_class="major"),
            R.make("e", "environment", "archaeological", depth_ft=1.0, mitigation="major",
                   anadromous=True, substantial=True)]
    cfg = custom(list(CAT["methods"]), modifiers=list(CAT["modifiers"]),
                 scenarios=["S1"], domains=["D1", "D2"])
    res = run(cfg, recs, dam={"current_class": 2, "is_new": False})
    assert res["suggested_class"] >= 3


# ---------------------------------------------------------------- reports ------------------
JURISDICTIONS = ("North Dakota", "Nebraska", "New York", "Virginia", "Texas", "Idaho",
                 "Colorado", "Rhode Island", "Arizona", "California", "Alaska", "FEMA", "USBR",
                 "Reclamation", "BIA", "NRCS", "REG_05", "NYCRR", "TOGS", "TAC", "CCR", "AAC",
                 "IDAPA", "4VAC", "RICR", "NeDNR", "DWEE")


def test_custom_report_has_no_jurisdiction_names_in_method_list():
    cfg = custom(list(CAT["methods"]), modifiers=list(CAT["modifiers"]), scenarios=["S1"])
    res = run(cfg, [home("h", depth=1.0)])
    secs = dict(report.sections(res, CAT))
    _t, hdr, rows = secs["Methods"]
    text = " ".join(" ".join(str(c) for c in r) for r in rows) + " ".join(hdr)
    _t, _h, mrows = secs["Modifiers"]
    text += " ".join(" ".join(str(c) for c in r) for r in mrows)
    for j in JURISDICTIONS:
        assert j.lower() not in text.lower(), j
    assert "Verification" not in hdr
    # the citations still name the sources
    assert any("Nebraska" in c for c in secs["Citations"])
    md = report.markdown(res, CAT)
    assert "Disclaimer" in md and "not a regulatory determination" in md
    html = report.html_report(res, CAT)
    assert "<table>" in html
    assert report.as_json(res).startswith("{")


def test_preset_report_marks_verification():
    res = run(preset("NY"), [home("h", depth=0.5, floor_height_ft=0.0)])
    md = report.markdown(res, CAT)
    assert "(draft)" in md and "Class A" in md
    res = run(preset("NRCS"), [home("h", depth=0.5)])
    assert "(unverified)" in report.markdown(res, CAT)


# ---------------------------------------------------------------- DAM_JSON contract --------
def test_flat_dam_record_contract():
    """damit:classify's DAM_JSON stays a flat record (storage_acft, current_class ordinal 0-4,
    is_new, analysis, name, ...), read the same with presets from DamIT Catalog."""
    dam = {"name": "Test Dam", "storage_acft": 250, "current_class": 1, "is_new": False,
           "analysis": "simplified"}
    res = run(preset("ND"), [home("h", depth=0.2, vel=0.1)], scenario="S3", dim="2D", dam=dam)
    assert res["suggested_class"] == 3 and "r8_storage" in codes(res)
    dam = dict(dam, storage_acft=50)
    res = run(preset("ND"), [home("h", depth=0.2, vel=0.1)], scenario="S3", dim="2D", dam=dam)
    assert "r8_storage" not in codes(res)
    # S6 picks its condition from the ordinal (Rhode Island)
    res = run(preset("RI"), [], scenario="S6", dam={"current_class": 3, "is_new": False})
    assert "s6_condition" in codes(res) and "s6_class" not in codes(res)
    res = run(preset("RI"), [], scenario="S6", dam={"is_new": True})
    assert "s6_condition" in codes(res)
    res = run(preset("RI"), [], scenario="S6", dam={})
    assert "s6_class" in codes(res)


def test_usbr_alias_classifies_the_same():
    recs = [home("h{}".format(i), depth=6.5, vel=1.0, occupants=1) for i in range(3)]
    a, b = run(preset("USBR"), recs), run(preset("USBR_TM11"), recs)
    assert a["suggested_class"] == b["suggested_class"]
    assert a["config"]["preset"] == b["config"]["preset"] == "USBR"
