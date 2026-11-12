"""Combination logic (Appendix A, 'Combination logic') and the method / modifier evaluators.

    result = classify(cat, cfg, runs, dam=None, charts=None)

runs: [{"scenario": "S3", "label": "...", "model_dim": "2D" | "1D" | None,
        "breach_location": optional, "has_non_breach": bool, "receptors": [receptor dicts]}]
dam:  optional dam record: dam_id = the dam's NID ID (USACE National Inventory of Dams, e.g. ND00199),
      nid_id, is_new, is_sample (see nid_rule), storage_acft, current_class, analysis,
      downstream_dam_classes, municipalities, development_curtailed, lives_in_jeopardy,
      population_inundation, access_controlled, eap_warning, evacuation_credit, name)

1. every run (scenario) is evaluated; the most severe governs;
2. every enabled method scores every receptor; each hit = class, receptor(s), method, strength;
3. suggested class = highest rule-strength hit (advisory hits are listed beside it and count
   only with cfg["apply_advisory"]);
4. modifiers (R-codes) adjust which receptors count (before) and the class (after);
5. the driving receptors and method IDs are reported with the suggestion.
A method whose inputs are missing flags the gap (result["flags"]) instead of passing silently.
"""
import datetime
import re

from . import catalog as C
from . import catalog_bridge
from . import tm11

ERROR, WARNING, INFO = "error", "warning", "info"
LIFE_METHODS = ("M1", "M2", "M4a", "M4b", "M4c", "M5", "M7")
STRUCT_KINDS = ("structure", "facility")


class Flags(object):
    def __init__(self):
        self.items, self._idx = [], {}

    def add(self, level, code, message, method=None, receptor=None, scenario=None):
        key = (level, code, method, scenario, message)
        f = self._idx.get(key)
        if f is None:
            f = {"level": level, "code": code, "message": message, "method": method,
                 "scenario": scenario, "receptors": []}
            self._idx[key] = f
            self.items.append(f)
        for rid in (receptor if isinstance(receptor, (list, tuple)) else [receptor]):
            if rid is not None and rid not in f["receptors"]:
                f["receptors"].append(rid)
        return f


# ---------------------------------------------------------------- NID IDs ----------------
# The dam inventory is the NID. The rule lives in DamIT Catalog (damit_catalog.handoff.nid_rule), shared with
# DamIT Screener / Runner and the records DamIT Crest hands off; these are thin pass-throughs, not a copy.
def _handoff():
    ho = catalog_bridge.damit_handoff()
    if not hasattr(ho, "nid_rule"):
        raise catalog_bridge.CatalogMissing("This DamIT Catalog has no NID-ID rule (handoff.nid_rule); update the "
                                            "'DamIT Catalog' plugin to the one shipped with this DamIT Hazard.")
    return ho


def is_nid_id(value):
    """True for an NID ID (ND00199, TX12345). DWR-2801, DUG-130, SAMPLE-4031, DESK-014 and NEW are not."""
    return _handoff().is_nid_id(value)


def nid_rule(dam):
    """DamIT Catalog's handoff.nid_rule: returns (error, warning, nid_id) for a dam record."""
    return _handoff().nid_rule(dam)


def _nid(dam, flags):
    """Flag the dam record's NID ID (error / warning); returns the NID ID or None."""
    if not any(dam.get(k) not in (None, "") for k in _handoff().NID_KEYS):
        flags.add(INFO, "nid_none", "no dam id in the dam record: this result is not tied to an NID dam")
        return None
    error, warning, nid = nid_rule(dam)
    if error:
        flags.add(ERROR, "nid_id", error)
    elif warning:
        flags.add(WARNING, "nid_exception", warning)
    return nid


# Habitability, one rule for the methods (M6 ...) and the depth-velocity chart (engine/dvchart.py).
BASIS_UNKNOWN, BASIS_TYPE, BASIS_OCCUPANCY = "type_unknown", "type", "occupancy"
OCCUPANCY_HABITABLE = ("overnight", "regular", "daytime", "regular_daytime")
OCCUPANCY_NOT_OCCUPIED = ("occasional", "unoccupied", "vacant")


def habitable_basis(r, habitable_types):
    """(habitable?, basis): the receptor's habitability as Hazard decides it. No type: habitable, a home
    (basis "type_unknown"; the engine flags it); a type in the catalog's habitable_types; else only a
    habitable occupancy (overnight, regular, daytime, regular_daytime). basis None when not habitable."""
    t = r.get("type")
    if t is None:
        return True, BASIS_UNKNOWN
    if t in habitable_types:
        return True, BASIS_TYPE
    if r.get("occupancy") in OCCUPANCY_HABITABLE:
        return True, BASIS_OCCUPANCY
    return False, None


# The 911 / reviewed rule (0.4.0), the habitability the depth-velocity chart plots, and (HABITABLE_RULE = reviewed) the
# rule the methods can follow. Same words as DamSafety Hazard: yes / unverified / no.
RULE_LEGACY, RULE_REVIEWED = "legacy", "reviewed"
STATUS_YES, STATUS_UNVERIFIED, STATUS_NO = "yes", "unverified", "no"
BASIS_911, BASIS_REVIEWED = "911_address", "reviewed_habitable"
BASIS_REVIEWED_NOT, BASIS_911_NOT = "reviewed_not_habitable", "911_not_habitable"
BASIS_UNREVIEWED = "unreviewed_not_911"


def reviewed_status(r, habitable_types):
    """(status, basis) of a structure under the E911 / reviewed rule. ONLY an ND E911 address point is habitable by
    itself; every other structure is "unverified" until an engineer reviews it in Hazard (reviewed_habitable true /
    false, set only by habitable_review.sign_off). The review wins over everything. An NSI occtype, a USA Structures
    footprint, a type or an occupancy never make a non-E911 structure habitable. An E911 point is habitable unless it
    is marked habitable = false, or has a type that is not habitable (the Hazard type rule)."""
    rv = r.get("reviewed_habitable")
    if rv is not None:
        return (STATUS_YES, BASIS_REVIEWED) if rv else (STATUS_NO, BASIS_REVIEWED_NOT)
    if not r.get("is_911"):
        return STATUS_UNVERIFIED, BASIS_UNREVIEWED
    if r.get("habitable") is False:
        return STATUS_NO, BASIS_911_NOT
    if r.get("habitable") is True or r.get("type") is None:
        return STATUS_YES, BASIS_911
    ok = r["type"] in habitable_types or r.get("occupancy") in OCCUPANCY_HABITABLE
    return (STATUS_YES, BASIS_911) if ok else (STATUS_NO, BASIS_911_NOT)


def is_occupied(r, habitable_types):
    """R2 without the flag: habitable and not occasional / unoccupied / vacant."""
    if r.get("occupancy") in OCCUPANCY_NOT_OCCUPIED:
        return False
    return habitable_basis(r, habitable_types)[0]


def _list(x):
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def _f(x, nd=2):
    return "?" if x is None else ("{:." + str(nd) + "f}").format(x)


