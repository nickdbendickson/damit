"""Screening steps (pure Python): inventory prepare, terrain, storage, breach direction,
hydrograph, triage, preliminary suggestion, 2D-engine hook and hand-off. The Processing tools and
damit_screen:runchain call these same functions.

Nothing here launches LISFLOOD-FP, ANUGA, HEC-RAS or Wine; the 2D engine hook records the
input/output contract only (not run in 0.1.0)."""
import csv
import math
import os

from . import catalog_bridge as CB

STATUS_OK, STATUS_GAP, STATUS_FAIL, STATUS_NOT_RUN = "ok", "gap", "fail", "not_run"

# standard dam record fields (feet, acre-feet, degrees); field_map maps layer fields onto these
# dam_id is the NID ID (USACE National Inventory of Dams); nid_id carries it when dam_id is something else.
DAM_FIELDS = ("dam_id", "nid_id", "is_new", "is_sample", "name", "height_ft", "storage_acft", "top_of_dam_elev_ft",
              "normal_pool_elev_ft",
              "emergency_spillway_elev_ft", "pmf_peak_elev_ft", "peak_pool_100yr_elev_ft", "existing_class",
              "new_or_existing", "breach_azimuth_deg", "surface_area_ac", "storage_curve_csv",
              "hydrograph_csv", "flood_hydrograph_csv", "breach_locations", "downstream_dam_class")
NUMERIC = ("height_ft", "storage_acft", "top_of_dam_elev_ft", "normal_pool_elev_ft", "emergency_spillway_elev_ft",
           "pmf_peak_elev_ft", "peak_pool_100yr_elev_ft", "breach_azimuth_deg", "surface_area_ac",
           "breach_locations", "downstream_dam_class")
FT = 0.3048
ACFT_M3 = 1233.4818375
CFS_PER_CMS = 35.3146667


def nid_check(d):
    """Apply DamIT Catalog's NID-ID rule (handoff.nid_rule) to a prepared record; sets nid_id / is_new / is_sample.

    Returns (problem or None, step): a record needs an NID ID (nid_id, or a dam_id that is an NID ID); a non-NID
    nid_id or a DWR- / DUG- / UNK-style dam_id is a problem (FAIL); a new / proposed dam (is_new) or a desk sample
    (is_sample) may lack one and passes with a GAP."""
    _, _, HO = CB.modules()
    d["is_new"] = HO.is_new_dam(d)
    d["is_sample"] = HO.flag(d.get("is_sample"))
    error, warning, nid = HO.nid_rule(d)
    if error:
        return error, None
    d["nid_id"] = nid
    if warning:
        return None, step(STATUS_GAP, warning, nid_id=nid)
    return None, step(STATUS_OK, "NID ID {}".format(nid), nid_id=nid)


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def step(status, detail="", **extra):
    d = {"status": status, "detail": detail}
    d.update(extra)
    return d


# ---------------------------------------------------------------- 1 prepare --
def prepare(records, field_map=None):
    """Normalize raw dam records ({field: value, '_x', '_y', '_crs'}) to DamIT dam records.
    Returns (dams, problems). A record with no dam_id, a duplicate id, or no NID ID (nid_check: only a new /
    proposed dam or a desk sample may lack one) is a problem, not dropped silently. Each kept record carries
    ``nid_step`` (OK, or GAP for a new dam / sample / dam_id that is not the NID ID)."""
    fm = {k: k for k in DAM_FIELDS}
    fm.update({k: v for k, v in (field_map or {}).items() if v})
    dams, problems, seen = [], [], set()
    for i, rec in enumerate(records):
        d = {}
        for k in DAM_FIELDS:
            v = rec.get(fm[k])
            if v in ("", None):
                v = None
            if k in NUMERIC and v is not None:
                n = _num(v)
                if n is None:
                    problems.append("record {}: {} ({}) is not a number: {!r}".format(i + 1, k, fm[k], v))
                v = n
            d[k] = v
        d["x"], d["y"], d["crs"] = _num(rec.get("_x")), _num(rec.get("_y")), rec.get("_crs")
        if d["dam_id"] in (None, "") and d.get("nid_id") not in (None, ""):
            d["dam_id"] = d["nid_id"]                   # dam_id = NID ID when only the NID ID field is mapped
        if d["dam_id"] in (None, ""):
            problems.append("record {}: no dam id (field {!r})".format(i + 1, fm["dam_id"]))
            continue
        d["dam_id"] = str(d["dam_id"]).strip()
        if d["dam_id"] in seen:
            problems.append("record {}: duplicate dam id {!r}".format(i + 1, d["dam_id"]))
            continue
        problem, nid_step = nid_check(d)
        if problem:
            problems.append("record {}: {}".format(i + 1, problem))
            continue
        d["nid_step"] = nid_step
        seen.add(d["dam_id"])
        dams.append(d)
    return dams, problems


