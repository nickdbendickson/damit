"""DamIT Hazard's view of DamIT Catalog: the run configuration the classifier reads.

DamIT Catalog (``damit_catalog``, a separate plugin) is the single source of truth for Appendix A:
methods M1-M13, scenarios S1-S7, domain cutoffs D1-D2, modifiers R1-R10, class labels and the
jurisdiction presets (``damit_catalog/data/*.json``; ``DAMIT_CATALOG_DIR`` points at an edited
copy). :func:`load` reads it and translates it to the shape the classifier evaluates. Every
threshold comes from the catalog's methods / modifiers / scenarios / presets files; the catalog's
``hazard.json`` adds only what those do not express (receptor-type vocabulary, TM-11 chart
assignment, sampling defaults, Hazard-specific engine switches and per-preset notes). Nothing
here knows a number of any rule.

``python3 -m damit_hazard.engine.catalog --export out.json`` writes the translated catalog (for
tools that want one JSON file, e.g. DamIT Crest's jurisdiction index).
"""
import copy
import json
import os

from . import catalog_bridge

GENERIC_LABELS = {0: "Minimal", 1: "Low", 2: "Significant", 3: "High", 4: "Extremely High"}
# the order the methods are evaluated in: lethality first (M6 / M5 / M7 read it), the
# low-volume road exclusion before the descriptor fallback that would otherwise score those roads
EVAL_ORDER = ("M1", "M2", "M3", "M4a", "M4b", "M4c", "M5", "M6", "M7",
              "M8e", "M8a", "M8b", "M8c", "M8d", "M8f", "M8g",
              "M9a", "M9b", "M9c", "M10a", "M10b", "M11a", "M11b", "M11c",
              "M12a", "M12b", "M12c", "M12d", "M13")
STRENGTHS = ("rule", "advisory")

# catalog parameter name -> classifier parameter name, where it is a plain rename. Used for the
# translation and so OVERRIDES may use either name.
RENAMES = {
    "M1": {"datum": "depth_datum"},
    "M2": {"depth_ft": "threshold_ft", "datum": "depth_datum"},
    "M4a": {"n_min": "min_count"},
    "M4b": {"shallow_depth_ft": "depth_split_ft"},
    "M7": {"lives_min": "min_lives", "population_min": "min_population"},
    "M8c": {"depth_ft": "depth_split_ft"},
    "M8d": {"high_classes": "high", "significant_classes": "significant", "low_classes": "low"},
    "M8f": {"homes_min": "min_homes_isolated"},
    "M8g": {"municipal_roads_min": "min_municipal_washouts"},
    "M9a": {"freight_high_trains_per_day": "high_min_trains_per_day"},
    "M9b": {"main_line_trains_per_day": "main_min_trains_per_day", "depth_ft": "depth_split_ft"},
    "M10a": {"hospital_depth_ft": "hospital_high_depth_ft", "datum": "depth_datum"},
    "M11b": {"outage_high_days": "high_outage_days_over"},
    "M11c": {"important_units_min": "important_min_units",
             "significant_outage_max_days": "sig_max_outage_days",
             "wastewater_significant_sizes": "wastewater_sig_classes"},
    "R6": {"distance_mi_by_city_class": "distance_mi"},
    "R8": {"storage_acft_limit": "storage_limit_acft"},
    "R9": {"may_lower_class": "may_lower"},
    "D1": {"incremental_rise_ft": "max_rise_ft"},
    "D2": {"convergence_ft": "max_rise_ft"},
}


class CatalogError(ValueError):
    pass


# =========================================================================== loading ==
def source(folder=None):
    """The DamIT Catalog object (``damit_catalog.catalog.Catalog``)."""
    dc = catalog_bridge.damit_catalog()
    try:
        return dc.load(folder or None)
    except dc.CatalogError as e:
        raise CatalogError(str(e))


def load(path=None):
    """The classifier catalog, translated from DamIT Catalog.

    path: a DamIT Catalog data folder (or its catalog.json manifest). Default: what DamIT Catalog
    picks (DAMIT_CATALOG_DIR, else its bundled data/)."""
    folder = path
    if path and os.path.isfile(path):
        folder = os.path.dirname(os.path.abspath(path))
        with open(path, encoding="utf-8") as f:
            head = json.load(f)
        if head.get("schema") != "damit.catalog":
            raise CatalogError("{} is not a DamIT Catalog manifest (schema 'damit.catalog'); DamIT Hazard "
                               "reads its presets and thresholds from DamIT Catalog".format(path))
    cat = build(source(folder))
    problems = validate(cat)
    if problems:
        raise CatalogError("DamIT Catalog as read by DamIT Hazard: " + "; ".join(problems))
    return cat