class Ctx(object):
    """One run (scenario) being evaluated."""

    def __init__(self, cat, cfg, charts, run, dam, flags, rule=RULE_LEGACY):
        self.cat, self.cfg, self.charts, self.run, self.dam, self.flags = \
            cat, cfg, charts, run, dam or {}, flags
        self.rule = rule
        self.scenario = run.get("scenario")
        dim = (run.get("model_dim") or "").strip().upper() or None
        self.dim = dim if dim in ("1D", "2D") else None
        self.general = cfg["general"]
        self.wet_min = float(self.general.get("wet_min_depth_ft", 0.0))
        self.hits = []
        self.receptors = []            # scored receptors (after the domain / future filters)
        self._lives = None

    # -- configuration
    def on(self, mid):
        return mid in self.cfg["methods"] or mid in self.cfg["modifiers"]

    def p(self, mid):
        e = self.cfg["methods"].get(mid) or self.cfg["modifiers"].get(mid)
        return e["params"] if e else {}

    def strength(self, mid):
        e = self.cfg["methods"].get(mid) or self.cfg["modifiers"].get(mid)
        return e["strength"] if e else "rule"

    def flag(self, level, code, msg, method=None, receptor=None):
        return self.flags.add(level, code, msg, method, receptor, self.scenario)

    def hit(self, mid, cls, receptors, reason, strength=None):
        if cls is None:
            return
        h = {"method": mid, "class": int(cls), "receptors": [r["id"] if isinstance(r, dict)
                                                             else r for r in _list(receptors)],
             "strength": strength or self.strength(mid), "reason": reason,
             "scenario": self.scenario}
        self.hits.append(h)
        return h

    # -- receptor sets
    def of(self, *kinds):
        return [r for r in self.receptors if r["kind"] in kinds]

    def life(self, mid, *kinds):
        """Receptors a life-safety method may count (R1 removes transients)."""
        kinds = kinds or STRUCT_KINDS
        return [r for r in self.of(*kinds) if not r.get("_transient_excluded")]

    def impacted(self, r, mid=None):
        """True / False, or None (unknown: flagged) - wet from the rasters, else the receptor's
        'inundated' attribute (M13's presence-only case)."""
        if r.get("_not_incremental"):
            return False
        if r.get("sampled") and r.get("depth_ft") is not None:
            return r["depth_ft"] > self.wet_min
        if r.get("inundated") is not None:
            return bool(r["inundated"])
        self.flag(WARNING, "no_hydraulics", "no depth sampled and no 'inundated' attribute: "
                  "receptor not scored", mid, r["id"])
        return None

    def habitable(self, r):
        if self.rule == RULE_REVIEWED and r.get("kind") == "structure":
            return reviewed_status(r, self.cat["habitable_types"])[0] == STATUS_YES
        ok, basis = habitable_basis(r, self.cat["habitable_types"])
        if basis == BASIS_UNKNOWN:
            self.flag(WARNING, "type_unknown", "structure type unknown: treated as habitable "
                      "(a home)", None, r["id"])
        return ok

    def occupied(self, r):
        """R2: habitable structures are presumed occupied; occasionally used ones are not."""
        if r.get("occupancy") in OCCUPANCY_NOT_OCCUPIED:
            return False
        return self.habitable(r)

    # -- hydraulics
    def depth_at(self, r, datum, mid=None):
        """Depth (ft) against 'ground', 'foundation' or 'floor'; a missing datum falls back to
        the ground depth with a flag (A.7: no floor elevation -> ground depth, warning)."""
        d = r.get("depth_ft")
        if d is None:
            return None
        if datum == "ground":
            return d
        if datum == "foundation":
            if r.get("foundation_elev") is not None and r.get("wse_ft") is not None:
                return r["wse_ft"] - r["foundation_elev"]
            return d                        # the sampled ground depth is at the foundation line
        if datum == "floor":
            if r.get("floor_elev") is not None and r.get("wse_ft") is not None:
                return r["wse_ft"] - r["floor_elev"]
            if r.get("floor_height_ft") is not None:
                return d - r["floor_height_ft"]
            if r.get("floor_elev") is not None and r.get("ground_elev") is not None:
                return d - (r["floor_elev"] - r["ground_elev"])
            if self.on("R2") and self.p("R2").get("floor_presumption"):
                self.flag(INFO, "floor_presumed", "no floor elevation: R2 presumes a flooded "
                          "home is flooded above its lowest occupied floor (ground depth used)",
                          mid, r["id"])
            else:
                self.flag(WARNING, "floor_fallback", "no floor elevation or first-floor height: "
                          "ground depth used for the lowest-floor datum", mid, r["id"])
            return d
        raise ValueError("unknown datum " + str(datum))

    def pairs(self, r, datum, mid):
        """[(depth at datum, velocity)] of the receptor's wet cells; velocity None when absent."""
        dd = self.depth_at(r, datum, mid)
        if dd is None:
            return []
        shift = r["depth_ft"] - dd
        cells = r.get("cells")
        if cells:
            return [(c[0] - shift, c[1]) for c in cells
                    if c[0] is not None and c[0] > self.wet_min]
        return [(dd, r.get("velocity_fps"))]

    def charts_for(self, r, chart_ids, mapping):
        key = "road" if r["kind"] == "road" else (r.get("type") or "home")
        return [c for c in _list(mapping.get(key)) if c in chart_ids]

    def zone(self, r, chart_ids, datum, mid, mapping=None):
        """(worst zone, chart, (d, v), margin) over the charts that apply, or None when no
        digitized chart applies / no velocity (flagged)."""
        mapping = mapping or self.cat["methods"]["M1"]["params"]["chart_for_type"]
        cids = self.charts_for(r, chart_ids, mapping)
        if not cids:
            return None
        pairs = self.pairs(r, datum, mid)
        if not pairs:
            return None
        if any(v is None for _d, v in pairs):
            self.flag(ERROR, "no_velocity", "no velocity sampled: the depth-velocity charts "
                      "cannot be read", mid, r["id"])
            return None
        best = None
        for cid in cids:
            if not self.charts.digitized(cid):
                self.flag(WARNING, "chart_not_digitized", "TM-11 chart '{}' is not digitized: "
                          "an engineer reads the figure (or supply a curve)".format(
                              self.charts.title(cid)), mid, r["id"])
                continue
            z, at, margin = self.charts.worst(cid, pairs)
            if z is None:
                continue
            if best is None or tm11.RANK[z] > tm11.RANK[best[0]]:
                best = (z, cid, at, margin)
        return best

    def danger_zone(self, r, mid):
        """The receptor's zone for life-loss counting: M1's when M1 ran, else from the M5
        danger charts (flagged once)."""
        if "_zone" in r:
            return r["_zone"]
        charts = self.p("M5").get("danger_charts") or ["houses", "mobile_homes"]
        z = self.zone(r, charts, "ground", mid)
        r["_zone"] = z[0] if z else None
        if z:
            self.flag(INFO, "danger_from_charts", "lethality read from the TM-11 houses / "
                      "mobile-homes charts at ground depth (M1 not enabled)", mid)
        return r["_zone"]

    def lethal(self, r, mid):
        return bool(r.get("_m2")) or self.danger_zone(r, mid) == tm11.HIGH

    def dv(self, r, mid):
        if r.get("dv_ft2s") is not None:
            if r.get("dv_source") == "cells":
                self.flag(INFO, "dv_from_cells", "no DV raster: DV is the largest depth x "
                          "velocity of the max rasters at one cell (may overstate the event "
                          "maximum DV)", mid)
            return r["dv_ft2s"]
        cells = r.get("cells")
        if cells and all(c[1] is not None for c in cells):
            self.flag(INFO, "dv_from_cells", "no DV raster: DV is the largest depth x velocity "
                      "of the max rasters at one cell (may overstate the event maximum DV)", mid)
            return max(c[0] * c[1] for c in cells)
        if r.get("velocity_fps") is not None and r.get("depth_ft") is not None:
            return r["depth_ft"] * r["velocity_fps"]
        self.flag(WARNING, "no_dv", "no velocity / DV: the DV test is not scored", mid, r["id"])
        return None

    def lives_in_jeopardy(self, mid):
        """(lives, [receptor ids]) in dangerous depth-velocity zones (M1 / M2)."""
        if self._lives is not None:
            return self._lives
        if self.dam.get("lives_in_jeopardy") is not None:
            self.flag(INFO, "lives_given", "lives in jeopardy taken from the dam record ({})"
                      .format(self.dam["lives_in_jeopardy"]), mid)
            self._lives = (float(self.dam["lives_in_jeopardy"]), [])
            return self._lives
        count_j = bool(self.p("M5").get("count_judgment_zone"))
        lives, ids = 0.0, []
        for r in self.life(mid):
            if not self.impacted(r, mid) or not self.occupied(r):
                continue
            z = self.danger_zone(r, mid)
            if r.get("_m2") or z == tm11.HIGH or (count_j and z == tm11.JUDGMENT):
                n = r.get("occupants")
                if n is None:
                    n = 1.0
                    self.flag(WARNING, "occupants_unknown", "occupants unknown: counted as 1 "
                              "life (a lower bound)", mid, r["id"])
                lives += n
                ids.append(r["id"])
        self._lives = (lives, ids)
        return self._lives

    def need(self, mid, kinds):
        rs = self.of(*kinds)
        if not rs:
            given = [r for r in self.run.get("receptors") or [] if r["kind"] in kinds]
            if not given:
                self.flag(WARNING, "no_layer", "no {} receptors supplied: {} not scored".format(
                    "/".join(kinds), mid), mid)
            else:
                # (0.2.2) the layer WAS supplied and sampled; none of its features is in the scored set
                out = sum(1 for r in given if r.get("in_domain") is False)
                self.flag(INFO, "layer_none_scored", "{} {} receptor(s) were supplied and sampled, but none is in the scored set "
                          "({} outside the routed domain, {} left out by the scenario / development / cutoff filters): "
                          "{} has nothing to score".format(len(given), "/".join(kinds), out, len(given) - out, mid), mid)
        return rs