def missing_dam_fields(dam, needs):
    """The needs ('a|b' alternatives) a dam record does not satisfy."""
    out = []
    for need in needs:
        if not any(dam.get(alt) not in (None, "") for alt in need.split("|")):
            out.append(need)
    return out


# ---------------------------------------------------------------- 2 terrain --
def terrain(dam, dem_path, info=None):
    """Record the DEM for a dam. ``info`` (from QGIS): {'crs', 'extent': (xmin, ymin, xmax, ymax),
    'extent_crs'} when the raster was opened. Download / clipping is not done in 0.1.0."""
    if not dem_path:
        return step(STATUS_GAP, "no terrain (DEM) given; the Runner needs one", path=None)
    if not os.path.exists(dem_path):
        return step(STATUS_FAIL, "DEM not found: {}".format(dem_path), path=dem_path)
    covers = None
    if info and info.get("extent") and dam.get("x") is not None and info.get("crs") == dam.get("crs"):
        xmin, ymin, xmax, ymax = info["extent"]
        covers = xmin <= dam["x"] <= xmax and ymin <= dam["y"] <= ymax
    if covers is False:
        return step(STATUS_GAP, "DEM does not cover the dam point", path=dem_path, covers_dam=False)
    return step(STATUS_OK, "DEM recorded" + ("" if covers else " (coverage not checked: CRS differs or unknown)"),
                path=dem_path, covers_dam=covers, crs=(info or {}).get("crs"))


# ---------------------------------------------------------------- 3 storage --
def read_curve(path):
    """Elevation-storage / elevation-area curve CSV: elev_ft plus storage_acft or area_ac."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            r = {k.strip().lower(): v for k, v in r.items() if k}
            e = _num(r.get("elev_ft"))
            if e is None:
                continue
            rows.append((e, _num(r.get("storage_acft")), _num(r.get("area_ac"))))
    rows.sort()
    return rows


def storage_at(rows, elev):
    """Storage (ac-ft) at an elevation: interpolated storage column, else the area column
    integrated with the trapezoid rule from the lowest row (storage 0 there)."""
    if not rows:
        return None
    if all(s is not None for _, s, _ in rows):
        pts = [(e, s) for e, s, _ in rows]
    elif all(a is not None for _, _, a in rows):
        pts, acc = [(rows[0][0], 0.0)], 0.0
        for (e0, _, a0), (e1, _, a1) in zip(rows, rows[1:]):
            acc += 0.5 * (a0 + a1) * (e1 - e0)
            pts.append((e1, acc))
    else:
        return None
    if elev <= pts[0][0]:
        return pts[0][1]
    for (e0, s0), (e1, s1) in zip(pts, pts[1:]):
        if e0 <= elev <= e1:
            return s0 + (s1 - s0) * (elev - e0) / (e1 - e0) if e1 > e0 else s1
    return None                                  # above the curve: not extrapolated


def scenario_pool(dam, scenario):
    """(pool elevation ft or None, note) for a scenario, from the scenario's 'pool' rule."""
    rule = scenario.get("pool")
    g = lambda k: _num(dam.get(k))  # noqa: E731
    if rule == "normal_pool":
        return g("normal_pool_elev_ft"), "normal pool"
    if rule == "high_water_line":
        v = g("emergency_spillway_elev_ft")
        return (v, "emergency spillway crest") if v is not None else (g("top_of_dam_elev_ft"), "dam crest (no emergency spillway)")
    if rule == "min(top_of_dam, pmf_peak)":
        t, p = g("top_of_dam_elev_ft"), g("pmf_peak_elev_ft")
        if t is None or p is None:
            return None, "needs top of dam and PMF peak elevation"
        return min(t, p), "lower of top of dam and PMF peak"
    if rule == "max(peak_pool_100yr, auxiliary_spillway_crest)":
        a, b = g("peak_pool_100yr_elev_ft"), g("emergency_spillway_elev_ft")
        if a is None or b is None:
            return None, "needs 100-yr routed peak pool and auxiliary spillway crest"
        return max(a, b), "100-yr peak pool, not below auxiliary spillway crest"
    if rule == "by_current_class":
        cls = str(dam.get("existing_class") or "").strip().lower()
        if str(dam.get("new_or_existing") or "").lower() == "new" or cls == "low":
            return g("top_of_dam_elev_ft"), "top of embankment (new or Low)"
        return None, "flood loading (1/2 PMF or 500-yr storm) needs hydrology: routed by the Runner / engineer"
    if rule == "flood_routed":
        return None, "flood routing (SDF / PMF with and without failure) is done by the Runner / engineer"
    if rule == "inherit":
        return None, "multiple breach locations: pool from the companion scenario"
    return None, "unknown pool rule {!r}".format(rule)


