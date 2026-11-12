"""The run report: Markdown, HTML and JSON from a classify() result.

Sections: suggestion (class, local label, driving receptors and method IDs), advisory results,
per-scenario classes, flags, configuration (scenarios, methods with parameters and strength,
modifiers), modifier notes, inputs (layers with their versions, run date: R10), citations and
the disclaimer. In custom mode the configuration lists method names and parameters only; the
sources appear in the Citations section so an engineer can trace each rule (Appendix A.7).
"""
import html
import json

MAX_IDS = 12


def _ids(ids):
    ids = list(ids or [])
    if not ids:
        return "-"
    s = ", ".join(str(i) for i in ids[:MAX_IDS])
    return s + (" … (+{})".format(len(ids) - MAX_IDS) if len(ids) > MAX_IDS else "")


def _params(p):
    return json.dumps(p, sort_keys=True, ensure_ascii=False)


def _nodata_sampling_lines(result):
    """One Inputs line per run: depth-grid cell size, the 20 m threshold, and which NoData path applies."""
    out = []
    for p in result.get("nodata_sampling") or []:
        cell = p.get("cell_m")
        min_m = p.get("nodata_neighbourhood_min_cell_m", 20.0)
        allowed = p.get("neighbourhood_allowed")
        cell_s = "{:g} m".format(cell) if cell is not None else "unknown"
        path = ("neighbourhood fill (sampling=neighbourhood, flag nodata_neighbourhood)"
                if allowed else
                "NoData scored dry (sampling=centre_nodata_dry, flag nodata_dry_review)")
        who = p.get("scenario") or p.get("label") or "run"
        out.append("NoData receptors ({}): depth-grid cell {} (larger side, converted to metres); "
                   "neighbourhood fill only when the cell is coarser than "
                   "NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m (strictly greater than). This run: {}."
                   .format(who, cell_s, min_m, path))
    return out


def _dam_line(result):
    """The Inputs line for the dam record, in words (0.2.2). It used to print the record as JSON, so a run with no dam
    record file showed only {"name": "..."} (the DAM_NAME input) as if that were the record."""
    dam = {k: v for k, v in (result.get("dam") or {}).items() if v not in (None, "")}
    name = dam.pop("name", None)
    from_file = any(L.get("role") == "dam record" for L in result.get("layers") or [])
    searched = [L for L in result.get("layers") or [] if L.get("role") == "dam record search"]
    if not from_file:
        txt = "Dam record: none given or found" + (" ({})".format(searched[0].get("note")) if searched else "")
        if name:
            txt += "; only the name was given: {}".format(name)
        if dam:
            txt += "; other values set: " + ", ".join("{} = {}".format(k, _scalar(dam[k])) for k in sorted(dam))
        return txt
    txt = "Dam record: " + (name if name else "(no name)")
    if dam:
        txt += " (" + ", ".join("{} = {}".format(k, _scalar(dam[k])) for k in sorted(dam)) + ")"
    return txt


def _scalar(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)