# ============================================================== methods ==
def m1(ctx):
    P = ctx.p("M1")
    if P.get("require_2d") and ctx.dim != "2D":
        if ctx.dim == "1D":
            ctx.flag(ERROR, "m1_blocked_1d", "M1 is blocked: this method's charts need a 2D "
                     "model and the run is 1D", "M1")
        else:
            ctx.flag(ERROR, "dim_unknown", "model dimensionality not given: M1 (2D only) is "
                     "not scored", "M1")
        return
    charts = P["charts"]
    kinds = ("structure", "facility", "road") if "passenger_vehicles" in charts else STRUCT_KINDS
    r7 = ctx.p("R7") if ctx.on("R7") else {}
    for r in ctx.life("M1", *kinds):
        if not ctx.impacted(r, "M1"):
            continue
        if r["kind"] != "road" and not ctx.occupied(r):
            continue
        z = ctx.zone(r, charts, P["depth_datum"], "M1", P["chart_for_type"])
        if z is None:
            continue
        zone, cid, (d, v), margin = z
        r["_zone"] = zone
        where = "{} at {} ft, {} ft/s ({} datum)".format(ctx.charts.title(cid), _f(d), _f(v),
                                                         P["depth_datum"])
        if zone == tm11.HIGH:
            ctx.hit("M1", P.get("high_class"), r, "high danger zone: " + where)
        elif zone == tm11.JUDGMENT:
            ctx.flag(WARNING, "judgment_zone", "M1 judgment zone: engineer review needed",
                     "M1", r["id"])
            near = r7.get("near_margin_ft")
            if r7.get("judgment_zone_to_high"):
                ctx.hit("M1", 3, r, "judgment zone taken higher (R7): " + where)
            elif near is not None and margin is not None and margin <= float(near):
                ctx.hit("M1", 3, r, "within {} ft of the high-danger line, taken higher (R7): {}"
                        .format(near, where))
            elif P.get("judgment_hit_class") is not None:
                ctx.hit("M1", P["judgment_hit_class"], r, "judgment zone: " + where)
        if P.get("above_low_class") is not None and zone in (tm11.JUDGMENT, tm11.HIGH):
            ctx.hit("M1", P["above_low_class"], r, "above the Low Danger zone: " + where)


def m2(ctx):
    P = ctx.p("M2")
    if P.get("only_if_1d") and ctx.dim != "1D":
        if ctx.dim is None:
            ctx.flag(ERROR, "dim_unknown", "model dimensionality not given: M2 (1D only) is "
                     "not scored", "M2")
        else:
            ctx.flag(INFO, "m2_not_1d", "M2 applies to 1D runs only; this run is 2D", "M2")
        return
    # "habitable" (every occupied habitable structure), "residence", or a list of receptor types
    rt = P.get("receptor_types")
    types = ctx.cat["residence_types"] if rt == "residence" else \
        list(rt) if isinstance(rt, (list, tuple)) else None
    thr, cmp_ = float(P["threshold_ft"]), P["comparator"]
    for r in ctx.life("M2"):
        if not ctx.impacted(r, "M2"):
            continue
        if types is not None and r.get("type") not in types:
            continue
        if types is None and not ctx.occupied(r):
            continue
        d = ctx.depth_at(r, P["depth_datum"], "M2")
        if d is None:
            continue
        if (d > thr) if cmp_ == ">" else (d >= thr):
            r["_m2"] = True
            ctx.hit("M2", 3, r, "depth {} ft {} {} ft ({} datum)".format(
                _f(d), cmp_, thr, P["depth_datum"]))


def _m3_row(ctx, r, row, rname, mid, walkout_option):
    # row["datum"] is the Significant / Low split datum, row["high_datum"] the High test's (both
    # from the catalog M3 rules: institutions split at the foundation, High at the lowest floor)
    d = ctx.depth_at(r, row["datum"], mid)
    if d is None:
        return
    hdat = row.get("high_datum") or row["datum"]
    d_hi = d if hdat == row["datum"] else ctx.depth_at(r, hdat, mid)
    if row.get("low_only"):
        if d > 0:
            ctx.hit(mid, 1, r, "unoccupied farm / storage building, flow above the foundation "
                               "line ({} ft)".format(_f(d)))
        return
    if row.get("min_nights_per_year") is not None:
        n = r.get("nights_per_year")
        if n is None:
            ctx.flag(WARNING, "nights_unknown", "campground nights occupied per year unknown: "
                     "assumed more than {}".format(row["min_nights_per_year"]), mid, r["id"])
        elif n <= row["min_nights_per_year"]:
            ctx.flag(INFO, "campground_seasonal", "campground occupied {} nights/yr or fewer: "
                     "matrix row not applied".format(row["min_nights_per_year"]), mid, r["id"])
            return
    hi_d = row["high_depth_ft"]
    if walkout_option and r.get("walkout") and row.get("walkout_high_depth_ft") is not None:
        hi_d = row["walkout_high_depth_ft"]
    dv = ctx.dv(r, mid)
    why = "{} row: {} ft ({} datum), DV {}".format(rname, _f(d), row["datum"], _f(dv))
    if hdat != row["datum"]:
        why += ", {} ft ({} datum, High test)".format(_f(d_hi), hdat)
    if d_hi >= hi_d or (dv is not None and dv >= row["high_dv"]):
        ctx.hit(mid, 3, r, why + " -> High (>= {} ft or DV >= {})".format(hi_d, row["high_dv"]))
        return
    lb = row["low_below_ft"]
    low = d <= 0 if lb == 0 else d < lb
    ctx.hit(mid, 1 if low else 2, r, why)


def m3(ctx, mid="M3", only_row=None):
    # M10b reads its own institutions row (catalog M10b parameters) when it has one, else the
    # M3 rows: the configured ones when M3 is enabled, else the catalog's
    P = ctx.p("M3") if "M3" in ctx.cfg["methods"] else ctx.cat["methods"]["M3"]["params"]
    rows = P["rows"]
    if mid != "M3" and ctx.p(mid).get("rows"):
        rows = ctx.p(mid)["rows"]
    rs = ctx.need(mid, STRUCT_KINDS)
    for r in rs:
        if not ctx.impacted(r, mid):
            continue
        hit_row = None
        for rname, row in rows.items():
            if only_row and rname != only_row:
                continue
            if r.get("type") in row["types"] or (r.get("type") is None and rname == "home"
                                                and not only_row):
                hit_row = (rname, row)
                break
        if hit_row is None:
            if not only_row:
                ctx.flag(INFO, "m3_type", "structure type '{}' has no row in the matrix".format(
                    r.get("type")), mid, r["id"])
            continue
        _m3_row(ctx, r, hit_row[1], hit_row[0], mid, P.get("walkout_option"))


def m4a(ctx):
    P = ctx.p("M4a")
    deep = []
    for r in ctx.life("M4a"):
        if ctx.impacted(r, "M4a") and ctx.occupied(r):
            d = ctx.depth_at(r, P["depth_datum"], "M4a")
            if d is not None and d >= P["depth_ft"]:
                deep.append(r)
    if len(deep) >= P["min_count"]:
        ctx.hit("M4a", 3, deep, "{} occupied structures with {} ft or more ({} or more)".format(
            len(deep), P["depth_ft"], P["min_count"]))
    elif deep:
        ctx.flag(INFO, "m4a_count", "{} occupied structure(s) with {} ft or more (fewer than {})"
                 .format(len(deep), P["depth_ft"], P["min_count"]), "M4a")


def _band(count, bands):
    for i, (lo, hi) in enumerate(bands):
        if count >= lo and (hi is None or count <= hi):
            return i
    return None


def m4b(ctx):
    P = ctx.p("M4b")
    rows = {"up_to_split": [], "over_split": [], "above_low_danger": []}
    for r in ctx.life("M4b"):
        if r.get("type") not in ctx.cat["residence_types"] and r.get("type") is not None:
            continue
        if not ctx.impacted(r, "M4b") or not ctx.occupied(r):
            continue
        d = ctx.depth_at(r, P["depth_datum"], "M4b")
        if d is None or d <= 0:
            continue
        rows["up_to_split"].append(r)
        if d > P["depth_split_ft"]:
            rows["over_split"].append(r)
        z = ctx.zone(r, P["low_danger_charts"], P["depth_datum"], "M4b")
        if z and z[0] in (tm11.JUDGMENT, tm11.HIGH):
            rows["above_low_danger"].append(r)
    best = None
    for key, rs in rows.items():
        col = _band(len(rs), P["count_bands"])
        if col is None:
            continue
        cls = P["table"][key][col]
        if best is None or cls > best[0]:
            best = (cls, key, rs)
    if best:
        ctx.hit("M4b", best[0], best[2], "{} home(s) in row '{}' of the homes x depth table"
                .format(len(best[2]), best[1]))


