"""DamIT Runner: run preparation and the breach model run.

damit_run:rundam accepts a damit.handoff package (from damit_screen:handoff) or equivalent
parameters, validates it against DamIT Catalog, and prepares a NEW run folder with
run_setup.json, a copy of the package and the expected-output contract that DamIT Hazard
(damit:classify) will read after a model run.

NID dams only: the package's dam must carry an NID ID (dam_id or nid_id), or be marked new / proposed
(is_new) or a desk sample (is_sample); DamIT Catalog's handoff.nid_rule decides, and validate() refuses the rest.

0.2.0 runs the model the way the DamSafety Runner's rundam does (run_model; DamSafety parameter names and
defaults; damit_runner/flood): LISFLOOD-FP (or the built-in numpy engine when LISFLOOD_EXE = "builtin"), then
ANUGA when TIER asks for it, into a NEW run folder, and copies Depth (Max), hmax and the flood polygons into the
dam folder. DRY_RUN on keeps the 0.1.0 prepare / record only path.

0.3.0: an empty LISFLOOD_EXE looks for LISFLOOD-FP in the provider settings, NDBREACH_LISFLOOD, PATH and the usual
install places, and when there is none runs the built-in engine with a warning (the old ND Breach Runner's fallback);
run_setup.json 'engine_selection' and the outputs ENGINE_USED / ENGINE_FALLBACK / ENGINE_NOTE say which ran. ANUGA
runs on the DamSafety Runner's default mesh (flood/mesh.py). HEC-RAS 2D is refused; DamIT never starts
HEC-RAS or Wine, and never calls the ND suite's breach runner or batch tools.

0.3.1: run_progress.json in the run folder (flood/model.py write_progress): the model CRS and each pass's folder and bounds
after every pass, and "complete" once run_report.json is written, so a run watcher can georeference a pass and tell the run is
over while it is going. No change to the model or its outputs.

0.3.2: a dam line that is a MultiLineString is read (flood/damfolder.py pick_dam_line): DWR-2645 Pheasant Lake's dam_line.geojson is
one, it was skipped without a word, the model had no dam line, the toe fell back to 150 m from the inventory point and the inflow
landed 192 m on the pool side. The parts are joined end to end where two meet, the longest is used when several remain, and the
run notes say which and why. The Screener and the QGIS crest reader use the same rule.

0.3.3: run_report.json inflow.toe_band records the band the inflow really came from (effective_inner_m, effective_outer_m,
original_outer_m, widened, widening_reason: DWR-2645 widened 27 m to 37 m because the nearer ground was the dam's face), and a run that
ends with a wet edge warns (flood/model.py final_edge_note: edges, depths, outflow %, the limit it stopped at or why the domain did not
grow). The report's warnings are now in the log ("Warning: ...") and in run_setup.json run_notes. No change to the model or its numbers.
"""
import datetime
import json
import os

from . import catalog_bridge as CB

VERSION = "0.3.3"
PROVIDER_ID = "damit_run"
RUN_SETUP = "run_setup.json"
RUN_SCHEMA = "damit.run_setup"
# 0.2.0: ENGINE is kept for the 0.1.0 callers; TIER (the DamSafety Runner's "Models") decides by default
ENGINE_LABELS = ["From Models (TIER)", "LISFLOOD-FP", "ANUGA (LISFLOOD-FP for the extent, then ANUGA)",
                 "HEC-RAS 2D (not run by DamIT Runner)"]
ENGINE_NONE = 0          # 0.1.0 name of index 0 (it meant "prepare only"); 0.2.0: "from TIER"
ENGINE_TIER, ENGINE_LISFLOOD, ENGINE_ANUGA, ENGINE_HECRAS = 0, 1, 2, 3
REFUSAL = ("DamIT Runner does not run {}: HEC-RAS 2D needs HEC-RAS 6.6 (and Wine on Linux), and DamIT never starts "
           "HEC-RAS or Wine, and never calls the ND suite's breach runner or batch tools. Choose LISFLOOD-FP, or "
           "LISFLOOD-FP then ANUGA. Nothing was run.")
