"""Receptor records: one dict per structure / road / rail line / facility / lifeline /
environmental feature, with its attributes (normalised names and values) and the hydraulics
sampled at it.

    {"id", "kind", "type", <attributes>, "sampled", "depth_ft", "velocity_fps", "dv_ft2s",
     "dv_source", "cells" [(depth ft, velocity ft/s), ...], "wse_ft", "rise_ft", "arrival_h",
     "in_domain"}

Attribute names are matched case-insensitively against ALIASES (first match wins); a value the
engine needs and does not find stays None, and the method that needs it flags the gap.
"""
import re

ALIASES = {
    "type": ("type", "struct_type", "structure_type", "bldg_type", "occ_type", "category",
             "occupancy_type", "facility_type", "lifeline_type", "env_type", "site_type"),
    "occtype": ("occtype",),                       # NSI occupancy type (RES1-1SWB, COM1, AGR1 ...)
    "habitable": ("habitable", "is_habitable"),    # DamIT Crest's flag on the structures it hands off
    "address_source": ("source",),                 # Crest: "nd911" for a 911 address point
    "placed": ("placed",),                         # Crest: "911 address point"
    "nguid": ("nguid", "ng911_guid"),              # a NENA GUID: an ND 911 address point layer
    "is_911": ("is_911", "nd911", "address_point_911"),
    "occupancy": ("occupancy", "occ", "use_pattern"),
    "occupants": ("occupants", "people", "persons", "par", "pop", "population"),
    "floor_elev": ("floor_elev", "ffe", "first_floor_elev", "lowest_floor_elev", "floor_elev_ft"),
    "floor_height_ft": ("floor_height_ft", "ffh", "found_ht", "first_floor_height", "ffh_ft"),
    "ground_elev": ("ground_elev", "lag", "grade_elev", "ground_elev_ft"),
    "foundation_elev": ("foundation_elev", "found_elev", "foundation_elev_ft"),
    "walkout": ("walkout", "walkout_basement"),
    "future": ("future", "proposed", "planned", "future_dev"),
    "nights_per_year": ("nights_per_year", "nights", "occupied_nights"),
    "damage_state": ("damage_state", "damage"),
    "indirect_life_loss": ("indirect_life_loss", "indirect_loss"),
    "public_safety_threat": ("public_safety_threat", "safety_threat"),
    "descriptor": ("descriptor", "m13", "m13_descriptor"),
    "inundated": ("inundated", "in_area", "flooded"),
    "road_class": ("road_class", "rd_class", "class", "roadclass", "route_type"),
    "aadt": ("aadt", "adt", "traffic"),
    "lanes": ("lanes", "num_lanes", "lane_count"),
    "func_class": ("func_class", "functional_class", "fclass", "fc"),
    "sole_access": ("sole_access", "only_access"),
    "isolates_homes": ("isolates_homes", "homes_isolated", "units_isolated"),
    "crossings_failed": ("crossings_failed", "failed_crossings"),
    "washout": ("washout", "washed_out"),
    "trip_group": ("trip_group", "same_trips"),
    "access_residences": ("access_residences", "residence_access"),
    "active": ("active", "in_service"),
    "trains_per_day": ("trains_per_day", "trains_day", "daytrains", "trains"),
    "passenger": ("passenger", "is_passenger", "commuter"),
    "freight_class": ("freight_class", "rr_class", "railroad_class"),
    "line_category": ("line_category", "rail_category", "line_type"),
    "hazmat_yard": ("hazmat_yard", "tih_yard", "toxic_hazmat"),
    "strategic": ("strategic", "strategic_corridor", "defense"),
    "fuel_line": ("fuel_line", "fuel_delivery"),
    "main_line": ("main_line", "mainline"),
    "isolated": ("isolated", "cut_off"),
    "impact": ("impact", "impact_type"),
    "units_served": ("units_served", "residential_units", "customers"),
    "outage_days": ("outage_days", "outage", "interruption_days"),
    "major_population": ("major_population", "major_pop"),
    "ww_class": ("ww_class", "wastewater_class", "plant_size"),
    "own_supply": ("own_supply", "dams_own_supply"),
    "mitigation": ("mitigation", "mitigation_needed"),
    "substantial": ("substantial", "substantial_damage"),
    "anadromous": ("anadromous", "anadromous_fish", "aws"),
    "agency_identified": ("agency_identified", "resource_agency"),
    "unique": ("unique",),
    "permanent": ("permanent",),
    "in_domain": ("in_domain", "routed"),
}