# ======================================================================= translation ==
def _terms(cond):
    """Flatten a catalog condition ({"all"/"any": [...]}, nested) to [field, op, value] terms."""
    out = []
    if isinstance(cond, dict):
        for k in ("all", "any"):
            for c in cond.get(k) or []:
                out += _terms(c)
    elif isinstance(cond, (list, tuple)) and len(cond) == len(("f", "op", "v")) and \
            isinstance(cond[0], str):
        out.append(list(cond))
    return out


def _val(v, params):
    return params.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v


def _datum_of(src, field):
    for name, f in src.datums.items():
        if f == field:
            return name
    raise CatalogError("no datum for field {!r}".format(field))


def _rule_classes(rec, field, params):
    """{class: [values]} of the 'field eq / in' terms of a method's receptor rules."""
    out = {}
    for r in rec.get("receptor_rules") or []:
        for f, op, v in _terms(r.get("when")):
            if f != field:
                continue
            v = _val(v, params)
            out.setdefault(r["class"], [])
            out[r["class"]] += list(v) if op == "in" else [v] if op == "eq" else []
    return out


def _rule_literal(rec, label, fields, params):
    """The value a method's labelled receptor rule compares one of ``fields`` with."""
    for r in rec.get("receptor_rules") or []:
        if r.get("label") == label:
            for f, _op, v in _terms(r.get("when")):
                if f in fields:
                    return _val(v, params)
    raise CatalogError("{}: no rule {!r} reading a depth".format(rec.get("name"), label))


def _rule_datum(src, rec, label):
    """The datum ('ground' / 'foundation' / 'floor') of the depth a method's labelled receptor rule
    reads (e.g. M3 'institution High' reads the lowest floor)."""
    fields = list(src.datums.values())
    for r in rec.get("receptor_rules") or []:
        if r.get("label") == label:
            for f, _op, _v in _terms(r.get("when")):
                if f in fields:
                    return _datum_of(src, f)
    raise CatalogError("{}: no rule {!r} reading a depth".format(rec.get("name"), label))


def _bands(count):
    return [(b["min"], b.get("max"), b["class"]) for b in count["bands"]]


def _band_class(bands, n, params):
    for lo, hi, cls in bands:
        lo, hi = _val(lo, params), _val(hi, params)
        if n >= lo and (hi is None or n <= hi):
            return cls
    return None


def _min_for(bands, cls, params):
    m = [_val(lo, params) for lo, _hi, c in bands if c == cls]
    return min(m) if m else None


def _renamed(key, params):
    ren = RENAMES.get(key, {})
    return {ren.get(k, k): copy.deepcopy(v) for k, v in params.items()}


def _structure_types(hz, catalog_types):
    m = hz["receptor_types"]["structure_type_map"]
    return [t for t, c in m.items() if c in catalog_types]


def _road(hz, classes):
    m = hz["receptor_types"]["road_class_map"]
    return [m.get(c, c) for c in classes]


