"""A fresh USGS 3DEP DEM around a point for damit_pmp:watershed (network only; no process is started).

Uses the runner's own 3DEP client (``runner_shared/terrain3dep.py``, copied verbatim): the 3DEP ImageServer
exportImage service, EPSG:5070, float32 metres, bilinear, in tiles. Tests replace ``OPENER``; no test downloads terrain."""
import os
import time

from .runner_shared import terrain3dep as T

OPENER = None            # tests set a fake urlopen(url, timeout=) context manager
SOURCE = T.SOURCE
CITATION = "U.S. Geological Survey 3D Elevation Program (3DEP), https://www.usgs.gov/3d-elevation-program"
MAX_PIXELS = 36_000_000  # about 140 MB of float32: refuse a request that would fill the disk or the memory


class DemFetchError(IOError):
    pass


def fetch(x5070, y5070, radius_m, cell_m, folder, log=None):
    """Download a square of half-width ``radius_m`` around an EPSG:5070 point at ``cell_m`` into ``folder`` and mosaic it
    to ``<folder>/dem_3dep_<cell>m_5070.tif``. 
    Returns {'path', 'extent', 'tiles', 'source', 'cell_m'}."""
    from osgeo import gdal
    gdal.UseExceptions()
    ext = (x5070 - radius_m, y5070 - radius_m, x5070 + radius_m, y5070 + radius_m)
    ext = tuple(round(v / cell_m) * cell_m for v in ext)
    px = (ext[2] - ext[0]) / cell_m * ((ext[3] - ext[1]) / cell_m)
    if px > MAX_PIXELS:
        raise DemFetchError("a {:.0f} km square at {:g} m is {:.0f} million cells: use a larger cell or a smaller radius".format(
            2 * radius_m / 1000.0, cell_m, px / 1e6))
    os.makedirs(folder, exist_ok=True)
    tiles_dir = os.path.join(folder, "tiles")
    try:
        tiles = T.fetch_3dep(ext, cell_m, tiles_dir, "t", log=log, opener=OPENER, sleep=(lambda s_: None) if OPENER else time.sleep)
    except (IOError, OSError, ValueError) as err:
        raise DemFetchError("the USGS 3DEP DEM request failed ({}): check the network, or give a DEM file".format(err))
    out = os.path.join(folder, "dem_3dep_{:g}m_5070.tif".format(cell_m))
    vrt = os.path.join(tiles_dir, "mosaic.vrt")
    ds = gdal.BuildVRT(vrt, tiles)
    if ds is None:
        raise DemFetchError("could not mosaic the 3DEP tiles")
    ds = None
    gdal.Translate(out, vrt, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    for p in tiles + [vrt]:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(tiles_dir)
    except OSError:
        pass
    return {"path": out, "extent": ext, "tiles": len(tiles), "source": SOURCE, "cell_m": cell_m, "citation": CITATION}
