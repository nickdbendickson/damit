# Vendored from nickdbendickson/DWR_Plugins 591f48d (DamSafety Screening core/terrain.py: EXPORT_URL, tile_extents,
# fetch_3dep_tile, fetch_3dep; core/solve_gate.py TILE_PX), unchanged except where marked "DamIT:".
"""A fresh USGS 3DEP terrain clip for DamIT Screener's larger screening clips (larger_clips 1, the DamSafety
Screening default "USGS 3DEP service"): when the screening flood reaches the clip edge, the bigger clip is
downloaded from the 3DEP ImageServer (exportImage, EPSG:5070, float32 metres, bilinear) at the model cell, in tiles
of at most TILE_PX pixels, into a NEW folder under the dam folder (screen_inputs/terrain_3dep/r<radius>m/), mosaicked
as a VRT and read like any DEM. Nothing is written beside a source raster.

Network only (urllib); no process is started. Tests replace urlopen; no test downloads terrain."""
import math
import os
import time
import urllib.parse
import urllib.request

EXPORT_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
              "3DEPElevation/ImageServer/exportImage")
MAX_PX = 8000          # service maxImageWidth / maxImageHeight
TARGET_EPSG = 5070
SPLIT_MIN_PX = 1000    # a failed tile this large is asked for as four quarters
TILE_PX = 1200         # DamSafety Screening solve_gate.TILE_PX
SOURCE = "USGS 3DEP ImageServer (exportImage, EPSG:5070, m)"


class TerrainError(IOError):
    pass


def _quarters(extent):
    """Four boxes that cover extent. Callers already accept a list of tiles."""
    xmin, ymin, xmax, ymax = extent
    mx = (xmin + xmax) / 2.0
    my = (ymin + ymax) / 2.0
    return (
        (xmin, ymin, mx, my),
        (mx, ymin, xmax, my),
        (xmin, my, mx, ymax),
        (mx, my, xmax, ymax),
    )


def tile_extents(xmin, ymin, xmax, ymax, cell, max_px=None):
    """Split an extent into tiles no larger than max_px on a side (default TILE_PX)."""
    max_px = TILE_PX if max_px is None else max_px          # DamIT: TILE_PX here, not from solve_gate
    step = max_px * cell
    x = xmin
    while x < xmax:
        y = ymin
        while y < ymax:
            yield (x, y, min(x + step, xmax), min(y + step, ymax))
            y += step
        x += step


def fetch_3dep_tile(extent, cell, out_path, retries=3, timeout=120, opener=None, sleep=time.sleep):
    """Download one GeoTIFF tile (float32, metres) in EPSG:5070. DamIT: opener / sleep for the tests."""
    opener = opener or urllib.request.urlopen
    xmin, ymin, xmax, ymax = extent
    w = int(round((xmax - xmin) / cell))
    h = int(round((ymax - ymin) / cell))
    if w > MAX_PX or h > MAX_PX:
        raise ValueError("tile exceeds service limit")
    params = {
        "f": "image", "format": "tiff", "pixelType": "F32",
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": TARGET_EPSG, "imageSR": TARGET_EPSG,
        "size": f"{w},{h}", "interpolation": "RSP_BilinearInterpolation",
    }
    url = EXPORT_URL + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            with opener(url, timeout=timeout) as r:
                data = r.read()
            if data[:4] not in (b"II*\x00", b"MM\x00*"):
                raise IOError("response is not a TIFF: %r" % data[:120])
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
        except Exception as e:  # noqa: BLE001
            last = e
            sleep(2 * (attempt + 1))
    raise IOError(f"3DEP request failed: {last}")


def fetch_3dep(extent, cell, out_dir, stem, max_px=None, log=None, progress=None, opener=None, sleep=time.sleep,
               deadline=None):
    """Fetch all tiles for an extent; returns list of tile paths. DamIT: deadline (time.time()) stops it."""
    os.makedirs(out_dir, exist_ok=True)
    tiles = list(tile_extents(*extent, cell, max_px))
    paths = []
    for i, ext in enumerate(tiles):
        if deadline is not None and time.time() > deadline:
            raise TerrainError("the screening time limit was reached during the 3DEP download")
        if progress:
            progress(i, len(tiles))
        if log:
            log("3DEP tile {} of {} for {}".format(i + 1, len(tiles), stem))
        p = os.path.join(out_dir, f"{stem}_t{i}.tif")
        try:
            paths.append(fetch_3dep_tile(ext, cell, p, opener=opener, sleep=sleep))
        except IOError as err:
            w = int(round((ext[2] - ext[0]) / cell))
            h = int(round((ext[3] - ext[1]) / cell))
            if max(w, h) < SPLIT_MIN_PX:
                raise
            if log:
                log("3DEP tile {} failed ({}); requesting four quarters".format(i + 1, err))
            for q, qext in enumerate(_quarters(ext)):
                qp = os.path.join(out_dir, "{}_t{}q{}.tif".format(stem, i, q))
                paths.append(fetch_3dep_tile(qext, cell, qp, opener=opener, sleep=sleep))
    return paths


# ---------------------------------------------------------------------------------------------- DamIT: a clip --
def extent_5070(bounds, wkt, pad_m):
    """The model-CRS bounds as an EPSG:5070 box (corners and edge points), padded and snapped outward."""
    import numpy as np
    from . import rasters as R
    x0, y0, x1, y1 = bounds
    pts = [(x, y) for x in np.linspace(x0, x1, 5) for y in np.linspace(y0, y1, 5)]
    q = R.transform_points(pts, wkt, "EPSG:{}".format(TARGET_EPSG))
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    return (math.floor(min(xs) - pad_m), math.floor(min(ys) - pad_m), math.ceil(max(xs) + pad_m),
            math.ceil(max(ys) + pad_m))


def fetch_clip(bounds, wkt, cell, folder, radius_m, log=None, opener=None, sleep=time.sleep, deadline=None):
    """Download the 3DEP terrain covering `bounds` (model CRS `wkt`) at `cell` m into a new folder
    <folder>/terrain_3dep/r<radius>m/ and return {'path' (VRT), 'z_units' 'm', 'source', 'tiles', 'folder'}."""
    from . import rasters as R
    gdal, _, _ = R._gdal()
    out = os.path.join(folder, "terrain_3dep", "r{:.0f}m".format(radius_m))
    n = 0
    while os.path.exists(out):                                  # never into an existing folder
        n += 1
        out = os.path.join(folder, "terrain_3dep", "r{:.0f}m_{}".format(radius_m, n))
    os.makedirs(out)
    ext = extent_5070(bounds, wkt, 2.0 * cell)
    tiles = fetch_3dep(ext, cell, out, "3dep", log=log, opener=opener, sleep=sleep, deadline=deadline)
    vrt = os.path.join(out, "3dep.vrt")
    with R.pam_off():
        ds = gdal.BuildVRT(vrt, tiles)
        if ds is None:
            raise TerrainError("could not mosaic the 3DEP tiles in {}".format(out))
        ds = None
    return {"path": vrt, "z_units": "m", "source": SOURCE, "tiles": len(tiles), "folder": out}
