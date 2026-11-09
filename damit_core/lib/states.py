"""US states, DC and Puerto Rico: postal code, name, FIPS, WGS84 bounding box and the names the
public downloads use (data/states.json; boxes from the Census cartographic boundary file)."""
import json

from . import data_path

_CACHE = None


def table():
    global _CACHE
    if _CACHE is None:
        with open(data_path("states.json"), encoding="utf-8") as fh:
            _CACHE = json.load(fh)["states"]
    return _CACHE


def postal_codes():
    return [s["postal"] for s in table()]


def get(code):
    """State record by postal code, name or 2-digit FIPS (case-insensitive). Raises KeyError."""
    c = str(code or "").strip()
    for s in table():
        if c.upper() == s["postal"] or c.lower() == s["name"].lower() or c.zfill(2) == s["fips"]:
            return dict(s)
    raise KeyError("unknown US state or territory {!r}; use a postal code such as ND or NE".format(code))


def bbox_intersects(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def states_for_bbox(bbox):
    """Postal codes whose box meets a WGS84 (xmin, ymin, xmax, ymax) box."""
    return [s["postal"] for s in table() if bbox_intersects(s["bbox_wgs84"], bbox)]


def state_for_point(lon, lat):
    """Postal codes whose box holds the point (boxes overlap near borders; may be several)."""
    return [s["postal"] for s in table()
            if s["bbox_wgs84"][0] <= lon <= s["bbox_wgs84"][2] and s["bbox_wgs84"][1] <= lat <= s["bbox_wgs84"][3]]
