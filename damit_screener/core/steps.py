"""Screening steps (pure Python): inventory prepare, terrain, storage, breach direction,
hydrograph, triage, preliminary suggestion, 2D-engine hook and hand-off. The Processing tools and
damit_screen:runchain call these same functions.

0.2.0: engine2d runs the DamSafety Screening tool-7 2D flood (DamIT Runner's flood/screen.py, the built-in
finite-volume engine, in this process) and samples peak depth, velocity and depth x velocity at the receptors, so
suggest gives a preliminary class. Nothing here launches LISFLOOD-FP, ANUGA, HEC-RAS or Wine.

0.3.0: engine2d 'lisflood' runs the screening flood on LISFLOOD-FP instead (started only by DamIT Runner's
flood/lisflood.py; no LISFLOOD-FP found = the built-in engine with a warning), and larger clips (larger_clips 1)
are downloaded fresh from the USGS 3DEP service into the dam folder (flood/terrain3dep.py). ANUGA, HEC-RAS and Wine
are never started.

0.3.1: a dam line that is a MultiLineString is read (DamIT Runner 0.3.2 flood/damfolder.py), and the engine2d notes say which part
was used and why."""
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
def terrain(dam, dem_path, info=None, modules=None):
    """Record the DEM for a dam. ``info`` (from QGIS): {'crs', 'extent': (xmin, ymin, xmax, ymax),
    'extent_crs'} when the raster was opened. 0.3.0: the coverage is checked in the DEM's own CRS (read with GDAL,
    PAM off) with the dam point transformed into it, so an EPSG:5070 VRT and a lon / lat dam point no longer give
    "CRS differs or unknown"; the QGIS extent is used only when GDAL cannot read the DEM."""
    if not dem_path:
        return step(STATUS_GAP, "no terrain (DEM) given; the Runner needs one", path=None)
    if not os.path.exists(dem_path):
        return step(STATUS_FAIL, "DEM not found: {}".format(dem_path), path=dem_path)
    covers, crs, why = None, (info or {}).get("crs"), None
    if dam.get("x") is not None and dam.get("y") is not None:
        try:
            from . import runner_bridge as RB
            R = (modules or RB.modules())[3]
            di = R.dem_info(dem_path)
            if di.get("wkt"):
                s = R.srs_from(di["wkt"])
                code = s.GetAuthorityCode(None)
                crs = "{}:{}".format(s.GetAuthorityName(None), code) if code else (crs or "custom")
                x, y = R.transform_points([(float(dam["x"]), float(dam["y"]))], str(dam.get("crs") or "EPSG:4326"),
                                          di["wkt"])[0]
                xmin, ymin, xmax, ymax = di["bounds"]
                covers = xmin <= x <= xmax and ymin <= y <= ymax
            else:
                why = "the DEM has no CRS"
        except Exception as e:                                   # noqa: BLE001 - fall back to the QGIS extent
            why = str(e)
        if covers is None and info and info.get("extent") and info.get("crs") == dam.get("crs"):
            xmin, ymin, xmax, ymax = info["extent"]
            covers = xmin <= dam["x"] <= xmax and ymin <= dam["y"] <= ymax
    if covers is False:
        return step(STATUS_GAP, "DEM does not cover the dam point", path=dem_path, covers_dam=False, crs=crs)
    return step(STATUS_OK, "DEM recorded" + (" (covers the dam point; DEM CRS {})".format(crs) if covers else
                                             " (coverage not checked: {})".format(why or "no dam point")),
                path=dem_path, covers_dam=covers, crs=crs)


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
BREACH_DIR_CRS = "EPSG:5070"      # DamSafety Screening's planar working CRS for breach_dir
BREACH_DIR_CELL_M = 5.0
BREACH_DIR_PAD_M = 500.0


