"""DamIT Hazard reads DamIT Catalog: every Appendix A ID and A.6 preset, thresholds in the data."""
import configparser
import copy
import json
import os
import re
import shutil
import tempfile

from _helpers import CAT, C, ROOT, core, home, run

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
    assert nd["methods"]["M1"]["charts"] == ["houses", "mobile_homes"]
    assert nd["methods"]["M1"]["require_2d"] is True
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


def _damit_catalog():
    return C.source()


def test_no_second_catalog_in_hazard():
    """Presets and thresholds come from DamIT Catalog only: no catalog file ships with Hazard."""
    data = os.path.join(ROOT, "damit_hazard", "data")
    assert sorted(os.listdir(data)) == ["tm11_charts.json"]
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(ROOT, "damit_hazard", "metadata.txt"), encoding="utf-8")
    assert cp["general"]["plugin_dependencies"] == "DamIT Catalog"
    src = _damit_catalog()
    assert CAT["damit_catalog"]["sha256"] == src.digest
    assert CAT["catalog_version"] == src.version


def test_no_threshold_literals_in_the_catalog_bridge():
    """The translation from DamIT Catalog knows no number of any rule either."""
    for name in ("catalog.py", "catalog_bridge.py"):
        src = open(os.path.join(ROOT, "damit_hazard", "engine", name), encoding="utf-8").read()
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', '""', code)
        code = re.sub(r'"[^"\n]*"', '""', code)
        bad = [n for n in re.findall(r"(?<![\w.])(\d+\.\d+|\d+)(?![\w.])", code)
               if n not in ("0", "1", "2", "3", "4")]          # 0-4: class ordinals
        assert bad == [], (name, bad)


def test_thresholds_are_the_catalog_values():
    src = _damit_catalog()
    m, sm = CAT["methods"], src.methods
    assert m["M2"]["params"]["threshold_ft"] == sm["M2"]["params"]["depth_ft"]
    assert m["M3"]["params"]["rows"]["home"]["high_depth_ft"] == sm["M3"]["params"]["home_high_depth_ft"]
    assert m["M3"]["params"]["rows"]["campground"]["min_nights_per_year"] == \
        sm["M3"]["params"]["campground_min_nights_per_year"]
    assert m["M7"]["params"]["min_population"] == sm["M7"]["params"]["population_min"]
    assert m["M8a"]["params"]["high_above_aadt"] == sm["M8a"]["params"]["high_above_aadt"]
    assert m["M9a"]["params"]["high_min_trains_per_day"] == \
        sm["M9a"]["params"]["freight_high_trains_per_day"]
    assert m["M10b"]["params"]["rows"]["institution"]["high_dv"] == \
        sm["M10b"]["params"]["institution_high_dv"]
    assert CAT["modifiers"]["R8"]["params"]["storage_limit_acft"] == \
        src.modifiers["R8"]["params"]["storage_acft_limit"]
    assert CAT["domains"]["D2"]["params"]["max_rise_ft"] == src.domain_cutoffs["D2"]["convergence_ft"]
    # M4b / M4c bands are read from the catalog's count bands
    assert m["M4b"]["params"]["count_bands"] == [[1, 10], [11, 99], [100, None]]
    assert m["M4b"]["params"]["table"] == {"up_to_split": [1, 2, 3], "over_split": [2, 2, 3],
                                           "above_low_danger": [3, 3, 3]}
    assert (m["M4c"]["params"]["lives_sig_min"], m["M4c"]["params"]["structures_high_min"]) == (1, 3)
    # labels and preset labels are the catalog's
    assert CAT["presets"]["ND"]["label"] == src.presets["ND"]["label"]
    assert CAT["presets"]["ND"]["labels"] == src.presets["ND"]["label_map"]


def test_hazard_profile_repeats_no_catalog_value():
    """hazard.json (DamIT Catalog's engine profile for Hazard) adds structure only: none of its
    method / modifier parameters is a parameter the Appendix A files already carry."""
    src = _damit_catalog()
    hz = src.hazard
    for kind, recs in (("methods", src.methods), ("modifiers", src.modifiers)):
        for rid, h in (hz.get(kind) or {}).items():
            catalog_keys = set((recs[rid].get("params") or {}))
            catalog_keys |= set(C.RENAMES.get(rid, {}).values())
            dup = catalog_keys & set(h.get("params") or {})
            assert not dup, (rid, dup)
    for pid in hz.get("presets") or {}:
        assert src.canonical_preset_id(pid), pid


