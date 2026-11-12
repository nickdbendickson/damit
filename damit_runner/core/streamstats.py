"""USGS StreamStats API client for automated basin delineation and flood frequency.

StreamStats (https://streamstats.usgs.gov/) provides:
  - Basin delineation from a pour point (lat/lon)
  - Basin characteristics (area, slope, CN, precipitation)
  - Flood frequency estimates (Q2, Q10, Q25, Q50, Q100, Q500) for ungauged sites

The API is free, rate-limited, and does not require authentication. Basin
delineation can take 30-120 seconds. Not all states are supported — check
``supported_states()`` first.

Usage::

    from damit_runner.core import streamstats as SS
    # Delineate a basin at a dam's downstream face
    basin = SS.delineate(-96.79, 46.87, state="ND")
    # Get flood frequency estimates
    flows = SS.flood_frequency(basin)
    # flows = {"Q2": 150, "Q10": 450, "Q25": 650, ..., "area_sqmi": 12.3}
"""
import json
import logging
import time
import urllib.parse
import urllib.request

LOG = logging.getLogger(__name__)

BASE = "https://streamstats.usgs.gov"
SS_API = BASE + "/ss-delineate/v1"  # new API (legacy streamstatsservices decommissioned 2026-01-30)
TIMEOUT = 180  # basin delineation can be slow


