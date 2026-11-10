"""DamIT Hazard follows DamIT Catalog 2026.11.09.4: the In-Depth Summaries (Nov. 2026) presets and
corrections, read from the catalog (no Hazard-only rules), with Nick's M1 / M3 / status decisions kept."""
from _helpers import CAT, C, R, codes, home, methods_hit, preset, road, run

NEW = {"AL": "High", "NC": "Class C", "USACE": "High", "TVA": "High"}


def test_new_presets_from_the_catalog():
    src = C.source()
    for pid in NEW:
        assert pid in src.presets and pid in CAT["presets"], pid
        p = CAT["presets"][pid]
        assert sorted(p["methods"]) == ["M13", "M5"], pid
        assert p["methods"]["M5"]["high_min"] == 1 and p["methods"]["M5"]["sig_min"] is None, pid
        assert p["method_fallback"] is True, pid
        assert p["scenarios"] == [], pid
    assert CAT["presets"]["USACE"]["verification"] == "secondary"
    assert dict(C.preset_choices(CAT))["USACE"].endswith("(secondary)")
    for pid in ("FERC", "USFWS", "MSHA"):
        assert C.canonical_preset(CAT, pid) is None, pid


def test_new_presets_classify_and_flag_the_fallback():
    for pid, label in NEW.items():
        res = run(preset(pid), [home("h", depth=6.5, vel=2.0, occupants=1)])
        assert res["suggested_class"] == 3 and res["suggested_label"] == label, pid
        assert "M5" in methods_hit(res, 3), pid
        assert "method_fallback_m13" in codes(res), pid
    for pid in ("FEMA333", "ND", "TX"):           # presets with confirmed methods are not flagged
        assert "method_fallback_m13" not in codes(run(preset(pid), [home("h", depth=0.5)])), pid
    nc = run(preset("NC"), [R.make("f", "structure", "home", depth_ft=0.3, velocity_fps=0.2, occupants=0,
                                   descriptor="isolated_home")])
    assert nc["suggested_label"] == "Class B"


def test_texas_m13_economic_loss():
    assert CAT["presets"]["TX"]["methods"]["M13"]["wording"] == "texas_30TAC299.14"
    res = run(preset("TX"), [road("r", "us_state", descriptor="secondary_highway")])
    assert res["suggested_class"] == 2 and "M13" in methods_hit(res, 2, "rule")
    res = run(preset("TX"), [R.make("c", "structure", "commercial", depth_ft=1.0, velocity_fps=1.0,
                                    descriptor="excessive_economic_loss_urban")])
    assert res["suggested_class"] == 3
    assert run(preset("TX"), [home("h", depth=1.0, occupants=7)])["suggested_class"] == 3
    assert run(preset("TX"), [home("h", depth=1.0, occupants=2)])["suggested_class"] == 2


def test_alaska_wording_and_anadromous():
    p = CAT["presets"]["AK"]
    assert p["methods"]["M13"]["wording"] == "alaska_11AAC93.157"
    assert "anadromous" in p["notes"] and "superseded" in p["notes"]
    res = run(preset("AK"), [road("r", "us_state", descriptor="major_highway")])
    assert res["suggested_label"] == "Class II"
    res = run(preset("AK"), [R.make("e", "environment", "anadromous", depth_ft=1.0, anadromous=True)])
    assert res["suggested_label"] == "Class II" and "M12c" in methods_hit(res, 2)
    assert run(preset("AK"), [home("h", depth=6.5, vel=2.0, occupants=1)])["suggested_label"] == "Class I"


def test_new_york_m5_single_life():
    assert CAT["presets"]["NY"]["methods"]["M5"]["high_min"] == 1
    res = run(preset("NY"), [], dam={"lives_in_jeopardy": 1})
    assert res["suggested_label"] == "Class C" and "M5" in methods_hit(res, 3)
    assert CAT["presets"]["NY"]["verification"] == "draft"


def test_nick_decisions_unchanged():
    p = CAT["presets"]["USBR"]["methods"]
    assert p["M1"]["high_class"] is None and p["M1"]["above_low_class"] is None
    assert (p["M5"]["sig_min"], p["M5"]["high_min"]) == (1, 7)
    rows = CAT["methods"]["M3"]["params"]["rows"]
    assert rows["institution"]["datum"] == "foundation" and rows["institution"]["high_datum"] == "floor"
    assert CAT["presets"]["NRCS"]["verification"] == "unverified"
    assert CAT["presets"]["NY"]["verification"] == "draft"


def test_sources_in_the_report():
    assert CAT["catalog_version"] == "2026.11.10.1"
    assert "Corrected Edition" in CAT["source_document"]
    assert "In-Depth Summaries" in CAT["source_document"]
    res = run(preset("AL"), [home("h", depth=0.5)])
    assert "In-Depth Summaries" in (res.get("source_document") or "")
