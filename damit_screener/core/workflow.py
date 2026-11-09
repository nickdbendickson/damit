"""Screening workflow (pure Python): settings, preflight, the scenario-driven chain, hand-off
packages and the run report. damit_screen:preflight / :runchain / :handoff / :report are thin
Processing wrappers over this module."""
import datetime
import json
import os
import shutil

from . import catalog_bridge as CB
from . import steps as ST

VERSION = "0.1.0"
PROVIDER_ID = "damit_screen"
OK, WARN, FAIL = "ok", "warn", "fail"
MIN_FREE_MB = 200.0

DEFAULT_SETTINGS = {
    "mode": "preset",            # preset | custom
    "preset": "",                # preset id from DamIT Catalog presets.json (no default jurisdiction)
    "scenarios": [],             # S-codes; replaces the preset's (needed where the preset has a dash)
    "method_overrides": {},      # {M-id: {param: value}} on top of the preset
    "custom_methods": [], "custom_params": {}, "custom_modifiers": [], "custom_cutoffs": [],
    "apply_advisories": False,
    "field_map": {},             # DamIT dam field -> layer field
    "terrain": "",               # DEM path (optional)
    "catalog_dir": "",           # edited catalog copy (optional; else DAMIT_CATALOG_DIR or the plugin's data)
    "summary": {},               # dam-level facts for the suggestion (model_dimension, hydraulics_source, ...)
    "dam_ids": [],               # limit the chain to these dams (empty = all)
}

STEP_ORDER = ("prepare", "terrain", "storage", "breach_direction", "hydrograph", "triage", "engine2d",
              "suggest", "handoff")


def settings_from(text_or_path):
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    t = (text_or_path or "").strip()
    if not t:
        return s
    if os.path.isfile(t):
        with open(t, encoding="utf-8") as fh:
            t = fh.read()
    loaded = json.loads(t)
    if not isinstance(loaded, dict):
        raise ValueError("settings must be a JSON object")
    s.update(loaded)
    return s


def check(status, title, detail="", fix=""):
    return {"status": status, "title": title, "detail": detail, "fix": fix}


def receptor_fields_used(config):
    """Receptor attribute names the enabled methods reference (from the rule language)."""
    out = set()

    def walk(c):
        if isinstance(c, list) and len(c) == 3 and isinstance(c[0], str):
            if not c[0].startswith("@") and c[0] not in ("wet", "receptor_type"):
                out.add(c[0])
        elif isinstance(c, dict):
            for x in c.get("all", []) + c.get("any", []):
                walk(x)
    for m in config.get("methods", {}).values():
        for r in (m.get("receptor_rules") or []):
            walk(r["when"])
        for e in (m.get("counts") or []):
            walk(e["select"])
    return out