def _get(url, timeout=TIMEOUT):
    """GET JSON from the StreamStats API."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "DamIT-Runner/0.2",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def supported_states():
    """List of state codes StreamStats supports (2-letter postal codes)."""
    # Legacy stateservices.json is decommissioned; return known list.
    return ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
            "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
            "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
            "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
            "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]


def delineate(lon, lat, state=None, crs=4326):
    """Delineate the watershed at a pour point using the SS-Delineate API.

    Returns a dict with 'featurecollection' (basin polygon) and 'parameters'.
    The legacy watershed.json endpoint was decommissioned 2026-01-30.

    Parameters
    ----------
    lon, lat : float
        Pour point in decimal degrees (WGS84).
    state : str
        Two-letter state code (required for the new API).
    crs : int
        EPSG code of the coordinates (default 4326 = WGS84).
    """
    if not state:
        raise ValueError("state is required for SS-Delineate")
    url = "{}/delineate/sshydro/{}?lat={}&lon={}".format(SS_API, state.upper(), lat, lon)
    LOG.info("SS-Delineate: %s, %s (state=%s)", lon, lat, state)
    t0 = time.time()
    raw = _get(url, timeout=TIMEOUT)
    LOG.info("SS-Delineate: %.0f s", time.time() - t0)
    # Normalize to the legacy response shape for callers.
    ws = raw.get("bcrequest", {}).get("wsresp", {})
    return {
        "workspaceID": ws.get("workspace_id", ""),
        "featurecollection": ws.get("featurecollection", []),
        "parameters": ws.get("parameters", []),
        "_raw": raw,
    }


def basin_characteristics(workspace_id, state):
    """Basin characteristics from a delineated watershed.

    Parameters
    ----------
    workspace_id : str
        From the delineation response: ``result["workspaceID"]``.
    state : str
        Two-letter state code.

    Returns dict with keys like ``DRNAREA`` (area), ``LC11IMP`` (impervious),
    ``PRECIP`` (mean annual precipitation), ``BSLDEM10M`` (basin slope), etc.
    """
    params = {"rcode": state.upper(), "workspaceID": workspace_id,
              "includeparameters": "true"}
    url = SS_API + "/parameters.json?" + urllib.parse.urlencode(params)
    data = _get(url, timeout=60)
    out = {}
    for p in data.get("parameters", []):
        code = p.get("code", "")
        val = p.get("value")
        if code and val is not None:
            out[code] = val
    return out


def flood_frequency(basin_result, state=None):
    """Flood frequency estimates from a delineated basin.

    Parameters
    ----------
    basin_result : dict
        The full response from ``delineate()``.
    state : str, optional
        Two-letter state code (extracted from basin_result if not given).

    Returns
    -------
    dict with keys Q2, Q5, Q10, Q25, Q50, Q100, Q200, Q500 (cfs),
    area_sqmi, and the raw response in ``_raw``.
    """
    ws = basin_result.get("workspaceID", "")
    if state is None:
        feats = (basin_result.get("featurecollection") or [{}])
        for fc in feats:
            for feat in fc.get("feature", {}).get("features", []):
                st = (feat.get("properties") or {}).get("STABBR")
                if st:
                    state = st
                    break
    if not state or not ws:
        raise ValueError("Cannot determine state or workspace from basin result")

    params = {"rcode": state.upper(), "workspaceID": ws,
              "includeflowtypes": "true"}
    url = SS_API + "/flowstatistics.json?" + urllib.parse.urlencode(params)
    data = _get(url, timeout=120)

    out = {"_raw": data, "area_sqmi": None}
    for group in data if isinstance(data, list) else [data]:
        for stat in group.get("RegressionRegions", []):
            for result in stat.get("Results", []):
                name = result.get("Name", "")
                val = result.get("Value")
                # Map "Peak Flood, 100-Year Recurrence Interval" → Q100
                for ri in (2, 5, 10, 25, 50, 100, 200, 500):
                    if str(ri) in name and "peak" in name.lower():
                        out["Q{}".format(ri)] = val
    # Basin area from parameters
    for p in basin_result.get("parameters", []):
        if isinstance(p, dict) and p.get("code") == "DRNAREA":
            out["area_sqmi"] = p.get("value")
    return out


def quick_estimate(lon, lat, state, return_intervals=(100, 500)):
    """One-call convenience: delineate + flood frequency.

    Returns {Q100: cfs, Q500: cfs, area_sqmi: float, ...} or raises on failure.
    Note: flood frequency uses the legacy endpoint which may be unavailable;
    use pmf_inflow for a volume-based estimate from Atlas 14 instead.
    """
    basin = delineate(lon, lat, state=state)
    flows = flood_frequency(basin, state=state)
    return {k: v for k, v in flows.items() if k != "_raw"}


def basin_area_sqmi(basin_result):
    """Approximate drainage area (sq mi) from a delineation result.

    Uses the bounding box of the watershed polygon. The true polygon area
    is smaller; this is a conservative overestimate for DEM sizing.
    """
    import math
    feats = basin_result.get("featurecollection") or []
    for fc in feats:
        for item in fc if isinstance(fc, list) else [fc]:
            if item.get("name") == "globalwatershed":
                geom = item.get("feature", {}).get("features", [{}])[0].get("geometry", {})
                coords = (geom.get("coordinates") or [[]])[0]
                if coords:
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    dlon = max(lons) - min(lons)
                    dlat = max(lats) - min(lats)
                    lat_mid = (max(lats) + min(lats)) / 2
                    return dlon * 69 * math.cos(math.radians(lat_mid)) * dlat * 69
    return None


def pmf_inflow(area_sqmi, depth_in, duration_hr=24.0, runoff_ratio=1.0):
    """PMF inflow volume and a triangular hydrograph from drainage area and depth.

    For PMF breach or spillway capacity checks. Does not replace a full
    hydrologic model; gives a volume and a simple peak for screening.

    Parameters
    ----------
    area_sqmi : float
        Drainage area in square miles.
    depth_in : float
        Storm depth in inches (e.g. Atlas 14 1000-yr or a PMP estimate).
    duration_hr : float
        Storm duration in hours (default 24).
    runoff_ratio : float
        Fraction of rainfall that becomes runoff (default 1.0 = no losses).

    Returns
    -------
    dict with volume_acft, peak_cfs, duration_hr, time_to_peak_hr.
    """
    # 1 inch over 1 sq mi = 53.33 acre-ft
    volume_acft = area_sqmi * depth_in * 53.33 * runoff_ratio
    # Triangular hydrograph: peak at duration/2, base = duration
    # Volume = 0.5 * peak * duration * 3600 (cfs-seconds) / 43560 (ac-ft)
    # peak_cfs = volume_acft * 43560 / (0.5 * duration_hr * 3600)
    peak_cfs = volume_acft * 43560 / (0.5 * duration_hr * 3600)
    return {
        "volume_acft": round(volume_acft, 1),
        "peak_cfs": round(peak_cfs, 0),
        "duration_hr": duration_hr,
        "time_to_peak_hr": duration_hr / 2,
        "area_sqmi": area_sqmi,
        "depth_in": depth_in,
        "runoff_ratio": runoff_ratio,
    }


def dem_covers_basin(dem_extent, basin_extent, buffer_m=1000):
    """Check if a DEM extent covers a basin extent (with buffer).

    Both extents are (lon_min, lat_min, lon_max, lat_max) in WGS84.
    Returns (covers: bool, message: str).
    """
    import math
    dem_lon0, dem_lat0, dem_lon1, dem_lat1 = dem_extent
    bas_lon0, bas_lat0, bas_lon1, bas_lat1 = basin_extent
    buf_deg = buffer_m / 111320
    need_lon0 = bas_lon0 - buf_deg
    need_lat0 = bas_lat0 - buf_deg
    need_lon1 = bas_lon1 + buf_deg
    need_lat1 = bas_lat1 + buf_deg
    covers = (dem_lon0 <= need_lon0 and dem_lat0 <= need_lat0 and
              dem_lon1 >= need_lon1 and dem_lat1 >= need_lat1)
    if covers:
        msg = "DEM covers the basin with {:.0f} m buffer".format(buffer_m)
    else:
        msg = ("DEM does not cover the basin. Need at least "
               "{:.4f},{:.4f},{:.4f},{:.4f}").format(need_lon0, need_lat0, need_lon1, need_lat1)
    return covers, msg