def method_params(src, hz, mid, cp):
    """Classifier parameters of method ``mid`` from catalog parameters ``cp`` (already merged
    with the preset / user overrides in catalog names)."""
    rec = src.methods[mid]
    extra = copy.deepcopy(((hz.get("methods") or {}).get(mid) or {}).get("params") or {})
    p = _renamed(mid, cp)
    ret = rec.get("returns")
    if mid == "M1":
        zones = cp.get("class_zones") or []
        high = ret.get("high_danger") if isinstance(ret, dict) else ret
        names = hz["charts"]["names"]
        p = {"charts": [names.get(c, c) for c in cp.get("charts") or []],
             "depth_datum": cp["datum"], "require_2d": bool(cp.get("require_2d")),
             "high_class": high if "high_danger" in zones else None,
             "above_low_class": high if "judgment" in zones else None}
    elif mid == "M2":
        types = _structure_types(hz, cp.get("structure_types") or [])
        p = {"threshold_ft": cp["depth_ft"], "comparator": cp["comparator"],
             "depth_datum": cp["datum"], "only_if_1d": bool(cp.get("only_if_1d")),
             # every habitable type: the occupied-habitable test (unknown type = a home)
             "receptor_types": "habitable" if set(hz["receptor_types"]["habitable_types"]) <=
             set(types) else types}
    elif mid in ("M3", "M10b"):
        m3 = src.methods["M3"]
        m3p = dict(m3.get("params") or {})
        if mid == "M3":
            m3p.update(cp)
        rows = copy.deepcopy(hz["methods"]["M3"]["params"]["rows"])
        for rname, cells in hz["methods"]["M3"]["row_params"].items():
            row = rows[rname]
            for cell, ref in cells.items():
                if cell == "low_below_rule":
                    row["low_below_ft"] = _rule_literal(m3, ref, list(src.datums.values()), m3p)
                elif cell == "datum_rule":            # Significant / Low split datum
                    row["datum"] = _rule_datum(src, m3, ref)
                elif cell == "high_datum_rule":       # High test datum
                    row["high_datum"] = _rule_datum(src, m3, ref)
                else:
                    row[cell] = m3p[ref]
        walkout = m3p.get("walkout_high_depth_ft")
        opt = walkout is not None and walkout != m3p.get("home_high_depth_ft")
        rows["home"]["walkout_high_depth_ft"] = walkout if opt else \
            m3p.get("walkout_high_depth_ft_allowed")
        if mid == "M3":
            p = {"rows": rows, "walkout_option": opt,
                 "rows_note": hz["methods"]["M3"]["params"].get("rows_note", "")}
            extra = {}
        else:
            row = extra.get("m3_row", "institution")
            rows[row]["high_depth_ft"] = cp["institution_high_depth_ft"]
            rows[row]["high_dv"] = cp["institution_high_dv"]
            p = {"m3_row": row, "rows": {row: rows[row]}}
    elif mid == "M4a":
        sel = rec["counts"][0]["select"]
        field = next(f for f, _o, v in _terms(sel) if v == "$depth_ft")
        p = {"min_count": cp["n_min"], "depth_ft": cp["depth_ft"],
             "depth_datum": _datum_of(src, field)}
    elif mid == "M4b":
        up = over = above = None
        field = None
        for c in rec["counts"]:
            ts = _terms(c["select"])
            if any(f == "m1_zone" for f, _o, _v in ts):
                above = c
            for f, o, v in ts:
                if v == "$shallow_depth_ft":
                    field = f
                    if o == "<=":
                        up = c
                    elif o == ">":
                        over = c
        if not (up and over and above and field):
            raise CatalogError("M4b: the catalog counts are not the homes x depth table")
        bands = _bands(up)
        p = {"depth_datum": _datum_of(src, field), "depth_split_ft": cp["shallow_depth_ft"],
             "count_bands": [[_val(lo, cp), _val(hi, cp)] for lo, hi, _c in bands],
             "table": {"up_to_split": [c for _l, _h, c in bands],
                       "over_split": [_band_class(_bands(over), _val(lo, cp), cp)
                                      for lo, _h, _c in bands],
                       "above_low_danger": [_band_class(_bands(above), _val(lo, cp), cp)
                                            for lo, _h, _c in bands]}}
    elif mid == "M4c":
        lives = next(c for c in rec["counts"] if str(c.get("measure", "")).startswith("sum:"))
        structs = next(c for c in rec["counts"] if c.get("measure") == "count")
        sig, high = ret.get("Significant"), ret.get("High")
        p = {"lives_sig_min": _min_for(_bands(lives), sig, cp),
             "lives_high_min": _min_for(_bands(lives), high, cp),
             "structures_sig_min": _min_for(_bands(structs), sig, cp),
             "structures_high_min": _min_for(_bands(structs), high, cp)}
    elif mid == "M5":
        p = {"sig_min": cp.get("sig_min"), "high_min": cp.get("high_min"),
             "purpose": "lowering_only" if cp.get("lowering_only") else "classify"}
    elif mid == "M6":
        p = {"variant": hz["variant_map"]["M6"].get(cp.get("variant"), cp.get("variant"))}
    elif mid == "M8a":
        by = _rule_classes(rec, "road_class", cp)
        p.update({"high_classes": _road(hz, by.get(ret["High"], [])),
                  "sig_classes": _road(hz, by.get(ret["Significant"], [])),
                  "low_classes": _road(hz, by.get(ret["Low"], []))})
    elif mid == "M8g":
        by = _rule_classes(rec, "road_class", cp)
        p["highway_classes"] = _road(hz, sum(by.values(), []))
    elif mid == "M9c":
        p["high_freight_classes"] = [str(x) for x in cp.get("high_freight_classes") or []]
    elif mid == "M13":
        wording = cp.get("variant") or "general"
        p = {"wording": wording,
             "descriptors": {wording: {str(ret["Low"]): list(cp.get("low_kinds") or []),
                                       str(ret["Significant"]): list(cp.get("significant_kinds") or []),
                                       str(ret["High"]): list(cp.get("high_kinds") or [])}}}
        auto = extra.pop("auto_map", {})               # only the active wording (no other jurisdiction's)
        if wording in auto:
            p["auto_map"] = {wording: auto[wording]}
    p.update(extra)
    if mid == "M1" and cp.get("judgment_class") is not None:
        p["judgment_hit_class"] = int(cp["judgment_class"])     # ND: the judgment zone is Medium (flagged)
    return p


