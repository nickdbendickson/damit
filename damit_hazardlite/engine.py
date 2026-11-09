"""DamIT Hazard Lite engine (pure Python + numpy optional): receptor records from sampled cells
and the suggested class from DamIT Catalog.

No threshold, label or method parameter lives here: the wet depth, sampling distances and the
lowest class come from DamIT Catalog's hazard.json (``general``), the receptor-type vocabulary
from hazard.json ``receptor_types``, and every class rule from the resolved preset / custom
methods, evaluated by ``damit_catalog.evaluate`` (the same evaluator and data DamIT Hazard uses).
"""
import json
import math
import os

from . import _deps  # noqa: F401
from damit_core.lib import catalog_access

FT_PER_M = 3.280839895
HERE = os.path.dirname(os.path.abspath(__file__))
RECEPTOR_KINDS = ("structure", "road", "rail")


def load_vocab(path=None):
    with open(path or os.path.join(HERE, "data", "vocab.json"), encoding="utf-8") as fh:
        return json.load(fh)


def profile(cat):
    """Sampling and vocabulary settings from the catalog (hazard.json)."""
    hz = cat.hazard or {}
    g = hz.get("general") or {}
    rt = hz.get("receptor_types") or {}
    missing = [k for k in ("wet_min_depth_ft", "point_radius_ft", "line_step_ft", "edge_ring_ft", "base_class")
               if k not in g]
    if missing or "structure_type_map" not in rt:
        raise ValueError("DamIT Catalog hazard.json lacks {}; update DamIT Catalog.".format(
            ", ".join(missing or ["receptor_types.structure_type_map"])))
    return {"wet_min_depth_ft": float(g["wet_min_depth_ft"]), "point_radius_ft": float(g["point_radius_ft"]),
            "line_step_ft": float(g["line_step_ft"]), "edge_ring_ft": float(g["edge_ring_ft"]),
            "base_class": int(g["base_class"]), "habitable_types": list(rt.get("habitable_types") or []),
            "structure_type_map": dict(rt["structure_type_map"])}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def to_bool(v, vocab):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in vocab["true_values"]:
        return True
    if s in vocab["false_values"]:
        return False
    return None


def reduce_cells(depths, velocities, wet_min_ft):
    """Peak depth over the cells, peak velocity over the WET cells (depth > wet_min), peak
    depth x velocity over the wet cells. Depth values are feet (None / NaN = dry), velocity ft/s
    (None / NaN = unknown). Returns a dict of receptor fields."""
    d = [(_num(x) or 0.0) for x in depths]
    v = [_num(x) for x in (velocities if velocities is not None else [None] * len(d))]
    wet = [i for i, x in enumerate(d) if x > wet_min_ft]
    dmax = max(d) if d else 0.0
    wv = [v[i] for i in wet if v[i] is not None]
    dv = [d[i] * v[i] for i in wet if v[i] is not None]
    out = {"depth_ground_ft": round(dmax, 4), "wet": bool(wet), "cells": len(d), "wet_cells": len(wet),
           "velocity_fps": round(max(wv), 4) if wv else None, "dv_ft2s": round(max(dv), 4) if dv else None,
           "velocity_unknown": bool(wet) and not wv}
    return out


def structure_type(value, vocab):
    if value in (None, ""):
        return None
    s = str(value).strip()
    t = vocab["structure_type"].get(s.lower())
    if t:
        return t
    best = None
    for pre, typ in vocab["structure_type_prefix"].items():
        if pre.startswith("_"):
            continue
        if s.upper().startswith(pre) and (best is None or len(pre) > len(best[0])):
            best = (pre, typ)
    return best[1] if best else None


def structure_record(rid, cells, attrs, prof, vocab, fields):
    """One structure receptor. ``fields``: {'type', 'habitable', 'occupants', 'm1_zone', 'occupancy'}
    -> layer field names (or None)."""
    rec = {"id": rid, "receptor_type": "structure"}
    rec.update(cells)
    htype = structure_type(attrs.get(fields.get("type")) if fields.get("type") else None, vocab)
    rec["hazard_type"] = htype
    rec["structure_type"] = prof["structure_type_map"].get(htype, htype) if htype else None
    hab = to_bool(attrs.get(fields["habitable"]), vocab) if fields.get("habitable") else None
    if hab is None and htype:
        hab = htype in prof["habitable_types"]
    rec["habitable"] = hab
    for k in ("occupants", "m1_zone", "occupancy"):
        f = fields.get(k)
        if f and attrs.get(f) not in (None, ""):
            rec[k] = _num(attrs[f]) if k == "occupants" else str(attrs[f]).strip().lower()
    return rec


def road_record(rid, cells, attrs, vocab, fields):
    rec = {"id": rid, "receptor_type": "road"}
    rec.update(cells)
    rc = attrs.get(fields["road_class"]) if fields.get("road_class") else None
    if rc not in (None, ""):
        rec["road_class"] = vocab["road_class"].get(str(rc).strip().lower(), str(rc).strip().lower())
    if fields.get("aadt"):
        rec["aadt"] = _num(attrs.get(fields["aadt"]))
    if fields.get("name"):
        rec["name"] = attrs.get(fields["name"])
    return rec


