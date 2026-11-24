"""Real downstream receptors for damit:classify: structures, roads and rail lines on the ground, not the desk's
schematic seeds.

The desk's own receptors (classify-receptors.ts) are what a user typed or mapped, plus seeds the desk places along its
straight schematic valley. Those are fine for the desk's ND / TM-11 screen, but damit:classify samples a real model
depth raster, and a seed placed on a schematic valley is not where the house or road is. Without rail lines M9a is
not scored at all, so a dam whose class is set by a freight line (Absaraka, ND00199: BNSF, ND High) came out Low.

This module finds the same layers DamIT Data keeps offline (damit_data core/sources.py), for the area of the depth
raster:

    STRUCTURES  USACE National Structure Inventory (NSI) points
    ROADS       FHWA HPMS roads (AADT, functional class)
    RAIL        FRA / BTS North American Rail Network lines (owner, subdivision; no trains per day)

Order, per layer:
  1. the DamIT data folder (DAMIT_DATA or ~/.damit/config.json), <data>/<STATE>/<source folder>/<file>.geojson,
     clipped to the area here (no GDAL needed);
  2. the same public services online, one bounding-box query each (paged), unless DAMIT_OFFLINE=1.

A layer that neither gives is reported as NOT CHECKED, and the classification is marked incomplete: the desk then
does not lead with that class as if it were complete. E911 address points are read by damit:classify itself from a
configured offline pack (ADDRESS_POINTS); the desk does not fetch them here.

Nothing here starts QGIS. The area comes from the depth raster's own GeoTIFF tags (EPSG:4326 / 4269, 5070 CONUS
Albers, UTM north on NAD83 or WGS84, 3857), else from the dam point and the desk's reach."""

from __future__ import annotations

import json
import math
import os
import struct
import threading
import urllib.parse
import urllib.request
from pathlib import Path

#: The layers a complete consequence screen needs; FACILITIES / LIFELINES / ENVIRONMENT have no national source here.
CORE_LAYERS = ("STRUCTURES", "ROADS", "RAIL")

NSI_API = "https://nsi.sec.usace.army.mil/nsiapi/structures"
HPMS_FEATURE_SERVER = "https://geo.dot.gov/server/rest/services/Hosted/{state_name}_2018_PR/FeatureServer/0"
#: FRA's service first (DamIT Data's source); BTS's copy of the same network (same fields) when FRA is down.
RAIL_FEATURE_SERVERS = (
    "https://fragis.fra.dot.gov/arcgis/rest/services/FRA/FRA_Rail_Network/FeatureServer/0",
    "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_North_American_Rail_Network_Lines/FeatureServer/0",
)
#: All fields: the service's names are lower case (aadt, f_system, through_lanes...), and asking for upper-case names
#: is an HTTP 500 there. damit:classify reads aadt / f_system case-insensitively.
HPMS_FIELDS = "*"
#: Local DamIT Data files per layer (damit_data SOURCES folder / layer file), in order of preference.
DATA_FILES = {
    "STRUCTURES": (("nsi", "nsi.geojson"),),
    "ROADS": (("hpms", "hpms.geojson"),),
    "RAIL": (("fra_rail", "fra_rail.geojson"),),
}
SOURCE_LABEL = {
    "STRUCTURES": "USACE NSI structures",
    "ROADS": "FHWA HPMS roads",
    "RAIL": "FRA / BTS rail lines",
}
#: Biggest local layer file clipped here (a statewide NSI GeoJSON is a few hundred MB at most).
MAX_LOCAL_BYTES = 600 * 1024 * 1024
MAX_FEATURES = 60000
PAGE = 2000
NSI_TILE_DEG = 0.5  # NSI answers one bbox up to 1 square degree; tiles keep each request well under it
TIMEOUT_S = 90

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "NewHampshire",
    "NJ": "NewJersey", "NM": "NewMexico", "NY": "NewYork", "NC": "NorthCarolina", "ND": "NorthDakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "RhodeIsland", "SC": "SouthCarolina",
    "SD": "SouthDakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "WestVirginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "PuertoRico",
}


class ReceptorFetchError(RuntimeError):
    pass


# ---- the depth raster's area ------------------------------------------------------------------------------------

_TYPES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_FMT = {1: "B", 2: "c", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii", 11: "f", 12: "d",
        16: "Q", 17: "q", 18: "Q"}


