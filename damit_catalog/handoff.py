"""DamIT hand-off package: what DamIT Screener writes and DamIT Runner reads (pure Python).

One JSON file per dam, ``damit_handoff.json`` (schema ``damit.handoff`` version 1), inside a
per-dam folder. Paths to terrain, hydrograph and receptor layers are referenced, never copied.
DamIT Hazard (``damit:classify``) can later read the same file next to a finished run to know
the preset / custom method list and scenarios that were intended.
"""
import datetime
import json
import os
import re

SCHEMA = "damit.handoff"
SCHEMA_VERSION = 1
FILENAME = "damit_handoff.json"
RUNNER_ALG = "damit_run:rundam"
CLASSIFIER_ALG = "damit:classify"
SCREENER_ALG = "damit_screen:handoff"

REQUIRED_TOP = ("schema", "schema_version", "created", "created_by", "catalog", "mode", "scenarios",
                "methods", "modifiers", "label_map", "dam", "inputs", "screening", "gaps", "target")
REQUIRED_DAM = ("dam_id",)
DAM_NUMERIC = ("x", "y", "height_ft", "storage_acft", "crest_elev_ft", "top_of_dam_elev_ft",
               "normal_pool_elev_ft", "emergency_spillway_elev_ft", "breach_azimuth_deg", "peak_outflow_cfs",
               "surface_area_ac")
INPUT_PATHS = ("terrain", "hydrograph_csv", "storage_curve_csv", "receptors_json")


class HandoffError(ValueError):
    pass


def safe_name(s):
    s = re.sub(r"[^\w\- ]+", "_", str(s)).strip()
    return s or "dam"


def build(config, dam, inputs=None, screening=None, gaps=None, created_by=None, apply_advisories=False):
    """A package dict from a resolved catalog config and a dam record."""
    dam = dict(dam or {})
    given = dict(inputs or {})
    inputs = {k: given.get(k) or None for k in INPUT_PATHS}
    inputs.update({k: v for k, v in given.items() if k not in INPUT_PATHS})
    pkg = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "created_by": created_by or {"plugin": "damit_screener", "algorithm": SCREENER_ALG},
        "catalog": config.get("catalog") or {},
        "mode": config.get("mode"), "preset_id": config.get("preset_id"),
        "preset_label": config.get("preset_label"),
        "scenarios": [{"id": s["id"], "name": s.get("name", ""),
                       "params": {k: v for k, v in s.items() if k in ("analyses", "pool", "inflow")}}
                      for s in config.get("scenarios", [])],
        "scenarios_confirmed": bool(config.get("scenarios")) and not any(
            f.get("code") == "scenario_unconfirmed" for f in config.get("flags", [])),
        "conditional_scenarios": config.get("conditional_scenarios") or [],
        "domain_cutoffs": [{"id": d["id"], **{k: v for k, v in d.items() if k.endswith("_ft")}}
                           for d in config.get("domain_cutoffs", [])],
        "methods": {mid: {"params": m.get("params", {}), "strength": m.get("strength")}
                    for mid, m in config.get("methods", {}).items()},
        "modifiers": [r["id"] for r in config.get("modifiers", [])],
        "label_map": config.get("label_map") or {},
        "apply_advisories": bool(apply_advisories),
        "dam": dam, "inputs": inputs,
        "screening": screening or {"status": "not_computed", "suggested_ordinal": None,
                                   "suggested_label": None, "driving": [], "flags": []},
        "gaps": list(gaps or []),
        "config_flags": config.get("flags", []),
        "target": {"runner_algorithm": RUNNER_ALG, "classifier_algorithm": CLASSIFIER_ALG},
        "disclaimer": "Suggested classification only; the engineer of record and the regulating agency "
                      "make the determination.",
    }
    return pkg


def validate(pkg, catalog=None, check_paths=False):
    """List of problems (empty = valid). With a catalog, IDs are cross-checked against it."""
    errs = []
    if not isinstance(pkg, dict):
        return ["package is not a JSON object"]
    for k in REQUIRED_TOP:
        if k not in pkg:
            errs.append("missing '{}'".format(k))
    if pkg.get("schema") != SCHEMA:
        errs.append("schema is {!r}, expected {!r}".format(pkg.get("schema"), SCHEMA))
    try:
        if int(pkg.get("schema_version", 0)) > SCHEMA_VERSION:
            errs.append("schema_version {} is newer than this reader ({})".format(pkg.get("schema_version"), SCHEMA_VERSION))
    except (TypeError, ValueError):
        errs.append("schema_version is not a number")
    if pkg.get("mode") not in ("preset", "custom"):
        errs.append("mode must be 'preset' or 'custom'")
    if pkg.get("mode") == "preset" and not pkg.get("preset_id"):
        errs.append("preset mode without preset_id")
    dam = pkg.get("dam") or {}
    for k in REQUIRED_DAM:
        if dam.get(k) in (None, ""):
            errs.append("dam.{} is required".format(k))
    for k in DAM_NUMERIC:
        v = dam.get(k)
        if v not in (None, ""):
            try:
                float(v)
            except (TypeError, ValueError):
                errs.append("dam.{} is not a number: {!r}".format(k, v))
    if not isinstance(pkg.get("methods"), dict) or not pkg.get("methods"):
        errs.append("methods must be a non-empty object")
    tgt = pkg.get("target") or {}
    if tgt.get("runner_algorithm") != RUNNER_ALG:
        errs.append("target.runner_algorithm must be {}".format(RUNNER_ALG))
    if catalog is not None:
        for mid in (pkg.get("methods") or {}):
            if mid not in catalog.methods:
                errs.append("unknown method {}".format(mid))
        for s in pkg.get("scenarios") or []:
            if s.get("id") not in catalog.scenarios:
                errs.append("unknown scenario {}".format(s.get("id")))
        for r in pkg.get("modifiers") or []:
            if r not in catalog.modifiers:
                errs.append("unknown modifier {}".format(r))
        for d in pkg.get("domain_cutoffs") or []:
            if d.get("id") not in catalog.domain_cutoffs:
                errs.append("unknown domain cutoff {}".format(d.get("id")))
        if pkg.get("mode") == "preset" and pkg.get("preset_id") not in catalog.presets:
            errs.append("unknown preset {}".format(pkg.get("preset_id")))
    if check_paths:
        for k in INPUT_PATHS:
            p = (pkg.get("inputs") or {}).get(k)
            if p and not os.path.exists(p):
                errs.append("inputs.{} does not exist: {}".format(k, p))
    return errs


def write(pkg, folder):
    """Write ``damit_handoff.json`` into ``folder`` (created). Returns the path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, FILENAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, path)
    return path


def read(path):
    """Read a package from a file or a folder that holds ``damit_handoff.json``."""
    if os.path.isdir(path):
        path = os.path.join(path, FILENAME)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise HandoffError("cannot read hand-off package {}: {}".format(path, e))
