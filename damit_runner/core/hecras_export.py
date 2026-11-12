"""Export a finished breach run as a HEC-RAS 6.6 project. Nothing here starts HEC-RAS,
Wine, or RasUnsteady, and nothing here replaces Depth (Max).tif or the other final rasters.

damit_run:hecrasexport calls export_package. The project is a new folder. The run's
outputs stay where the flood model wrote them.
"""
import json
import os
import shutil
import tempfile

from . import hecras

DEPTH_NAME = "Depth (Max).tif"
# final rasters the export must never write back onto the run or the dam folder
PUBLISHED = (DEPTH_NAME, "Velocity (Max).tif", "WSE (Max).tif", "Arrival Time.tif",
             "hmax_ft.tif", "vmax_fps.tif", "arr_hr.tif", "wsemax_ft.tif")


class ExportError(hecras.HecRasError):
    pass


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _depth_of(folder):
    for rel in (os.path.join("outputs", DEPTH_NAME), DEPTH_NAME):
        p = os.path.join(folder, rel)
        if os.path.isfile(p):
            return p
    return None


def _hydrograph_of(folder):
    for rel in (os.path.join("outputs", hecras.HYDROGRAPH_CSV),
                os.path.join(hecras.MODEL_FOLDER, hecras.HYDROGRAPH_CSV)):
        p = os.path.join(folder, rel)
        if os.path.isfile(p):
            return p
    return None


def _nd_report(folder):
    path = os.path.join(folder, hecras.MODEL_FOLDER, hecras.RUN_REPORT_JSON)
    if not os.path.isfile(path):
        return None
    try:
        report = _load(path)
    except (OSError, ValueError):
        return None
    if isinstance(report, dict) and report.get("dam") and report.get("hydrograph"):
        return report
    return None


def _damit_report(folder, dem_path):
    """The ND-shaped report a DamIT run folder can support. Does not recompute the flood."""
    path = os.path.join(folder, "run_report.json")
    if not os.path.isfile(path):
        raise ExportError("not a finished run: no run_report.json in {}".format(folder))
    try:
        report = _load(path)
    except (OSError, ValueError) as e:
        raise ExportError("cannot read {}: {}".format(path, e))
    setup_path = os.path.join(folder, "run_setup.json")
    setup = {}
    if os.path.isfile(setup_path):
        try:
            setup = _load(setup_path)
        except (OSError, ValueError):
            setup = {}
    params = setup.get("parameters") if isinstance(setup, dict) else None
    params = params if isinstance(params, dict) else {}
    dam = report.get("dam") if isinstance(report.get("dam"), dict) else None
    hydro = report.get("hydrograph") if isinstance(report.get("hydrograph"), dict) else {}
    has_width = "avg_breach_width_ft" in hydro or "bottom_width_ft" in hydro
    if not dam or not has_width:
        dam, hydro = _recover_breach(report, params, dam, hydro)
    dem = dem_path or (report.get("settings") or {}).get("input_files", {}).get("DEM") or params.get("dem")
    if not dem or not os.path.isfile(str(dem)):
        raise ExportError("the DEM of the run was not found ({}); choose it. Nothing was exported."
                          .format(dem or "not recorded"))
    settings = dict(report.get("settings") or {})
    files = dict(settings.get("input_files") or {})
    files["DEM"] = dem
    settings["input_files"] = files
    settings.setdefault("cell_size_m", report.get("record_cell_m") or params.get("cell_m") or 10.0)
    settings.setdefault("manning_n", params.get("manning") or 0.06)
    inflow = (report.get("inflow_point") or {}).get("xy") or (report.get("inflow") or {}).get("xy")
    if inflow and not settings.get("breach_xy"):
        settings["breach_xy"] = list(inflow)
    out = dict(report)
    out["dam"] = dam
    out["hydrograph"] = hydro
    out["settings"] = settings
    out.setdefault("work_crs", report.get("crs_wkt"))
    if inflow and not (out.get("inflow_point") or {}).get("xy"):
        out["inflow_point"] = {"xy": list(inflow)}
    return out, params