def breach_direction(dam, dem_path=None, folder=None, modules=None):
    """The breach azimuth: the dam record's breach_azimuth_deg when given; otherwise (0.3.0) the DamSafety Screening
    estimate (core/breach_dir.resolve_breach, vendored in DamIT Runner's flood package): the dam axis from the dam
    line, the downstream side from the reservoir point and the terrain at five stations along the line (the terrain
    wins a disagreement; the steepest DEM drop from the midpoint when neither votes), the breach at the lowest
    downstream toe, and the azimuth the downstream normal. Without a dam line: reservoir point -> dam point
    (fallback_direction), else the steepest DEM drop from the dam point. All in EPSG:5070 on a 5 m DEM window."""
    az = _num(dam.get("breach_azimuth_deg"))
    if az is not None:
        return step(STATUS_OK, "breach azimuth from the dam record", azimuth_deg=az % 360.0, estimated=False)
    try:
        from . import runner_bridge as RB
        _, DF, _, R, _ = modules or RB.modules()
        from damit_runner.flood.screening import breach_dir as BD
    except ImportError as e:
        return step(STATUS_GAP, "no breach azimuth: give breach_azimuth_deg (the DamSafety estimate needs DamIT "
                    "Runner: {})".format(e), azimuth_deg=None)
    info = DF.read(folder) if folder else {"dam_line": None, "reservoir": None, "breach_point": None}
    try:
        return _estimate_breach_direction(dam, dem_path, info, R, BD)
    except Exception as e:                                       # noqa: BLE001 - a step result, not a crash
        return step(STATUS_GAP, "no breach azimuth: the DamSafety estimate failed ({}); give breach_azimuth_deg"
                    .format(e), azimuth_deg=None)


def _estimate_breach_direction(dam, dem_path, info, R, BD):
    import math
    to = BREACH_DIR_CRS
    pt = None
    if dam.get("x") is not None and dam.get("y") is not None:
        pt = R.transform_points([(float(dam["x"]), float(dam["y"]))], str(dam.get("crs") or "EPSG:4326"), to)[0]
    line = R.transform_points(info["dam_line"], "EPSG:4326", to) if info.get("dam_line") else None
    res_pt = R.transform_points([info["reservoir"]], "EPSG:4326", to)[0] if info.get("reservoir") else None
    if pt is None and line:
        pt = BD.midpoint(line)
    if pt is None:
        return step(STATUS_GAP, "no breach azimuth: no dam position", azimuth_deg=None)
    dem_fn = None
    if dem_path and os.path.isfile(str(dem_path)):
        xs = [p[0] for p in (line or [])] + [pt[0]]
        ys = [p[1] for p in (line or [])] + [pt[1]]
        c = BREACH_DIR_CELL_M
        b = (math.floor((min(xs) - BREACH_DIR_PAD_M) / c) * c, math.floor((min(ys) - BREACH_DIR_PAD_M) / c) * c,
             math.ceil((max(xs) + BREACH_DIR_PAD_M) / c) * c, math.ceil((max(ys) + BREACH_DIR_PAD_M) / c) * c)
        g = R.read_window(dem_path, b, c, R.srs_from(to).ExportToWkt(), dam.get("z_units") or "auto")

        def dem_fn(x, y):
            r, cc = g.rc(x, y)
            if not g.inside(r, cc):
                return None
            v = g.data[r, cc]
            return float(v) if v == v else None
    water_fn = None
    if res_pt is not None:
        def water_fn(x, y):
            return math.hypot(x - res_pt[0], y - res_pt[1])
    h = _num(dam.get("height_ft"))
    if line:
        r = BD.resolve_breach(line, pt, water_fn, dem_fn, known_height_m=h * FT if h else None)
        if not r.get("ok"):
            return step(STATUS_GAP, "no breach azimuth: the DamSafety estimate {} (dam line {:.0f} m); give "
                        "breach_azimuth_deg".format(r.get("reason"), r.get("length_m") or 0), azimuth_deg=None)
        bll = R.transform_points([r["breach"]], to, "EPSG:4326")[0]
        return step(STATUS_OK, "breach azimuth {:.0f} deg estimated as DamSafety Screening does: downstream side by "
                    "{} ({} confidence), breach at the {}".format(r["flow_az"], r["dir_method"], r["dir_conf"],
                                                                 r["breach_method"]),
                    azimuth_deg=round(r["flow_az"] % 360.0, 1), estimated=True, method="dam line",
                    dir_method=r["dir_method"], confidence=r["dir_conf"], breach_method=r["breach_method"],
                    breach_lonlat=[round(bll[0], 7), round(bll[1], 7)], axis_az=round(r["axis_az"], 1),
                    dam_line_m=round(r["length_m"], 1), notes=r.get("notes") or [])
    if res_pt is not None:
        a = BD.fallback_direction(pt, res_pt)
        if a is not None:
            return step(STATUS_OK, "breach azimuth {:.0f} deg estimated from the reservoir point through the dam "
                        "point (no dam line; DamSafety fallback_direction, low confidence)".format(a),
                        azimuth_deg=round(a % 360.0, 1), estimated=True, method="reservoir to dam point",
                        confidence="low")
    if dem_fn is not None:
        tr = BD.steepest_drop(dem_fn, pt)
        if tr is not None:
            a = BD.bearing(*tr[0])
            return step(STATUS_OK, "breach azimuth {:.0f} deg from the steepest DEM drop at the dam point ({:.1f} m "
                        "over {:.0f} m; no dam line or reservoir point; low confidence, verify)".format(
                            a, tr[1], tr[2]), azimuth_deg=round(a % 360.0, 1), estimated=True,
                        method="terrain trace", confidence="low")
    return step(STATUS_GAP, "no breach azimuth: give breach_azimuth_deg, a dam line or a reservoir point (the "
                "DamSafety estimate had nothing to go on)", azimuth_deg=None)


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