def preflight(work, settings, dams=None, dam_problems=None, receptors=None, receptor_fields=None,
              disk_free_mb=None):
    """OK / WARN / FAIL checks. Missing inputs are WARN or FAIL, never silently passed.
    ``dams``: prepared dam records (or None if no layer); ``receptors``: receptor records."""
    checks = []
    if not work:
        checks.append(check(FAIL, "Work folder", "none given", "Choose a work folder."))
    else:
        checks.append(check(OK, "Work folder", work))
    if disk_free_mb is not None:
        checks.append(check(OK if disk_free_mb >= MIN_FREE_MB else WARN, "Disk space",
                            "{:.0f} MB free".format(disk_free_mb), "Free space in the work folder's disk."))
    try:
        cat = CB.load_catalog(settings.get("catalog_dir") or None)
        checks.append(check(OK, "DamIT Catalog", "{} ({} presets, {} methods)".format(
            cat.version, len(cat.presets), len(cat.methods))))
    except Exception as e:                                       # noqa
        checks.append(check(FAIL, "DamIT Catalog", str(e), "Install DamIT Catalog or fix the data folder."))
        return checks, None, None
    mode = (settings.get("mode") or "preset").lower()
    if mode not in ("preset", "custom"):
        checks.append(check(FAIL, "Mode", "unknown mode {!r}".format(mode), "Use 'preset' or 'custom'."))
        return checks, cat, None
    if mode == "preset" and not settings.get("preset"):
        checks.append(check(FAIL, "Preset", "preset mode with no preset chosen",
                            "Pick one of: " + ", ".join(cat.preset_ids()) + " (or use custom mode)."))
        return checks, cat, None
    try:
        config = CB.resolve(cat, settings)
    except Exception as e:                                       # noqa
        checks.append(check(FAIL, "Preset / method selection", str(e), "Fix the preset, scenario or method IDs."))
        return checks, cat, None
    checks.append(check(OK, "Mode", "{}{}".format(mode, ": " + config["preset_label"] if mode == "preset" else
                                                    " ({} method(s))".format(len(config["methods"])))))
    for f in config.get("flags", []):
        st = WARN
        checks.append(check(st, "Catalog flag: " + f["code"], f["message"],
                            "Confirm with the engineer of record before relying on it."))
    if not config["scenarios"]:
        checks.append(check(WARN, "Scenarios", "no scenario selected; hand-off packages will say "
                            "'scenario unconfirmed'", "Set 'scenarios' (S-codes) in the settings."))
    else:
        checks.append(check(OK, "Scenarios", ", ".join(s["id"] for s in config["scenarios"])))
    if dams is None:
        checks.append(check(FAIL, "Dams layer", "none given", "Choose the dams point layer."))
    elif not dams:
        checks.append(check(FAIL, "Dams layer", "no usable dam records", "Check the dam id field mapping."))
    else:
        checks.append(check(OK, "Dams layer", "{} dam(s)".format(len(dams))))
    for p in dam_problems or []:
        checks.append(check(FAIL, "Dam record", p, "Fix the record or the field mapping."))
    needs = list(cat.dam_fields_all)
    for s in config["scenarios"]:
        needs += [n for n in s.get("dam_fields", []) if n not in needs]
    for d in dams or []:
        miss = ST.missing_dam_fields(d, needs)
        if miss:
            checks.append(check(WARN, "Dam {} inputs".format(d["dam_id"]), "missing: " + ", ".join(miss),
                                "Add the fields (or map them) so the scenario pool and storage can be set."))
    if settings.get("terrain"):
        ok = os.path.exists(settings["terrain"])
        checks.append(check(OK if ok else FAIL, "Terrain (DEM)", settings["terrain"],
                            "" if ok else "The DEM path does not exist."))
    else:
        checks.append(check(WARN, "Terrain (DEM)", "none given", "The Runner needs a DEM for each dam."))
    if receptors is None:
        checks.append(check(WARN, "Receptors", "none given: no triage or preliminary suggestion",
                            "Give a receptor layer (structures, roads, rail, ...) to screen."))
    else:
        used = receptor_fields_used(config)
        have = set(receptor_fields or [])
        for r in receptors:
            have |= {k for k, v in r.items() if v not in (None, "")}
        miss = sorted(used - have)
        checks.append(check(WARN if miss else OK, "Receptor fields",
                            ("missing for the enabled methods: " + ", ".join(miss)) if miss else
                            "{} receptor(s); fields cover the enabled methods".format(len(receptors)),
                            "Add the fields; methods without their inputs are flagged, not passed."))
        if not ST.has_hydraulics(receptors):
            checks.append(check(WARN, "Receptor hydraulics", "no depth / DV / chart-zone fields: the "
                                "preliminary suggestion will not be computed", "Run the Runner, then DamIT Hazard."))
    if "M1" in config["methods"] and config["methods"]["M1"]["params"].get("require_2d"):
        dim = str((settings.get("summary") or {}).get("model_dimension") or "").upper()
        checks.append(check(OK if dim == "2D" else WARN, "M1 requires a 2D model",
                            "model_dimension = {}".format(dim or "not given"),
                            "Use a 2D run, or M1 is blocked and flagged."))
    return checks, cat, config


def ready(checks):
    return not any(c["status"] == FAIL for c in checks)


def report_lines(checks):
    return ["{:4} {}: {}{}".format(c["status"].upper(), c["title"], c["detail"],
                                   (" -> " + c["fix"]) if c["fix"] and c["status"] != OK else "") for c in checks]


def dam_receptors(receptors, dam_id):
    """Receptors linked to a dam (receptor 'dam_id' field), or all if none carry a dam_id."""
    if not receptors:
        return []
    if any(r.get("dam_id") not in (None, "") for r in receptors):
        return [r for r in receptors if str(r.get("dam_id")) == str(dam_id)]
    return list(receptors)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, path)
    return path