def storage(dam, scenarios):
    """Storage per scenario pool and at top of dam."""
    out = {"top_of_dam_acft": None, "by_scenario": {}, "source": None}
    rows = []
    if dam.get("storage_curve_csv"):
        try:
            rows = read_curve(dam["storage_curve_csv"])
        except OSError as e:
            return step(STATUS_FAIL, "storage curve unreadable: {}".format(e), **out)
    top = _num(dam.get("top_of_dam_elev_ft"))
    if rows and top is not None:
        out["top_of_dam_acft"], out["source"] = storage_at(rows, top), "storage curve"
    if out["top_of_dam_acft"] is None and _num(dam.get("storage_acft")) is not None:
        out["top_of_dam_acft"], out["source"] = _num(dam["storage_acft"]), "inventory storage_acft (taken as top of dam)"
    for s in scenarios:
        pool, note = scenario_pool(dam, s)
        v = storage_at(rows, pool) if (rows and pool is not None) else None
        if v is None and pool is not None and top is not None and abs(pool - top) < 1e-6:
            v = out["top_of_dam_acft"]
        out["by_scenario"][s["id"]] = {"pool_elev_ft": pool, "pool_note": note, "storage_acft": v}
    if out["top_of_dam_acft"] is None:
        return step(STATUS_GAP, "no storage: give storage_acft or a storage curve CSV", **out)
    return step(STATUS_OK, "storage from " + out["source"], **out)


# ---------------------------------------------------------------- 4 breach direction --
def breach_direction(dam):
    az = _num(dam.get("breach_azimuth_deg"))
    if az is None:
        return step(STATUS_GAP, "no breach azimuth: give breach_azimuth_deg (DEM-based estimate not in 0.1.0)",
                    azimuth_deg=None)
    return step(STATUS_OK, "breach azimuth from the dam record", azimuth_deg=az % 360.0)


# ---------------------------------------------------------------- 5 hydrograph --
def froehlich_1995_peak_cfs(storage_acft, head_ft):
    """Froehlich (1995) peak breach outflow, Qp = 0.607 Vw^0.295 Hw^1.24 (SI). A screening
    reference only; the Runner (or the engineer's own hydrograph) governs."""
    if not storage_acft or not head_ft or storage_acft <= 0 or head_ft <= 0:
        return None
    q = 0.607 * (storage_acft * ACFT_M3) ** 0.295 * (head_ft * FT) ** 1.24
    return q * CFS_PER_CMS


def read_hydrograph(path):
    pts = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            r = {k.strip().lower(): v for k, v in r.items() if k}
            t, q = _num(r.get("time_hr")), _num(r.get("discharge_cfs"))
            if t is not None and q is not None:
                pts.append((t, q))
    return pts