# ---------------------------------------------------------------- 7 2D engine --
ENGINE_CONTRACT = {
    "inputs": ["terrain (DEM, GeoTIFF / VRT)", "hydrograph_csv (time_hr, discharge_cfs), else a Froehlich (2008) "
               "piping breach from the top of dam", "dam point; dam line and reservoir point from the dam folder",
               "height_ft, top_of_dam_elev_ft, storage_acft"],
    "outputs": ["<dam folder>/Screening Depth (Max).tif (ft)", "Screening Velocity (Max).tif (ft/s)",
                "Screening DV (Max).tif (ft2/s, max of depth x velocity over the event)",
                "Screening Arrival Time.tif (h)", "receptor depth_ground_ft / velocity_fps / dv_ft2s / m1_zone"],
    "settings": {"engine2d": "builtin (default, the DamSafety Screening default) | lisflood (LISFLOOD-FP ACC; "
                              "lisflood_exe, else an installed one, else the built-in engine with a warning) | off",
                 "larger_clips": "1 (default) = a fresh USGS 3DEP download for each larger clip | 2 = local_dem | "
                                 "0 = the first clip only"},
    "note": "DamSafety Screening tool 7 (built-in 2D engine or LISFLOOD-FP, hydrograph injection at the downstream "
            "toe). A screening flood for the preliminary class; DamIT Runner (damit_run:rundam) runs the model of "
            "record.",
}
ENGINES = ("builtin", "lisflood", "off")   # 0.3.0: lisflood = LISFLOOD-FP ACC (DamIT Runner's launcher)
SCREEN_TIMEOUT_SHARE = 0.8      # of DAMIT_SCREENING_TIMEOUT_S: the rest is for the other steps and the report


