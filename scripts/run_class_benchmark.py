#!/usr/bin/env python3
"""Known-class benchmark. Exit 1 if DamIT's class is below the official class.

Reads tests/class_benchmark/dams.json (or --dams). Each dam is classified under each listed
preset. Rasters, when named, are read from DAMIT_CLASS_BENCHMARK_DATA (or --data). This
environment has no GDAL, so a raster path is reported as skipped rather than sampled.
A fixture whose file purpose is "self-test" is not an official class; it only proves the
LOWER exit. Official dams.json stays empty until a citation and inputs exist.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_DAMS = os.path.join(ROOT, "tests", "class_benchmark", "dams.json")
DATA_ENV = "DAMIT_CLASS_BENCHMARK_DATA"
GENERIC = {0: "Minimal", 1: "Low", 2: "Significant", 3: "High", 4: "Extremely High"}


def load_file(path):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, list):
        return {"purpose": "official", "dams": doc}
    return doc


def _ordinal(value, label_map):
    """An ordinal, or None when the text is not a catalog label (do not guess)."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    low = text.lower()
    for k, lab in (label_map or {}).items():
        if str(lab).strip().lower() == low:
            return int(k)
    for k, lab in GENERIC.items():
        if lab.lower() == low:
            return k
    return None


def verdict(official, damit):
    if official is None or damit is None:
        return "unmapped"
    if damit < official:
        return "LOWER"
    if damit > official:
        return "higher"
    return "agree"


def preset_marks(src, preset_id):
    """status and verification from presets.json. Unknown preset -> None."""
    try:
        pr = src.preset(preset_id)
    except Exception:
        return None
    return {"id": src.canonical_preset_id(preset_id),
            "status": pr.get("status"),
            "verification": pr.get("verification") or {}}


def print_marks(marks):
    for m in marks:
        ver = m["verification"]
        ver_s = "(none)" if not ver else ", ".join("{}={}".format(k, v) for k, v in sorted(ver.items()))
        print("preset {}  status={}  verification={}".format(
            m["id"], m["status"] or "(none)", ver_s))


def _receptors(raw):
    """JSON receptors through the same normaliser the classifier's tests use."""
    from damit_hazard.engine import receptors as R
    out = []
    for i, rec in enumerate(raw or []):
        rec = dict(rec)
        rid = rec.pop("id", "r{}".format(i + 1))
        kind = rec.pop("kind", "structure")
        out.append(R.make(rid, kind, **rec))
    return out


def _classify(hcat, hsrc, charts, preset_id, receptors, dam_id):
    cfg = hcat.preset_config(hsrc, preset_id)
    scenarios = list(cfg.get("scenarios") or [])
    if not scenarios:
        return None, "preset has no confirmed scenario"
    run = {"scenario": scenarios[0], "model_dim": "2D", "label": "benchmark",
           "receptors": _receptors(receptors)}
    dam = {"dam_id": dam_id or "benchmark", "is_sample": True}
    res = hcat_core_classify(hsrc, cfg, [run], dam, charts)
    return int(res["suggested_class"]), None


def hcat_core_classify(hsrc, cfg, runs, dam, charts):
    from damit_hazard.engine import core
    return core.classify(hsrc, cfg, runs, dam=dam, charts=charts)


def run_benchmark(doc, data_dir, hsrc, charts, cat_src):
    """(rows, marks, n_lower). A row is a dict. Does not invent an official class."""
    from damit_hazard.engine import catalog as hcat
    purpose = doc.get("purpose") or "official"
    self_test = purpose == "self-test"
    rows = []
    used = []
    for dam in doc.get("dams") or []:
        if dam.get("official_record") is False and not self_test:
            continue
        presets = list(dam.get("presets") or [])
        receptors = dam.get("receptors")
        raster = dam.get("rasters")
        for pid in presets:
            mark = preset_marks(cat_src, pid)
            if mark:
                used.append(mark)
            label_map = {}
            try:
                label_map = cat_src.resolve_preset(pid).get("label_map") or {}
            except Exception:
                pass
            official = _ordinal(dam.get("official_class"), label_map)
            base = {"id": dam.get("id"), "preset": pid, "official": official,
                    "damit": None, "verdict": "skipped", "detail": ""}
            if receptors:
                try:
                    damit, why = _classify(hcat, hsrc, charts, pid, receptors, dam.get("id"))
                except Exception as e:
                    base["detail"] = "{}: {}".format(type(e).__name__, e)
                    rows.append(base)
                    continue
                if why:
                    base["detail"] = why
                    rows.append(base)
                    continue
                base["damit"] = damit
                base["verdict"] = verdict(official, damit)
                rows.append(base)
                continue
            if raster:
                root = data_dir or ""
                path = raster if os.path.isabs(raster) else os.path.join(root, raster) if root else ""
                if not path or not os.path.exists(path):
                    base["detail"] = "rasters not in this environment ({})".format(DATA_ENV)
                else:
                    base["detail"] = "rasters present but not sampled (no GDAL in this environment)"
                rows.append(base)
                continue
            base["detail"] = "no receptors and no rasters"
            rows.append(base)
    if not used:
        for pid in cat_src.preset_ids():
            pr = cat_src.presets[pid]
            if pr.get("status") or pr.get("verification"):
                used.append({"id": pid, "status": pr.get("status"),
                             "verification": pr.get("verification") or {}})
    n_lower = sum(1 for r in rows if r["verdict"] == "LOWER")
    return rows, used, n_lower


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare DamIT classes with official classes. Exit 1 on LOWER.")
    ap.add_argument("--dams", default=DEFAULT_DAMS, help="dams.json (default: tests/class_benchmark/dams.json)")
    ap.add_argument("--data", default=None, help="folder of rasters (default: ${})".format(DATA_ENV))
    a = ap.parse_args(argv)
    try:
        doc = load_file(a.dams)
    except (OSError, ValueError) as e:
        print("cannot read {}: {}".format(a.dams, e), file=sys.stderr)
        return 2
    data = a.data if a.data is not None else os.environ.get(DATA_ENV) or os.environ.get(doc.get("data_env") or DATA_ENV)
    from damit_catalog import catalog as C
    from damit_hazard.engine import catalog as hcat, tm11
    cat_src = C.load()
    hsrc = hcat.load()
    charts = tm11.load()
    rows, marks, n_lower = run_benchmark(doc, data, hsrc, charts, cat_src)
    purpose = doc.get("purpose") or "official"
    print("class benchmark: {} dam(s) in {} ({})".format(
        len(doc.get("dams") or []), a.dams, purpose))
    if purpose != "self-test" and not doc.get("dams"):
        print("official list is empty: no dam is included without a citation and inputs")
    print_marks(marks)
    if purpose == "self-test":
        print("SELF-TEST fixture: labeled classes are not official classes")
    print("{:<22} {:<12} {:>8} {:>8}  {}".format("dam", "preset", "official", "damit", "verdict"))
    for r in rows:
        print("{:<22} {:<12} {:>8} {:>8}  {}{}".format(
            str(r["id"]), str(r["preset"]),
            "-" if r["official"] is None else r["official"],
            "-" if r["damit"] is None else r["damit"],
            r["verdict"], ("  " + r["detail"]) if r["detail"] else ""))
    if n_lower:
        print("LOWER: {}".format(n_lower))
        return 1
    print("LOWER: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
