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
SS_API = BASE + "/streamstatsservices"
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
    try:
        data = _get(SS_API + "/stateservices.json", timeout=30)
        return sorted(s["code"].upper() for s in data if isinstance(s, dict) and s.get("code"))
    except Exception as e:
        LOG.warning("StreamStats: could not fetch supported states: %s", e)
        # Known supported states as of 2025
        return ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]


def delineate(lon, lat, state=None, crs=4326):
    """Delineate the watershed at a pour point.

    Returns the full StreamStats watershed response (dict) including the
    delineated polygon and workspace ID for subsequent calls. This can take
    30-120 seconds.

    Parameters
    ----------
    lon, lat : float
        Pour point in decimal degrees (WGS84).
    state : str, optional
        Two-letter state code. If None, StreamStats determines it.
    crs : int
        EPSG code of the coordinates (default 4326 = WGS84).
    """
    params = {
        "xlocation": str(lon),
        "ylocation": str(lat),
        "crs": str(crs),
        "includeparameters": "true",
        "includefeatures": "true",
        "simplify": "true",
    }
    if state:
        params["rcode"] = state.upper()
    url = SS_API + "/watershed.json?" + urllib.parse.urlencode(params)
    LOG.info("StreamStats delineation: %s, %s (state=%s)", lon, lat, state)
    t0 = time.time()
    result = _get(url, timeout=TIMEOUT)
    LOG.info("StreamStats delineation: %.0f s", time.time() - t0)
    return result


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
    """
    basin = delineate(lon, lat, state=state)
    flows = flood_frequency(basin, state=state)
    return {k: v for k, v in flows.items() if k != "_raw"}