TYPE_VALUES = {
    "home": ("home", "house", "residence", "residential", "single_family", "res", "dwelling",
             "sfr", "duplex", "apartment", "multi_family"),
    "mobile_home": ("mobile_home", "mobile", "manufactured", "mh", "trailer"),
    "school": ("school",),
    "hospital": ("hospital",),
    "nursing_home": ("nursing_home", "nursing", "care_home", "assisted_living"),
    "institution": ("institution", "institutional"),
    "commercial": ("commercial", "business", "retail", "office", "com"),
    "industrial": ("industrial", "ind", "plant", "factory"),
    "campground": ("campground", "camp", "rv", "campsite", "camping"),
    "farm_occupied": ("farm_occupied", "farm_house", "occupied_farm"),
    "farm_unoccupied": ("farm_unoccupied", "farm", "barn", "ag", "agricultural", "bin",
                        "grain_bin"),
    "storage": ("storage", "shed", "garage", "warehouse_unoccupied"),
    "outbuilding": ("outbuilding", "out_building", "accessory"),
    "fire_station": ("fire_station", "fire"),
    "police_station": ("police_station", "police"),
    "oil_pad": ("oil_pad", "well_pad"),
}
# NSI (National Structure Inventory) occtype -> a catalog receptor type, a SUGGESTION only (0.4.0): it fills
# `suggested_type`, never `type`, and never makes a structure habitable (that is an ND 911 address point or an
# engineer's review). The code is the HAZUS occupancy class: three letters, a number, optional letters / a dash and a
# foundation-and-stories suffix (RES1-1SWB, RES3A, COM10). Not mapped -> None.
NSI_RES = {1: "home", 2: "mobile_home", 3: "home", 4: "commercial", 5: "institution", 6: "nursing_home"}
NSI_BY_CLASS = {"IND": "industrial", "AGR": "farm_unoccupied", "REL": "institution", "GOV": "institution"}
NSI_COM = {6: "hospital", 10: "storage"}                  # COM1-5, 7-9 commercial; COM10 parking: not habitable
NSI_EDU = {1: "school", 2: "institution"}
_NSI_CODE = re.compile(r"^\s*(RES|COM|IND|AGR|REL|GOV|EDU)\s*(\d+)", re.I)
SOURCES_911 = ("nd911", "nd_911", "911", "e911", "ng911", "address_point_911")
KEY_FIELDS = ("structure_id", "struct_id", "bid", "fd_id", "usastrucid", "nguid", "crest_id", "source_ref")


def nsi_type(occtype):
    """The catalog receptor type an NSI occtype suggests (case and suffixes ignored), or None when not mapped."""
    m = _NSI_CODE.match(str(occtype)) if occtype not in (None, "") else None
    if not m:
        return None
    cls, num = m.group(1).upper(), int(m.group(2))
    if cls == "RES":
        return NSI_RES.get(num)
    if cls == "COM":
        return NSI_COM.get(num, "commercial")
    if cls == "EDU":
        return NSI_EDU.get(num)
    return NSI_BY_CLASS[cls]


def nsi_class(occtype):
    """The NSI class letters (RES, COM, IND, AGR, REL, GOV, EDU) of an occtype, or None."""
    m = _NSI_CODE.match(str(occtype)) if occtype not in (None, "") else None
    return m.group(1).upper() if m else None


def address_point_911(r):
    """True for an ND 911 address point: an explicit is_911 flag, Crest's source "nd911" / placed "911 address
    point", or a NENA GUID (nguid) - whatever a 911 layer carries."""
    if r.get("is_911") is not None:
        return bool(r["is_911"])
    if str(r.get("address_source") or "").strip().lower() in SOURCES_911:
        return True
    if str(r.get("placed") or "").strip().lower() == "911 address point":
        return True
    return bool(r.get("nguid"))


def review_key(r):
    """The key an engineer's review of this receptor is saved under: a stable attribute of the layer (NSI bid /
    fd_id, nguid, crest_id ...) as "field:value", else its id in this run."""
    return r.get("struct_key") or r["id"]