def sections(result, cat):
    """[(title, [lines] | ("table", header, rows))] - one structure for every format."""
    cfg = result["config"]
    lab = cfg["labels"]
    out = []
    head = ["**Suggested class: {} ({} / ordinal {})**".format(
        result["suggested_label"], result["generic_label"], result["suggested_class"])]
    if cfg["mode"] == "preset":
        v = cfg.get("preset_verification")
        head.append("Preset: {}{}".format(cfg["preset_label"],
                                          "" if v == "verified" else " ({})".format(v)))
    else:
        head.append("Custom mode: generic labels")
    head.append("Rule class {} · with advisory results {} · advisory {}".format(
        lab.get(result["rule_class"]), lab.get(result["class_with_advisory"]),
        "applied (opt-in)" if result["advisory_applied"] else "reported, not applied"))
    if result.get("design_requirement"):
        head.append("Design requirement: {}".format(result["design_requirement"]))
    head.append("Run date: {} · catalog {}".format(result["run_date"],
                                                   result.get("catalog_version")))
    out.append(("Suggestion", head))
    out.append(("Driving receptors and methods", ("table", ["Method", "Class", "Strength",
                                                             "Scenario", "Receptors", "Why"],
        [[h["method"], lab.get(h["class"]), h["strength"], h.get("scenario") or "-",
          _ids(h["receptors"]), h["reason"]] for h in result["driving"]])))
    out.append(("Advisory results", ("table", ["Method", "Class", "Scenario", "Receptors", "Why"],
        [[h["method"], lab.get(h["class"]), h.get("scenario") or "-", _ids(h["receptors"]),
          h["reason"]] for h in result["advisory"]])))
    out.append(("Scenarios", ("table", ["Scenario", "Run", "Model", "Class", "Receptors",
                                        "Scored"],
        [[p["scenario"] or "?", p["label"], p["model_dim"] or "?", lab.get(p["class"]),
          p["receptors"], p["scored"]] for p in result["per_scenario"]])))
    order = {"error": 0, "warning": 1, "info": 2}
    fl = sorted(result["flags"], key=lambda f: order.get(f["level"], 3))
    out.append(("Flags", ("table", ["Level", "Code", "Method", "Scenario", "Receptors",
                                    "Message"],
        [[f["level"], f["code"], f.get("method") or "-", f.get("scenario") or "-",
          "{} ({})".format(_ids(f["receptors"]), len(f["receptors"])) if f["receptors"]
          else "-", f["message"]] for f in fl])))
    # configuration
    rows = []
    for sid in cfg["scenarios"]:
        s = cat["scenarios"][sid]
        rows.append([sid, s["name"], s["condition"]])
    for sid, why in cfg.get("optional_scenarios", {}).items():
        rows.append([sid + " (optional)", cat["scenarios"][sid]["name"], why])
    for did, p in cfg.get("domains", {}).items():
        rows.append([did, cat["domains"][did]["name"], _params(p)])
    out.append(("Scenarios and domain cutoffs enabled", ("table", ["ID", "Name", "Condition"],
                                                         rows)))
    mrows = []
    for mid, e in cfg["methods"].items():
        m = cat["methods"][mid]
        row = [mid, m["name"], e["strength"], _params(e["params"])]
        if cfg["mode"] == "preset":
            row.append(m.get("verification", ""))
        mrows.append(row)
    hdr = ["ID", "Method", "Strength", "Parameters"] + (["Verification"]
                                                       if cfg["mode"] == "preset" else [])
    out.append(("Methods", ("table", hdr, mrows)))
    out.append(("Modifiers", ("table", ["ID", "Modifier", "Parameters"],
        [[rid, cat["modifiers"][rid]["name"], _params(e["params"])]
         for rid, e in cfg["modifiers"].items()])))
    out.append(("Modifier notes", ["{}: {}".format(k, v) for k, v in result["modifier_notes"]]
                or ["-"]))
    out.append(("Labels", ["{} = {}".format(k, v) for k, v in sorted(lab.items())]))
    lines = []
    for L in result.get("layers") or []:
        if L.get("role") == "dam record search":          # said in the "Dam record:" line below
            continue
        lines.append("{}: {} (modified {}, {} bytes{})".format(
            L.get("role"), L.get("source"), L.get("modified"), L.get("size"),
            ", " + L["note"] if L.get("note") else ""))
    if result.get("nid_id"):
        lines.append("NID ID: {} (USACE National Inventory of Dams)".format(result["nid_id"]))
    lines.append(_dam_line(result))
    lines.extend(_nodata_sampling_lines(result))
    out.append(("Inputs (R10: re-run when these change)", lines or ["-"]))
    cites = []
    if cfg["mode"] == "preset":
        cites.append("Preset {}: {} {}".format(cfg["preset"], cfg.get("preset_notes", ""),
                                               "(verification: {})".format(
                                                   cfg.get("preset_verification"))))
    for sid in cfg["scenarios"] + list(cfg.get("optional_scenarios", {})):
        s = cat["scenarios"][sid]
        cites.append("{}: {} [{}]".format(sid, s["source"], s["verification"]))
    for did in cfg.get("domains", {}):
        d = cat["domains"][did]
        cites.append("{}: {} [{}]".format(did, d["source"], d["verification"]))
    for mid in cfg["methods"]:
        m = cat["methods"][mid]
        cites.append("{}: {} [{}]{}".format(mid, m["source"], m["verification"],
                                           " " + m["verification_note"]
                                           if m.get("verification_note") else ""))
    for rid in cfg["modifiers"]:
        m = cat["modifiers"][rid]
        cites.append("{}: {} [{}]".format(rid, m["source"], m["verification"]))
    cites.append("Source document: " + (result.get("source_document") or ""))
    dc = result.get("damit_catalog") or {}
    if dc:
        cites.append("DamIT Catalog {} (sha256 {}) from {}".format(
            dc.get("catalog_version"), dc.get("sha256"), dc.get("folder")))
    out.append(("Citations", cites))
    out.append(("Disclaimer", [result.get("disclaimer") or ""]))
    return _display_units(out)


