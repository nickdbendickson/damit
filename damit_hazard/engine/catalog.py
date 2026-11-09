"""The methods catalog (data/catalog.json) and the run configuration built from it.

Every threshold lives in the data file (Appendix A.7): a preset is a bundle of scenario, method
and modifier IDs with parameter overrides and a label map; custom mode is a list of IDs with the
catalog defaults (both take user overrides on top). Nothing here knows a number of any rule.
"""
import copy
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(HERE, "data", "catalog.json")
GENERIC_LABELS = {0: "Minimal", 1: "Low", 2: "Significant", 3: "High", 4: "Extremely High"}
# the order the methods are evaluated in: lethality first (M6 / M5 / M7 read it), the
# low-volume road exclusion before the descriptor fallback that would otherwise score those roads
EVAL_ORDER = ("M1", "M2", "M3", "M4a", "M4b", "M4c", "M5", "M6", "M7",
              "M8e", "M8a", "M8b", "M8c", "M8d", "M8f", "M8g",
              "M9a", "M9b", "M9c", "M10a", "M10b", "M11a", "M11b", "M11c",
              "M12a", "M12b", "M12c", "M12d", "M13")
STRENGTHS = ("rule", "advisory")


class CatalogError(ValueError):
    pass


def load(path=None):
    with open(path or DEFAULT_FILE, encoding="utf-8") as f:
        cat = json.load(f)
    problems = validate(cat)
    if problems:
        raise CatalogError("catalog.json: " + "; ".join(problems[:8]))
    return cat


def validate(cat):
    """Problems of a catalog ([] = usable)."""
    out = []
    for key in ("classes", "scenarios", "methods", "modifiers", "presets", "general"):
        if key not in cat:
            out.append("no '{}'".format(key))
    if out:
        return out
    for mid, m in cat["methods"].items():
        for f in ("name", "inputs", "params", "strength", "source", "verification"):
            if f not in m:
                out.append("method {} lacks {}".format(mid, f))
        if m.get("strength") not in STRENGTHS:
            out.append("method {} strength {!r}".format(mid, m.get("strength")))
        if mid not in EVAL_ORDER:
            out.append("method {} has no evaluator".format(mid))
    for mid in EVAL_ORDER:
        if mid not in cat["methods"]:
            out.append("evaluator {} has no catalog record".format(mid))
    for rid, r in cat["modifiers"].items():
        for f in ("name", "rule", "params", "source", "verification"):
            if f not in r:
                out.append("modifier {} lacks {}".format(rid, f))
    for pid, p in cat["presets"].items():
        for f in ("label", "scenarios", "methods", "modifiers", "labels", "verification"):
            if f not in p:
                out.append("preset {} lacks {}".format(pid, f))
        for s in list(p.get("scenarios", [])) + list(p.get("optional_scenarios", {})) + \
                list(p.get("scenarios_any_of", [])):
            if s not in cat["scenarios"]:
                out.append("preset {} names unknown scenario {}".format(pid, s))
        for d in p.get("domains", []):
            if d not in cat.get("domains", {}):
                out.append("preset {} names unknown domain {}".format(pid, d))
        for mid in p.get("methods", {}):
            if mid not in cat["methods"]:
                out.append("preset {} names unknown method {}".format(pid, mid))
        for rid in p.get("modifiers", {}):
            if rid not in cat["modifiers"]:
                out.append("preset {} names unknown modifier {}".format(pid, rid))
    return out


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("chart_for_type",):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _entry(record, over):
    """{"params", "strength"} of a method / modifier: catalog params <- override (an override's
    'strength' key sets the strength, every other key is a parameter)."""
    over = dict(over or {})
    strength = over.pop("strength", None) or record.get("strength", "rule")
    params = _merge(record.get("params", {}), over)
    if "strength" in record.get("params", {}) and strength:      # R4 keeps it as a parameter
        params["strength"] = strength
    return {"params": params, "strength": params.get("strength", strength)}


def labels_for(cat, preset_id=None):
    labels = dict(GENERIC_LABELS)
    if preset_id:
        for k, v in cat["presets"][preset_id]["labels"].items():
            labels[int(k)] = v
    return labels


def preset_config(cat, preset_id, overrides=None, apply_advisory=False):
    """The run configuration of a jurisdiction preset. overrides: {ID: {param: value}}."""
    if preset_id not in cat["presets"]:
        raise CatalogError("no preset {!r}".format(preset_id))
    p = cat["presets"][preset_id]
    overrides = overrides or {}
    methods = {mid: _entry(cat["methods"][mid], _merge(over, overrides.get(mid)))
               for mid, over in p["methods"].items()}
    mods = {rid: _entry(cat["modifiers"][rid], _merge(over, overrides.get(rid)))
            for rid, over in p["modifiers"].items()}
    domains = {d: _merge(cat["domains"][d]["params"], overrides.get(d))
               for d in p.get("domains", [])}
    return {"mode": "preset", "preset": preset_id, "preset_label": p["label"],
            "preset_verification": p.get("verification"), "preset_notes": p.get("notes", ""),
            "scenarios": list(p["scenarios"]),
            "optional_scenarios": dict(p.get("optional_scenarios", {})),
            "scenarios_any_of": list(p.get("scenarios_any_of", [])),
            "scenario_note": p.get("scenario_note", ""),
            "domains": domains, "methods": methods, "modifiers": mods,
            "labels": labels_for(cat, preset_id), "apply_advisory": bool(apply_advisory),
            "general": copy.deepcopy(cat["general"])}


def custom_config(cat, methods, modifiers=(), scenarios=(), domains=(), overrides=None,
                  apply_advisory=False):
    """Custom mode: the ticked IDs with the catalog defaults (+ overrides); generic labels."""
    overrides = overrides or {}
    bad = [m for m in methods if m not in cat["methods"]] + \
          [r for r in modifiers if r not in cat["modifiers"]] + \
          [s for s in scenarios if s not in cat["scenarios"]] + \
          [d for d in domains if d not in cat.get("domains", {})]
    if bad:
        raise CatalogError("unknown ID(s): " + ", ".join(bad))
    return {"mode": "custom", "preset": None, "preset_label": None, "preset_verification": None,
            "preset_notes": "", "scenarios": list(scenarios), "optional_scenarios": {},
            "scenarios_any_of": [], "scenario_note": "",
            "domains": {d: _merge(cat["domains"][d]["params"], overrides.get(d)) for d in domains},
            "methods": {m: _entry(cat["methods"][m], overrides.get(m)) for m in methods},
            "modifiers": {r: _entry(cat["modifiers"][r], overrides.get(r)) for r in modifiers},
            "labels": dict(GENERIC_LABELS), "apply_advisory": bool(apply_advisory),
            "general": copy.deepcopy(cat["general"])}


def preset_choices(cat):
    """[(id, label shown in preset mode)]: the label carries (secondary) / (unverified) /
    (draft) when the preset's verification is not 'verified'."""
    out = []
    for pid, p in cat["presets"].items():
        v = p.get("verification", "verified")
        out.append((pid, p["label"] + ("" if v == "verified" else " ({})".format(v))))
    return out
