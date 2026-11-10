"""Minimal services catalogue — replaces damsuite.services for DamIT Runner.

The DWR version carries the full catalogue of ND DWR data services and a
QGIS-bound ``http_get``.  DamIT Runner only needs:

* ``BUILTIN`` — the terrain/NLCD/structure services the engines discover.
* ``urllib_get`` — fetch a URL to bytes, through the system proxy.
* ``ServiceError`` — the exception that failed fetches raise.
"""
import re
import urllib.parse
import urllib.request

from . import netproxy

USER_AGENT = "DamIT-Runner/1.0"

_ARC = re.compile(r"/rest/services/(?P<path>.+?)/(?P<type>MapServer|FeatureServer|ImageServer)"
                  r"(?:/(?P<layer>\d+))?/?(?:\?.*)?$", re.I)


class ServiceError(Exception):
    """A service that cannot be reached or returned an unusable answer."""


def _s(sid, role, name, kind, url, **kw):
    d = {"id": sid, "role": role, "name": name, "kind": kind, "url": url}
    d.update(kw)
    return d


BUILTIN = [
    # --- terrain
    _s("usgs_3dep_image", "dem", "USGS 3DEP elevation (ImageServer)", "arcgis_image",
       "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer",
       notes="metres; exportImage in EPSG:5070"),
    _s("usgs_3dep_wcs", "dem", "USGS 3DEP elevation (WCS)", "wcs",
       "https://elevation.nationalmap.gov/arcgis/services/3DEPElevation/ImageServer/WCSServer",
       layer="DEP3Elevation"),
    # --- land cover
    _s("mrlc_nlcd2021_wcs", "nlcd", "NLCD 2021 land cover (MRLC WCS)", "wcs",
       "https://www.mrlc.gov/geoserver/mrlc_download/wcs",
       layer="mrlc_download__NLCD_2021_Land_Cover_L48", scale_axes=["i", "j"]),
    # --- structures (FEMA USA Structures)
    _s("fema_usa_structures", "structures", "FEMA USA Structures", "arcgis_feature",
       "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/USA_Structures_View/"
       "FeatureServer/0", fields=("OCC_CLS", "PRIM_OCC", "HEIGHT", "SQMETERS")),
]


def urllib_get(url, timeout=60):
    """Fetch *url* to bytes through the system proxy.  Only http(s)."""
    parts = urllib.parse.urlparse(url or "")
    if parts.scheme not in ("http", "https"):
        raise ServiceError("refusing {}: only http and https".format(parts.scheme or "no scheme"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with netproxy.urlopen(req, timeout=timeout) as r:
        return r.read()


# ------------------------------------------------------------------ addresses --

def split_arcgis(url):
    """(service url, layer id or None) of an ArcGIS REST address."""
    base = (url or "").split("?")[0].rstrip("/")
    m = _ARC.search(base)
    if not m:
        return base, None
    lay = m.group("layer")
    if lay is not None:
        base = base[: base.rfind("/")]
    return base, (int(lay) if lay is not None else None)


def export_image_url(service, box, size, sr=5070, pixel_type="F32", fmt="tiff"):
    """ArcGIS ImageServer /exportImage address for a box (in *sr*) and pixel size."""
    base, _lay = split_arcgis(service.get("url"))
    p = {"f": "image", "format": fmt, "pixelType": pixel_type,
         "bbox": "{},{},{},{}".format(*box), "bboxSR": sr, "imageSR": sr,
         "size": "{},{}".format(int(size[0]), int(size[1])),
         "interpolation": "RSP_BilinearInterpolation" if pixel_type == "F32" else
         "RSP_NearestNeighbor"}
    return base + "/exportImage?" + urllib.parse.urlencode(p)


def wcs_coverage_url(service, box, size, crs="EPSG:5070"):
    """WCS 2.0.1 GetCoverage address (GeoTIFF) for a box in *crs*."""
    url = service.get("url", "").split("?")[0]
    cov = service.get("layer") or ""
    if not cov:
        raise ServiceError("{}: choose a coverage first".format(service.get("name")))
    ax = tuple(service.get("scale_axes") or ("X", "Y"))
    q = [("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
         ("coverageId", cov), ("format", "image/tiff"),
         ("subset", "X({},{})".format(box[0], box[2])), ("subset", "Y({},{})".format(box[1], box[3])),
         ("subsettingCrs", "http://www.opengis.net/def/crs/EPSG/0/" + crs.split(":")[-1]),
         ("outputCrs", "http://www.opengis.net/def/crs/EPSG/0/" + crs.split(":")[-1]),
         ("scaleSize", "{}({}),{}({})".format(ax[0], int(size[0]), ax[1], int(size[1])))]
    return url + "?" + urllib.parse.urlencode(q)
