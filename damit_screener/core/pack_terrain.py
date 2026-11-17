"""Prefer the configured offline pack DEM for the Screener's larger clips (DamIT Screener 0.3.4).

larger_clips 1 (the default) downloads each larger clip fresh from USGS 3DEP. When the DamIT data
folder (damit_core settings data_folder), the ND suite data folder (NDSUITE_DATA / NDSUITE_PACK,
~/.ndsuite/config.json) or DAMIT_DATA holds a DEM in <folder>/dem, the larger clips are read from
that DEM instead (larger_clips 2, local_dem = the DEM FILE: flood/screen.py opens local_dem as a
raster). Nothing here is a hard-coded path, and the pack is never written.

0.3.4 review fixes (2026-11-17):
  * local_dem is the DEM file, not its folder (a folder made every larger clip fail to open);
  * only <folder>/dem holds the DEM; rasters at the top of a data folder are never terrain;
  * the DamIT data folder setting is read (no damsuite import: DamIT has none);
  * settings that set larger_clips themselves are kept; offline_pack_terrain = false turns this off;
  * the coverage check runs per dam in run_dam for ANY local_dem (settings_from has no dam point,
    and once it had set local_dem the per-dam check used to be skipped): a dam outside the DEM
    goes back to the USGS 3DEP download for its larger clips, with a note.
"""
from __future__ import annotations

import json
import os

RASTER_EXT = (".tif", ".tiff", ".vrt", ".img")
DEM_DIR = "dem"
OPT_OUT_KEY = "offline_pack_terrain"


def _existing_dir(raw):
    p = os.path.expanduser(str(raw or "").strip())
    return os.path.abspath(p) if p and os.path.isdir(p) else ""


def _config_values(*paths_and_keys):
    """Read keys from JSON config files (e.g. ~/.ndsuite/config.json)."""
    out = []
    for path, keys in paths_and_keys:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                data = json.loads(fh.read())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in keys:
            v = _existing_dir(data.get(key))
            if v:
                out.append(v)
    return out


def _damit_data_folder():
    try:
        from damit_core.lib import settings as DS
        return DS.get("data_folder")
    except Exception:                                            # noqa
        return ""


