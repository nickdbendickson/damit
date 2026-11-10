"""Suggested-class evaluator driven by the catalog data (pure Python, no QGIS).

Implements the Appendix A combination logic:
  1. every enabled scenario runs; the most severe consequence governs;
  2. every enabled method is applied at every receptor; each hit records class, receptor,
     method ID and strength (rule / advisory);
  3. the suggested class is the highest RULE-strength result; advisories are reported beside it
     and applied only when ``apply_advisories`` is True;
  4. modifier rules (R-codes) are applied;
  5. the driving receptor(s) and method ID(s) are reported.

All thresholds come from the resolved configuration (catalog JSON + preset/custom overrides);
this module only interprets the rule language (conditions, counts, bands).

A suggestion is not a determination: the engineer of record and the regulating agency decide.
DamIT Hazard (``damit:classify``) is the classifier for finished rasters; DamIT Screener uses
this module only for a preliminary suggestion when receptor hydraulics already exist.

Receptor record (dict): ``id``, ``receptor_type`` (structure / road / rail / facility / lifeline /
environment / feature), optional ``scenario`` (S-code), ``in_domain`` (bool) and attribute
fields named in methods.json ``inputs`` (depth_ground_ft, depth_foundation_ft, depth_floor_ft,
velocity_fps, dv_ft2s, structure_type, habitable, occupancy, occupants, m1_zone, road_class,
aadt, ...). Summary record (dict, dam level): model_dimension (1D/2D), hydraulics_source
(breach_model / simplified / none), analysis (as DamIT Hazard's dam record: breach_model / simplified /
unsteady_tm11), current_class (ordinal or class label), storage_acft, lives_in_jeopardy,
population_at_risk, ... optionally ``by_scenario`` {S-code: {...}}.

M1 returns a class only for the zones in its ``class_zones`` parameter; an empty list (the USBR
preset) means M1 only marks the lives in jeopardy that M5 counts. R2's floor presumption and R8's
variant are modifier parameters (modifiers.json / a preset's modifier_overrides), the same ones
DamIT Hazard reads.
"""
import datetime

from .catalog import _flag

OPS = (">", ">=", "<", "<=", "eq", "ne", "in")
WET_FIELDS = ("depth_ground_ft", "depth_foundation_ft", "depth_floor_ft", "depth_ft")


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "t"):
        return True
    if s in ("0", "false", "no", "n", "f"):
        return False
    return None


class _Ctx(object):
    def __init__(self, params, datums, record, missing):
        self.params = params
        self.datums = datums
        self.record = record
        self.missing = missing

    def value(self, token):
        if isinstance(token, str) and token.startswith("$"):
            return self.params.get(token[1:])
        return token

    def field(self, name):
        if name.startswith("@"):
            datum = self.params.get(name[1:], "ground")
            name = self.datums.get(datum, datum)
        if name == "wet":
            return _wet(self.record)
        v = self.record.get(name)
        if v is None or v == "":
            self.missing.add(name)
            return None
        return v


def _wet(rec):
    w = _bool(rec.get("wet"))
    if w is not None:
        return w
    seen = False
    for f in WET_FIELDS:
        n = _num(rec.get(f))
        if n is not None:
            seen = True
            if n > 0:
                return True
    imp = _bool(rec.get("impacted"))
    if imp is not None:
        return imp
    return False if seen else None