def m4c(ctx):
    P = ctx.p("M4c")
    hab = [r for r in ctx.life("M4c") if ctx.impacted(r, "M4c") and ctx.habitable(r)
           and r.get("type") not in ("farm_unoccupied", "storage", "outbuilding")]
    n = len(hab)
    if n >= P["structures_high_min"]:
        ctx.hit("M4c", 3, hab, "{} habitable structures in the inundation area".format(n))
    elif n >= P["structures_sig_min"]:
        ctx.hit("M4c", 2, hab, "{} habitable structure(s) in the inundation area".format(n))
    lives = ctx.dam.get("lives_in_inundation")
    if lives is None:
        occ = [r.get("occupants") for r in hab]
        if hab and any(o is None for o in occ):
            ctx.flag(WARNING, "lives_unknown", "occupants missing on some structures: the lives "
                     "test counts only the known occupants", "M4c",
                     [r["id"] for r in hab if r.get("occupants") is None])
        lives = sum(o for o in occ if o is not None)
    if lives >= P["lives_high_min"]:
        ctx.hit("M4c", 3, hab, "{:g} lives in the inundation area".format(lives))
    elif lives >= P["lives_sig_min"]:
        ctx.hit("M4c", 2, hab, "{:g} li{} in the inundation area".format(
            lives, "fe" if lives == 1 else "ves"))


def m5(ctx):
    P = ctx.p("M5")
    lives, ids = ctx.lives_in_jeopardy("M5")
    lowering = P.get("purpose") == "lowering_only"
    strength = "advisory" if lowering else None
    tag = " (supports lowering a proposed class only)" if lowering else ""
    if P.get("high_min") is not None and lives >= P["high_min"]:
        ctx.hit("M5", 3, ids, "{:g} li{} in jeopardy (High at {} or more){}".format(
            lives, "fe" if lives == 1 else "ves", P["high_min"], tag), strength)
    elif P.get("sig_min") is not None and lives >= P["sig_min"]:
        ctx.hit("M5", 2, ids, "{:g} li{} in jeopardy (Significant at {} or more){}".format(
            lives, "fe" if lives == 1 else "ves", P["sig_min"], tag), strength)
    elif lowering:
        ctx.flag(INFO, "m5_none", "no lives in jeopardy found: supports lowering a proposed "
                 "class", "M5")


def m6(ctx):
    P = ctx.p("M6")
    var = P.get("variant", "any_inundation")
    if var == "indirect_life_loss":
        for r in ctx.receptors:
            if not ctx.impacted(r, "M6"):
                continue
            if r.get("indirect_life_loss"):
                ctx.hit("M6", 2, r, "damage that may cause indirect loss of life")
            elif r["kind"] in ("road", "rail") and r.get("indirect_life_loss") is None:
                ctx.flag(INFO, "m6_indirect", "inundated road / rail: check for indirect loss "
                         "of life (washout leading to crashes); set indirect_life_loss", "M6",
                         r["id"])
        return
    for r in ctx.need("M6", STRUCT_KINDS):
        if not ctx.impacted(r, "M6") or not ctx.occupied(r):
            continue
        if r.get("sampled") and r.get("depth_ft") is not None and round(r["depth_ft"], 2) <= ctx.wet_min:
            # 0.1.2: a structure whose sampled depth rounds to 0.00 ft is not wet; M6 counted one
            # ("inundated (0.00 ft)") on the DWR-2801 run
            ctx.flag(INFO, "m6_trace_depth", "sampled depth {:.4f} ft rounds to 0.00 ft: not counted as an "
                     "inundated structure".format(r["depth_ft"]), "M6", r["id"])
            continue
        if ctx.lethal(r, "M6"):
            continue
        if var == "uninhabitable_inoperable":
            if r.get("damage_state") in ("uninhabitable", "inoperable"):
                ctx.hit("M6", 2, r, "left {} by the flood".format(r["damage_state"]))
            elif r.get("damage_state") is None:
                ctx.flag(WARNING, "m6_damage_unknown", "inundated structure without a "
                         "damage_state (uninhabitable / inoperable): not scored", "M6", r["id"])
        else:
            ctx.hit("M6", 2, r, "habitable structure inundated ({} ft) without lethal "
                    "conditions".format(_f(r.get("depth_ft"))))


def m7(ctx):
    P = ctx.p("M7")
    lives, ids = ctx.lives_in_jeopardy("M7")
    pop = ctx.dam.get("population_inundation")
    wet = [r for r in ctx.life("M7") if ctx.impacted(r, "M7")]
    if pop is None:
        occ = [r.get("occupants") for r in wet if r["kind"] == "structure"]
        pop = sum(o for o in occ if o is not None)
        ctx.flag(INFO if all(o is not None for o in occ) else WARNING, "m7_population",
                 "population in the inundation area derived from structure occupants ({:g}); "
                 "set population_inundation on the dam to override".format(pop), "M7")
    crit, crit_unknown = [], []
    for r in ctx.of("structure", "facility"):
        if r.get("type") in ctx.cat["critical_facility_types"] and ctx.impacted(r, "M7"):
            if r.get("public_safety_threat"):
                crit.append(r)
            elif r.get("public_safety_threat") is None:
                crit_unknown.append(r["id"])
    if crit_unknown:
        ctx.flag(WARNING, "m7_case_by_case", "inundated critical facility: whether it poses a "
                 "significant public-safety threat is case by case (set public_safety_threat)",
                 "M7", crit_unknown)
    if lives >= P["min_lives"] and (pop >= P["min_population"] or crit):
        why = "population {:g} >= {}".format(pop, P["min_population"]) \
            if pop >= P["min_population"] else "critical facilities posing a public-safety threat"
        ctx.hit("M7", 4, ids + [r["id"] for r in crit],
                "{:g} li{} expected and {}".format(lives, "fe" if lives == 1 else "ves", why))


def _roads(ctx, mid):
    return [r for r in ctx.need(mid, ("road",)) if ctx.impacted(r, mid)
            and not r.get("_limited_use")]


def m8a(ctx):
    P = ctx.p("M8a")
    for r in _roads(ctx, "M8a"):
        c, a = r.get("road_class"), r.get("aadt")
        cls, why = None, []
        if c in P["high_classes"]:
            cls, why = 3, [c]
        elif c in P["sig_classes"]:
            cls, why = 2, [c]
        elif c in P["low_classes"]:
            cls, why = 1, [c]
        if a is not None:
            ca = 3 if a > P["high_above_aadt"] else (2 if a >= P["low_below_aadt"] else 1)
            why.append("AADT {:g}".format(a))
            # The catalog takes the highest matching rule, so AADT raises a Low
            # road class (a private road with AADT over 2,000 is High).
            cls = ca if cls is None or ca > cls else cls
        if cls is None:
            ctx.flag(WARNING, "m8a_unknown", "road class and AADT unknown: not scored", "M8a",
                     r["id"])
            continue
        ctx.hit("M8a", cls, r, "road impacted: " + ", ".join(why))


def m8b(ctx):
    rs = _roads(ctx, "M8b")
    if rs and all(r.get("sole_access") is None for r in rs):
        ctx.flag(WARNING, "m8b_attr", "no road carries a sole_access attribute: the sole-access "
                 "test is not scored", "M8b")
    for r in rs:
        if r.get("sole_access"):
            ctx.hit("M8b", 2, r, "only access to an occupied location")