def geotiff_info(path) -> dict:
    """Width, height, the pixel-to-map transform and the EPSG code of a GeoTIFF (classic or BigTIFF), from its tags.
    Raises ValueError when the file is not a georeferenced TIFF."""
    with open(path, "rb") as fh:
        head = fh.read(16)
        if head[:2] == b"II":
            e = "<"
        elif head[:2] == b"MM":
            e = ">"
        else:
            raise ValueError("not a TIFF")
        magic = struct.unpack(e + "H", head[2:4])[0]
        big = magic == 43
        if magic not in (42, 43):
            raise ValueError("not a TIFF")
        off = struct.unpack(e + "Q", head[8:16])[0] if big else struct.unpack(e + "I", head[4:8])[0]
        fh.seek(off)
        count = struct.unpack(e + ("Q" if big else "H"), fh.read(8 if big else 2))[0]
        tags = {}
        entry = 20 if big else 12
        raw = fh.read(entry * count)
        for i in range(count):
            b = raw[i * entry:(i + 1) * entry]
            tag, typ = struct.unpack(e + "HH", b[:4])
            n = struct.unpack(e + ("Q" if big else "I"), b[4:12] if big else b[4:8])[0]
            size = _TYPES.get(typ, 1) * n
            inline = b[12:20] if big else b[8:12]
            if size <= len(inline):
                data = inline[:size]
            else:
                pos = struct.unpack(e + ("Q" if big else "I"), inline)[0]
                here = fh.tell()
                fh.seek(pos)
                data = fh.read(size)
                fh.seek(here)
            if typ in (2,):
                tags[tag] = data.rstrip(b"\0").decode("latin-1")
                continue
            fmt = _FMT.get(typ)
            if not fmt or typ in (5, 10):
                continue
            tags[tag] = list(struct.unpack(e + fmt * n, data[:struct.calcsize(fmt) * n]))
    width, height = (tags.get(256) or [0])[0], (tags.get(257) or [0])[0]
    if 34264 in tags:
        m = tags[34264]
        gt = (m[3], m[0], m[1], m[7], m[4], m[5])
    elif 33550 in tags and 33922 in tags:
        sx, sy = tags[33550][0], tags[33550][1]
        i, j, _, x, y, _ = tags[33922][:6]
        gt = (x - i * sx, sx, 0.0, y + j * sy, 0.0, -sy)
    else:
        raise ValueError("no georeferencing tags")
    keys = tags.get(34735) or []
    geo = {}
    for k in range(4, len(keys), 4):
        key_id, loc, _, val = keys[k:k + 4]
        if loc == 0:
            geo[key_id] = val
    epsg = geo.get(3072) or geo.get(2048)
    if geo.get(1024) == 2 and not geo.get(3072):  # geographic model
        epsg = geo.get(2048) or 4326
    return {"width": width, "height": height, "gt": gt, "epsg": epsg}


_A, _F = 6378137.0, 1 / 298.257222101  # GRS80 (NAD83); WGS84 differs by under a millimetre here


def _albers_inverse(x, y, lat0=23.0, lon0=-96.0, sp1=29.5, sp2=45.5, x0=0.0, y0=0.0):
    a, e2 = _A, 2 * _F - _F * _F
    e = math.sqrt(e2)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e2 * math.sin(phi) ** 2)

    def q(phi):
        s = math.sin(phi)
        return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))

    p0, p1, p2 = (math.radians(v) for v in (lat0, sp1, sp2))
    n = (m(p1) ** 2 - m(p2) ** 2) / (q(p2) - q(p1))
    c = m(p1) ** 2 + n * q(p1)
    rho0 = a * math.sqrt(c - n * q(p0)) / n
    x, y = x - x0, y - y0
    rho = math.hypot(x, rho0 - y)
    theta = math.atan2(x, rho0 - y)
    qq = (c - (rho * n / a) ** 2) / n
    phi = math.asin(max(-1.0, min(1.0, qq / 2)))
    for _ in range(25):
        s = math.sin(phi)
        d = ((1 - e2 * s * s) ** 2 / (2 * math.cos(phi))) * (
            qq / (1 - e2) - s / (1 - e2 * s * s) + (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))
        phi += d
        if abs(d) < 1e-12:
            break
    return lon0 + math.degrees(theta / n), math.degrees(phi)


def _utm_inverse(x, y, zone, south=False):
    a, e2, k0 = _A, 2 * _F - _F * _F, 0.9996
    ep2 = e2 / (1 - e2)
    x -= 500000.0
    if south:
        y -= 10000000.0
    mm = y / k0
    mu = mm / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32)
            * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * s * s)
    t1, c1 = t * t, ep2 * c * c
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * t / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
                                  + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1)
           * d ** 5 / 120) / c
    return (zone - 1) * 6 - 180 + 3 + math.degrees(lon), math.degrees(lat)