def modifier_params(src, hz, rid, cp, strength):
    p = _renamed(rid, cp)
    p.update(copy.deepcopy(((hz.get("modifiers") or {}).get(rid) or {}).get("params") or {}))
    if rid == "R1":
        p["variant"] = hz["variant_map"]["R1"].get(cp.get("variant"), cp.get("variant"))
    elif rid == "R4":
        p["strength"] = strength
    elif rid == "R5":
        if cp.get("scope") == "existing_development":
            p["count_future"] = False
    elif rid == "R6":
        p["distance_mi"] = {k: float(v) for k, v in (cp.get("distance_mi_by_city_class") or {}).items()}
    return p


def _modifier_override(ov):
    """A presets.json modifier override ({"strength": ..} or {"params": {..}}) as
    (catalog params, strength)."""
    ov = copy.deepcopy(ov or {})
    params = ov.pop("params", {}) or {}
    strength = ov.pop("strength", None)
    params.update(ov)
    return params, strength


def _verification(hz, v):
    return hz["verification_map"].get(v or "as_documented", v)


def _scenario(src, hz, sid, s, ordinals):
    out = {"name": s["name"], "condition": s.get("starting_condition", ""),
           "source": s.get("source", ""), "verification": _verification(hz, s.get("verification"))}
    if s.get("requires_non_breach_run"):
        out["needs_non_breach"] = True
    if s.get("multiple_breach_locations"):
        out["needs_multiple_locations"] = True
    if s.get("by_current_class"):
        by_label = {v.lower(): k for k, v in ordinals.items()}
        bcc = {}
        for k, v in s["by_current_class"].items():
            key = k if k == "new" else by_label.get(str(k).lower(), str(k))
            if isinstance(v, dict):
                parts = []
                if v.get("scenario"):
                    parts.append(v["scenario"] + (" at " + v["pool"].replace("_", " ")
                                                  if v.get("pool") else ""))
                if v.get("inflow"):
                    parts.append(v["inflow"].replace("_", " ") + " with failure")
                v = "; ".join(parts)
            bcc[key] = v
        out["by_current_class"] = bcc
    return out


def _source_document(s):
    """The source line: the Appendix A document, then any supplement (catalog.json source.supplements)."""
    out = "{} ({}), Appendix {} pp. {}".format(s.get("title", ""), s.get("date", ""),
                                              s.get("appendix", ""), s.get("pages", ""))
    for sup in s.get("supplements") or []:
        out += "; {} ({})".format(sup.get("title", ""), sup.get("date", ""))
    return out


