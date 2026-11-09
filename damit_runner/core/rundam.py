"""DamIT Runner run preparation (pure Python).

damit_run:rundam accepts a damit.handoff package (from damit_screen:handoff) or equivalent
parameters, validates it against DamIT Catalog, and prepares a NEW run folder with
run_setup.json, a copy of the package and the expected-output contract that DamIT Hazard
(damit:classify) will read after a model run.

NID dams only: the package's dam must carry an NID ID (dam_id or nid_id), or be marked new / proposed
(is_new) or a desk sample (is_sample); DamIT Catalog's handoff.nid_rule decides, and validate() refuses the rest.

0.1.0 is prepare / record only: it never starts LISFLOOD-FP, ANUGA, HEC-RAS, Wine,
ndbreach:rundam or ndbreach:batch. Any request for a model engine is refused.
"""
import datetime
import json
import os

from . import catalog_bridge as CB

VERSION = "0.1.0"
PROVIDER_ID = "damit_run"
RUN_SETUP = "run_setup.json"
RUN_SCHEMA = "damit.run_setup"
ENGINE_LABELS = ["None - prepare and record the run only (0.1.0)", "LISFLOOD-FP (not available in 0.1.0)",
                 "ANUGA (not available in 0.1.0)", "HEC-RAS 2D (not available in 0.1.0)"]
ENGINE_NONE = 0
REFUSAL = ("DamIT Runner 0.1.0 prepares and records runs only; it does not launch {} (nor LISFLOOD-FP, ANUGA, "
           "HEC-RAS, Wine, ndbreach:rundam or ndbreach:batch). Nothing was run. Run the model outside DamIT "
           "with the prepared run_setup.json, put its rasters in the run folder's outputs/, then classify with "
           "DamIT Hazard (damit:classify).")
EXPECTED_OUTPUTS = {
    "depth_max": "outputs/Depth (Max).tif",
    "velocity_max": "outputs/Velocity (Max).tif",
    "dv_max": "outputs/DV (Max).tif",
    "wse_max": "outputs/WSE (Max).tif",
    "arrival": "outputs/Arrival.tif",
    "non_breach_wse_max": "outputs/WSE NonBreach (Max).tif",
    "units": {"depth": "ft", "velocity": "ft/s", "dv": "ft2/s (maximum of depth x velocity over the event)",
              "wse": "ft", "arrival": "hours"},
}


class RunError(ValueError):
    pass


def refuse_engine(engine, dry_run=True):
    """Raise RunError for any request that would launch a model."""
    try:
        e = int(engine or 0)
    except (TypeError, ValueError):
        e = -1
    if e != ENGINE_NONE:
        name = ENGINE_LABELS[e].split(" (")[0] if 0 <= e < len(ENGINE_LABELS) else "engine {!r}".format(engine)
        raise RunError(REFUSAL.format(name))
    if not dry_run:
        raise RunError(REFUSAL.format("a model (dry_run=false was requested)"))


def package_from_params(cat, dam, mode="preset", preset=None, scenarios=None, methods=None, inputs=None):
    """Equivalent parameters -> a damit.handoff package (same schema the screener writes)."""
    _, _, HO = CB.modules()
    if mode == "custom":
        cfg = cat.resolve_custom(methods or [], scenarios or [])
    else:
        if not preset:
            raise RunError("preset mode needs a preset ID")
        cfg = cat.resolve_preset(preset, scenarios or None)
    return HO.build(cfg, dam, inputs or {}, None, [],
                    created_by={"plugin": "damit_runner", "version": VERSION, "algorithm": "damit_run:rundam"})


def readiness(pkg):
    """What a model run would still need (gaps), from the package."""
    inp = pkg.get("inputs") or {}
    dam = pkg.get("dam") or {}
    gaps = []
    if not inp.get("terrain"):
        gaps.append("terrain (DEM)")
    if not inp.get("hydrograph_csv") and not (dam.get("storage_top_of_dam_acft") or dam.get("storage_acft")):
        gaps.append("hydrograph CSV or storage")
    if not pkg.get("scenarios"):
        gaps.append("scenario (S-code)")
    if dam.get("x") in (None, "") or dam.get("y") in (None, ""):
        gaps.append("dam location")
    for s in pkg.get("scenarios") or []:
        pools = (dam.get("scenario_pools") or {}).get(s.get("id")) or {}
        if pools and pools.get("pool_elev_ft") is None:
            gaps.append("{} pool elevation ({})".format(s.get("id"), pools.get("pool_note", "")))
    return gaps


