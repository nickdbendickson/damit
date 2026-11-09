"""The catalog covers every Appendix A ID and every A.6 preset; thresholds live in the data."""
import json
import os
import re

from _helpers import CAT, C, ROOT

SCEN = ["S{}".format(i) for i in range(1, 8)]
DOMAINS = ["D1", "D2"]
METHODS = ["M1", "M2", "M3", "M4a", "M4b", "M4c", "M5", "M6", "M7",
           "M8a", "M8b", "M8c", "M8d", "M8e", "M8f", "M8g", "M9a", "M9b", "M9c",
           "M10a", "M10b", "M11a", "M11b", "M11c", "M12a", "M12b", "M12c", "M12d", "M13"]
MODS = ["R{}".format(i) for i in range(1, 11)]
PRESETS = {  # Appendix A.6: preset -> (scenarios, methods, modifiers, labels)
    "FEMA333": (["S1"], ["M5", "M13"], ["R1", "R3"], ["Low", "Significant", "High"]),
    "USBR": (["S1"], ["M1", "M5"], ["R1"], ["Low", "Significant", "High"]),
    "BIA": ([], ["M5"], [], ["Low", "Significant", "High"]),
    "NRCS": ([], ["M13"], ["R5"], ["Low", "Significant", "High"]),
    "ND": (["S3", "S7"], ["M1", "M2", "M6", "M8a", "M8b", "M9a", "M11a"],
           ["R2", "R3", "R4", "R5", "R7", "R8", "R9"], ["Low", "Medium", "High"]),
    "NE": (["S4"], ["M3", "M4a", "M8c", "M9b", "M11b", "M12a"], ["R4", "R5", "R6"],
           ["Minimal", "Low", "Significant", "High"]),
    "NY": (["S1", "S5"], ["M1", "M4b", "M8d", "M8f", "M9c", "M10a", "M11c", "M12b"],
           ["R1", "R2", "R4", "R8"], ["Class A", "Class B", "Class C"]),
    "VA": (["S1", "S5"], ["M13", "M8e", "M5"], ["R5", "R9"], ["Low", "Significant", "High"]),
    "TX": ([], ["M4c"], ["R5"], ["Low", "Significant", "High"]),
    "ID": ([], ["M2", "M6"], [], ["Low", "Significant", "High"]),
    "CO": (["S2"], ["M5", "M6"], ["R10"], ["No Public Hazard", "Low", "Significant", "High"]),
    "RI": (["S6"], ["M13", "M8g"], ["R1", "R10"], ["Low", "Significant", "High"]),
    "AZ": ([], ["M13", "M12d"], ["R1", "R5", "R10"], ["Very Low", "Low", "Significant",
                                                      "High"]),
    "CA": ([], ["M5", "M7"], [], ["Low", "Significant", "High", "Extremely High"]),
    "AK": ([], ["M5", "M12c", "M13"], [], ["Class III", "Class II", "Class I"]),
}


def test_every_id_catalogued():
    assert sorted(CAT["scenarios"]) == sorted(SCEN)
    assert sorted(CAT["domains"]) == sorted(DOMAINS)
    assert sorted(CAT["methods"]) == sorted(METHODS)
    assert sorted(CAT["modifiers"], key=lambda x: int(x[1:])) == MODS
    assert C.validate(CAT) == []
    for mid, m in CAT["methods"].items():
        assert m["verification"] in CAT["verification_legend"], mid
        assert m["strength"] in ("rule", "advisory")


def test_every_preset_matches_a6():
    assert sorted(CAT["presets"]) == sorted(PRESETS)
    for pid, (sc, ms, mods, labels) in PRESETS.items():
        p = CAT["presets"][pid]
        assert p["scenarios"] == sc, pid
        assert sorted(p["methods"]) == sorted(ms), pid
        assert sorted(p["modifiers"]) == sorted(mods), pid
        got = [p["labels"][k] for k in sorted(p["labels"], key=int)]
        assert got == labels, (pid, got)
    nd = CAT["presets"]["ND"]
    assert nd["methods"]["M1"] == {"charts": ["houses", "mobile_homes"], "require_2d": True}
    assert nd["methods"]["M2"]["only_if_1d"] is True
    assert nd["methods"]["M6"]["strength"] == "advisory"
    assert nd["modifiers"]["R4"]["strength"] == "advisory"
    assert CAT["presets"]["NE"]["modifiers"]["R4"]["strength"] == "rule"
    assert CAT["presets"]["NY"]["domains"] == ["D1"]
    assert CAT["presets"]["VA"]["domains"] == ["D2"]
    assert "unverified" in CAT["presets"]["USBR"]["optional_scenarios"]["S5"]
    assert CAT["presets"]["BIA"]["verification"] == "secondary"


def test_thresholds_from_the_document():
    m = CAT["methods"]
    assert m["M8a"]["params"]["low_below_aadt"] == 500 and m["M8a"]["params"][
        "high_above_aadt"] == 2000
    assert m["M3"]["params"]["rows"]["home"]["high_depth_ft"] == 3.5
    assert m["M3"]["params"]["rows"]["institution"]["high_dv"] == 15.0
    assert m["M3"]["params"]["rows"]["campground"]["high_dv"] == 8.0
    assert m["M4a"]["params"] == {"min_count": 20, "depth_ft": 2.0, "depth_datum": "foundation"}
    assert m["M4c"]["params"]["lives_high_min"] == 7
    assert m["M7"]["params"]["min_population"] == 1000
    assert m["M8e"]["params"]["limited_use_max_aadt"] == 400
    assert m["M9a"]["params"]["high_min_trains_per_day"] == 10
    assert m["M9b"]["params"]["main_min_trains_per_day"] == 5
    assert CAT["modifiers"]["R8"]["params"]["storage_limit_acft"] == 200


def test_no_threshold_literals_in_evaluators():
    """Every number a rule uses comes from catalog.json: the evaluator code compares with
    parameters, never with a literal threshold (0 and 1 aside)."""
    src = open(os.path.join(ROOT, "damit_hazard", "engine", "core.py"), encoding="utf-8").read()
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    code = re.sub(r'"[^"\n]*"', '""', code)
    bad = [n for n in re.findall(r"(?<![\w.])(\d+\.\d+|\d+)(?![\w.])", code)
           if n not in ("0", "1", "0.0", "1.0", "2", "3", "4")]
    assert bad == [], bad


def test_catalog_json_is_utf8_and_loads():
    path = os.path.join(ROOT, "damit_hazard", "data", "catalog.json")
    with open(path, encoding="utf-8") as f:
        json.load(f)
