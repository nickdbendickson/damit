"""Batch classification of dam records that are already sampled.

Each dam is classified on its own with the Catalog. One dam's class is never copied onto
another, and nothing in this module lowers a class it computed.
"""

import json
import os

from . import core


def classify_one(cat, cfg, receptors, dam=None, scenario="S1", dim="2D", charts=None):
    res = core.classify(cat, cfg, [{"scenario": scenario, "model_dim": dim,
                                    "receptors": list(receptors or []), "label": "batch"}],
                        dam=dam or {}, charts=charts)
    return {"suggested_class": res["suggested_class"], "suggested_label": res["suggested_label"],
            "rule_class": res["rule_class"], "flags": [f["code"] for f in res["flags"]]}


def classify_records(cat, cfg, records, charts=None):
    """records: {id, receptors, dam?, scenario?, model_dim?}. Classes are per dam."""
    out = []
    for rec in records or []:
        one = classify_one(cat, cfg, rec.get("receptors") or [], dam=rec.get("dam") or {},
                           scenario=rec.get("scenario") or "S1",
                           dim=rec.get("model_dim") or "2D", charts=charts)
        one["id"] = rec.get("id")
        out.append(one)
    return out


def load_record(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"receptors": data}
    if not isinstance(data, dict):
        raise ValueError("{} is not a receptor record".format(path))
    data.setdefault("id", os.path.splitext(os.path.basename(path))[0])
    return data


def classify_directory(cat, cfg, folder, charts=None):
    """Every *.json in `folder` is one dam. Returns the per-dam classes."""
    names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".json"))
    records = [load_record(os.path.join(folder, n)) for n in names]
    return classify_records(cat, cfg, records, charts=charts)
