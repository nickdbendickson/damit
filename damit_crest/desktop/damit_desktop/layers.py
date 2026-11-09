"""AOI layers: the DamIT data folder the DamIT plugins share, or a public US download for this dam.

The data folder is jurisdiction-neutral: DAMIT_DATA, else "damit/data_folder" in ~/.damit/config.json. Nothing else
(no state suite pack). It holds DEMs, receptors and other layers; the dam inventory is the NID (nid.py), not a file
in the data folder."""

from __future__ import annotations

import json
import math
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

THREEDEP = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
# Large-scale flowline and waterbody. Public National Map layers (not a dam inventory).
NHD_LAYERS = ((6, "streams.geojson"), (12, "waterbodies.geojson"))
RASTER_EXT = {".tif", ".tiff", ".vrt", ".img"}
CONFIG_KEY = "damit/data_folder"
SETTINGS_NAME = "damit_settings.json"


def _config_folder(config: Path, key: str) -> str | None:
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get(key) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return str(path.resolve()) if path.is_dir() else None


def _env_folder(name: str) -> str | None:
    env = (os.environ.get(name) or "").strip()
    if env:
        path = Path(env).expanduser()
        if path.is_dir():
            return str(path.resolve())
    return None


def find_data_folder_with_source() -> tuple[str | None, str]:
    """(folder, where it came from): DAMIT_DATA, else damit/data_folder in ~/.damit/config.json."""
    home = Path.home()
    for found, where in (
        (_env_folder("DAMIT_DATA"), "DAMIT_DATA"),
        (_config_folder(home / ".damit" / "config.json", CONFIG_KEY), "~/.damit/config.json"),
    ):
        if found:
            return found, where
    return None, ""


def find_data_folder() -> str | None:
    return find_data_folder_with_source()[0]


def data_dem(folder: str | None) -> str | None:
    """A DEM mosaic in <data folder>/dem. A tile cache (e.g. lidar_1m) is not one DEM."""
    if not folder:
        return None
    dem_dir = Path(folder) / "dem"
    if not dem_dir.is_dir():
        return None
    found = [p for p in dem_dir.iterdir() if p.is_file() and p.suffix.lower() in RASTER_EXT]
    vrts = [p for p in found if p.suffix.lower() == ".vrt"]
    if vrts:
        return str(sorted(vrts)[0].resolve())
    if not found:
        return None
    return str(sorted(found)[0].resolve())


def write_settings(
    work: Path,
    data_folder: str | None,
    dem_file: str | None,
    only_ids: str | None = None,
    classification: dict | None = None,
) -> Path:
    """damit_settings.json for --SETTINGS. only_ids limits the screening chain to that dam (a screener that filters
    from settings rather than a DAM_ID parameter reads it here). classification carries the desk's jurisdiction
    choice (preset id or custom method ids) so the screener and damit:classify see the same context."""
    data: dict = {"format": "damit/settings", "format_version": 1}
    if only_ids:
        data["only_ids"] = str(only_ids).strip()
        # DamIT Screener's key: runchain screens only these dam_ids.
        data["dam_ids"] = [i.strip() for i in str(only_ids).split(",") if i.strip()]
    if data_folder:
        data["data_folder"] = data_folder
        # The ND screener's key, kept so a screener ported from it finds the folder unchanged.
        data["suite_folder"] = data_folder
    if dem_file:
        data["terrain_source"] = 1
        data["local_dem"] = str(Path(dem_file).resolve().parent)
        # DamIT Screener's key: the terrain raster itself.
        data["terrain"] = str(Path(dem_file).resolve())
    if isinstance(classification, dict) and classification:
        data["classification"] = classification
    path = work / SETTINGS_NAME
    # Atomic write: a crash mid-write must not leave a truncated settings file for the next run to read.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def _nums(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Python's json accepts NaN/Infinity literals, so a malformed request can carry non-finite
        # coordinates. Drop them here: they would otherwise reach int(width_m / 10) and crash the job.
        return [float(value)] if math.isfinite(value) else []
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_nums(item))
        return out
    return []