def screening_timeout_s(settings=None, environ=None):
    """The engine's wall-clock limit (s): settings 'timeout_s', else 0.8 x DAMIT_SCREENING_TIMEOUT_S, else
    3600 (the DamSafety Screening default)."""
    v = _num((settings or {}).get("timeout_s"))
    if v and v > 0:
        return v
    env = os.environ if environ is None else environ
    t = _num(env.get("DAMIT_SCREENING_TIMEOUT_S"))
    if t and t > 0:
        return max(60.0, SCREEN_TIMEOUT_SHARE * t)
    return 3600.0


def _chart_for(r):
    t = str(r.get("structure_type") or r.get("type") or r.get("kind") or "").lower()
    return "mobile_homes" if "mobile" in t else "houses"


ZONE_NAMES = {"high": "high_danger", "judgment": "judgment", "low": "low_danger"}


def engine2d(dam, settings=None, folder=None, hydro_step=None, receptors=None, log=print, cancel=None,
             modules=None):
    """Run the screening flood for one dam. Returns the step; step['receptors'] are the receptors with peak
    depth / velocity / dv (and m1_zone when DamIT Hazard's charts are there) at their points."""
    S = dict(settings or {})
    eng = str(S.get("engine2d") or "builtin").lower()
    if eng not in ENGINES:
        return step(STATUS_FAIL, "unknown engine2d setting {!r} (one of {})".format(eng, ", ".join(ENGINES)))
    if eng == "off":
        return step(STATUS_NOT_RUN, "engine2d is off in the settings; no screening flood", contract=ENGINE_CONTRACT)
    dem = S.get("terrain") or dam.get("terrain")
    if not dem or not os.path.isfile(str(dem)):
        return step(STATUS_GAP, "no terrain (DEM): the screening flood needs one", contract=ENGINE_CONTRACT)
    h, top, vol = _num(dam.get("height_ft")), _num(dam.get("top_of_dam_elev_ft")), _num(dam.get("storage_acft"))
    miss = [n for n, x in (("height_ft", h), ("top_of_dam_elev_ft", top), ("storage_acft", vol)) if x is None]
    if miss:
        return step(STATUS_GAP, "the screening flood needs " + ", ".join(miss), contract=ENGINE_CONTRACT)
    try:
        from . import runner_bridge as RB
        BR, DF, MD, R, SC = modules or RB.modules()
    except ImportError as e:
        return step(STATUS_GAP, str(e), contract=ENGINE_CONTRACT)
    info = DF.read(folder)
    lonlat = None
    if dam.get("x") is not None and dam.get("y") is not None:
        crs = str(dam.get("crs") or "EPSG:4326")
        lonlat = (float(dam["x"]), float(dam["y"])) if crs.upper() in ("EPSG:4326", "OGC:CRS84") else \
            R.transform_points([(float(dam["x"]), float(dam["y"]))], crs, "EPSG:4326")[0]
    if info.get("breach_point"):
        lonlat = info["breach_point"]
    if lonlat is None and info.get("dam_line"):
        lonlat = tuple(sum(c) / len(info["dam_line"]) for c in zip(*info["dam_line"]))
    if lonlat is None:
        return step(STATUS_GAP, "no dam position", contract=ENGINE_CONTRACT)
    cell = float(S.get("grid_m") if S.get("grid_m") not in (None, "") else 20.0)
    p = {"dem": dem, "z_units": S.get("z_units") or "auto", "dam_lonlat": lonlat,
         "dam_point_given": bool(info.get("breach_point")), "dam_line_lonlat": info.get("dam_line"),
         "reservoir_lonlat": info.get("reservoir"), "azimuth_deg": _num(dam.get("breach_azimuth_deg")),
         "cell_m": cell if cell > 0 else 10.0, "top_ft": top, "height_ft": h,
         "ds_slope": _num(dam.get("ds_slope_h")) or _num((info.get("fields") or {}).get("ds_slope_h"))}
    notes = []
    if info.get("dam_line_note"):                       # a MultiLineString dam line: which part is used, and why
        notes.append(info["dam_line_note"])
    try:
        wkt = R.model_wkt(dem, lonlat)
        csv_path = (hydro_step or {}).get("hydrograph_csv") or dam.get("hydrograph_csv")
        d = BR.DamData(dam_id=str(dam.get("dam_id")), dam_height_ft=h, storage_top_acft=vol, top_of_dam_ft=top,
                       surface_area_top_ac=_num(dam.get("surface_area_ac")))
        piping = BR.make_hydrograph(d, BR.METHOD_PIPING)          # sunny day: the reservoir at the top of dam
        if csv_path and os.path.isfile(csv_path):
            hy = BR.read_user_hydrograph(csv_path)
            hsrc = "the dam's hydrograph CSV ({})".format(os.path.basename(csv_path))
        else:
            hy = piping
            hsrc = "Froehlich (2008) piping, sunny day from the top of dam"
        site = MD.site(p, wkt, log)
        width = _num(piping.params.get("avg_breach_width_ft")) or 100.0
        vw = vol * ACFT_M3
        sp = {"dem": dem, "z_units": p["z_units"], "grid_m": cell, "simh": S.get("simh", 12.0),
              "simmax": S.get("simmax", 96.0), "larger_clips": S.get("larger_clips", 1),
              "local_dem": S.get("local_dem") or "", "timeout_s": screening_timeout_s(S), "engine": eng,
              "lisflood_exe": S.get("lisflood_exe") or "", "workdir": folder or ""}
        log("  engine2d: {} 2D screening flood, {} m cell, clock {} h (to {} h), larger clips: {}, time limit "
            "{:.0f} s; hydrograph: {}".format("LISFLOOD-FP" if eng == "lisflood" else "built-in", cell or "automatic",
                                              sp["simh"], sp["simmax"], SC.LARGER_CLIPS[int(sp["larger_clips"])],
                                              sp["timeout_s"], hsrc))
        res = SC.simulate(sp, hy.t_s, hy.q_cms, {"inflow_xy": site["inflow_xy"], "downstream": site["downstream"],
                                                  "breach_width_m": width * FT, "vw_m3": vw}, wkt, log, cancel)
    except Exception as e:                                       # noqa: BLE001 - a step result, not a crash
        return step(STATUS_FAIL, "screening flood failed: {}".format(e), contract=ENGINE_CONTRACT)
    if res.get("status") not in ("ok", "partial"):
        return step(STATUS_FAIL, "screening flood {}: {}".format(res.get("status"), "; ".join(res.get("notes") or [])),
                    contract=ENGINE_CONTRACT)
    files = SC.write_rasters(folder, res, wkt) if folder else {}
    recs = [dict(r) for r in (receptors or [])]
    charts = RB.tm11_charts()
    if not charts:
        notes.append("DamIT Hazard's TM-11 charts are not installed: no M1 chart zones at the receptors")
    sampled = 0
    for r in recs:
        if r.get("_x") is None or r.get("_y") is None:
            continue
        xy = (float(r["_x"]), float(r["_y"]))
        src = r.get("_crs") or "EPSG:4326"
        try:
            xy = R.transform_points([xy], src, wkt)[0]
        except Exception:                                        # noqa: BLE001
            continue
        hyd = SC.receptor_hydraulics(res, [xy])[0]
        if hyd is None:
            r["in_domain"] = False
            continue
        r.update(hyd)
        r.setdefault("receptor_type", "structure")
        sampled += 1
        if charts and r.get("receptor_type") == "structure":
            _, ch = charts
            z = ch.zone(_chart_for(r), hyd["depth_ground_ft"], hyd["velocity_fps"])
            if ZONE_NAMES.get(z):
                r["m1_zone"] = ZONE_NAMES[z]
    g = res["grid"]
    wet = res["depth"] >= 0.1 * FT
    import numpy as np
    stats = {"cell_m": res["cell_m"], "sim_time_hr": round(res["sim_s"] / 3600.0, 2),
             "flooded_acres": round(float(np.nansum(wet)) * g.dx ** 2 / 4046.8564224, 1),
             "max_depth_ft": round(float(np.nanmax(res["depth"])) / FT, 2) if np.isfinite(res["depth"]).any() else 0,
             "edge_flag": res["edge_flag"], "timed_out": res["timed_out"], "radius_m": res["radius_m"],
             "larger_clips": res["larger_clips"], "run_s": res["run_s"], "terrain": res.get("terrain"),
             "terrains": res.get("terrains")}
    # 0.3.0: a flood that ran is OK (2801: GAP after a finished flood); a time-limit partial result is a gap, and a
    # flood truncated at the terrain edge stays OK with the edge flag in stats and the notes
    status = STATUS_OK if res["status"] == "ok" else STATUS_GAP
    used = res.get("engine") or SC.BUILTIN_NAME
    detail = "screening flood ({}{}): {} ac, max {} ft, {} receptor(s) sampled".format(
        used, ", partial: time limit" if res["timed_out"] else (", reaches the terrain edge" if res["edge_flag"] else ""),
        stats["flooded_acres"], stats["max_depth_ft"], sampled)
    return step(status, detail, contract=ENGINE_CONTRACT, engine=used, engine_requested=eng,
                engine_how=res.get("engine_how"), engine_fallback=bool(res.get("engine_fallback")),
                rasters=files, stats=stats, notes=res["notes"] + notes + site.get("checks", []),
                inflow={"xy": list(site["inflow_xy"]), "how": site["inflow_how"], "toe_band": site["toe_band"],
                        "downstream_how": site["downstream_how"]},
                hydrograph={"source": hsrc, "peak_cfs": round(hy.peak_cfs, 0)}, receptors=recs,
                model_dimension="2D")