def m8c(ctx):
    P = ctx.p("M8c")
    for r in _roads(ctx, "M8c"):
        c, d = r.get("road_class"), r.get("depth_ft")
        lanes = r.get("lanes")
        if c == "interstate" or (c == "us_state" and lanes is not None
                                 and lanes >= P["multilane_min_lanes"]):
            if d is None:
                continue
            ctx.hit("M8c", 3 if d >= P["depth_split_ft"] else 2, r,
                    "interstate / multi-lane highway, {} ft over the road".format(_f(d)))
        elif c == "us_state":
            if lanes is None:
                ctx.flag(WARNING, "m8c_lanes", "lanes unknown: treated as under {} lanes".format(
                    P["multilane_min_lanes"]), "M8c", r["id"])
            ctx.hit("M8c", 2 if (d or 0) >= P["depth_split_ft"] else 1, r,
                    "U.S. / state highway, {} ft over the road".format(_f(d)))
        elif c in ("other_public", "municipal", "township_county"):
            ctx.hit("M8c", 1, r, "other maintained public road")
        elif c is None:
            ctx.flag(WARNING, "m8c_class", "road class unknown: not scored", "M8c", r["id"])


def m8d(ctx):
    P = ctx.p("M8d")
    for r in _roads(ctx, "M8d"):
        fc, a = r.get("func_class"), r.get("aadt")
        if a is not None and a <= P["minor_road_max_aadt"]:
            ctx.hit("M8d", 1, r, "AADT {:g}: minor road".format(a))
            continue
        cls = 3 if fc in P["high"] else 2 if fc in P["significant"] else 1 if fc in P["low"] \
            else None
        if cls is None:
            ctx.flag(WARNING, "m8d_fc", "functional class unknown ('{}'): not scored".format(fc),
                     "M8d", r["id"])
            continue
        ctx.hit("M8d", cls, r, "functional class " + fc)


def m8e(ctx):
    P = ctx.p("M8e")
    lim = [r for r in _roads(ctx, "M8e") if r.get("aadt") is not None
           and r["aadt"] <= P["limited_use_max_aadt"]]
    if not lim:
        return
    groups = {}
    for r in lim:
        g = r.get("trip_group") or r["id"]
        groups[g] = max(groups.get(g, 0.0), r["aadt"])
    total = sum(groups.values()) if P.get("sum_aadt", True) else max(groups.values())
    if total > P["limited_use_max_aadt"]:
        ctx.flag(WARNING, "m8e_sum", "the low-volume roads' AADTs sum to {:g} (over {}): they "
                 "are not treated as limited use".format(total, P["limited_use_max_aadt"]),
                 "M8e", [r["id"] for r in lim])
        return
    for r in lim:
        r["_limited_use"] = True
        ctx.hit("M8e", 1, r, "limited-use road (AADT {:g}; total {:g})".format(r["aadt"], total))


def m8f(ctx):
    P = ctx.p("M8f")
    rs = _roads(ctx, "M8f")
    if rs and all(r.get("isolates_homes") is None for r in rs):
        ctx.flag(WARNING, "m8f_attr", "no road carries isolates_homes: isolation not scored",
                 "M8f")
    for r in rs:
        n = r.get("isolates_homes")
        if n is not None and n >= P["min_homes_isolated"]:
            ctx.hit("M8f", 2, r, "cuts off {:g} homes from emergency services".format(n))
        if r.get("crossings_failed"):
            ctx.flag(WARNING, "m8f_crossings", "failed road / driveway crossings ({:g}): 'many' "
                     "is an engineer's call".format(r["crossings_failed"]), "M8f", r["id"])


def m8g(ctx):
    P = ctx.p("M8g")
    muni = []
    for r in _roads(ctx, "M8g"):
        c = r.get("road_class")
        if r.get("washout") is None:
            ctx.flag(WARNING, "m8g_washout", "inundated road without a washout attribute: "
                     "washout not assessed", "M8g", r["id"])
        if r.get("washout") and c in P["highway_classes"]:
            ctx.hit("M8g", 2, r, "washout of a state or federal highway")
        elif r.get("washout") and c in P["municipal_classes"]:
            muni.append(r)
        if r.get("access_residences") or (r.get("access_residences") is None
                                          and r.get("sole_access")):
            ctx.hit("M8g", 2, r, "loss of vehicle access to residences")
    if len(muni) >= P["min_municipal_washouts"]:
        ctx.hit("M8g", 2, muni, "washout of {} municipal roads".format(len(muni)))


def _rails(ctx, mid):
    out = []
    for r in ctx.need(mid, ("rail",)):
        if not ctx.impacted(r, mid):
            continue
        if r.get("active") is False:
            continue
        if r.get("active") is None:
            ctx.flag(INFO, "rail_active", "rail 'active' unknown: treated as active", mid,
                     r["id"])
        out.append(r)
    return out


def _trains_ruling(ctx, mid, r):
    if r.get("trains_needs_ruling"):
        ctx.flag(WARNING, "trains_lookup", "trains per day {:g} from the RAIL_TRAINS_LOOKUP input ({}): not in "
                 "the rail layer, needs Nick's ruling before a class resting on it is used".format(
                     r["trains_per_day"], r.get("trains_source") or "no source"), mid, r["id"])


def m9a(ctx):
    P = ctx.p("M9a")
    for r in _rails(ctx, "M9a"):
        t = r.get("trains_per_day")
        _trains_ruling(ctx, "M9a", r)
        if r.get("passenger"):
            ctx.hit("M9a", 3, r, "active passenger line")
        elif t is not None and t >= P["high_min_trains_per_day"]:
            ctx.hit("M9a", 3, r, "freight line, {:g} trains/day".format(t))
        else:
            if t is None:
                ctx.flag(WARNING, "trains_unknown", "trains per day unknown: High test (10+ "
                         "freight trains or passenger) not confirmed; give trains_per_day in the rail "
                         "layer or a RAIL_TRAINS_LOOKUP CSV (no default is assumed)", "M9a", r["id"])
            ctx.hit("M9a", 2, r, "active rail line impacted")


def m9b(ctx):
    P = ctx.p("M9b")
    for r in _rails(ctx, "M9b"):
        t, d = r.get("trains_per_day"), r.get("depth_ft") or 0.0
        _trains_ruling(ctx, "M9b", r)
        main = (t >= P["main_min_trains_per_day"]) if t is not None else r.get("main_line")
        if main is None:
            ctx.flag(WARNING, "trains_unknown", "trains per day unknown and no main_line flag: "
                     "not scored", "M9b", r["id"])
            continue
        deep = d >= P["depth_split_ft"]
        ctx.hit("M9b", (3 if deep else 2) if main else (2 if deep else 1), r,
                "{} line, {} ft over the rail bed".format("main" if main else "minor", _f(d)))


def m9c(ctx):
    P = ctx.p("M9c")
    for r in _rails(ctx, "M9c"):
        cat = r.get("line_category")
        if r.get("passenger") or cat in P.get("high_services", ()) or \
                cat in ("intercity_passenger", "commuter", "transit"):
            ctx.hit("M9c", 3, r, "passenger / commuter / transit line")
        elif r.get("freight_class") in P["high_freight_classes"]:
            ctx.hit("M9c", 3, r, "Class {} freight".format(r["freight_class"]))
        elif r.get("fuel_line") or r.get("strategic") or r.get("hazmat_yard"):
            ctx.hit("M9c", 3, r, "fuel-delivery / strategic line or toxic-hazmat yard")
        elif cat in P.get("significant_services", ()) or \
                cat in ("scenic", "tourist", "other_freight", "freight") or \
                r.get("freight_class") is not None:
            ctx.hit("M9c", 2, r, "scenic / tourist or other freight line")
        else:
            ctx.flag(WARNING, "m9c_category", "rail line category unknown: not scored", "M9c",
                     r["id"])


def m10a(ctx):
    P = ctx.p("M10a")
    fac = [r for r in ctx.need("M10a", ("facility", "structure"))
           if r.get("type") in ctx.cat["critical_facility_types"]]
    if not fac:
        ctx.flag(INFO, "m10a_none", "no hospital, nursing home, fire or police station among "
                 "the receptors", "M10a")
    for r in fac:
        if r.get("isolated"):
            ctx.hit("M10a", 2, r, "{} isolated by floodwater".format(r["type"]))
        elif r.get("isolated") is None:
            ctx.flag(WARNING, "m10a_isolated", "critical facility without an 'isolated' "
                     "attribute: isolation not assessed", "M10a", r["id"])
        if r["type"] == "hospital" and ctx.impacted(r, "M10a"):
            d = ctx.depth_at(r, P["depth_datum"], "M10a")
            if d is not None and d >= P["hospital_high_depth_ft"]:
                ctx.hit("M10a", 3, r, "hospital flooded {} ft".format(_f(d)))


def m10b(ctx):
    m3(ctx, "M10b", only_row=ctx.p("M10b").get("m3_row", "institution"))