def aoi_bbox(dam: dict) -> tuple[float, float, float, float] | None:
    """(min lon, min lat, max lon, max lat), capped near 15 km so a download stays local."""
    geom = (dam or {}).get("geometry") if isinstance(dam, dict) else None
    aoi = (geom or {}).get("aoi") if isinstance(geom, dict) else None
    coords = _nums(((aoi or {}).get("geometry") or {}).get("coordinates"))
    lons = coords[0::2]
    lats = coords[1::2]
    if not lons:
        point = None
        for key in ("breachPoint", "reservoirPoint"):
            feature = (geom or {}).get(key) if isinstance(geom, dict) else None
            nums = _nums(((feature or {}).get("geometry") or {}).get("coordinates"))
            if len(nums) >= 2:
                point = nums[0], nums[1]
                break
        if point is None and isinstance(dam, dict):
            lon, lat = dam.get("lon"), dam.get("lat")
            if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
                point = float(lon), float(lat)
        if point is None:
            return None
        lons, lats = [point[0] - 0.04, point[0] + 0.04], [point[1] - 0.04, point[1] + 0.04]
    minx, maxx = min(lons), max(lons)
    miny, maxy = min(lats), max(lats)
    if maxx - minx < 0.01:
        mid = (minx + maxx) / 2
        minx, maxx = mid - 0.02, mid + 0.02
    if maxy - miny < 0.01:
        mid = (miny + maxy) / 2
        miny, maxy = mid - 0.02, mid + 0.02
    if maxx - minx > 0.2:
        mid = (minx + maxx) / 2
        minx, maxx = mid - 0.1, mid + 0.1
    if maxy - miny > 0.2:
        mid = (miny + maxy) / 2
        miny, maxy = mid - 0.1, mid + 0.1
    return minx, miny, maxx, maxy


def _save_url(url: str, dest: Path, timeout: float, fetch) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fetch is not None:
        fetch(url, dest)
        return
    request = urllib.request.Request(url, headers={"User-Agent": "DamIT-Crest-desktop"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(80_000_000 + 1)
    except urllib.error.URLError as exc:
        raise OSError(str(exc)) from exc
    if len(data) > 80_000_000:
        raise OSError("the download was larger than 80 MB and was not saved")
    dest.write_bytes(data)


def download_aoi(work: Path, dam: dict, log, fetch=None) -> dict:
    box = aoi_bbox(dam)
    if not box:
        log("No drawn area and no dam location, so nothing was downloaded.")
        return {"ok": False, "stopped": True}
    minx, miny, maxx, maxy = box
    log(f"Area: longitude {minx:.4f} to {maxx:.4f}, latitude {miny:.4f} to {maxy:.4f}.")
    width_m = max((maxx - minx) * 111320 * 0.7, 500)
    pixels = max(64, min(1500, int(width_m / 10)))
    dem_url = THREEDEP + "?" + urllib.parse.urlencode({
        "bbox": f"{minx},{miny},{maxx},{maxy}",
        "bboxSR": "4326",
        "imageSR": "5070",
        "size": f"{pixels},{pixels}",
        "format": "tiff",
        "pixelType": "F32",
        "f": "image",
    })
    dem = work / "dem.tif"
    try:
        _save_url(dem_url, dem, 180, fetch)
        log(f"DEM: {dem} (3DEP, about {pixels} cells on a side, EPSG:5070).")
    except OSError as exc:
        log(f"DEM was not downloaded: {exc}")
        dem = None
    out_dir = work / "aoi"
    for layer, name in NHD_LAYERS:
        query = urllib.parse.urlencode({
            "where": "1=1",
            "geometry": f"{minx},{miny},{maxx},{maxy}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
        })
        url = f"{NHD}/{layer}/query?{query}"
        dest = out_dir / name
        try:
            _save_url(url, dest, 120, fetch)
            log(f"Wrote {dest}")
        except OSError as exc:
            log(f"{name} was not downloaded: {exc}")
    log("Dam lines and structure layers are not on that public service. Put them in the DamIT data folder. The dam inventory is the NID.")
    if dem and dem.is_file():
        write_settings(work, find_data_folder(), str(dem))
        return {"ok": True, "stopped": False, "dem": str(dem)}
    return {"ok": False, "stopped": True}


def use_data_folder(work: Path, log) -> dict:
    folder, where = find_data_folder_with_source()
    if not folder:
        log("No DamIT data folder is set.")
        log("Set DAMIT_DATA, or damit/data_folder in ~/.damit/config.json, to the folder the DamIT plugins share.")
        log("Or choose Download DEM and streams for this area (USGS 3DEP and NHD, United States only).")
        return {"ok": False, "stopped": True}
    log(f"DamIT data folder ({where}): {folder}")
    dem = data_dem(folder)
    if dem:
        log(f"Data folder DEM: {dem}")
    else:
        log("No DEM mosaic in the data folder's dem folder. A tile cache is not used as the one DEM.")
    settings = write_settings(work, folder, dem)
    log(f"Wrote {settings} so a headless chain can see the data folder.")
    return {"ok": True, "stopped": False, "dem": dem or "", "dataFolder": folder}