def test_edited_catalog_copy_drives_hazard():
    """DAMIT_CATALOG_DIR / a copied data folder: one edit changes what Hazard classifies with."""
    src = _damit_catalog()
    tmp = tempfile.mkdtemp(prefix="damit_hz_cat_")
    try:
        d = os.path.join(tmp, "data")
        shutil.copytree(src.folder, d)
        path = os.path.join(d, "methods.json")
        with open(path, encoding="utf-8") as f:
            methods = json.load(f)
        methods["methods"]["M2"]["params"]["depth_ft"] = 4.0
        with open(path, "w", encoding="utf-8") as f:
            json.dump(methods, f)
        cat = C.load(d)
        assert cat["methods"]["M2"]["params"]["threshold_ft"] == 4.0
        assert cat["damit_catalog"]["sha256"] != src.digest
        recs = [home("h", depth=3.0, vel=0.1)]
        res = core.classify(cat, C.custom_config(cat, ["M2"]),
                            [{"scenario": "S1", "model_dim": "1D", "receptors": recs}])
        assert "M2" not in set(h["method"] for h in res["hits"])
        old = environ = os.environ.get("DAMIT_CATALOG_DIR")
        os.environ["DAMIT_CATALOG_DIR"] = d
        try:
            assert C.load()["methods"]["M2"]["params"]["threshold_ft"] == 4.0
        finally:
            if environ is None:
                os.environ.pop("DAMIT_CATALOG_DIR", None)
            else:
                os.environ["DAMIT_CATALOG_DIR"] = old
        res = run(C.custom_config(CAT, ["M2"]), recs, dim="1D")
        assert "M2" in set(h["method"] for h in res["hits"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_old_hazard_catalog_file_is_refused():
    tmp = tempfile.mkdtemp(prefix="damit_hz_old_")
    try:
        p = os.path.join(tmp, "catalog.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "presets": {}}, f)
        try:
            C.load(p)
        except C.CatalogError as e:
            assert "DamIT Catalog" in str(e)
        else:
            raise AssertionError("a Hazard-style catalog.json was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_usbr_and_usbr_tm11_are_one_preset():
    assert "USBR" in CAT["presets"] and "USBR_TM11" not in CAT["presets"]
    assert CAT["preset_aliases"] == {"USBR_TM11": "USBR"}
    assert C.canonical_preset(CAT, "USBR_TM11") == "USBR"
    a, b = C.preset_config(CAT, "USBR"), C.preset_config(CAT, "USBR_TM11")
    assert a["preset"] == b["preset"] == "USBR"
    assert b["requested_preset"] == "USBR_TM11"
    a.pop("requested_preset"), b.pop("requested_preset")
    assert a == b
    assert C.labels_for(CAT, "USBR_TM11") == C.labels_for(CAT, "USBR")
    assert dict(C.preset_choices(CAT))["USBR"] == "USBR (ACER TM-11)"
    try:
        C.preset_config(CAT, "USBR_TM12")
    except C.CatalogError as e:
        assert "USBR_TM11" in str(e)
    else:
        raise AssertionError("unknown preset accepted")


def test_overrides_take_catalog_or_hazard_names():
    a = C.preset_config(CAT, "ND", overrides={"M2": {"depth_ft": 3.0}})
    b = C.preset_config(CAT, "ND", overrides={"M2": {"threshold_ft": 3.0}})
    assert a["methods"]["M2"]["params"]["threshold_ft"] == 3.0
    assert a["methods"] == b["methods"]


def test_export_for_other_tools():
    tmp = tempfile.mkdtemp(prefix="damit_hz_exp_")
    try:
        out = os.path.join(tmp, "hazard_catalog.json")
        C._main(["--export", out])
        with open(out, encoding="utf-8") as f:
            exp = json.load(f)
        assert sorted(exp["presets"]) == sorted(CAT["presets"])
        assert exp["presets"]["USBR"]["aliases"] == ["USBR_TM11"]
        for p in exp["presets"].values():      # what DamIT Crest's jurisdiction index reads
            assert {"label", "scenarios", "methods", "modifiers", "labels", "verification"} <= set(p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_is_deterministic():
    assert C.build(_damit_catalog()) == copy.deepcopy(CAT)