def dam_folder(work, dam_id):
    _, _, HO = CB.modules()
    return os.path.join(work, "dams", HO.safe_name(dam_id))


def handoff_folder(work, dam_id):
    _, _, HO = CB.modules()
    return os.path.join(work, "handoff", HO.safe_name(dam_id))


def build_handoff(cat, config, dam, results, settings, receptors_json=None):
    """The damit.handoff package for one dam from its step results."""
    _, _, HO = CB.modules()
    gaps = []
    for k in STEP_ORDER:
        r = results.get(k)
        if r and r["status"] in (ST.STATUS_GAP, ST.STATUS_FAIL, ST.STATUS_NOT_RUN):
            gaps.append({"step": k, "status": r["status"], "detail": r["detail"]})
    st = results.get("storage") or {}
    hy = results.get("hydrograph") or {}
    bd = results.get("breach_direction") or {}
    te = results.get("terrain") or {}
    d = {k: dam.get(k) for k in ST.DAM_FIELDS if k not in ("hydrograph_csv", "storage_curve_csv", "flood_hydrograph_csv")}
    d.update({"x": dam.get("x"), "y": dam.get("y"), "crs": dam.get("crs"),
              "storage_top_of_dam_acft": st.get("top_of_dam_acft"),
              "scenario_pools": st.get("by_scenario") or {},
              "breach_azimuth_deg": bd.get("azimuth_deg", dam.get("breach_azimuth_deg")),
              "peak_outflow_cfs": hy.get("peak_cfs"),
              "reference_peaks_cfs": hy.get("reference_peaks_cfs") or {}})
    inputs = {"terrain": te.get("path"), "hydrograph_csv": hy.get("hydrograph_csv"),
              "storage_curve_csv": dam.get("storage_curve_csv"), "receptors_json": receptors_json,
              "flood_hydrograph_csv": dam.get("flood_hydrograph_csv")}
    sug = (results.get("suggest") or {}).get("screening")
    tri = results.get("triage") or {}
    screening = dict(sug) if sug else {"status": "not_computed"}
    if sug and sug.get("status") == "computed_preliminary":
        screening = {k: sug[k] for k in ("status", "suggested_ordinal", "suggested_label", "generic_label",
                                         "per_scenario", "driving", "advisories", "modifiers_applied",
                                         "modifiers_reported", "flags", "apply_advisories", "citations")}
    screening["triage"] = {k: tri.get(k) for k in ("ordinal", "generic_label", "recommend_detailed_run")} if tri else None
    pkg = HO.build(config, d, inputs, screening, gaps,
                   created_by={"plugin": "damit_screener", "version": VERSION, "algorithm": HO.SCREENER_ALG},
                   apply_advisories=settings.get("apply_advisories"))
    return pkg


def run_dam(cat, config, dam, settings, work, receptors=None, terrain_info=None, log=print):
    """All screening steps for one dam. Returns the per-step results dict (+ 'handoff_path')."""
    _, _, HO = CB.modules()
    res = {"prepare": ST.step(ST.STATUS_OK, "dam record prepared")}
    scen = config["scenarios"]
    res["terrain"] = ST.terrain(dam, settings.get("terrain") or dam.get("terrain"), terrain_info)
    res["storage"] = ST.storage(dam, scen)
    res["breach_direction"] = ST.breach_direction(dam)
    res["hydrograph"] = ST.hydrograph(dam, res["storage"], scen)
    recs = dam_receptors(receptors, dam["dam_id"])
    res["triage"] = ST.triage(cat, dam, recs)
    res["engine2d"] = ST.engine2d(dam)
    summ = dict(settings.get("summary") or {})
    summ.setdefault("storage_acft", res["storage"].get("top_of_dam_acft"))
    res["suggest"] = ST.suggest(cat, config, dam, recs, summ, settings.get("apply_advisories"))
    folder = dam_folder(work, dam["dam_id"])
    rjson = None
    if recs:
        rjson = _write_json(os.path.join(folder, "receptors.json"), recs)
    _write_json(os.path.join(folder, "steps.json"), res)
    pkg = build_handoff(cat, config, dam, res, settings, rjson)
    errs = HO.validate(pkg, cat)
    if errs:
        res["handoff"] = ST.step(ST.STATUS_FAIL, "package invalid: " + "; ".join(errs))
    else:
        path = HO.write(pkg, handoff_folder(work, dam["dam_id"]))
        res["handoff"] = ST.step(ST.STATUS_OK, "hand-off package written", path=path)
        res["handoff_path"] = path
    for k in STEP_ORDER:
        if k in res:
            log("  {} {:16} {} {}".format(dam["dam_id"], k, res[k]["status"].upper(), res[k]["detail"]))
    return res