def new_run_folder(out_root, dam_id, now=None):
    """A NEW folder under out_root/<dam>/; never reuses or writes into an existing run folder."""
    _, _, HO = CB.modules()
    now = now or datetime.datetime.now()
    base = os.path.join(out_root, HO.safe_name(dam_id), "run_" + now.strftime("%Y%m%d_%H%M%S"))
    path, n = base, 1
    while os.path.exists(path):
        n += 1
        path = "{}_{}".format(base, n)
    os.makedirs(path)
    return path


def prepare_run(pkg, out_root, cat=None, engine=ENGINE_NONE, dry_run=True, now=None):
    """Validate the package and prepare a run folder. Returns (run_folder, run_setup dict)."""
    refuse_engine(engine, dry_run)
    _, _, HO = CB.modules()
    cat = cat or CB.load_catalog()
    errs = HO.validate(pkg, cat, check_paths=True)
    if errs:
        raise RunError("hand-off package rejected: " + "; ".join(errs))
    dam = pkg["dam"]
    _, nid_warning, nid = HO.nid_rule(dam)
    if nid and not dam.get("nid_id"):
        dam = dict(dam, nid_id=nid)
    folder = new_run_folder(out_root, dam["dam_id"], now)
    os.makedirs(os.path.join(folder, "outputs"))
    HO.write(pkg, folder)
    gaps = readiness(pkg)
    setup = {
        "schema": RUN_SCHEMA, "schema_version": 1,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "created_by": {"plugin": "damit_runner", "version": VERSION, "algorithm": "damit_run:rundam"},
        "status": "prepared", "model_launched": False, "engine": "none", "dry_run": True,
        "dam": dam, "nid_id": nid, "nid_warning": nid_warning,
        "mode": pkg.get("mode"), "preset_id": pkg.get("preset_id"),
        "preset_label": pkg.get("preset_label"),
        "scenarios": pkg.get("scenarios"), "conditional_scenarios": pkg.get("conditional_scenarios") or [],
        "domain_cutoffs": pkg.get("domain_cutoffs") or [], "methods": pkg.get("methods"),
        "modifiers": pkg.get("modifiers"), "label_map": pkg.get("label_map"),
        "apply_advisories": pkg.get("apply_advisories", False),
        "inputs": pkg.get("inputs"), "expected_outputs": EXPECTED_OUTPUTS,
        "model_dimension": None,
        "ready_to_run": not gaps, "gaps": gaps, "screening_gaps": pkg.get("gaps") or [],
        "screening": pkg.get("screening"),
        "classification": {"by": "DamIT Hazard", "algorithm": "damit:classify", "status": "pending",
                           "note": "DamIT Runner does not classify; it attaches the catalog metadata below."},
        "catalog": {"used": cat.identity(), "package": pkg.get("catalog"),
                    "citations": {k: v for k, v in _citations(cat, pkg).items()},
                    "disclaimer": cat.disclaimer},
        "handoff": HO.FILENAME,
    }
    with open(os.path.join(folder, RUN_SETUP), "w", encoding="utf-8") as fh:
        json.dump(setup, fh, indent=1, ensure_ascii=False, default=str)
    _write_readme(folder, setup)
    return folder, setup


def _citations(cat, pkg):
    out = {}
    for m in pkg.get("methods") or {}:
        out[m] = cat.methods.get(m, {}).get("source", "")
    for s in pkg.get("scenarios") or []:
        out[s.get("id")] = cat.scenarios.get(s.get("id"), {}).get("source", "")
    for r in pkg.get("modifiers") or []:
        out[r] = cat.modifiers.get(r, {}).get("source", "")
    return out


def _write_readme(folder, setup):
    lines = ["# DamIT Runner - prepared run (no model launched)", "",
             "Dam: {} {}".format(setup["dam"].get("dam_id"), setup["dam"].get("name") or ""),
             "Mode: {} {}".format(setup["mode"], setup.get("preset_label") or ""),
             "Scenarios: {}".format(", ".join(s.get("id") for s in setup["scenarios"] or []) or "none (unconfirmed)"),
             "Ready to run: {}{}".format("yes" if setup["ready_to_run"] else "no",
                                         "" if setup["ready_to_run"] else " - missing: " + "; ".join(setup["gaps"])),
             "", "DamIT Runner 0.1.0 only prepares and records the run. Put the model's rasters in outputs/ "
             "with the names in run_setup.json 'expected_outputs', then classify with DamIT Hazard "
             "(damit:classify). Suggested classifications only; the engineer of record and the regulating "
             "agency make the determination."]
    with open(os.path.join(folder, "README_run.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