_FREE_TEXT_COLUMNS = ("Why", "Message", "Condition")
_KEEP_SECTIONS = ("Labels", "Inputs (R10: re-run when these change)", "Citations")


def _display_units(out):
    """Under the DamIT SI display setting, quantities in the free-text parts of the report
    (reasons, flag messages, notes) are shown in SI and the report says so. Parameters, the
    dam record, inputs and citations stay as stored (US); the JSON report is never converted."""
    try:
        from damit_core.lib import display_units as DU
    except Exception:                                             # noqa - older DamIT Core
        return out
    if DU.system() != DU.SI:
        return out
    conv = []
    for name, body in out:
        if name in _KEEP_SECTIONS:
            pass
        elif isinstance(body, tuple):
            _t, hdr, rows = body
            cols = [i for i, h in enumerate(hdr) if h in _FREE_TEXT_COLUMNS]
            body = (_t, hdr, [[DU.convert_text(c) if i in cols and isinstance(c, str) else c
                               for i, c in enumerate(r)] for r in rows])
        else:
            body = [DU.convert_text(x) if isinstance(x, str) else x for x in body]
        conv.append((name, body))
    if conv and not isinstance(conv[0][1], tuple):
        conv[0] = (conv[0][0], list(conv[0][1]) + [
            "Units: SI in reasons and messages, converted from the US values the "
            "classification uses; parameters, the dam record and the JSON report keep US units."])
    return conv


def markdown(result, cat, title="DamIT Hazard run report"):
    out = ["# " + title, ""]
    for name, body in sections(result, cat):
        out += ["## " + name, ""]
        if isinstance(body, tuple):
            _t, hdr, rows = body
            if not rows:
                out += ["(none)", ""]
                continue
            out.append("| " + " | ".join(hdr) + " |")
            out.append("|" + "---|" * len(hdr))
            for r in rows:
                out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ")
                                             for c in r) + " |")
            out.append("")
        else:
            out += ["- " + x if name in ("Citations", "Modifier notes", "Inputs (R10: re-run "
                                         "when these change)", "Labels") else x
                    for x in body] + [""]
    return "\n".join(out)


def html_report(result, cat, title="DamIT Hazard run report"):
    e = html.escape
    out = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>{}</title>".format(e(title)),
           "<style>body{font-family:sans-serif;max-width:70em;margin:1em auto}"
           "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:3px;"
           "vertical-align:top;font-size:90%;word-break:break-word}</style></head><body>",
           "<h1>{}</h1>".format(e(title))]
    for name, body in sections(result, cat):
        out.append("<h2>{}</h2>".format(e(name)))
        if isinstance(body, tuple):
            _t, hdr, rows = body
            if not rows:
                out.append("<p>(none)</p>")
                continue
            out.append("<table><tr>" + "".join("<th>{}</th>".format(e(h)) for h in hdr) + "</tr>")
            for r in rows:
                out.append("<tr>" + "".join("<td>{}</td>".format(e(str(c))) for c in r) +
                           "</tr>")
            out.append("</table>")
        else:
            out.append("<ul>" + "".join("<li>{}</li>".format(e(x).replace("**", ""))
                                        for x in body) + "</ul>")
    out.append("</body></html>")
    return "\n".join(out)


def as_json(result):
    def conv(o):
        if isinstance(o, set):
            return sorted(o)
        if isinstance(o, tuple):
            return list(o)
        try:
            return float(o)
        except Exception:
            return str(o)
    return json.dumps(result, indent=1, default=conv, ensure_ascii=False)