def to_lonlat(epsg, x, y):
    """(lon, lat) of a point in a CRS this module knows, else None."""
    if epsg in (4326, 4269, 4258, 4617, 4283):
        return x, y
    if epsg == 5070:
        return _albers_inverse(x, y)
    if epsg == 3857:
        return math.degrees(x / _A), math.degrees(2 * math.atan(math.exp(y / _A)) - math.pi / 2)
    if epsg and (26901 <= epsg <= 26923 or 32601 <= epsg <= 32660):
        return _utm_inverse(x, y, epsg % 100)
    if epsg and 32701 <= epsg <= 32760:
        return _utm_inverse(x, y, epsg % 100, south=True)
    return None


def raster_bbox(path) -> tuple[float, float, float, float] | None:
    """The raster's area as lon/lat (west, south, east, north), or None (not a GeoTIFF, or a CRS not known here)."""
    try:
        info = geotiff_info(path)
    except (OSError, ValueError, struct.error, IndexError):
        return None
    gt, w, h = info["gt"], info["width"], info["height"]
    if not w or not h:
        return None
    pts = []
    for fx in (0, 0.5, 1):
        for fy in (0, 0.5, 1):
            px, py = fx * w, fy * h
            x = gt[0] + px * gt[1] + py * gt[2]
            y = gt[3] + px * gt[4] + py * gt[5]
            ll = to_lonlat(info["epsg"], x, y)
            if ll is None:
                return None
            pts.append(ll)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    box = (min(xs), min(ys), max(xs), max(ys))
    if not all(math.isfinite(v) for v in box) or not (-180 <= box[0] < box[2] <= 180 and -90 <= box[1] < box[3] <= 90):
        return None
    return box


def dam_bbox(dam: dict, analysis: dict | None, min_km: float = 10.0) -> tuple[float, float, float, float] | None:
    """A box round the dam point, as far as the desk's reach (at least min_km): used when the raster gives no area."""
    lon, lat = dam.get("lon"), dam.get("lat")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return None
    reach = ((analysis or {}).get("flood") or {}).get("lengthM") if isinstance(analysis, dict) else None
    km = max(min_km, (reach or 0) / 1000.0 if isinstance(reach, (int, float)) else 0)
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.2, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


# ---- clipping -----------------------------------------------------------------------------------------------------

def _coords(geom):
    c = (geom or {}).get("coordinates")
    t = (geom or {}).get("type")
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        yield from c
    elif t in ("MultiLineString", "Polygon"):
        for part in c:
            yield from part
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


def touches(geom, bbox) -> bool:
    """True when any vertex of the geometry is inside bbox, or a line's vertices straddle it."""
    w, s, e, n = bbox
    xs, ys = [], []
    try:
        for p in _coords(geom):
            x, y = float(p[0]), float(p[1])
            if w <= x <= e and s <= y <= n:
                return True
            xs.append(x)
            ys.append(y)
    except (TypeError, ValueError, IndexError):
        return False
    if not xs:
        return False
    return min(xs) <= e and max(xs) >= w and min(ys) <= n and max(ys) >= s and (geom or {}).get("type") != "Point"


def _wgs84(fc: dict) -> bool:
    name = str((((fc or {}).get("crs") or {}).get("properties") or {}).get("name") or "")
    return not name or "4326" in name or "CRS84" in name


# ---- sources --------------------------------------------------------------------------------------------------------

