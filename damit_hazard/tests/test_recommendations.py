"""Decisions on DamIT PR #5's open questions (DamIT Catalog 2026.11.09.3), as DamIT Hazard applies them.

1. USBR M1 marks lives in jeopardy; M5 sets the class (1-6 Significant, 7 or more High). The rule is
   in DamIT Catalog's presets.json (USBR M1 class_zones []), not in a Hazard-only override.
2. M3 institutions: Significant / Low split at the foundation ground line, High test at the lowest
   floor (datums read from the catalog's M3 rules).
3. Preset status (NRCS unverified, NY draft) is read from presets.json 'status'; methods stay as
   documented.
"""
import json
import os
import shutil
import tempfile

from _helpers import CAT, C, R, report, run, preset, home, methods_hit


def test_usbr_m1_rule_comes_from_the_catalog():
    src = C.source()
    assert src.presets["USBR"]["methods"]["M1"]["class_zones"] == []
    assert "methods" not in (src.hazard["presets"].get("USBR") or {})      # no Hazard-only override
    p = CAT["presets"]["USBR"]["methods"]["M1"]
    assert p["high_class"] is None and p["above_low_class"] is None
    assert CAT["presets"]["USBR"]["methods"]["M5"]["sig_min"] == src.presets["USBR"]["methods"]["M5"]["sig_min"]
    # ND keeps the document's general M1 rule: high-danger zone -> High
    assert CAT["presets"]["ND"]["methods"]["M1"]["high_class"] == 3


def test_usbr_m1_does_not_assign_high_alone_m5_sets_class():
    for n, want in ((1, 2), (6, 2), (7, 3)):
        res = run(preset("USBR"), [home("h", depth=6.5, vel=1.0, occupants=n)])
        assert res["suggested_class"] == want, (n, res["suggested_class"])
        assert "M1" not in methods_hit(res), n
        assert [h["method"] for h in res["driving"]] == ["M5"], n
    recs = [home("a", depth=6.5, vel=1.0, occupants=4), home("b", depth=6.5, vel=1.0, occupants=3)]
    assert run(preset("USBR"), recs)["suggested_class"] == 3


def _school(found, floor, ground=None, dv=1.0, rid="s", t="school"):
    """A school: depth above its foundation ground line and above its lowest occupied floor."""
    g = found if ground is None else ground
    wse = 100.0 + g
    return R.make(rid, "structure", t, depth_ft=g, velocity_fps=0.1, dv_ft2s=dv, wse_ft=wse,
                  ground_elev=100.0, foundation_elev=wse - found, floor_elev=wse - floor)


def _m3(rec, pid="NE", mid="M3", scenario="S4"):
    res = run(preset(pid), [rec], scenario=scenario)
    return max([h["class"] for h in res["hits"] if h["method"] == mid] or [None])


def test_m3_institution_split_at_foundation_high_at_floor():
    rows = CAT["methods"]["M3"]["params"]["rows"]
    assert (rows["institution"]["datum"], rows["institution"]["high_datum"]) == ("foundation", "floor")
    for r in ("home", "commercial"):
        assert rows[r]["datum"] == rows[r]["high_datum"] == "foundation", r
    assert rows["campground"]["datum"] == rows["campground"]["high_datum"] == "ground"
    assert rows["unoccupied_farm"]["datum"] == "foundation"
    assert CAT["methods"]["M10b"]["params"]["rows"]["institution"]["high_datum"] == "floor"
    # the thresholds are the catalog's (2 ft / DV 15), unchanged
    src = C.source()
    assert rows["institution"]["high_depth_ft"] == src.methods["M3"]["params"]["institution_high_depth_ft"]
    assert rows["institution"]["high_dv"] == src.methods["M3"]["params"]["institution_high_dv"]
    hz_rows = src.hazard["methods"]["M3"]["params"]["rows"]
    assert all("datum" not in r for r in hz_rows.values())          # datums come from the catalog rules
    assert _m3(_school(1.0, -0.5)) == 2       # above the foundation, below the floor: Significant (was Low)
    assert _m3(_school(0.0, -1.5, ground=0.3)) == 1
    assert _m3(_school(3.0, 1.9)) == 2        # 3 ft at the foundation, under 2 ft at the floor: not High
    assert _m3(_school(3.5, 2.0)) == 3
    assert _m3(_school(0.5, -1.0, dv=15.0)) == 3
    res = run(C.custom_config(CAT, ["M10b"]), [_school(3.0, 1.9, t="hospital")])
    assert max(h["class"] for h in res["hits"] if h["method"] == "M10b") == 2
    res = run(C.custom_config(CAT, ["M10b"]), [_school(1.0, -0.5, t="hospital")])
    assert max(h["class"] for h in res["hits"] if h["method"] == "M10b") == 2


def test_preset_status_read_from_catalog():
    src = C.source()
    for pid in ("NRCS", "NY"):
        assert CAT["presets"][pid]["verification"] == src.presets[pid]["status"], pid
        assert "verification" not in (src.hazard["presets"].get(pid) or {}), pid
    assert (src.presets["NRCS"]["status"], src.presets["NY"]["status"]) == ("unverified", "draft")
    assert CAT["presets"]["ND"]["verification"] == "verified"
    for mid, m in CAT["methods"].items():           # no method-level draft marks (catalog: as documented)
        assert m["verification"] == "verified", mid
    res = run(preset("NY"), [home("h", depth=0.5, floor_height_ft=0.0)])
    assert "(draft)" in report.markdown(res, CAT)
    tmp = tempfile.mkdtemp(prefix="damit_hz_status_")
    try:
        d = os.path.join(tmp, "data")
        shutil.copytree(src.folder, d)
        path = os.path.join(d, "presets.json")
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        p["presets"]["NY"].pop("status")
        p["presets"]["ND"]["status"] = "draft"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p, f)
        cat = C.load(d)
        assert cat["presets"]["NY"]["verification"] == "verified"
        assert cat["presets"]["ND"]["verification"] == "draft"
        assert dict(C.preset_choices(cat))["ND"].endswith("(draft)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ny_r2_r8_variants_come_from_the_catalog():
    src = C.source()
    assert "R2" not in src.hazard["modifiers"] and "params" not in src.hazard["modifiers"]["R8"]
    ny = CAT["presets"]["NY"]["modifiers"]
    assert ny["R2"]["floor_presumption"] is True and ny["R8"]["variant"] == "lowering_from_high"
    nd = CAT["presets"]["ND"]["modifiers"]
    assert nd["R2"]["floor_presumption"] is False and nd["R8"]["variant"] == "storage_limit"
    res = run(preset("NY"), [home("h", depth=0.5, vel=0.1)], dam={"current_class": 3,
                                                                  "analysis": "breach_model"})
    assert res["suggested_class"] == 3 and "R8" in [h["method"] for h in res["driving"]]
    res = run(preset("NY"), [home("h", depth=0.5, vel=0.1)], dam={"current_class": 3,
                                                                  "analysis": "unsteady_tm11"})
    assert res["suggested_class"] < 3