def _recover_breach(report, params, dam, hydro):
    """A run from before the report stored the opening: rebuild the breach parameters from
    the saved inputs. The hydrograph file already written is the one exported."""
    need = ("dam_id", "height_ft", "storage_acft", "top_ft", "method")
    src = dict(params)
    src.setdefault("dam_id", report.get("dam_id"))
    src.setdefault("method", hydro.get("method"))
    missing = [k for k in need if src.get(k) in (None, "")]
    if missing:
        raise ExportError("this run does not record the breach opening ({}); re-run it. "
                          "Nothing was exported.".format(", ".join(missing)))
    from ..flood.model import hydrograph_for
    try:
        dam_obj, hy = hydrograph_for(src)
    except Exception as e:                                   # noqa: BLE001 - the inputs are the boundary
        raise ExportError("the breach opening could not be rebuilt ({}); nothing was exported."
                          .format(e))
    from ..flood import breach as BR
    built = _jsonable(hy.summary())
    built["notes"] = list(hy.notes)
    built["label"] = BR.METHOD_LABELS.get(hy.method)
    if hydro:
        built.setdefault("rule", hydro.get("rule"))
    return _jsonable(BR.dam_to_dict(dam_obj)) if not dam else dam, built


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) or value is None or isinstance(value, (str, int, bool)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def prepare_stage(run_folder, dest, dem_path=None):
    """Fill `dest` with the layout build_package reads. Copies the depth raster in; never
    writes a raster back to `run_folder`."""
    run_folder = os.path.abspath(run_folder)
    depth = _depth_of(run_folder)
    if depth is None:
        raise ExportError("the run has no {} (it is not a finished flood). Nothing was exported."
                          .format(DEPTH_NAME))
    hy_csv = _hydrograph_of(run_folder)
    if hy_csv is None:
        raise ExportError("the run has no breach_hydrograph.csv. Nothing was exported.")
    os.makedirs(dest, exist_ok=True)
    shutil.copy2(depth, os.path.join(dest, DEPTH_NAME))
    model = os.path.join(dest, hecras.MODEL_FOLDER)
    os.makedirs(model, exist_ok=True)
    shutil.copy2(hy_csv, os.path.join(model, hecras.HYDROGRAPH_CSV))
    src_json = os.path.join(run_folder, "dam.json")
    if os.path.isfile(src_json):
        shutil.copy2(src_json, os.path.join(dest, "dam.json"))
    report = _nd_report(run_folder)
    params = {}
    if report is None:
        report, params = _damit_report(run_folder, dem_path)
    if not report.get("dam_xy"):
        lonlat = params.get("dam_lonlat") or (report.get("parameters") or {}).get("dam_lonlat")
        if isinstance(lonlat, (list, tuple)) and len(lonlat) >= 2:
            with open(os.path.join(dest, "dam.json"), "w", encoding="utf-8") as f:
                json.dump({"point": {"lon": float(lonlat[0]), "lat": float(lonlat[1])}}, f)
    with open(os.path.join(model, hecras.RUN_REPORT_JSON), "w", encoding="utf-8") as f:
        json.dump(_jsonable(report), f, indent=1)
    for name in PUBLISHED:
        if name == DEPTH_NAME:
            continue
        written = os.path.join(dest, name)
        if os.path.isfile(written):
            os.remove(written)
    return dest


def export_package(run_folder, out_folder=None, dem_path=None, log=None):
    """Build the HEC-RAS project for a finished run.

    Returns build_package's dict (folder, zip, ...). Does not start HEC-RAS. Does not copy
    Depth (Max).tif, or any other final raster, onto the run folder or a dam folder.
    """
    from . import hecras_package as hp
    log = log or (lambda m: None)
    run_folder = os.path.abspath(run_folder)
    before = _published_stamps(run_folder)
    out_root = out_folder or os.path.join(run_folder, "_hecras_export")
    os.makedirs(out_root, exist_ok=True)
    parent = tempfile.mkdtemp(prefix="damit_hecras_export_")
    try:
        stage = prepare_stage(run_folder, os.path.join(parent, "stage"), dem_path)
        log("Writing the HEC-RAS project (HEC-RAS is not started)")
        built = hp.build_package(stage, out_root=out_root, log=log)
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    after = _published_stamps(run_folder)
    for key, was in before.items():
        if after.get(key) != was:
            raise ExportError("the export changed {} ; that file is the published flood and "
                              "must not be replaced".format(key))
    extra = [key for key in after if key not in before]
    if extra:
        raise ExportError("the export wrote {} onto the run; the final rasters are not replaced"
                          .format(", ".join(extra)))
    return built


def _published_stamps(folder):
    out = {}
    for name in PUBLISHED:
        for rel in (os.path.join("outputs", name), name):
            st = _stamp(os.path.join(folder, rel))
            if st is not None:
                out[rel.replace("\\", "/")] = st
    return out


def _stamp(path):
    if not os.path.isfile(path):
        return None
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)