def configured_pack_folders():
    """Existing folders already set for the DamIT / ND suite data on this computer. No box paths."""
    found = []
    for env in ("DAMIT_DATA", "DAMIT_DATA_FOLDER", "NDSUITE_PACK", "NDSUITE_DATA"):
        v = _existing_dir(os.environ.get(env, ""))
        if v:
            found.append(v)
    v = _existing_dir(_damit_data_folder())
    if v:
        found.append(v)
    found.extend(_config_values(
        (os.path.join("~", ".ndsuite", "config.json"),
         ("ndsuite/data_folder", "ndsuite/pack_path")),
    ))
    out, seen = [], set()
    for p in found:
        key = os.path.normcase(os.path.realpath(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def pack_dem(folder):
    """The DEM in <folder>/dem: a .vrt first (a mosaic), else the only raster, else ''
    (damit_runner.compat.suitedata.local_dem's rule). Files directly in <folder> are never used."""
    folder = _existing_dir(folder)
    if not folder:
        return ""
    dem_dir = os.path.join(folder, DEM_DIR)
    try:
        names = sorted(os.listdir(dem_dir))
    except OSError:
        return ""
    files = [os.path.join(dem_dir, n) for n in names
             if not n.startswith(".") and os.path.splitext(n)[1].lower() in RASTER_EXT
             and os.path.isfile(os.path.join(dem_dir, n))]
    vrts = [p for p in files if p.lower().endswith(".vrt")]
    if vrts:
        return vrts[0]
    return files[0] if len(files) == 1 else ""


def find_pack_dem():
    """(dem path, folder it came from) for the first configured folder that has a DEM, else ('', '')."""
    for folder in configured_pack_folders():
        dem = pack_dem(folder)
        if dem:
            return dem, folder
    return "", ""


def raster_bounds(path):
    """(minx, miny, maxx, maxy, epsg_or_None) of a raster, or None when it cannot be read."""
    try:
        from osgeo import gdal, osr
    except ImportError:
        return None
    ds = gdal.Open(path)
    if ds is None:
        return None
    try:
        gt = ds.GetGeoTransform()
        w, h = ds.RasterXSize, ds.RasterYSize
        xs = (gt[0], gt[0] + w * gt[1] + h * gt[2])
        ys = (gt[3], gt[3] + w * gt[4] + h * gt[5])
        epsg = None
        wkt = ds.GetProjection()
        if wkt:
            srs = osr.SpatialReference()
            if srs.ImportFromWkt(wkt) == 0:
                try:
                    srs.AutoIdentifyEPSG()
                    code = srs.GetAuthorityCode(None)
                    epsg = int(code) if code else None
                except Exception:
                    epsg = None
        return (min(xs), min(ys), max(xs), max(ys), epsg)
    finally:
        ds = None


def _point_in_bounds(bounds, xy, xy_epsg=4326):
    if not bounds or not xy or len(xy) < 2:
        return True
    minx, miny, maxx, maxy, epsg = bounds
    x, y = float(xy[0]), float(xy[1])
    if epsg and xy_epsg and int(epsg) != int(xy_epsg):
        try:
            from osgeo import osr
            src, dst = osr.SpatialReference(), osr.SpatialReference()
            src.ImportFromEPSG(int(xy_epsg))
            dst.ImportFromEPSG(int(epsg))
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            t = osr.CoordinateTransformation(src, dst)
            x, y, _ = t.TransformPoint(x, y)
        except Exception:
            return True  # cannot compare CRSs: do not reject the DEM
    pad_x = max(1.0, 0.01 * (maxx - minx))
    pad_y = max(1.0, 0.01 * (maxy - miny))
    return (minx - pad_x) <= x <= (maxx + pad_x) and (miny - pad_y) <= y <= (maxy + pad_y)


def pack_covers(dem, xy=None, xy_epsg=4326):
    """True when the DEM can be used at xy. Unknown bounds (no GDAL) count as covering; a missing file does not."""
    if not dem or not os.path.isfile(dem):
        return False
    if xy is None:
        return True
    bounds = raster_bounds(dem)
    if bounds is None:
        return True
    return _point_in_bounds(bounds, xy, xy_epsg)


def _off(v):
    return v is False or str(v).strip().lower() in ("false", "no", "0", "off")


def apply_offline_pack_terrain(settings, xy=None, xy_epsg=4326, log=None, explicit=()):
    """Larger clips from the configured pack DEM when the settings did not choose otherwise.

    `explicit`: the keys the user's settings JSON set (larger_clips set there is kept).
    With `xy` (the dam, lon / lat) a local_dem that does not cover the dam goes back to the 3DEP
    download for this dam. Returns the same dict; notes in _terrain_source_notes."""
    S = settings if isinstance(settings, dict) else {}
    explicit = set(explicit or ())
    notes = []

    def _log(msg):
        notes.append(msg)
        if log:
            log(msg)

    def _done(used):
        S["_terrain_source_used"] = used
        S["_terrain_source_notes"] = notes
        return S

    if _off(S.get(OPT_OUT_KEY, True)):
        _log("terrain: offline pack default is turned off ({} = false)".format(OPT_OUT_KEY))
        return _done("settings:pack_default_off")

    local = (S.get("local_dem") or "").strip()
    if local:
        if os.path.isdir(local):               # a folder (DamIT Crest writes the DWR-style folder): its DEM file
            terrain = str(S.get("terrain") or "").strip()
            dem = terrain if os.path.isfile(terrain) else ""
            if not dem and os.path.basename(os.path.normpath(local)) == DEM_DIR:
                dem = pack_dem(os.path.dirname(os.path.normpath(local)))
            if not dem:
                dem = pack_dem(local)
            S["local_dem"] = local = dem
            if not dem:
                _log("terrain: local_dem is a folder with no single DEM in it; larger clips use USGS 3DEP")
                if int(S.get("larger_clips") or 0) == 2:
                    S["larger_clips"] = 1
                return _done("3dep:local_dem_folder")
        if xy is not None and int(S.get("larger_clips") or 0) == 2 and not pack_covers(local, xy, xy_epsg):
            S["larger_clips"] = 1
            _log("terrain: the local DEM ({}) does not cover this dam; its larger clips are a USGS 3DEP "
                 "download".format(local))
            return _done("3dep:local_does_not_cover:{}".format(local))
        if int(S.get("larger_clips") or 0) == 1 and "larger_clips" not in explicit:
            S["larger_clips"] = 2
            _log("terrain: local DEM already set ({}); larger clips use it too, not a 3DEP download".format(local))
        else:
            _log("terrain: local DEM ({}); larger clips {}".format(local, S.get("larger_clips")))
        return _done("local_dem:{}".format(local))

    if "larger_clips" in explicit:
        _log("terrain: larger clips {} as the settings say".format(S.get("larger_clips")))
        return _done("settings:larger_clips")

    dem, folder = find_pack_dem()
    if not dem:
        _log("terrain: larger clips are a USGS 3DEP download (no DEM in <data folder>/dem; set the DamIT "
             "data folder, DAMIT_DATA, NDSUITE_DATA / NDSUITE_PACK or ~/.ndsuite)")
        return _done("3dep:no_pack")

    if not pack_covers(dem, xy, xy_epsg):
        _log("terrain: larger clips are a USGS 3DEP download (the pack DEM does not cover the dam): {}".format(dem))
        return _done("3dep:pack_does_not_cover:{}".format(dem))

    S["local_dem"] = dem
    S["larger_clips"] = 2
    _log("terrain: larger clips from the offline pack DEM {} (from {})".format(dem, folder))
    return _done("offline_pack:{}".format(dem))


def pop_notes(settings):
    """The notes apply_offline_pack_terrain left in `settings`, removed from it."""
    if not isinstance(settings, dict):
        return []
    settings.pop("_terrain_source_used", None)
    return list(settings.pop("_terrain_source_notes", None) or [])