def build(src):
    """The classifier catalog (a plain JSON-able dict) from a DamIT Catalog object."""
    hz = src.hazard
    if not hz:
        raise CatalogError("DamIT Catalog {} has no hazard.json engine profile (DamIT Hazard needs "
                           "DamIT Catalog with 'hazard' in catalog.json files)".format(src.folder))
    ordinals = dict(src.labels["ordinals"])
    rt = hz["receptor_types"]
    cat = {
        "schema": 1,
        "catalog_version": src.version,
        "damit_catalog": src.identity(),
        "source_document": _source_document(src.source),
        "disclaimer": " ".join(x for x in (hz.get("disclaimer_lead"), src.disclaimer,
                                           hz.get("disclaimer_tail")) if x),
        "verification_legend": copy.deepcopy(hz["verification_legend"]),
        "classes": ordinals,
        "general": copy.deepcopy(hz["general"]),
        "habitable_types": list(rt["habitable_types"]),
        "residence_types": list(rt["residence_types"]),
        "institution_types": [t for t, c in rt["structure_type_map"].items() if c == "institution"],
        "critical_facility_types": list(src.methods["M10a"]["params"]["kinds"]),
        "transient_occupancy": list(rt["transient_occupancy"]),
        "scenarios": {sid: _scenario(src, hz, sid, s, ordinals) for sid, s in src.scenarios.items()},
        "domains": {},
        "methods": {},
        "modifiers": {},
        "presets": {},
        "preset_aliases": dict(src.preset_aliases),
    }
    for did, d in src.domain_cutoffs.items():
        params = {RENAMES[did][k]: v for k, v in d.items() if k in RENAMES.get(did, {})}
        params.update(copy.deepcopy(((hz.get("domains") or {}).get(did) or {}).get("params") or {}))
        cat["domains"][did] = {"name": d["name"], "rule": d.get("rule", ""), "params": params,
                               "source": d.get("source", ""),
                               "verification": _verification(hz, d.get("verification"))}
    for mid, m in src.methods.items():
        hm = (hz.get("methods") or {}).get(mid) or {}
        cat["methods"][mid] = {
            "name": m["name"], "group": str(m.get("group", "")).replace("_", " "),
            "inputs": list(m.get("inputs") or []),
            "receptor_kinds": list(hm.get("receptor_kinds") or []),
            "rule": m.get("notes") or m["name"],
            "params": method_params(src, hz, mid, dict(m.get("params") or {})),
            "returns": copy.deepcopy(m.get("returns")), "strength": m["strength"],
            "source": m.get("source", ""), "verification": _verification(hz, m.get("verification")),
            "evaluation": m.get("evaluation", "auto")}
    for rid, r in src.modifiers.items():
        hm = (hz.get("modifiers") or {}).get(rid) or {}
        rec = {"name": r["name"], "rule": r.get("rule", ""),
               "params": modifier_params(src, hz, rid, dict(r.get("params") or {}), r["strength"]),
               "strength": r["strength"], "source": r.get("source", ""),
               "verification": _verification(hz, r.get("verification"))}
        if hm.get("variants"):
            rec["variants"] = copy.deepcopy(hm["variants"])
        cat["modifiers"][rid] = rec
    refine = {src.canonical_preset_id(k): v for k, v in (hz.get("presets") or {}).items()}
    for pid, pr in src.presets.items():
        cat["presets"][pid] = _preset(src, hz, pid, pr, refine.get(pid) or {})
    return cat


def _preset(src, hz, pid, pr, ref):
    methods = {}
    over_methods = pr.get("methods") or {}
    if not over_methods or not pr.get("methods_confirmed", True):
        over_methods = dict(over_methods)
        over_methods.setdefault("M13", {})            # the document's dash: M13 fallback
    for mid, ov in over_methods.items():
        ov = dict(ov or {})
        strength = ov.pop("strength", None)
        cp = dict(src.methods[mid].get("params") or {})
        cp.update(ov)
        params = method_params(src, hz, mid, cp)
        params.update(copy.deepcopy(((ref.get("methods") or {}).get(mid)) or {}))
        if strength:
            params["strength"] = strength
        methods[mid] = params
    mods = {}
    mo = pr.get("modifier_overrides") or {}
    for rid in pr.get("modifiers") or []:
        cp_over, strength = _modifier_override(mo.get(rid))
        cp = dict(src.modifiers[rid].get("params") or {})
        cp.update(cp_over)
        st = strength or src.modifiers[rid]["strength"]
        params = modifier_params(src, hz, rid, cp, st)
        params.update(copy.deepcopy(((ref.get("modifiers") or {}).get(rid)) or {}))
        if strength:
            params["strength"] = strength
        mods[rid] = params
    # the preset's document status (presets.json 'status': NRCS unverified, NY draft) is read from
    # DamIT Catalog; else the worst per-method mark of the preset (BIA M5 secondary)
    status = [v for v in (pr.get("verification") or {}).values()]
    verification = pr.get("status") or next(
        (s for s in ("unverified", "secondary") if s in status), "verified")
    notes = [n for n in (ref.get("notes"), pr.get("notes"),
                         "Citation: " + pr["citation"] if pr.get("citation") else None) if n]
    out = {"label": pr.get("label", pid),
           "scenarios": list(pr.get("scenarios") or []),
           "methods": methods, "modifiers": mods,
           "labels": {str(k): v for k, v in (pr.get("label_map") or {}).items()},
           "verification": verification, "notes": " ".join(notes),
           "aliases": sorted(a for a, t in src.preset_aliases.items() if t == pid)}
    if pr.get("conditional_scenarios"):
        out["optional_scenarios"] = {
            c["id"]: "for {}{}".format(c.get("when", ""), " ({})".format(c["verification"])
                                       if c.get("verification") else "")
            for c in pr["conditional_scenarios"]}
    if ref.get("scenarios_any_of"):
        out["scenarios_any_of"] = list(ref["scenarios_any_of"])
    if pr.get("scenario_note"):
        out["scenario_note"] = pr["scenario_note"]
    if pr.get("domain_cutoffs"):
        out["domains"] = list(pr["domain_cutoffs"])
    if pr.get("verification"):
        out["method_verification"] = dict(pr["verification"])
    if not (pr.get("methods") or {}) or not pr.get("methods_confirmed", True):
        out["method_fallback"] = True                 # the run is flagged: M13 and engineering judgment
    return out