EXPECTED_OUTPUTS = {
    "depth_max": "outputs/Depth (Max).tif",
    "velocity_max": "outputs/Velocity (Max).tif",
    "wse_max": "outputs/WSE (Max).tif",
    "arrival": "outputs/Arrival Time.tif",
    "hmax": "outputs/hmax_ft.tif",
    "flood_polygons": "outputs/Flood Polygons (Max Depth).geojson",
    "flood_extent": "outputs/Flood Extent.geojson",
    "arrival_zones": "outputs/Arrival Zones.geojson",
    "units": {"depth": "ft", "velocity": "ft/s", "wse": "ft", "arrival": "hours after breach initiation"},
}
# copied into the dam folder (<DAMS_FOLDER>/<dam id>/) after a finished run, as the DamSafety Runner leaves them
DAM_FOLDER_FILES = ("Depth (Max).tif", "Velocity (Max).tif", "WSE (Max).tif", "Arrival Time.tif", "hmax_ft.tif",
                    "vmax_fps.tif", "arr_hr.tif", "wsemax_ft.tif", "Flood Polygons (Max Depth).geojson",
                    "Flood Extent.geojson", "Arrival Zones.geojson", "breach_hydrograph.csv", "units.json")


class RunError(ValueError):
    pass


def refuse_engine(engine, dry_run=False):
    """Raise RunError for a request DamIT Runner does not run (HEC-RAS 2D). dry_run is the 0.1.0 prepare-only
    switch and is never refused."""
    try:
        e = int(engine or 0)
    except (TypeError, ValueError):
        e = -1
    if e == ENGINE_HECRAS:
        raise RunError(REFUSAL.format("HEC-RAS 2D"))
    if not 0 <= e < len(ENGINE_LABELS):
        raise RunError("unknown engine {!r}. Nothing was run.".format(engine))


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
    lines = ["# DamIT Runner - prepared run" + ("" if setup.get("model_launched") else " (no model launched)"), "",
             "Dam: {} {}".format(setup["dam"].get("dam_id"), setup["dam"].get("name") or ""),
             "Mode: {} {}".format(setup["mode"], setup.get("preset_label") or ""),
             "Scenarios: {}".format(", ".join(s.get("id") for s in setup["scenarios"] or []) or "none (unconfirmed)"),
             "Ready to run: {}{}".format("yes" if setup["ready_to_run"] else "no",
                                         "" if setup["ready_to_run"] else " - missing: " + "; ".join(setup["gaps"])),
             ""]
    if setup.get("model_launched"):
        lines += ["Model: {} ({}), status {}. Outputs in outputs/ (run_setup.json 'outputs'); copied into the dam "
                  "folder: {}.".format(setup.get("engine"), setup.get("model_dimension") or "2D", setup.get("status"),
                                       setup.get("dam_folder") or "no dam folder given")]
        sel = setup.get("engine_selection") or {}
        if sel:
            lines.append("Engine chosen by: {}{}".format(sel.get("how"), "" if not sel.get("warning") else
                                                       ". " + sel["warning"]))
        lines += ["Classify with DamIT Hazard (damit:classify) on Depth (Max).tif and Velocity (Max).tif."]
    else:
        lines += ["Prepared with DRY_RUN on: no model was launched. Run damit_run:rundam with DRY_RUN off to run "
                  "LISFLOOD-FP (or ANUGA) and write the rasters in run_setup.json 'expected_outputs', then classify "
                  "with DamIT Hazard (damit:classify)."]
    lines.append("Suggested classifications only; the engineer of record and the regulating agency make the "
                 "determination.")
    with open(os.path.join(folder, "README_run.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------------------------------ 0.2.0: model run --
# The DamSafety Runner's rundam parameters DamIT Runner takes, with the same defaults (DWR_Plugins main 591f48d,
# DamSafety Runner algorithms.py RunDamAlgorithm): name -> (model key, default)
MODEL_PARAMS = {
    "METHOD": ("method", 0), "TIER": ("tier", 0), "FORCE_ANUGA": ("force_anuga", False), "CELL": ("cell_m", 10.0),
    "MANNING": ("manning", 0.06), "ARRIVAL_FT": ("arrival_ft", 0.1), "EDGE_TOL_FT": ("edge_tol_ft", 1.0),
    "OUTFLOW_EXTEND_PCT": ("outflow_extend_pct", 5.0), "LENGTH_MI": ("length_mi", 4.0),
    "HALF_WIDTH_MI": ("half_width_mi", 1.0), "STEP_MI": ("step_mi", 3.0), "MAX_EXTENT_MI": ("max_extent_mi", 20.0),
    "MAX_RUNS": ("max_runs", 6), "LISFLOOD_MAX_WALL_S": ("max_wall_s", 0.0),
    "LISFLOOD_MAX_TOTAL_WALL_S": ("max_total_wall_s", 0.0), "DURATION_HR": ("duration_hr", 0.0),
    "DURATION_MAX_HR": ("duration_max_hr", 96.0), "GRID_REFINE": ("grid_refine", True),
    "GRID_CHECK_CELL": ("grid_check_cell_m", 0.0), "LISFLOOD_EXE": ("lisflood_exe", ""),
    "ANUGA_PYTHON": ("anuga_python", ""), "ANUGA_FINE": ("anuga_fine_m2", 100.0),
    "ANUGA_COARSE": ("anuga_coarse_m2", 1000.0), "ANUGA_NEAR_MI": ("anuga_near_mi", 1.0),
    "ANUGA_BUFFER": ("anuga_buffer_m", 500.0), "THREADS": ("threads", 0), "KEEP_FILES": ("keep_files", True),
    "PRODUCTS": ("products", True), "CONTOURS_HR": ("contours_hr", "0.25, 0.5, 1, 2, 4, 8"),
    "PIPE_FRACTION": ("pipe_fraction", 0.5), "PIPE_DIA_FT": ("pipe_dia_ft", 0.5),
    "DEM_Z": ("z_units", 0),
}
DEM_Z_UNITS = ["auto", "ft", "us_ft", "m"]
DEM_Z_LABELS = ["Detect from the raster", "Feet", "US survey feet", "Meters"]


def flood():
    """The flood package (numpy + GDAL; imported only when a model runs)."""
    from ..flood import breach, model
    return breach, model


def method_labels():
    br, _ = flood()
    return [br.METHOD_LABELS[m] for m in br.METHODS]


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def read_dam_folder(folder):
    """dam.json fields, the dam line, reservoir point and breach point of a dam folder (flood/damfolder.py)."""
    from ..flood import damfolder
    return damfolder.read(folder)


def model_params(values, pkg, dam_dir_info=None):
    """The flood-model inputs from the algorithm's values (DamSafety names), the package and the dam folder.
    Explicit values win, then the package's dam record, then dam.json. Returns (params, notes)."""
    br, _ = flood()
    notes = []
    v = dict(values or {})
    dam = (pkg or {}).get("dam") or {}
    rec = (dam_dir_info or {}).get("fields") or {}
    p = {}
    for name, (key, default) in MODEL_PARAMS.items():
        val = v.get(name)
        p[key] = default if val in (None, "") else val
    p["method"] = br.METHODS[int(p["method"])] if not isinstance(p["method"], str) else p["method"]
    p["z_units"] = DEM_Z_UNITS[int(p["z_units"])] if not isinstance(p["z_units"], str) else p["z_units"]
    p["contours_hr"] = tuple(float(x) for x in str(p["contours_hr"]).replace(";", ",").split(",") if x.strip())
    for k in ("cell_m", "manning", "arrival_ft", "edge_tol_ft", "outflow_extend_pct", "length_mi", "half_width_mi",
              "step_mi", "max_extent_mi", "max_wall_s", "max_total_wall_s", "duration_hr", "duration_max_hr",
              "grid_check_cell_m", "anuga_fine_m2", "anuga_coarse_m2", "anuga_near_mi", "anuga_buffer_m",
              "pipe_fraction", "pipe_dia_ft"):
        p[k] = float(p[k])
    for k in ("tier", "max_runs", "threads"):
        p[k] = int(p[k])
    for k in ("force_anuga", "grid_refine", "keep_files", "products"):
        p[k] = p[k] if isinstance(p[k], bool) else str(p[k]).strip().lower() in ("1", "true", "yes", "on")

    def pick(name, *alts):
        for a in (v.get(name),) + alts:
            x = _f(a)
            if x is not None:
                return x
        return None
    p["dam_id"] = dam.get("dam_id") or v.get("DAM_ID")
    p["name"] = dam.get("name") or rec.get("name") or ""
    p["height_ft"] = pick("HEIGHT_FT", dam.get("height_ft"), rec.get("height_ft"))
    p["storage_acft"] = pick("STORAGE_ACFT", dam.get("storage_top_of_dam_acft"), dam.get("storage_acft"),
                             rec.get("storage_acft"))
    p["top_ft"] = pick("TOP_FT", dam.get("top_of_dam_elev_ft"), rec.get("top_of_dam_ft"),
                       rec.get("top_of_dam_elev_ft"))
    p["area_ac"] = pick("AREA_AC", dam.get("surface_area_ac"), rec.get("surface_area_ac"))
    p["bottom_ft"] = pick("BOTTOM_FT")
    p["crest_width"] = pick("CREST_WIDTH")
    p["us_slope"] = pick("US_SLOPE")
    p["ds_slope"] = pick("DS_SLOPE", rec.get("ds_slope_h"), rec.get("downstream_slope_h"))
    p["crest_length_ft"] = pick("CREST_LENGTH", rec.get("dam_length_ft"))
    if v.get("PMF_FT") not in (None, ""):
        notes.append("PMF_FT is recorded but not used: the sunny-day breach starts at the top of dam (Nick's rule)")
    p["user_csv"] = v.get("USER_CSV") or None
    if p["method"] == br.METHOD_USER and not p["user_csv"]:
        p["user_csv"] = v.get("HYDROGRAPH") or ((pkg or {}).get("inputs") or {}).get("hydrograph_csv")
    if p["ds_slope"] is None:
        notes.append("downstream slope not known: the toe band uses 3:1")
    for need in ("height_ft", "storage_acft", "top_ft"):
        if p[need] is None:
            raise RunError("the model run needs {} (a parameter, the package or the dam folder's dam.json)"
                           .format(need))
    p["dem"] = v.get("DEM") or v.get("TERRAIN") or ((pkg or {}).get("inputs") or {}).get("terrain")
    if not p["dem"] or not os.path.isfile(str(p["dem"])):
        raise RunError("the model run needs a DEM (DEM or TERRAIN, or the package's terrain): {}".format(p["dem"]))
    info = dam_dir_info or {}
    # the dam position, lon / lat: X / Y in EPSG:4326, the package's x / y when EPSG:4326, the breach point,
    # dam.json lon / lat; the dam line and the reservoir point from the dam folder
    lonlat = None
    if _f(v.get("X")) is not None and _f(v.get("Y")) is not None and str(v.get("CRS") or "EPSG:4326").upper() in (
            "EPSG:4326", "WGS84", "OGC:CRS84"):
        lonlat = (float(v["X"]), float(v["Y"]))
    elif _f(dam.get("x")) is not None and _f(dam.get("y")) is not None:
        crs = str(dam.get("crs") or "EPSG:4326")
        if crs.upper() in ("EPSG:4326", "OGC:CRS84"):
            lonlat = (float(dam["x"]), float(dam["y"]))
        else:
            try:
                from ..flood import rasters
                lonlat = tuple(rasters.transform_points([(float(dam["x"]), float(dam["y"]))], crs, "EPSG:4326")[0])
            except Exception:                                    # noqa: BLE001 - then the dam folder decides
                lonlat = None
    p["dam_point_given"] = bool(info.get("breach_point"))
    if info.get("breach_point"):
        lonlat = info["breach_point"]
    elif lonlat is None and _f(rec.get("lon")) is not None:
        lonlat = (float(rec["lon"]), float(rec["lat"]))
    p["dam_lonlat"] = lonlat
    p["dam_line_lonlat"] = info.get("dam_line")
    if info.get("dam_line_note"):
        notes.append(info["dam_line_note"])
    p["reservoir_lonlat"] = info.get("reservoir")
    p["azimuth_deg"] = _f(dam.get("breach_azimuth_deg"))
    if v.get("INFLOW_LONLAT"):
        p["inflow_lonlat"] = tuple(float(c) for c in v["INFLOW_LONLAT"])
    return p, notes


def run_model(pkg, out_root, values, cat=None, dams_folder=None, log=print, cancel=None, now=None):
    """Prepare a NEW run folder, run the flood model there (LISFLOOD-FP / built-in engine, ANUGA tier) and copy
    the final rasters and vectors into <dams_folder>/<dam id>/. Returns (run_folder, run_setup)."""
    import shutil
    import time as _time
    _, _, HO = CB.modules()
    cat = cat or CB.load_catalog()
    engine = int(values.get("ENGINE") or 0)
    refuse_engine(engine)
    vals = dict(values)
    if engine == ENGINE_LISFLOOD:
        vals["TIER"] = 0
    elif engine == ENGINE_ANUGA:
        vals["TIER"] = 1
    dam_id = pkg["dam"]["dam_id"]
    dam_dir = os.path.join(dams_folder, HO.safe_name(dam_id)) if dams_folder else None
    info = read_dam_folder(dam_dir)
    params, notes = model_params(vals, pkg, info)
    folder, setup = prepare_run(pkg, out_root, cat, ENGINE_TIER, True, now)
    setup.update({"status": "running", "dry_run": False, "model_launched": True,
                  "parameters": {k: (list(x) if isinstance(x, tuple) else x) for k, x in params.items()},
                  "parameter_notes": notes, "dam_folder": dam_dir})
    _save(folder, setup)
    for n in notes:
        log("Note: " + n)
    # Warn if the DEM may not cover the contributing basin (PMF/spillway use)
    dem_path = params.get("dem")
    lon, lat = params.get("lon"), params.get("lat")
    if dem_path and lon and lat:
        try:
            from . import streamstats as SS
            basin = SS.delineate(lon, lat, state="ND")
            area = SS.basin_area_sqmi(basin)
            if area and area > 0:
                feats = basin.get("featurecollection") or []
                for fc in feats:
                    for item in fc if isinstance(fc, list) else [fc]:
                        if item.get("name") == "globalwatershed":
                            geom = item.get("feature", {}).get("features", [{}])[0].get("geometry", {})
                            coords = (geom.get("coordinates") or [[]])[0]
                            if coords:
                                lons = [c[0] for c in coords]
                                lats = [c[1] for c in coords]
                                basin_ext = (min(lons), min(lats), max(lons), max(lats))
                                log("Basin area ~{:.1f} sq mi; extent {:.4f},{:.4f},{:.4f},{:.4f}".format(
                                    area, *basin_ext))
                            break
        except Exception:
            pass  # delineation is optional; do not block the run
    _, model = flood()
    t0 = _time.time()
    try:
        rec = model.run_breach(params, folder, log=log, cancel=cancel)
    except Exception as e:                                       # noqa: BLE001 - recorded, then raised
        setup.update({"status": "failed", "error": str(e), "wall_s": round(_time.time() - t0, 1)})
        _save(folder, setup)
        raise RunError("the flood model failed: {}".format(e))
    copied = []
    if dam_dir:
        os.makedirs(dam_dir, exist_ok=True)
        for name in DAM_FOLDER_FILES:
            src = os.path.join(folder, "outputs", name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dam_dir, name))
                copied.append(os.path.join(dam_dir, name))
    sel = rec.get("engine_selection") or {}
    setup.update({"status": "finished", "engine": rec["engine"], "extent_engine": rec["extent_engine"],
                  "engine_selection": sel, "engine_fallback": bool(sel.get("fallback")),
                  "engine_note": sel.get("warning") or "",
                  "run_notes": list(rec.get("warnings") or []),
                  "model_dimension": "2D", "model": rec, "wall_s": round(_time.time() - t0, 1),
                  "outputs": {k: v for k, v in rec["outputs"].items()}, "dam_folder_files": copied,
                  "ready_to_run": True, "gaps": []})
    setup["classification"]["note"] = ("DamIT Runner does not classify; run DamIT Hazard (damit:classify) on "
                                       "Depth (Max).tif and Velocity (Max).tif.")
    _save(folder, setup)
    _write_readme(folder, setup)
    return folder, setup


def _save(folder, setup):
    tmp = os.path.join(folder, RUN_SETUP + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(setup, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, os.path.join(folder, RUN_SETUP))
