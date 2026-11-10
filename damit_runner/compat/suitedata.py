"""Data-folder helpers — replaces damsuite.suitedata for DamIT Runner.

The DWR version manages the ND offline pack, QGIS settings, and the full
hierarchy under the suite data folder.  DamIT Runner only needs:

* ``TERRAIN`` — the subfolder constant (``"terrain"``).
* ``DEM`` — the subfolder constant (``"dem"``).
* ``local_dem(folder)`` — find the user's own DEM in <folder>/dem/.
"""
import os

TERRAIN = "terrain"
NLCD = "nlcd"
DEM = "dem"
RASTER_EXT = (".tif", ".tiff", ".vrt", ".img", ".gpkg")
TILE_CACHES = ("lidar_1m",)


def rasters(folder, sub):
    """Raster paths under <folder>/<sub>/ (excluding tile-cache folders)."""
    d = os.path.join(folder, sub)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.lower().startswith(".") or name in TILE_CACHES:
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in RASTER_EXT:
            out.append(p)
    return out


def local_dem(folder=None):
    """The user's own DEM in dem/: a .vrt first (a mosaic), else the only raster, else ``""``."""
    if folder is None:
        return ""
    files = rasters(folder, DEM)
    vrts = [p for p in files if p.lower().endswith(".vrt")]
    if vrts:
        return vrts[0]
    return files[0] if len(files) == 1 else ""