# ======================================================================= validation ==
def validate(cat):
    """Problems of a classifier catalog ([] = usable)."""
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
    for alias, target in cat.get("preset_aliases", {}).items():
        if target not in cat["presets"]:
            out.append("preset alias {} -> unknown {}".format(alias, target))
    return out


# ==================================================================== configuration ==
def canonical_preset(cat, preset_id):
    """The stored preset ID for an ID or alias (USBR_TM11 -> USBR), or None."""
    if preset_id in cat["presets"]:
        return preset_id
    t = cat.get("preset_aliases", {}).get(preset_id)
    return t if t in cat["presets"] else None


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("chart_for_type",):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _over(key, over):
    """A user override for ``key``: catalog parameter names are renamed to the classifier's."""
    return _renamed(key, over or {}) if over else {}


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
    pid = canonical_preset(cat, preset_id) if preset_id else None
    if pid:
        for k, v in cat["presets"][pid]["labels"].items():
            labels[int(k)] = v
    return labels


def preset_config(cat, preset_id, overrides=None, apply_advisory=False):
    """The run configuration of a jurisdiction preset (ID or alias). overrides: {ID: {param: value}}
    in classifier or catalog parameter names."""
    pid = canonical_preset(cat, preset_id)
    if pid is None:
        known = ", ".join(list(cat["presets"]) + list(cat.get("preset_aliases", {})))
        raise CatalogError("no preset {!r} (known: {})".format(preset_id, known))
    p = cat["presets"][pid]
    overrides = overrides or {}
    methods = {mid: _entry(cat["methods"][mid], _merge(over, _over(mid, overrides.get(mid))))
               for mid, over in p["methods"].items()}
    mods = {rid: _entry(cat["modifiers"][rid], _merge(over, _over(rid, overrides.get(rid))))
            for rid, over in p["modifiers"].items()}
    domains = {d: _merge(cat["domains"][d]["params"], _over(d, overrides.get(d)))
               for d in p.get("domains", [])}
    return {"mode": "preset", "preset": pid, "requested_preset": preset_id,
            "preset_label": p["label"],
            "preset_verification": p.get("verification"), "preset_notes": p.get("notes", ""),
            "scenarios": list(p["scenarios"]),
            "optional_scenarios": dict(p.get("optional_scenarios", {})),
            "scenarios_any_of": list(p.get("scenarios_any_of", [])),
            "scenario_note": p.get("scenario_note", ""), "method_fallback": bool(p.get("method_fallback")),
            "domains": domains, "methods": methods, "modifiers": mods,
            "labels": labels_for(cat, pid), "apply_advisory": bool(apply_advisory),
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
            "domains": {d: _merge(cat["domains"][d]["params"], _over(d, overrides.get(d)))
                        for d in domains},
            "methods": {m: _entry(cat["methods"][m], _over(m, overrides.get(m))) for m in methods},
            "modifiers": {r: _entry(cat["modifiers"][r], _over(r, overrides.get(r)))
                          for r in modifiers},
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


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Write DamIT Catalog as DamIT Hazard reads it.")
    ap.add_argument("--export", required=True, help="output JSON path")
    ap.add_argument("--catalog-dir", default=None, help="DamIT Catalog data folder")
    a = ap.parse_args(argv)
    cat = load(a.catalog_dir)
    with open(a.export, "w", encoding="utf-8") as f:
        json.dump(cat, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("Wrote {} from DamIT Catalog {} ({})".format(a.export, cat["catalog_version"],
                                                      cat["damit_catalog"]["folder"]))


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
