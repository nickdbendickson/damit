"""Public data sources DamIT Data can keep offline, for any US state (or an extent for NSI).

Every source is national; the state or extent is the user's choice, never a default. Sources:

  nsi             USACE National Structure Inventory API: per county of the chosen state
                  (?fips=<5-digit county>), or one request for an extent (?bbox=...).
  microsoft       Microsoft US Building Footprints (legacy usbuildings-v2), one zip per state.
  osm             OpenStreetMap from Geofabrik: the state's free GeoPackage (zip).
  usa_structures  FEMA / ORNL USA Structures: a download link the user pastes (no stable public
                  per-state URL pattern is published), one zip.
"""
import hashlib

from damit_core.lib import states

NSI_API = "https://nsi.sec.usace.army.mil/nsiapi/structures"
MICROSOFT = "https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/{name}.geojson.zip"
GEOFABRIK = "https://download.geofabrik.de/{path}-latest-free.gpkg.zip"
NSI_MAX_EXTENT_DEG2 = 1.0          # one bbox request; larger areas: pick the state (per county)

SOURCES = {
    "nsi": {"name": "National Structure Inventory (USACE NSI API)", "folder": "nsi", "default": True,
            "scopes": ("state", "extent"), "layer_globs": ("nsi.geojson",),
            "citation": "USACE National Structure Inventory, https://www.hec.usace.army.mil/confluence/nsi"},
    "microsoft": {"name": "Microsoft US Building Footprints (usbuildings-v2)", "folder": "microsoft_footprints",
                  "default": True, "scopes": ("state",), "layer_globs": ("*.geojson",),
                  "citation": "Microsoft, US Building Footprints, ODbL, https://github.com/microsoft/USBuildingFootprints"},
    "osm": {"name": "OpenStreetMap (Geofabrik GeoPackage)", "folder": "osm", "default": True,
            "scopes": ("state",), "layer_globs": ("*.gpkg",),
            "citation": "OpenStreetMap contributors, ODbL; extract by Geofabrik GmbH, https://download.geofabrik.de"},
    "usa_structures": {"name": "USA Structures (FEMA / ORNL; paste the download link)", "folder": "usa_structures",
                       "default": False, "scopes": ("url",), "layer_globs": ("*.gdb", "*.shp", "*.gpkg"),
                       "citation": "FEMA / ORNL USA Structures, https://gis-fema.hub.arcgis.com/pages/usa-structures"},
}
ORDER = ("nsi", "microsoft", "osm", "usa_structures")


class SourceError(ValueError):
    pass


def extent_tag(bbox):
    key = ",".join("{:.4f}".format(v) for v in bbox)
    return "extent_" + hashlib.sha256(key.encode()).hexdigest()[:8]


def bbox_ring(bbox):
    x0, y0, x1, y1 = bbox
    pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    return ",".join("{:.6f},{:.6f}".format(x, y) for x, y in pts)


def plan(source_id, state=None, bbox=None, url=None):
    """What to fetch: {id, name, kind, urls, filename, area, folder, extract, version_mode, ...}.
    ``bbox`` is WGS84 (xmin, ymin, xmax, ymax). Raises SourceError when the source cannot serve
    the request (e.g. Microsoft footprints for an extent, a state with no published file)."""
    if source_id not in SOURCES:
        raise SourceError("unknown source {!r}; known: {}".format(source_id, ", ".join(ORDER)))
    s = SOURCES[source_id]
    st = states.get(state) if state else None
    if source_id == "nsi":
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            if x1 <= x0 or y1 <= y0:
                raise SourceError("NSI: the extent is empty.")
            if (x1 - x0) * (y1 - y0) > NSI_MAX_EXTENT_DEG2:
                raise SourceError("NSI: the extent is {:.2f} square degrees; the limit for one request is {:g}. "
                                  "Pick a smaller extent or the state (fetched county by county)."
                                  .format((x1 - x0) * (y1 - y0), NSI_MAX_EXTENT_DEG2))
            return _p(source_id, s, extent_tag(bbox), "nsi_api",
                      ["{}?bbox={}&fmt=fc".format(NSI_API, bbox_ring(bbox))], "nsi.geojson",
                      version_mode="content", extract=False, bbox=list(bbox))
        if st is None:
            raise SourceError("NSI: pick a state or an extent.")
        if not st.get("county_fips"):
            raise SourceError("NSI: no county list for {}.".format(st["name"]))
        return _p(source_id, s, st["postal"], "nsi_api",
                  ["{}?fips={}&fmt=fc".format(NSI_API, c) for c in st["county_fips"]], "nsi.geojson",
                  version_mode="content", extract=False, state=st["postal"])
    if source_id == "usa_structures":
        u = (url or "").strip()
        if not u.startswith("https://"):
            raise SourceError("USA Structures: paste the https download link of the zip from FEMA's USA "
                              "Structures page (no stable per-state link is published).")
        name = u.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "usa_structures.zip"
        area = st["postal"] if st else "custom"
        return _p(source_id, s, area, "file", [u], name, version_mode="headers",
                  extract=name.lower().endswith(".zip"))
    if bbox is not None and st is None:
        raise SourceError("{}: published per state only; pick the state (DamIT Data can list the states an "
                          "extent touches).".format(s["name"]))
    if st is None:
        raise SourceError("{}: pick a state.".format(s["name"]))
    if source_id == "microsoft":
        if not st.get("microsoft"):
            raise SourceError("Microsoft US Building Footprints publishes no file for {}.".format(st["name"]))
        u = MICROSOFT.format(name=st["microsoft"])
    else:
        u = GEOFABRIK.format(path=st["geofabrik"])
    return _p(source_id, s, st["postal"], "file", [u], u.rsplit("/", 1)[-1], version_mode="headers",
              extract=True, state=st["postal"])


def _p(sid, s, area, kind, urls, filename, **extra):
    d = {"id": sid, "name": s["name"], "kind": kind, "urls": urls, "filename": filename, "area": area,
         "folder": s["folder"], "layer_globs": list(s["layer_globs"]), "citation": s["citation"]}
    d.update(extra)
    return d