# ------------------------------------------- depth-velocity chart (habitable) --
DV_CHART_STEM = "damit_screener_dv_habitable"


def dv_chart(dam, receptors, folder, log=print, now=None):
    """The depth-velocity chart (PNG + CSV) of the wet HABITABLE structures of the screening flood, in the dam
    folder: DamIT Hazard's habitability rule and TM-11 charts (damit_hazard.engine.dvchart), the Screener's point
    sample at each structure. A step result; a chart problem never fails the Screener."""
    import datetime
    from . import runner_bridge as RB
    try:
        got = RB.dvchart()
    except Exception:                                            # noqa: BLE001
        got = None
    if not got:
        return step(STATUS_NOT_RUN, "DamIT Hazard is not installed: no depth-velocity chart of habitable structures")
    D, charts = got
    if not folder:
        return step(STATUS_NOT_RUN, "no dam folder: no depth-velocity chart")
    try:
        recs = D.from_screener(receptors)
        if not any(r.get("sampled") for r in recs):
            return step(STATUS_NOT_RUN, "no structure was sampled by the screening flood: no depth-velocity chart")
        meta = {"dam_id": dam.get("dam_id"), "dam_name": dam.get("name") or dam.get("dam_name"),
                "source": "Screener", "run_date": (now or datetime.datetime.now()).strftime("%Y-%m-%d"),
                "sampling": D.SAMPLING_POINT}
        c = D.build(recs, charts, meta, folder, stem=DV_CHART_STEM, log=log)
    except Exception as e:                                       # noqa: BLE001 - a chart is never a failed screening
        return step(STATUS_GAP, "depth-velocity chart not written: {}: {}".format(type(e).__name__, e))
    detail = "{}{}".format(c["text"], "" if c["status"] == "ok" else "; PNG not drawn: " + c["note"])
    return step(STATUS_OK if c["status"] == "ok" else STATUS_GAP, detail, png=c.get("png"), csv=c.get("csv"),
                counts=c["counts"], left_out=c["left_out"], note=c.get("note") or "")


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