def _lifelines(ctx, mid):
    return [r for r in ctx.need(mid, ("lifeline",)) if not r.get("own_supply")]


def m11a(ctx):
    for r in _lifelines(ctx, "M11a"):
        if r.get("impact") in ("reduced", "blocked", "blocked_access") or \
                ctx.impacted(r, "M11a"):
            ctx.hit("M11a", 2, r, "lifeline impacted ({})".format(r.get("impact") or "inundated"))


def m11b(ctx):
    P = ctx.p("M11b")
    for r in _lifelines(ctx, "M11b"):
        wet = ctx.impacted(r, "M11b")
        o = r.get("outage_days")
        if o is not None and o > P["high_outage_days_over"]:
            ctx.hit("M11b", 3, r, "service interruption {:g} days".format(o))
        elif r.get("type") in ("generation", "power_plant") and wet and \
                (ctx.depth_at(r, "floor", "M11b") or 0) > 0:
            ctx.hit("M11b", 3, r, "flow above the first floor of a generation facility")
        elif r.get("impact") in ("exposed", "undermined"):
            ctx.hit("M11b", 2, r, "{} line / tower".format(r["impact"]))
        elif wet:
            ctx.flag(WARNING, "m11b_impact", "inundated lifeline without impact / outage "
                     "attributes: not scored", "M11b", r["id"])


def m11c(ctx):
    P = ctx.p("M11c")
    for r in _lifelines(ctx, "M11c"):
        if not ctx.impacted(r, "M11c") and r.get("impact") is None:
            continue
        if r.get("type") == "wastewater":
            if r.get("ww_class") in P["wastewater_sig_classes"]:
                ctx.hit("M11c", 2, r, "{} wastewater plant".format(r["ww_class"]))
            elif r.get("ww_class") is None:
                ctx.flag(WARNING, "m11c_ww", "wastewater plant size class unknown", "M11c",
                         r["id"])
            else:
                ctx.hit("M11c", 1, r, "lesser wastewater plant")
            continue
        u, o = r.get("units_served"), r.get("outage_days")
        if u is None:
            ctx.flag(WARNING, "m11c_units", "units served unknown: 'important' utility test not "
                     "scored", "M11c", r["id"])
            continue
        if u < P["important_min_units"]:
            continue
        hi = P.get("high_outage_days")
        if r.get("major_population") or (hi is not None and o is not None and o >= hi):
            ctx.hit("M11c", 3, r, "important utility: loss to major populations / for weeks")
        elif o is not None and o <= P["sig_max_outage_days"]:
            ctx.hit("M11c", 2, r, "important utility interrupted {:g} days".format(o))
        else:
            ctx.flag(WARNING, "m11c_outage", "important utility with an outage over {} days or "
                     "unknown: High needs 'several weeks' or major populations (engineer)"
                     .format(P["sig_max_outage_days"]), "M11c", r["id"])
            ctx.hit("M11c", 2, r, "important utility interrupted (at least Significant)")


def _env(ctx, mid):
    return [r for r in ctx.need(mid, ("environment",)) if ctx.impacted(r, mid)]


def m12a(ctx):
    P = ctx.p("M12a")
    for r in _env(ctx, "M12a"):
        if r.get("type") not in P["site_types"]:
            continue
        m = r.get("mitigation")
        if m in ("extensive", "impossible"):
            ctx.hit("M12a", 3, r, "{} site: mitigation {}".format(r["type"], m))
        elif m == "major":
            ctx.hit("M12a", 2, r, "{} site: major mitigation".format(r["type"]))
        else:
            ctx.flag(WARNING, "m12a_mitigation", "cultural site without a mitigation level "
                     "(major / extensive / impossible): not scored", "M12a", r["id"])


def m12b(ctx):
    P = ctx.p("M12b")
    for r in _env(ctx, "M12b"):
        if r.get("substantial") or (r.get("substantial") is None and r.get("type") in P["types"]):
            ctx.hit("M12b", 2, r, "substantial environmental damage ({})".format(
                r.get("type") or "flagged"))


def m12c(ctx):
    for r in _env(ctx, "M12c"):
        if r.get("anadromous"):
            ctx.hit("M12c", 2, r, "important anadromous-fish water")


def m12d(ctx):
    for r in _env(ctx, "M12d"):
        if r.get("agency_identified"):
            ctx.flag(WARNING, "m12d_intangible", "intangible loss identified by a resource "
                     "agency ({}, {}): weigh it (no class in the source)".format(
                         "unique" if r.get("unique") else "common or unknown",
                         "permanent" if r.get("permanent") else "temporary or unknown"),
                     "M12d", r["id"])


def m13(ctx):
    P = ctx.p("M13")
    wording = P.get("wording", "general")
    desc = P["descriptors"][wording]
    by_desc = {d: int(c) for c, ds in desc.items() for d in ds}
    auto = P.get("auto_map", {}).get(wording, {})
    for r in ctx.receptors:
        if r.get("_limited_use"):
            continue
        if not ctx.impacted(r, "M13"):
            continue
        d = r.get("descriptor")
        if d:
            if d in by_desc:
                ctx.hit("M13", by_desc[d], r, "descriptor '{}'".format(d))
            else:
                ctx.flag(WARNING, "m13_descriptor", "descriptor '{}' not in this wording's "
                         "list".format(d), "M13", r["id"])
            continue
        if r["kind"] == "road":
            key = "road:" + (r.get("road_class") or "")
        elif r["kind"] == "rail":
            t = r.get("trains_per_day")
            main_min = ctx.cat["methods"]["M9b"]["params"]["main_min_trains_per_day"]
            key = "rail:" + ("main" if r.get("main_line") or (t is not None and t >= main_min)
                             else "minor") if (t is not None or r.get("main_line") is not None) \
                else "rail:"
        elif r["kind"] == "lifeline":
            key = "lifeline"
        else:
            key = r.get("type") or ""
        guess = auto.get(key)
        if guess and guess in by_desc:
            ctx.hit("M13", by_desc[guess], r, "descriptor guessed from type: '{}'".format(guess),
                    "advisory")
            ctx.flag(INFO, "m13_guessed", "M13 descriptor guessed from the receptor type "
                     "(advisory): set 'descriptor' to make it a rule", "M13", r["id"])
        else:
            ctx.flag(WARNING, "m13_none", "no descriptor for this receptor: set 'descriptor' "
                     "(engineering judgment)", "M13", r["id"])


EVALUATORS = {"M1": m1, "M2": m2, "M3": m3, "M4a": m4a, "M4b": m4b, "M4c": m4c, "M5": m5,
              "M6": m6, "M7": m7, "M8a": m8a, "M8b": m8b, "M8c": m8c, "M8d": m8d, "M8e": m8e,
              "M8f": m8f, "M8g": m8g, "M9a": m9a, "M9b": m9b, "M9c": m9c, "M10a": m10a,
              "M10b": m10b, "M11a": m11a, "M11b": m11b, "M11c": m11c, "M12a": m12a,
              "M12b": m12b, "M12c": m12c, "M12d": m12d, "M13": m13}