def _cmp(a, op, b):
    """Tri-state comparison: True / False / None (unknown input)."""
    if a is None:
        return None
    if op == "in":
        if b is None:
            return None
        vals = b if isinstance(b, (list, tuple)) else [b]
        return any(_eq(a, x) for x in vals)
    if op == "eq":
        return _eq(a, b)
    if op == "ne":
        return not _eq(a, b)
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return None
    return {">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[op]


def _eq(a, b):
    if isinstance(b, bool):
        return _bool(a) is b
    if isinstance(b, (int, float)):
        n = _num(a)
        return n is not None and n == float(b)
    return str(a).strip().lower() == str(b).strip().lower()


def cond(c, ctx):
    """Evaluate a condition: [field, op, value] or {"all": [...]} / {"any": [...]}. Tri-state."""
    if isinstance(c, list):
        field, op, val = c
        op = ctx.value(op)
        if op not in OPS:
            raise ValueError("unknown operator {!r}".format(op))
        b = ctx.value(val)
        a = ctx.field(field)
        if field == "wet" and a is None:
            ctx.missing.add("depth / impacted")
        if op == "ne" and a is None:
            return True                        # 'not X' holds when the flag is absent
        return _cmp(a, op, b)
    if "all" in c:
        res = [cond(x, ctx) for x in c["all"]]
        if any(r is False for r in res):
            return False
        return None if any(r is None for r in res) else True
    if "any" in c:
        res = [cond(x, ctx) for x in c["any"]]
        if any(r is True for r in res):
            return True
        return None if any(r is None for r in res) else False
    raise ValueError("bad condition {!r}".format(c))


def _class(v, params):
    if isinstance(v, str) and v.startswith("$"):
        v = params.get(v[1:])
    if isinstance(v, dict):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rule_pass(rules, record, params, datums):
    """(class, rule label, missing fields, final?) for one record. 'final' rules decide outright.
    Missing fields are reported whenever a rule that could give a HIGHER class than the one found
    could not be evaluated (so a lower fallback never hides a gap)."""
    best, label = None, None
    unknown = []                                  # (class, missing fields) of rules not evaluable
    for i, rule in enumerate(rules):
        ip = rule.get("if_param")
        if ip and any(params.get(k) != v for k, v in ip.items()):
            continue
        ms = set()
        ok = cond(rule["when"], _Ctx(params, datums, record, ms))
        c = _class(rule.get("class"), params)
        if ok is None:
            unknown.append((c, ms))
            continue
        if ok:
            if rule.get("final"):
                return c, rule.get("label", "rule {}".format(i + 1)), set(), True
            if c is not None and (best is None or c > best):
                best, label = c, rule.get("label", "rule {}".format(i + 1))
    missing = set()
    for c, ms in unknown:
        if best is None or (c is not None and c > best):
            missing |= ms
    return best, label, missing, False


def _band(value, bands, params):
    best = None
    for b in bands:
        lo = _num(params.get(b["min"][1:]) if isinstance(b.get("min"), str) else b.get("min"))
        hi = _num(params.get(b["max"][1:]) if isinstance(b.get("max"), str) else b.get("max"))
        if (lo is None or value >= lo) and (hi is None or value <= hi):
            c = _class(b.get("class"), params)
            if c is not None and (best is None or c > best):
                best = c
    return best


def _types(method):
    return (method.get("applies_to") or {}).get("receptor_type")


def _apply_r2(receptors, flags, params=None):
    floor_presumption = bool((params or {}).get("floor_presumption"))
    out = []
    for r in receptors:
        r = dict(r)
        if r.get("receptor_type") == "structure":
            if _bool(r.get("habitable")) is None and r.get("occupancy"):
                occ = str(r["occupancy"]).lower()
                r["habitable"] = occ in ("overnight", "daytime", "regular_daytime")
            if (floor_presumption and str(r.get("structure_type", "")).lower() == "home"
                    and r.get("depth_floor_ft") in (None, "")
                    and _num(r.get("depth_ground_ft")) and _num(r.get("depth_ground_ft")) > 0):
                r["depth_floor_ft"] = r["depth_ground_ft"]
                flags.append(_flag("r2_presumption", "Home assumed flooded above its lowest occupied floor "
                                   "(R2; no floor data).", method="R2", receptor=r.get("id")))
        out.append(r)
    return out


def _method_hits(mid, m, recs, summ, datums, sid, flags):
    params = m.get("params") or {}
    hits = []
    dim = str(summ.get("model_dimension") or "").upper()
    if params.get("only_if_1d") and dim == "2D":
        return hits
    if params.get("require_2d") and dim != "2D":
        if dim == "1D":
            flags.append(_flag("one_d_run_with_2d_only_method", "{} requires a 2D model; this run is 1D, so {} "
                               "is blocked.".format(mid, mid), method=mid, scenario=sid))
        else:
            flags.append(_flag("missing_input", "{} requires a 2D model; model_dimension is not given.".format(mid),
                               method=mid, scenario=sid))
        return hits
    if m.get("evaluation") == "manual":
        return hits
    types = _types(m)
    cands = []
    for r in recs:
        if types and r.get("receptor_type") not in types:
            continue
        if _bool(r.get("in_domain")) is False:
            flags.append(_flag("outside_routed_domain", "Receptor outside the routed domain; not evaluated.",
                               method=mid, receptor=r.get("id"), scenario=sid))
            continue
        cands.append(r)
    missing_by = {}

    def hit(rec_id, c, why):
        hits.append({"scenario": sid, "method": mid, "receptor": rec_id, "class": c,
                     "strength": m.get("strength", "rule"), "why": why})

    for r in cands if m.get("receptor_rules") else []:
        c, why, miss, _ = _rule_pass(m["receptor_rules"], r, params, datums)
        if c is not None:
            hit(r.get("id"), c, why)
        if miss:
            missing_by.setdefault(tuple(sorted(miss)), []).append(r.get("id"))
    if m.get("summary_rules"):
        c, why, miss, _ = _rule_pass(m["summary_rules"], summ, params, datums)
        if c is not None:
            hit("dam", c, why)
        if miss:
            missing_by.setdefault(tuple(sorted(miss)), []).append("dam")
    for entry in m.get("counts") or []:
        total, unknown = 0.0, 0
        for r in cands:
            ms = set()
            ok = cond(entry["select"], _Ctx(params, datums, r, ms))
            if ok is None:
                unknown += 1
                missing_by.setdefault(tuple(sorted(ms)), []).append(r.get("id"))
            elif ok:
                meas = entry.get("measure", "count")
                if meas == "count":
                    total += 1
                elif meas.startswith("sum:"):
                    v = _num(r.get(meas[4:]))
                    if v is None:
                        missing_by.setdefault((meas[4:],), []).append(r.get("id"))
                    else:
                        total += v
        if total > 0:
            c = _band(total, entry["bands"], params)
            if c is not None:
                hit("count", c, "{}: {:g}".format(entry.get("label", entry.get("measure")), total))
    special = m.get("special")
    if special == "chart_zone":
        zones = params.get("class_zones")
        if zones is None:
            zones = ["high_danger"]                # an empty list: M1 marks zones, returns no class
        ret = (m.get("returns") or {}).get("high_danger", 3)
        for r in cands:
            if _bool(r.get("habitable")) is False or _wet(r) is False:
                continue
            z = r.get("m1_zone")
            if not z:
                missing_by.setdefault(("m1_zone",), []).append(r.get("id"))
                continue
            z = str(z).lower()
            if z in zones:
                hit(r.get("id"), ret, "chart zone {}".format(z))
            elif z == "judgment":
                if params.get("judgment_zone_flag", True):
                    flags.append(_flag("m1_judgment_zone", "M1 judgment-zone hit: engineer review required.",
                                       method=mid, receptor=r.get("id"), scenario=sid))
                jc = _num(params.get("judgment_class"))
                if jc is not None:                 # ND: the judgment zone is Medium (still flagged)
                    hit(r.get("id"), int(jc), "chart zone judgment")
    elif special == "lives_in_jeopardy":
        lij = _num(summ.get("lives_in_jeopardy"))
        if lij is None:
            vals = [_num(r.get("occupants")) for r in recs if r.get("receptor_type") == "structure"
                    and (str(r.get("m1_zone", "")).lower() == "high_danger" or _bool(r.get("lethal")))]
            if vals and all(v is not None for v in vals):
                lij = sum(vals)
            elif not vals and recs and all(r.get("m1_zone") for r in recs if r.get("receptor_type") == "structure"):
                lij = 0.0
        if lij is None:
            missing_by.setdefault(("lives_in_jeopardy",), []).append("dam")
        else:
            hi, sg = _num(params.get("high_min")), _num(params.get("sig_min"))
            c = 3 if hi is not None and lij >= hi else (2 if sg is not None and lij >= sg else None)
            if c is not None:
                hit("dam", c, "lives in jeopardy {:g}".format(lij))
        if params.get("lowering_only"):
            for h in hits:
                h["strength"] = "advisory"
                h["why"] += " (supports lowering a proposed class only)"
    for fields, ids in missing_by.items():
        flags.append(_flag("missing_input", "{}: missing {} at {} receptor(s); not evaluated there.".format(
            mid, ", ".join(fields) or "inputs", len(ids)), method=mid, receptor=ids[:20], scenario=sid))
    return hits


def _class_of_record(config, catalog, value):
    """A current class (ordinal, preset label or generic label) as an ordinal, or None."""
    if value is None or value == "":
        return None
    n = _num(value)
    if n is not None:
        return int(n)
    v = str(value).strip().lower()
    for lm in (config.get("label_map") or {}, catalog.labels.get("ordinals") or {}):
        for k, lab in lm.items():
            if str(lab).strip().lower() == v:
                return int(k)
    return None


def label_for(config, ordinal):
    """Label for an ordinal under a resolved config (clamped to the preset's tiers)."""
    if ordinal is None:
        return "Not determined"
    lm = config.get("label_map") or {}
    if str(ordinal) in lm:
        return lm[str(ordinal)]
    keys = sorted(int(k) for k in lm) or [ordinal]
    k = keys[0] if ordinal < keys[0] else keys[-1]
    return lm.get(str(k), str(ordinal))


def evaluate(catalog, config, receptors, summary=None, apply_advisories=False, run_date=None):
    """Suggested class for one dam under a resolved config (Catalog.resolve_preset / resolve_custom)."""
    summary = dict(summary or {})
    flags = [dict(f) for f in config.get("flags", [])]
    mods = {r["id"]: r for r in config.get("modifiers", [])}
    recs = [dict(r) for r in (receptors or [])]
    if "R2" in mods:
        recs = _apply_r2(recs, flags, mods["R2"].get("params"))
    scen_ids = [s["id"] for s in config.get("scenarios", [])] or [None]
    datums = catalog.datums
    all_hits = []
    per_scenario = {}
    for sid in scen_ids:
        srecs = [r for r in recs if r.get("scenario") in (None, "", sid)]
        summ = dict(summary)
        summ.pop("by_scenario", None)
        summ.update((summary.get("by_scenario") or {}).get(sid) or {})
        hits = []
        for mid, m in config.get("methods", {}).items():
            hits.extend(_method_hits(mid, m, srecs, summ, datums, sid, flags))
        rule = [h["class"] for h in hits if h["strength"] == "rule"]
        adv = [h["class"] for h in hits if h["strength"] == "advisory"]
        best = max(rule + (adv if apply_advisories else []) or [None], key=lambda x: -1 if x is None else x)
        per_scenario[sid or "-"] = best
        all_hits.extend(hits)
    known = [v for v in per_scenario.values() if v is not None]
    ordinal = max(known) if known else None
    governing = [s for s, v in per_scenario.items() if v == ordinal and v is not None]
    driving = [h for h in all_hits if h["class"] == ordinal and h["scenario"] in [None if g == "-" else g for g in governing]
               and (h["strength"] == "rule" or apply_advisories)]
    rule_max = max([h["class"] for h in all_hits if h["strength"] == "rule"] or [-1])
    advisories = [h for h in all_hits if h["strength"] == "advisory"]
    for h in advisories:
        if h["class"] > rule_max:
            flags.append(_flag("advisory_only_hit", "Advisory {} hit (class {}) is above the rule-strength "
                               "result; applied only if opted in.".format(h["method"], h["class"]),
                               method=h["method"], receptor=h["receptor"], scenario=h["scenario"]))
    applied, reported = [], []
    for rid, r in mods.items():
        p = r.get("params") or {}
        if rid == "R4":
            ds = _num(summary.get("downstream_dam_class"))
            if ds is not None and (ordinal is None or ds > ordinal):
                if r.get("strength") == "rule":
                    ordinal = int(ds)
                    applied.append({"id": rid, "effect": "raised to downstream dam class {}".format(int(ds))})
                else:
                    flags.append(_flag("advisory_only_hit", "R4 (advisory): upstream should be at least the "
                                       "downstream dam class {}.".format(int(ds)), method=rid))
            continue
        if rid == "R6":
            if _bool(summary.get("new_dam")) and not _bool(summary.get("development_curtailed")):
                lim = (p.get("distance_mi_by_city_class") or {}).get(str(summary.get("city_class", "")).lower())
                d = _num(summary.get("distance_to_city_mi"))
                if lim is not None and d is not None and d <= lim and (ordinal or 0) < 3:
                    ordinal = 3
                    applied.append({"id": rid, "effect": "new dam within {} mi of a {} city -> High".format(
                        lim, summary.get("city_class"))})
            continue
        if rid == "R7":
            up = _num(summary.get("borderline_upper_ordinal"))
            if up is not None and (ordinal is None or up > ordinal):
                ordinal = int(up)
                applied.append({"id": rid, "effect": "borderline result takes the higher class"})
            continue
        if rid == "R8" and p.get("variant") == "lowering_from_high":
            cur = _class_of_record(config, catalog, summary.get("current_class"))
            analysis = str(summary.get("analysis") or summary.get("hydraulics_source") or "").lower()
            if cur is not None and cur >= 3 and (ordinal is None or ordinal < 3) and analysis != "unsteady_tm11":
                ordinal = 3
                applied.append({"id": rid, "effect": "current class High: lowering needs TM-11-based unsteady "
                                "modeling (analysis = unsteady_tm11); class kept High"})
            elif cur is None and (ordinal is None or ordinal < 3):
                flags.append(_flag("missing_input", "R8: current class not given; lowering from High (needs "
                                   "TM-11-based unsteady modeling) not checked.", method=rid))
            continue
        if rid == "R8":
            src = str(summary.get("hydraulics_source") or "").lower()
            if src != "breach_model":
                st = _num(summary.get("storage_acft"))
                lim = _num(p.get("storage_acft_limit"))
                if st is None:
                    flags.append(_flag("missing_input", "R8: storage at top of dam unknown and no breach model; a "
                                       "class below High cannot be justified.", method=rid))
                elif lim is not None and st >= lim and (ordinal is None or ordinal < 3):
                    ordinal = 3
                    applied.append({"id": rid, "effect": "no breach model and storage {:g} ac-ft >= {:g}: a class "
                                    "below High is not justified".format(st, lim)})
            continue
        if rid == "R10":
            applied.append({"id": rid, "effect": "re-review record stored",
                            "run_date": run_date or datetime.date.today().isoformat(),
                            "layer_versions": summary.get("layer_versions") or {}})
            continue
        if rid == "R2":
            applied.append({"id": rid, "effect": "occupancy presumption applied to receptor records"})
            continue
        reported.append({"id": rid, "name": r.get("name"), "note": "reported for engineer review"})
    seen, uniq = set(), []
    for f in flags:
        key = (f.get("code"), f.get("method"), f.get("message"), str(f.get("receptor")))
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    flags = uniq
    if ordinal is None:
        flags.append(_flag("not_determined", "No rule-strength method produced a class (missing inputs or no "
                           "consequences found); engineer review required."))
    if any(f["code"] == "m1_judgment_zone" for f in flags) and "R7" in mods:
        flags.append(_flag("r7_judgment", "R7: M1 judgment-zone hits are flagged; a borderline result takes "
                           "the higher class.", method="R7"))
    return {"suggested_ordinal": ordinal, "suggested_label": label_for(config, ordinal),
            "generic_label": catalog.generic_label(ordinal) if ordinal is not None else "Not determined",
            "mode": config.get("mode"), "preset_id": config.get("preset_id"),
            "per_scenario": per_scenario, "driving": driving, "advisories": advisories, "hits": all_hits,
            "modifiers_applied": applied, "modifiers_reported": reported, "flags": flags,
            "apply_advisories": bool(apply_advisories), "citations": catalog.citations(config),
            "disclaimer": catalog.disclaimer, "catalog": catalog.identity()}
