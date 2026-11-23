"""Hazard class probability from an ensemble of breach runs.

Every probability is over all runs. A run whose status is "no breach" is its own outcome:
it is not given a class and it is not dropped, so the class probabilities and P(no breach)
add to 1. P(class | breach) is reported beside that. The governing class is the highest
class among the breach runs that classified. A no-breach run cannot pull it down, and the
distribution is not itself a class.

Per-run results go in <output>/ensemble/<run id>/ (processing_qa2100's per-run folders).
"""

import csv
import json
import math
import os

from .catalog import GENERIC_LABELS

STATUS_NO_BREACH = "no breach"
NO_BREACH_ITEM = "No breach"
RUN_JSON = "run.json"
DEPTH_NAME = "Depth (Max).tif"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _weights(items):
    ws = [_num(it.get("weight")) for it in items]
    if items and all(w is not None and w > 0 for w in ws):
        return ws, True, "weighted by each run's weight"
    return [1.0] * len(items), False, "unweighted (every run counts once)"


def aggregate(items, labels=None):
    """Class distribution. items: {id, status, suggested_class, weight}.

    status "no breach" is its own outcome. suggested_class on a no-breach item is ignored.
    Returns probabilities over every item, p_given_breach over the breach runs only, and
    governing_class = the highest breach-run class (None when every run is no breach).
    """
    labels = dict(labels or GENERIC_LABELS)
    items = list(items or [])
    ws, weighted, note = _weights(items)
    total = sum(ws) or 1.0
    breach = [(it, w) for it, w in zip(items, ws) if it.get("status") != STATUS_NO_BREACH]
    nob = [(it, w) for it, w in zip(items, ws) if it.get("status") == STATUS_NO_BREACH]
    btot = sum(w for _it, w in breach)
    classes = {}
    for it, w in breach:
        c = it.get("suggested_class")
        try:
            c = int(c)
        except (TypeError, ValueError):
            c = None
        bucket = classes.setdefault(c, {"runs": 0, "weight": 0.0, "ids": [],
                                        "label": labels.get(c, str(c))})
        bucket["runs"] += 1
        bucket["weight"] += w
        bucket["ids"].append(it.get("id"))
    for bucket in classes.values():
        bucket["p"] = bucket["weight"] / total
        bucket["p_given_breach"] = bucket["weight"] / btot if btot else 0.0
    known = [c for c in classes if isinstance(c, int)]
    governing = max(known) if known else None
    p_nb = sum(w for _it, w in nob) / total
    return {
        "n": len(items), "n_breach": len(breach), "n_no_breach": len(nob),
        "weighted": weighted, "weight_note": note, "total_weight": total,
        "breach_weight": btot, "classes": classes,
        "no_breach": {"runs": len(nob), "weight": sum(w for _it, w in nob), "p": p_nb,
                      "ids": [it.get("id") for it, _w in nob], "label": NO_BREACH_ITEM},
        "governing_class": governing,
        "governing_label": labels.get(governing) if governing is not None else None,
        "probabilities_over": "all runs",
    }


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def find_runs(folder, max_runs=200):
    """Run folders under `folder` (or under folder/Runs). A run.json status of
    "no breach" is kept. Other folders count when they hold a depth raster or a class."""
    if not folder or not os.path.isdir(folder):
        return []
    root = folder
    for name in ("Runs", "runs"):
        cand = os.path.join(folder, name)
        if os.path.isdir(cand):
            root = cand
            break
    index = _read_json(os.path.join(root, "index.json"))
    listed = index.get("runs") if isinstance(index.get("runs"), list) else None
    names = listed if listed is not None else sorted(
        n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith("."))
    out = []
    for name in names:
        if len(out) >= int(max_runs):
            break
        path = name if os.path.isabs(str(name)) else os.path.join(root, str(name))
        if not os.path.isdir(path):
            path = os.path.join(root, os.path.basename(str(name)))
        if not os.path.isdir(path):
            continue
        meta = _read_json(os.path.join(path, RUN_JSON))
        status = str(meta.get("status") or "").strip().lower()
        if status in ("no breach", "no_breach", "nobreach"):
            status = STATUS_NO_BREACH
        elif os.path.isfile(os.path.join(path, DEPTH_NAME)) or meta.get("suggested_class") is not None:
            status = status or "done"
        else:
            continue
        out.append({"id": os.path.basename(path.rstrip(os.sep)), "folder": path,
                    "status": status, "weight": meta.get("weight"),
                    "suggested_class": None if status == STATUS_NO_BREACH else meta.get("suggested_class"),
                    "meta": meta})
    return out


def per_run_dir(output_folder, run_id):
    """<output>/ensemble/<run id>/ — one folder per run, never the dam folder itself."""
    path = os.path.join(output_folder, "ensemble", str(run_id))
    os.makedirs(path, exist_ok=True)
    return path


def write_distribution(output_folder, agg, runs):
    """Class_Probability.csv and one result.json per run. Returns the csv path."""
    os.makedirs(output_folder, exist_ok=True)
    csv_path = os.path.join(output_folder, "Class_Probability.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Section", "Item", "Label", "Runs", "Weight", "Probability",
                    "Probability_Given_Breach", "Run_IDs"])
        for c, bucket in sorted(agg["classes"].items(), key=lambda kv: (kv[0] is None, kv[0])):
            w.writerow(["class", c, bucket["label"], bucket["runs"], bucket["weight"],
                        bucket["p"], bucket["p_given_breach"], " ".join(str(i) for i in bucket["ids"])])
        nb = agg["no_breach"]
        w.writerow(["no_breach", NO_BREACH_ITEM, NO_BREACH_ITEM, nb["runs"], nb["weight"],
                    nb["p"], "", " ".join(str(i) for i in nb["ids"])])
        w.writerow(["governing", agg["governing_class"], agg["governing_label"] or "",
                    "", "", "", "", "highest class among breach runs; no-breach runs do not lower it"])
    for run in runs:
        folder = per_run_dir(output_folder, run.get("id") or "run")
        with open(os.path.join(folder, "result.json"), "w", encoding="utf-8") as fh:
            status = run.get("status")
            klass = None if status == STATUS_NO_BREACH else run.get("suggested_class")
            json.dump({"id": run.get("id"), "status": status,
                       "suggested_class": klass, "weight": run.get("weight"),
                       "note": "no breach is its own outcome; this folder is not a class"
                       if status == STATUS_NO_BREACH else ""}, fh, indent=1)
    with open(os.path.join(output_folder, "ensemble.json"), "w", encoding="utf-8") as fh:
        json.dump(agg, fh, indent=1)
    return csv_path


def summary_line(agg):
    if not agg or not agg.get("n"):
        return "Class probability: no runs."
    parts = []
    for c, bucket in sorted(agg["classes"].items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        parts.append("{} {:.2f} ({})".format(bucket["label"], bucket["p"], bucket["runs"]))
    nb = agg["no_breach"]
    if nb["runs"]:
        parts.append("no breach {:.2f} ({})".format(nb["p"], nb["runs"]))
    gov = agg["governing_label"] or "none"
    return ("Class probability over {} run(s), {}: {}; governing class {} "
            "(highest breach run; a no-breach run is not a lower class).".format(
                agg["n"], "weighted" if agg["weighted"] else "unweighted",
                ", ".join(parts) or "none", gov))