# ============================================================ modifiers ==
def _prefilter(ctx, notes):
    """Domain, future development, D-cutoffs, S5 incremental and R1 transients."""
    cfg, out = ctx.cfg, []
    count_future = ctx.on("R5") and ctx.p("R5").get("count_future", True)
    n_future = 0
    incr = ctx.scenario == "S5" and not (ctx.on("R9") and ctx.p("R9").get("may_lower") is False)
    if ctx.scenario == "S5" and not incr:
        ctx.flag(INFO, "r9_full_depth", "R9: an incremental analysis may not lower the class "
                 "here, so the S5 run is scored on its full breach depths", "R9")
    rises = [r.get("rise_ft") for r in ctx.run["receptors"] if r.get("rise_ft") is not None]
    if incr and not rises:
        ctx.flag(WARNING, "s5_no_rise", "S5 needs a non-breach run (incremental rise): none "
                 "given, full breach depths used", None)
    for r in ctx.run["receptors"]:
        for k in [k for k in r if k.startswith("_")]:
            del r[k]
        if r.get("in_domain") is False:
            ctx.flag(WARNING, "outside_domain", "receptor outside the routed domain (no raster "
                     "cell): not scored", None, r["id"])
            continue
        if r.get("future"):
            n_future += 1
            if not count_future:
                continue
        skip = False
        for did, dp in cfg.get("domains", {}).items():
            if r.get("rise_ft") is not None and r["rise_ft"] <= dp["max_rise_ft"] and \
                    (r.get("depth_ft") or 0) > ctx.wet_min:
                ctx.flag(INFO, "beyond_" + did.lower(), "{}: incremental rise {} ft or less "
                         "(routing may stop here)".format(did, dp["max_rise_ft"]), did, r["id"])
                skip = skip or bool(dp.get("exclude_beyond"))
        if skip:
            continue
        if incr and r.get("rise_ft") is not None and r["rise_ft"] <= 0:
            r["_not_incremental"] = True
        out.append(r)
    if n_future:
        notes.append(("R5", "{} future-development receptor(s) {}".format(
            n_future, "counted ({})".format(ctx.p("R5").get("basis")) if count_future
            else "left out")))
    if not ctx.on("R2") and any(r["kind"] == "structure" for r in out):
        ctx.flag(INFO, "occupancy_default", "habitable structures presumed occupied (plugin "
                 "default; R2 is not in this configuration)", None)
    # R1
    trans = [r for r in out if r.get("occupancy") in ctx.cat["transient_occupancy"]]
    if trans:
        if ctx.on("R1"):
            var = ctx.p("R1").get("variant", "general")
            exclude = True
            if var == "three_part_test":
                res = [r for r in out if r.get("type") in ctx.cat["residence_types"] or
                       (r.get("type") == "campground" and r.get("occupancy") not in
                        ctx.cat["transient_occupancy"])]
                ok = bool(ctx.dam.get("access_controlled")) and bool(ctx.dam.get("eap_warning")) \
                    and not any(ctx.impacted(r, "R1") for r in res)
                exclude = ok
                notes.append(("R1", "three-part test {}: people temporary, {} residences or "
                              "overnight sites, owner-controlled access {}, EAP with warning {}"
                              .format("passed" if ok else "NOT passed",
                                      "no" if not res else "has",
                                      bool(ctx.dam.get("access_controlled")),
                                      bool(ctx.dam.get("eap_warning")))))
            if exclude:
                for r in trans:
                    r["_transient_excluded"] = True
                ctx.flag(INFO, "r1_excluded", "R1: transient / occasional users left out of the "
                         "life-safety methods", "R1", [r["id"] for r in trans])
        else:
            ctx.flag(INFO, "transients_counted", "transient receptors are counted (no R1 in "
                     "this configuration)", None, [r["id"] for r in trans])
    return out


def _postmods(cat, cfg, dam, result, flags, notes):
    """R3, R4, R6, R8, R10 after the scenarios: (extra hits, notes)."""
    mods, extra = cfg["modifiers"], []
    labels = cfg["labels"]

    def to_ord(x):
        if x is None:
            return None
        try:
            return int(x)
        except (TypeError, ValueError):
            for k, v in labels.items():
                if str(v).lower() == str(x).lower():
                    return k
            for k, v in C.GENERIC_LABELS.items():
                if v.lower() == str(x).lower():
                    return k
        return None

    if dam.get("evacuation_credit") or dam.get("eap"):
        if "R3" in mods:
            notes.append(("R3", "the EAP / evacuation gives no credit (class not lowered)"))
        else:
            flags.add(WARNING, "evac_credit", "an EAP / evacuation credit is recorded on the dam; "
                      "this plugin never lowers a class for it")
    if "R4" in mods:
        ds = [to_ord(x) for x in _list(dam.get("downstream_dam_classes"))]
        ds = [x for x in ds if x is not None]
        if ds:
            extra.append({"method": "R4", "class": max(ds), "receptors": [],
                          "strength": mods["R4"]["params"].get("strength", "rule"),
                          "reason": "dams in series: a downstream dam this failure could fail is "
                                    "{}".format(labels.get(max(ds))), "scenario": None})
        elif dam.get("downstream_dam_classes") is None:
            flags.add(INFO, "r4_none", "no downstream dams recorded (downstream_dam_classes): "
                      "dams-in-series not applied", "R4")
    if "R6" in mods and dam.get("is_new"):
        P = mods["R6"]["params"]
        near = [m for m in _list(dam.get("municipalities"))
                if m.get("distance_mi") is not None and
                m["distance_mi"] <= P["distance_mi"].get(str(m.get("class", "")).lower(), -1)]
        if near and not dam.get("development_curtailed"):
            msg = "new dam within {} mi of a {} municipality: designed to High".format(
                near[0]["distance_mi"], near[0].get("class"))
            notes.append(("R6", msg))
            result["design_requirement"] = "High"
            if P.get("raises_class"):
                extra.append({"method": "R6", "class": 3, "receptors": [], "strength": "rule",
                              "reason": msg, "scenario": None})
        elif dam.get("municipalities") is None:
            flags.add(WARNING, "r6_none", "new dam without municipality distances: the "
                      "proximity rule is not checked", "R6")
    if "R10" in mods:
        notes.append(("R10", "re-run when downstream layers change; run date and layer versions "
                      "are stored in this report"))
    return extra


def _r8(cfg, dam, cls, flags, notes):
    if "R8" not in cfg["modifiers"]:
        return cls, None
    P = cfg["modifiers"]["R8"]["params"]
    if P.get("variant", "storage_limit") == "storage_limit":
        if dam.get("analysis", "breach_model") != "simplified" or cls >= 3:
            return cls, None
        st = dam.get("storage_acft")
        if st is None or st >= P["storage_limit_acft"]:
            msg = ("simplified analysis (no breach model) with storage {} ac-ft: a class below "
                   "High is justified only under {} ac-ft".format(
                       "unknown" if st is None else "{:g}".format(st), P["storage_limit_acft"]))
            flags.add(ERROR, "r8_storage", msg, "R8")
            notes.append(("R8", msg + " -> High"))
            return 3, msg
        return cls, None
    cur = dam.get("current_class")
    try:
        cur = int(cur) if cur is not None else None
    except (TypeError, ValueError):
        cur = 3 if str(cur).lower() in ("high", "class c", "c") else None
    if cur == 3 and cls < 3 and dam.get("analysis") != "unsteady_tm11":
        msg = "lowering from High needs TM-11-based unsteady modeling (analysis = " \
              "'unsteady_tm11'); class kept High"
        flags.add(ERROR, "r8_lowering", msg, "R8")
        notes.append(("R8", msg))
        return 3, msg
    return cls, None


def s7_location_count(dam):
    """How many breach locations the dam record gives (breach_locations: a list, a number, or a
    comma / semicolon separated text). S7 is expected only for two or more (0.1.2)."""
    v = (dam or {}).get("breach_locations")
    if v is None or v == "":
        return 0
    if isinstance(v, (list, tuple, set)):
        return len([x for x in v if x not in (None, "")])
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v) if v == v else 0
    txt = str(v).strip()
    try:
        return int(float(txt))
    except ValueError:
        return len([x for x in re.split(r"[;,]", txt) if x.strip()])