ROAD_CLASSES = {
    "interstate": ("interstate", "i", "freeway", "expressway_interstate"),
    "us_state": ("us_state", "us", "us_highway", "state", "state_highway", "highway", "sh",
                 "us_hwy", "state_hwy", "main_highway"),
    "township_county": ("county", "township", "township_county", "county_road"),
    "municipal": ("municipal", "city", "street", "local_street"),
    "private": ("private", "driveway"),
    "other_public": ("other_public", "public", "other", "local"),
}
TRUE = ("1", "true", "t", "yes", "y")
FALSE = ("0", "false", "f", "no", "n")


def _key(s):
    return str(s).strip().lower().replace(" ", "_").replace("-", "_")


def norm_value(table, value):
    if value is None:
        return None
    k = _key(value)
    for canon, names in table.items():
        if k == canon or k in names:
            return canon
    return k or None


def boolean(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    k = str(v).strip().lower()
    if k in TRUE:
        return True
    if k in FALSE:
        return False
    return None


def number(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


BOOL_FIELDS = ("habitable", "is_911", "walkout", "future", "sole_access", "washout", "active", "passenger",
               "hazmat_yard", "strategic", "fuel_line", "main_line", "isolated",
               "major_population", "own_supply", "substantial", "anadromous",
               "agency_identified", "unique", "permanent", "indirect_life_loss",
               "public_safety_threat", "inundated", "access_residences", "in_domain")
NUM_FIELDS = ("occupants", "floor_elev", "floor_height_ft", "ground_elev", "foundation_elev",
              "nights_per_year", "aadt", "lanes", "isolates_homes", "crossings_failed",
              "trains_per_day", "units_served", "outage_days")


def from_attributes(rid, kind, attrs, hyd=None):
    """A receptor dict from raw layer attributes (any field names) and sampled hydraulics."""
    low = {_key(k): v for k, v in (attrs or {}).items()}
    r = {"id": str(rid), "kind": kind, "raw": dict(attrs or {})}
    for canon, names in ALIASES.items():
        val = None
        for n in (canon,) + tuple(names):
            if n in low and low[n] not in (None, ""):
                val = low[n]
                break
        r[canon] = val
    if kind == "road":
        r["road_class"] = norm_value(ROAD_CLASSES, r.get("road_class"))
        r["type"] = "road"
    elif kind == "rail":
        r["type"] = "rail"
    else:
        r["type"] = norm_value(TYPE_VALUES, r.get("type"))
        r["suggested_type"] = None
        if r.get("occtype") is not None:
            r["occtype"] = str(r["occtype"]).strip()
            r["suggested_type"] = nsi_type(r["occtype"])
        r["struct_key"] = None
        for k in KEY_FIELDS:
            if k in low and low[k] not in (None, ""):
                r["struct_key"] = "{}:{}".format(k, low[k])
                break
    for f in BOOL_FIELDS:
        r[f] = boolean(r.get(f))
    for f in NUM_FIELDS:
        r[f] = number(r.get(f))
    for f in ("occupancy", "damage_state", "descriptor", "func_class", "freight_class",
              "line_category", "impact", "ww_class", "mitigation", "trip_group"):
        if r.get(f) is not None:
            r[f] = _key(r[f])
    if r.get("freight_class") is not None:
        r["freight_class"] = r["freight_class"].replace("class_", "")
    if kind not in ("road", "rail"):
        r["is_911"] = address_point_911(r)
    r.update(blank_hydraulics())
    if hyd:
        r.update(hyd)
    return r


def blank_hydraulics():
    return {"sampled": False, "depth_ft": None, "velocity_fps": None, "dv_ft2s": None,
            "dv_source": None, "cells": None, "wse_ft": None, "rise_ft": None,
            "arrival_h": None}


def make(rid, kind="structure", type=None, **kw):
    """A receptor for tests and scripts: make("h1", "structure", "home", depth_ft=3.0, ...).
    Any hydraulic value given marks it sampled."""
    attrs = {k: v for k, v in kw.items() if k not in blank_hydraulics()}
    if type is not None:
        attrs["type"] = type
    hyd = {k: v for k, v in kw.items() if k in blank_hydraulics()}
    if any(hyd.get(k) is not None for k in ("depth_ft", "cells")):
        hyd.setdefault("sampled", True)
    r = from_attributes(rid, kind, attrs, hyd)
    if kind == "road" and type:
        r["road_class"] = norm_value(ROAD_CLASSES, type)
    if r.get("in_domain") is None and "in_domain" in kw:
        r["in_domain"] = kw["in_domain"]
    return r
