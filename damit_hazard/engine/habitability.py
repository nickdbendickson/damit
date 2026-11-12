"""Habitability bookkeeping for a classify run (0.4.0): how the structures stand under the 911 / reviewed rule, how that
differs from the rule M6 and the class follow ("legacy": no type = presumed a home), and what the class would be under
the other rule. Reporting only: nothing here changes the suggestion unless the HABITABLE_RULE input is "reviewed".
Pure Python (no QGIS)."""
import copy

from . import core

LEGACY, REVIEWED = core.RULE_LEGACY, core.RULE_REVIEWED


def wet_structures(receptors, wet_min=0.0):
    return [r for r in receptors if r.get("kind") == "structure" and r.get("in_domain") is not False
            and r.get("sampled") and r.get("depth_ft") is not None and r["depth_ft"] > wet_min]


def tally(receptors, habitable_types, wet_min=0.0):
    """Counts over the wet structures: under the 911 / reviewed rule (yes / unverified / no and by basis), under the
    legacy rule, and how many the two rules disagree on; plus the USA Structures and occtype checks."""
    wet = wet_structures(receptors, wet_min)
    t = {"wet_structures": len(wet), "yes": 0, "unverified": 0, "no": 0, "by_basis": {}, "legacy_habitable": 0,
         "differs": 0, "legacy_yes_reviewed_not": 0, "usa_checked": 0, "usa_no_footprint": 0, "usa_class_differs": 0,
         "type_unknown": 0, "occtype_unmapped": 0, "reviews_applied": 0}
    for r in wet:
        status, basis = core.reviewed_status(r, habitable_types)
        t[status] += 1
        t["by_basis"][basis] = t["by_basis"].get(basis, 0) + 1
        legacy = core.habitable_basis(r, habitable_types)[0]
        t["legacy_habitable"] += legacy
        if legacy != (status == core.STATUS_YES):
            t["differs"] += 1
            if legacy:
                t["legacy_yes_reviewed_not"] += 1
        t["type_unknown"] += r.get("type") is None
        t["occtype_unmapped"] += bool(r.get("occtype")) and not r.get("suggested_type")
        t["reviews_applied"] += r.get("reviewed_habitable") is not None
        if r.get("usa_struct_match"):
            t["usa_checked"] += 1
            t["usa_no_footprint"] += r["usa_struct_match"] == "none"
            t["usa_class_differs"] += r.get("usa_occ_check") == "differs"
    return t


def _m6_receptors(res):
    return len({rid for h in res["hits"] if h["method"] == "M6" for rid in h["receptors"]})


def compare(cat, cfg, runs, charts, dam, layers, applied_rule, applied_result):
    """Classify the same runs once more under the OTHER habitability rule and return what differs: {applied, other,
    m6_receptors {applied, other}, class {applied, other}, class_changes}. The receptors are copied; the real result
    is not touched."""
    other = REVIEWED if applied_rule == LEGACY else LEGACY
    runs2 = [dict(run, receptors=[dict(r) for r in run["receptors"]]) for run in runs]
    res2 = core.classify(cat, cfg, runs2, dam=copy.deepcopy(dam), charts=charts, layers=layers, habitable_rule=other)
    return {"applied": applied_rule, "other": other,
            "m6_receptors": {"applied": _m6_receptors(applied_result), "other": _m6_receptors(res2)},
            "class": {"applied": applied_result["suggested_label"], "other": res2["suggested_label"]},
            "class_ordinal": {"applied": applied_result["suggested_class"], "other": res2["suggested_class"]},
            "class_changes": res2["suggested_class"] != applied_result["suggested_class"]}


def flag_text(t, cmp):
    """The report flag for a run where the rules differ on some wet structure (None when they agree)."""
    if not t["differs"]:
        return None
    if cmp is None:
        return None
    a = cmp["applied"]
    what = ("the suggested class would change from {} to {}".format(cmp["class"]["applied"], cmp["class"]["other"])
            if cmp["class_changes"] else "the suggested class would stay {}".format(cmp["class"]["applied"]))
    if a == LEGACY:
        return ("Habitability rule: M6 and the class follow Hazard's legacy rule (a structure with no type is presumed "
                "habitable). {} of {} wet structure(s) are counted habitable there but are not ND 911 address points and "
                "have no engineer review. Under the 911 / reviewed rule (HABITABLE_RULE = reviewed) M6 would count {} "
                "receptor(s) instead of {} and {}. Not applied: this needs a decision.".format(
                    t["legacy_yes_reviewed_not"], t["wet_structures"], cmp["m6_receptors"]["other"],
                    cmp["m6_receptors"]["applied"], what))
    return ("Habitability rule: HABITABLE_RULE = reviewed is applied (only ND 911 address points and structures an "
            "engineer reviewed habitable count). Under the legacy rule M6 would count {} receptor(s) instead of {} and "
            "{}.".format(cmp["m6_receptors"]["other"], cmp["m6_receptors"]["applied"], what))