def _validate_runs(cat, cfg, runs, dam, flags):
    have = [r.get("scenario") for r in runs]
    for s in have:
        if s is None:
            flags.add(WARNING, "scenario_none", "a run has no scenario ID")
        elif s not in cat["scenarios"]:
            flags.add(ERROR, "scenario_unknown", "unknown scenario ID {}".format(s))
    if cfg.get("method_fallback"):
        flags.add(WARNING, "method_fallback_m13", "the source documents give no confirmed method for "
                  "this preset: its methods are FEMA 333-style defaults with the M13 fallback; "
                  "engineering judgment needed", "M13")
    want = cfg.get("scenarios") or []
    for s in want:
        if s == "S7" and s not in have and s7_location_count(dam) < 2:
            continue                                   # 0.1.2: no locations, no S7 (see below)
        if s not in have:
            flags.add(WARNING, "scenario_missing", "scenario {} ({}) is expected and no run was "
                      "supplied for it".format(s, cat["scenarios"][s]["name"]), None, None, s)
    if cfg.get("scenarios_any_of") and not any(s in have for s in cfg["scenarios_any_of"]):
        flags.add(WARNING, "scenario_missing", "expected one of {} ({})".format(
            ", ".join(cfg["scenarios_any_of"]), cfg.get("scenario_note", "")))
    for s in have:
        if s and want and s not in want and s not in cfg.get("optional_scenarios", {}) and \
                s not in cfg.get("scenarios_any_of", []):
            flags.add(INFO, "scenario_extra", "run {} is not one of this configuration's "
                      "scenarios ({}); it is still scored".format(s, ", ".join(want)), None,
                      None, s)
    if "S7" in have:
        locs = set(r.get("breach_location") for r in runs if r.get("scenario") == "S7")
        if len(locs - {None}) < 2:
            flags.add(WARNING, "s7_locations", "S7 asks for several breach locations; {} "
                      "distinct location(s) supplied".format(len(locs - {None})), None, None,
                      "S7")
    elif "S7" in want:
        n = s7_location_count(dam)
        if n >= 2:
            flags.add(WARNING, "s7_locations", "S7: the dam record gives {} breach locations and no S7 "
                      "run was supplied".format(n), None, None, "S7")
        else:
            flags.add(INFO, "s7_not_applicable", "S7 (multiple breach locations) is not expected: the dam "
                      "record gives {} breach location(s); set breach_locations when the impoundment "
                      "has several".format(n), None, None, "S7")
    if "S6" in have or "S6" in want:
        cur = "new" if dam.get("is_new") else dam.get("current_class")
        cond = cat["scenarios"]["S6"]["by_current_class"].get(str(cur)) if cur is not None \
            else None
        if cond:
            flags.add(INFO, "s6_condition", "S6: the current class calls for: " + cond, None,
                      None, "S6")
        else:
            flags.add(WARNING, "s6_class", "S6 needs the dam's current class (or is_new) to "
                      "pick the starting condition", None, None, "S6")
    for r in runs:
        dim = (r.get("model_dim") or "").upper()
        if dim not in ("1D", "2D"):
            flags.add(WARNING, "dim_unknown", "run {} has no model dimensionality (1D / 2D)"
                      .format(r.get("label") or r.get("scenario")), None, None,
                      r.get("scenario"))


def _nodata_cell_and_threshold(ctx):
    """(cell_m, threshold_m) recorded for this run's NoData-receptor path, with fallbacks."""
    pol = ctx.run.get("nodata_sampling") or {}
    recs = ctx.run.get("receptors") or []
    cell = pol.get("cell_m")
    min_m = pol.get("nodata_neighbourhood_min_cell_m")
    if cell is None:
        cell = next((r.get("cell_m") for r in recs if r.get("cell_m") is not None), None)
    if min_m is None:
        min_m = next((r.get("nodata_neighbourhood_min_cell_m") for r in recs
                      if r.get("nodata_neighbourhood_min_cell_m") is not None), None)
    if min_m is None:
        from ..sampling.rasters import NODATA_NEIGHBOURHOOD_MIN_CELL_M
        min_m = NODATA_NEIGHBOURHOOD_MIN_CELL_M
    return cell, min_m


def _flag_nodata_neighbourhood(ctx):
    """Structures on a NoData cell next to water: neighbourhood fill on a grid coarser than
    NODATA_NEIGHBOURHOOD_MIN_CELL_M (nodata_neighbourhood); at that size or finer, scored dry
    and flagged (nodata_dry_review). Not a habitability rule."""
    recs = ctx.run.get("receptors") or []
    neigh = [r["id"] for r in recs
             if r.get("sampling") == "neighbourhood" or r.get("neighbourhood")]
    dry = [r["id"] for r in recs if r.get("sampling") == "centre_nodata_dry"]
    if not neigh and not dry:
        return
    cell, min_m = _nodata_cell_and_threshold(ctx)
    cell_s = "{:g} m".format(cell) if cell is not None else "unknown"
    if neigh:
        ctx.flag(WARNING, "nodata_neighbourhood",
                 "{} structure(s) sit on a NoData cell next to water on a {} grid "
                 "(coarser than NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m): peak depth and "
                 "velocity were taken from neighbouring wet cells (or the footprint) and need "
                 "review".format(len(neigh), cell_s, min_m), None, neigh)
    if dry:
        ctx.flag(WARNING, "nodata_dry_review",
                 "{} structure(s) sit on a NoData cell next to water on a {} grid "
                 "(at or finer than NODATA_NEIGHBOURHOOD_MIN_CELL_M = {:g} m): scored dry "
                 "from the NoData cell and need review"
                 .format(len(dry), cell_s, min_m), None, dry)




def classify(cat, cfg, runs, dam=None, charts=None, layers=None, run_date=None, habitable_rule=RULE_LEGACY):
    dam = dict(dam or {})
    charts = charts or tm11.load()
    flags, notes = Flags(), []
    nid = _nid(dam, flags)
    if nid:
        dam["nid_id"] = nid
    _validate_runs(cat, cfg, runs, dam, flags)
    base = int(cfg["general"].get("base_class", 1))
    apply_adv = bool(cfg.get("apply_advisory"))
    all_hits, per = [], []
    order = [m for m in C.EVAL_ORDER if m in cfg["methods"]]
    if not order:
        flags.add(ERROR, "no_methods", "no consequence method is enabled")
    for run in runs:
        ctx = Ctx(cat, cfg, charts, run, dam, flags, habitable_rule)
        _flag_nodata_neighbourhood(ctx)
        ctx.receptors = _prefilter(ctx, notes)
        for mid in order:
            EVALUATORS[mid](ctx)
        counted = [h for h in ctx.hits if h["strength"] == "rule" or apply_adv]
        cls = max([base] + [h["class"] for h in counted])
        per.append({"scenario": run.get("scenario"), "label": run.get("label") or "",
                    "model_dim": ctx.dim, "class": cls, "receptors": len(run["receptors"]),
                    "scored": len(ctx.receptors)})
        all_hits += ctx.hits
    result = {"design_requirement": None}
    extra = _postmods(cat, cfg, dam, result, flags, notes)
    all_hits += extra
    counted = [h for h in all_hits if h["strength"] == "rule" or apply_adv]
    rule_cls = max([base] + [h["class"] for h in all_hits if h["strength"] == "rule"])
    cls = max([base] + [h["class"] for h in counted])
    cls, r8_msg = _r8(cfg, dam, cls, flags, notes)
    driving = [h for h in counted if h["class"] == cls]
    if r8_msg and not driving:
        driving = [{"method": "R8", "class": 3, "receptors": [], "strength": "rule",
                    "reason": r8_msg, "scenario": None}]
    advisory = [h for h in all_hits if h["strength"] == "advisory"]
    adv_cls = max([rule_cls] + [h["class"] for h in advisory])
    adv_only = [h for h in advisory if h["class"] > rule_cls]
    if adv_only:
        flags.add(WARNING, "advisory_only", "advisory-only result{} above the rule class: {} "
                  "({}){}".format("s" if len(adv_only) > 1 else "",
                                  cfg["labels"].get(adv_cls), ", ".join(sorted(set(
                                      h["method"] for h in adv_only))),
                                  " - applied (opt-in)" if apply_adv else " - not applied"))
    if not any(h["strength"] == "rule" for h in all_hits) and order:
        flags.add(INFO, "no_rule_hit", "no rule-strength hit: the suggestion is the lowest "
                  "class ({})".format(cfg["labels"].get(base)))
    per_rec = {}
    for h in all_hits:
        for rid in h["receptors"]:
            e = per_rec.setdefault(rid, {"rule": None, "advisory": None, "methods": set()})
            k = "rule" if h["strength"] == "rule" else "advisory"
            e[k] = h["class"] if e[k] is None else max(e[k], h["class"])
            e["methods"].add(h["method"])
    flag_rec = {}
    for f in flags.items:
        for rid in f["receptors"]:
            flag_rec.setdefault(rid, []).append(f["code"])
    result.update({
        "suggested_class": cls, "suggested_label": cfg["labels"].get(cls, C.GENERIC_LABELS[cls]),
        "generic_label": C.GENERIC_LABELS[cls], "rule_class": rule_cls,
        "class_with_advisory": adv_cls, "advisory_applied": apply_adv,
        "driving": driving, "advisory": advisory, "hits": all_hits, "flags": flags.items,
        "habitable_rule": habitable_rule, "per_scenario": per, "modifier_notes": notes, "per_receptor": per_rec,
        "receptor_flags": flag_rec, "config": cfg, "dam": dam, "nid_id": nid, "layers": layers or [],
        "run_date": run_date or datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "catalog_version": cat.get("catalog_version"), "disclaimer": cat.get("disclaimer"),
        "damit_catalog": cat.get("damit_catalog"),
        "source_document": cat.get("source_document"),
        "nodata_sampling": [{"scenario": r.get("scenario"), "label": r.get("label"),
                             **(r["nodata_sampling"])}
                            for r in runs if r.get("nodata_sampling")],
    })
    return result