def hydrograph(dam, storage_step, scenarios):
    """Use the dam's own hydrograph CSV (time_hr, discharge_cfs) when given; otherwise record a
    Froehlich (1995) peak per scenario as a reference and flag that the Runner needs a hydrograph."""
    out = {"hydrograph_csv": None, "peak_cfs": None, "volume_acft": None, "reference_peaks_cfs": {}}
    path = dam.get("hydrograph_csv")
    bed = None
    if _num(dam.get("top_of_dam_elev_ft")) is not None and _num(dam.get("height_ft")) is not None:
        bed = _num(dam["top_of_dam_elev_ft"]) - _num(dam["height_ft"])
    for s in scenarios:
        bs = (storage_step.get("by_scenario") or {}).get(s["id"]) or {}
        if bs.get("pool_elev_ft") is not None and bed is not None:
            out["reference_peaks_cfs"][s["id"]] = froehlich_1995_peak_cfs(bs.get("storage_acft"),
                                                                          bs["pool_elev_ft"] - bed)
    if path:
        if not os.path.exists(path):
            return step(STATUS_FAIL, "hydrograph CSV not found: {}".format(path), **out)
        pts = read_hydrograph(path)
        if len(pts) < 2:
            return step(STATUS_FAIL, "hydrograph CSV needs columns time_hr, discharge_cfs and 2+ rows", **out)
        vol = sum(0.5 * (q0 + q1) * (t1 - t0) * 3600.0 for (t0, q0), (t1, q1) in zip(pts, pts[1:])) / 43560.0
        out.update(hydrograph_csv=path, peak_cfs=max(q for _, q in pts), volume_acft=vol)
        return step(STATUS_OK, "user hydrograph", **out)
    return step(STATUS_GAP, "no hydrograph CSV; Froehlich (1995) reference peaks recorded; the Runner must "
                "be given a hydrograph or build its own breach method", **out)


# ---------------------------------------------------------------- 6 triage --
def triage(cat, dam, receptors):
    """Quick screen from feature presence only (catalog M13 in custom mode, no branding)."""
    _, ev, _ = CB.modules()
    cfg = cat.resolve_custom(["M13"], ["S1"] if "S1" in cat.scenarios else None)
    cfg["flags"] = []
    res = ev.evaluate(cat, cfg, [dict(r, scenario=None) for r in receptors], {})
    o = res["suggested_ordinal"]
    return step(STATUS_OK if receptors else STATUS_GAP,
                "M13 presence screen of {} receptor(s)".format(len(receptors)),
                ordinal=o, generic_label=res["generic_label"],
                recommend_detailed_run=(o is None or o >= 2))


# ---------------------------------------------------------------- 7 2D engine hook --
ENGINE_CONTRACT = {
    "inputs": ["terrain (DEM, GeoTIFF)", "hydrograph_csv (time_hr, discharge_cfs)", "dam point and breach azimuth",
               "scenario pool elevation(s)", "domain cutoff (D-codes) if any"],
    "outputs": ["Depth (Max).tif (ft)", "Velocity (Max).tif (ft/s)", "DV (Max).tif (ft2/s, max of depth x velocity over the event)",
                "WSE (Max).tif (ft)", "Arrival.tif (hr, optional)", "model_dimension (1D/2D) in run_setup.json"],
    "note": "Built-in 2D screening engine is not run in DamIT Screener 0.1.0. Model runs belong to DamIT Runner "
            "(damit_run:rundam), which in 0.1.0 prepares and records the run only.",
}


def engine2d(dam):
    return step(STATUS_NOT_RUN, ENGINE_CONTRACT["note"], contract=ENGINE_CONTRACT)


# ---------------------------------------------------------------- 8 suggestion --
HYDRAULIC_FIELDS = ("depth_ground_ft", "depth_foundation_ft", "depth_floor_ft", "dv_ft2s", "velocity_fps", "m1_zone")


def has_hydraulics(receptors):
    return any(any(r.get(f) not in (None, "") for f in HYDRAULIC_FIELDS) for r in receptors)


def suggest(cat, config, dam, receptors, summary=None, apply_advisories=False):
    """Preliminary suggested class from the catalog when receptor hydraulics exist; otherwise a gap."""
    _, ev, _ = CB.modules()
    if not has_hydraulics(receptors):
        return step(STATUS_GAP, "no receptor hydraulics yet: suggestion not computed (DamIT Hazard classifies "
                    "the finished run)", screening={"status": "not_computed", "suggested_ordinal": None,
                                                    "suggested_label": None, "driving": [], "flags": []})
    summ = {"storage_acft": dam.get("storage_acft"), "downstream_dam_class": dam.get("downstream_dam_class"),
            "new_dam": str(dam.get("new_or_existing") or "").lower() == "new",
            "current_class": dam.get("existing_class")}            # R8 lowering-from-High (New York)
    summ.update(summary or {})
    res = ev.evaluate(cat, config, receptors, summ, apply_advisories=apply_advisories)
    res["status"] = "computed_preliminary"
    return step(STATUS_OK, "preliminary suggestion: {}".format(res["suggested_label"]), screening=res)