def run_chain(work, settings, dams, dam_problems=None, receptors=None, receptor_fields=None,
              terrain_info=None, do_preflight=True, log=print):
    """Preflight, then every selected dam through the steps. Returns a summary dict."""
    disk = None
    try:
        os.makedirs(work, exist_ok=True)
        disk = shutil.disk_usage(work).free / 1024.0 ** 2
    except OSError:
        pass
    checks, cat, config = preflight(work, settings, dams, dam_problems, receptors, receptor_fields, disk)
    for line in report_lines(checks):
        log(line)
    if (do_preflight and not ready(checks)) or cat is None or config is None:
        return {"ok": False, "refused": True, "checks": checks, "dams": {}, "work": work}
    sel = [d for d in dams if not settings.get("dam_ids") or d["dam_id"] in settings["dam_ids"]]
    out = {}
    for d in sel:
        out[d["dam_id"]] = run_dam(cat, config, d, settings, work, receptors, terrain_info, log)
    summary = {"ok": all(r.get("handoff", {}).get("status") == ST.STATUS_OK for r in out.values()),
               "refused": False, "checks": checks, "work": work, "mode": config["mode"],
               "preset_id": config.get("preset_id"), "scenarios": [s["id"] for s in config["scenarios"]],
               "catalog": cat.identity(), "dams": out,
               "finished": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    _write_json(os.path.join(work, "damit_screen", "chain_summary.json"), summary)
    rep = write_report(work, summary, cat, config)
    summary["report"] = rep
    return summary


def write_report(work, summary, cat, config):
    """Markdown run report: scenarios, parameters, flags and citations per Appendix A.7."""
    lines = ["# DamIT Screener run report", "",
             "Suggested classifications only. The engineer of record and the regulating agency make the "
             "determination.", "",
             "- Catalog: {} (sha256 {})".format(cat.version, cat.digest[:12]),
             "- Mode: {}{}".format(config["mode"], " - " + config["preset_label"] if config["mode"] == "preset" else ""),
             "- Scenarios: {}".format(", ".join(s["id"] for s in config["scenarios"]) or "none (unconfirmed)"),
             "- Domain cutoffs: {}".format(", ".join(d["id"] for d in config["domain_cutoffs"]) or "none"),
             "- Methods: {}".format(", ".join("{} ({})".format(k, m["strength"]) for k, m in config["methods"].items())),
             "- Modifiers: {}".format(", ".join(r["id"] for r in config["modifiers"]) or "none"), "",
             "| Dam | Suggested | Triage (M13) | Gaps | Hand-off |", "|---|---|---|---|---|"]
    for did, r in summary["dams"].items():
        sc = (r.get("suggest") or {}).get("screening") or {}
        tri = r.get("triage") or {}
        gaps = [k for k in STEP_ORDER if (r.get(k) or {}).get("status") in ("gap", "fail", "not_run")]
        lines.append("| {} | {} | {} | {} | {} |".format(did, sc.get("suggested_label") or "not computed",
                                                         tri.get("generic_label") or "-", ", ".join(gaps) or "none",
                                                         r.get("handoff_path") or "not written"))
    lines += ["", "## Parameters", ""]
    for k, m in config["methods"].items():
        lines.append("- {} {}: {}".format(k, m["name"], json.dumps(m.get("params", {}), sort_keys=True)))
    lines += ["", "## Flags", ""]
    for c in summary["checks"]:
        if c["status"] != OK:
            lines.append("- {} {}: {}".format(c["status"].upper(), c["title"], c["detail"]))
    lines += ["", "## Citations", ""]
    for k, v in sorted(cat.citations(config).items()):
        lines.append("- {}: {}".format(k, v))
    path = os.path.join(work, "reports", "damit_screener_report.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