def _get_json(url: str, opener=None, timeout: float = TIMEOUT_S):
    req = urllib.request.Request(url, headers={"User-Agent": "DamIT-Desk (receptors for damit:classify)"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
        body = resp.read()
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ReceptorFetchError("the service did not answer JSON (it may be down)") from None


def _arcgis(base: str, bbox, out_fields: str, opener=None, cancel=None) -> list[dict]:
    feats, offset = [], 0
    while True:
        if cancel is not None and cancel.is_set():
            raise ReceptorFetchError("cancelled")
        q = {
            "where": "1=1", "geometry": ",".join(f"{v:.6f}" for v in bbox), "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "outSR": "4326",
            "f": "geojson", "resultOffset": str(offset), "resultRecordCount": str(PAGE),
        }
        data = _get_json(f"{base}/query?{urllib.parse.urlencode(q)}", opener)
        if not isinstance(data, dict) or "error" in data or not isinstance(data.get("features"), list):
            why = (data.get("error") or {}).get("message") if isinstance(data, dict) and isinstance(data.get("error"), dict) else ""
            raise ReceptorFetchError(f"the service answered no features{': ' + why if why else ''}")
        page = data["features"]
        feats.extend(page)
        more = bool((data.get("properties") or {}).get("exceededTransferLimit") or data.get("exceededTransferLimit"))
        if not page or not more or len(feats) >= MAX_FEATURES:
            return feats
        offset += len(page)


def _nsi(bbox, opener=None, cancel=None) -> list[dict]:
    w, s, e, n = bbox
    nx = max(1, math.ceil((e - w) / NSI_TILE_DEG))
    ny = max(1, math.ceil((n - s) / NSI_TILE_DEG))
    if nx * ny > 36:
        raise ReceptorFetchError("the area is too large for the NSI per-area service (over 9 square degrees)")
    feats, seen = [], set()
    for i in range(nx):
        for j in range(ny):
            if cancel is not None and cancel.is_set():
                raise ReceptorFetchError("cancelled")
            x0 = w + (e - w) * i / nx
            x1 = w + (e - w) * (i + 1) / nx
            y0 = s + (n - s) * j / ny
            y1 = s + (n - s) * (j + 1) / ny
            ring = ",".join(f"{x:.6f},{y:.6f}" for x, y in ((x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)))
            data = _get_json(f"{NSI_API}?bbox={ring}&fmt=fc", opener)
            if not isinstance(data, dict) or not isinstance(data.get("features"), list):
                raise ReceptorFetchError("the NSI answered no features")
            for f in data["features"]:
                key = ((f.get("properties") or {}).get("fd_id"), json.dumps((f.get("geometry") or {}).get("coordinates")))
                if key in seen:
                    continue
                seen.add(key)
                feats.append(f)
    return feats


def _online(layer: str, bbox, state: str | None, opener=None, cancel=None) -> tuple[list[dict], str]:
    if layer == "STRUCTURES":
        return _nsi(bbox, opener, cancel), "USACE NSI (online)"
    if layer == "ROADS":
        name = STATE_NAMES.get((state or "").upper())
        if not name:
            raise ReceptorFetchError("HPMS roads are published per state; the dam has no state code")
        return _arcgis(HPMS_FEATURE_SERVER.format(state_name=name), bbox, HPMS_FIELDS, opener, cancel), "FHWA HPMS (online)"
    if layer == "RAIL":
        errors = []
        for base in RAIL_FEATURE_SERVERS:
            try:
                who = "FRA" if "fra.dot.gov" in base else "BTS NTAD"
                return _arcgis(base, bbox, "*", opener, cancel), f"{who} North American Rail Network (online)"
            except (OSError, ReceptorFetchError, ValueError) as exc:
                if "cancelled" in str(exc):
                    raise
                errors.append(f"{base.split('/')[2]}: {exc}")
        raise ReceptorFetchError("; ".join(errors))
    raise ReceptorFetchError(f"no source for {layer}")


def _local(layer: str, data_folder: str | None, state: str | None, bbox) -> tuple[list[dict], str] | None:
    if not data_folder:
        return None
    root = Path(data_folder)
    areas = [state.upper()] if state else []
    areas += [p.name for p in sorted(root.iterdir()) if p.is_dir() and p.name not in areas] if root.is_dir() else []
    for folder, fname in DATA_FILES.get(layer, ()):
        for area in areas:
            path = root / area / folder / fname
            if not path.is_file():
                continue
            if path.stat().st_size > MAX_LOCAL_BYTES:
                continue
            try:
                fc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(fc, dict) or not _wgs84(fc):
                continue
            feats = [f for f in fc.get("features") or [] if isinstance(f, dict) and touches(f.get("geometry"), bbox)]
            return feats[:MAX_FEATURES], f"DamIT data folder {path}"
    return None


def find_receptors(bbox, state: str | None, data_folder: str | None, log, offline: bool | None = None, opener=None,
                   cancel: threading.Event | None = None) -> dict:
    """Real receptor layers for bbox (lon/lat). Returns {"layers": {KEY: [features]}, "sources": {KEY: text},
    "missing": {KEY: why}}. A layer found with no feature in the area is found (the area has none), not missing."""
    if offline is None:
        offline = (os.environ.get("DAMIT_OFFLINE") or "").strip().lower() in ("1", "true", "yes")
    layers, sources, missing = {}, {}, {}
    for layer in CORE_LAYERS:
        if cancel is not None and cancel.is_set():
            missing[layer] = "cancelled"
            continue
        got = None
        try:
            got = _local(layer, data_folder, state, bbox)
        except OSError as exc:
            log(f"{SOURCE_LABEL[layer]}: the DamIT data folder could not be read ({exc}).")
        if got is None and not offline:
            try:
                got = _online(layer, bbox, state, opener, cancel)
            except (OSError, ReceptorFetchError, ValueError) as exc:
                missing[layer] = f"not in the DamIT data folder, and the online service failed: {exc}"
                continue
        if got is None:
            missing[layer] = ("not in the DamIT data folder, and online lookups are off (DAMIT_OFFLINE)"
                              if offline else "not in the DamIT data folder")
            continue
        feats, where = got
        layers[layer] = [f for f in feats if isinstance(f, dict) and isinstance(f.get("geometry"), dict)]
        sources[layer] = where
    return {"layers": layers, "sources": sources, "missing": missing}