def rail_record(rid, cells, attrs, vocab, fields):
    rec = {"id": rid, "receptor_type": "rail"}
    rec.update(cells)
    act = to_bool(attrs.get(fields["active"]), vocab) if fields.get("active") else None
    rec["active"] = True if act is None else act            # a mapped rail line is active unless the layer says not
    if fields.get("trains_per_day"):
        rec["trains_per_day"] = _num(attrs.get(fields["trains_per_day"]))
    if fields.get("passenger"):
        rec["passenger"] = to_bool(attrs.get(fields["passenger"]), vocab)
    return rec


def resolve(cat, mode, preset="", methods=None, scenarios=None):
    return catalog_access.resolve(cat, mode, preset, methods, scenarios)


def classify(cat, config, records, summary=None, apply_advisories=False, prof=None):
    """damit_catalog.evaluate on the records; with no hit at all the lowest consequence class
    (hazard.json general.base_class), as DamIT Hazard does, and the missing-input flags kept."""
    _, evaluate = catalog_access.modules()
    prof = prof or profile(cat)
    res = evaluate.evaluate(cat, config, records, summary or {}, apply_advisories)
    res["base_class_applied"] = False
    if res["suggested_ordinal"] is None and not res["hits"]:
        res["suggested_ordinal"] = prof["base_class"]
        res["suggested_label"] = evaluate.label_for(config, prof["base_class"])
        res["generic_label"] = cat.generic_label(prof["base_class"])
        res["base_class_applied"] = True
        res["flags"] = [f for f in res["flags"] if f.get("code") != "not_determined"]
    res["tool"] = "damit_lite:classify"
    res["receptor_counts"] = {k: sum(1 for r in records if r["receptor_type"] == k) for k in RECEPTOR_KINDS}
    res["wet_counts"] = {k: sum(1 for r in records if r["receptor_type"] == k and r.get("wet")) for k in RECEPTOR_KINDS}
    res["not_screened"] = sorted(m for m in config.get("methods", {})
                                 if not _lite_supported(config["methods"][m]))
    return res


def _lite_supported(m):
    types = (m.get("applies_to") or {}).get("receptor_type") or []
    return bool(set(types) & set(RECEPTOR_KINDS)) and m.get("evaluation") != "manual"


def receptor_class(res, rid):
    cs = [h["class"] for h in res["hits"] if h["receptor"] == rid]
    return max(cs) if cs else None


def summary_markdown(res, records, config, inputs):
    lines = ["# DamIT Hazard Lite - suggested hazard class", "",
             "**Suggested class: {} (ordinal {}; generic {})**".format(
                 res["suggested_label"], res["suggested_ordinal"], res["generic_label"]), "",
             "> Suggestion only. {}".format(res.get("disclaimer") or
                                            "The engineer of record and the regulating agency make the determination."), "",
             "* Mode: {}{}".format(config.get("mode"), " - preset {}".format(config.get("preset_id")) if config.get("preset_id") else ""),
             "* Catalog: {} (sha256 {})".format(res["catalog"]["catalog_version"], res["catalog"]["sha256"][:12]),
             "* Inputs: " + ", ".join("{}={}".format(k, v) for k, v in sorted(inputs.items()) if v),
             "* Receptors: " + ", ".join("{} {} ({} wet)".format(res["receptor_counts"][k], k, res["wet_counts"][k])
                                         for k in RECEPTOR_KINDS)]
    if res["base_class_applied"]:
        lines.append("* No method hit: the lowest consequence class (catalog hazard.json base_class).")
    lines += ["", "## Driving results", ""]
    lines += _hit_lines(res["driving"], True) or ["* none"]
    if res["advisories"]:
        lines += ["", "## Advisory results (not applied unless opted in)", ""]
        lines += _hit_lines(res["advisories"], False)
    lines += ["", "## Flags", ""]
    counts = {}
    for f in res["flags"]:
        counts[(f["code"], f["message"])] = counts.get((f["code"], f["message"]), 0) + 1
    lines += ["* [{}] {}{}".format(c, m, " (x{})".format(n) if n > 1 else "") for (c, m), n in counts.items()] or ["* none"]
    if res["not_screened"]:
        lines += ["", "## Methods Hazard Lite does not screen", "",
                  "Enabled by this preset / selection but not about structures, roads or rail (or manual): "
                  + ", ".join(res["not_screened"]) + ". Review them with DamIT Hazard (damit:classify) or by hand."]
    lines += ["", "## Citations", ""] + ["* {}".format(c) for c in _cites(res)]
    return "\n".join(lines) + "\n"


def _hit_lines(hits, why):
    """One line per method / receptor / class, with the scenarios it came from."""
    seen = {}
    for h in hits or []:
        k = (h["method"], h["strength"], str(h["receptor"]), h["class"], h["why"] if why else "")
        seen.setdefault(k, []).append(h.get("scenario") or "-")
    return ["* {} {} at {} -> class {}{} [scenario {}]".format(m, st, r, c, " ({})".format(w) if w else "",
                                                             ", ".join(sorted(set(sc))))
            for (m, st, r, c, w), sc in seen.items()]


def _cites(res):
    c = res.get("citations") or []
    if isinstance(c, dict):
        return ["{}: {}".format(k, v) for k, v in sorted(c.items())]
    return [str(x if not isinstance(x, dict) else x.get("text") or x) for x in c]
