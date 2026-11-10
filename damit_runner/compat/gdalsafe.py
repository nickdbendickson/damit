"""Safe GDAL raster helpers: read a window, write a GeoTIFF, without leaving files locked.

A thin wrapper around osgeo.gdal that closes datasets promptly (Python's GC +
GDAL's refcounting can leave files locked on Windows otherwise). Not a full
GDAL abstraction — just the patterns the Runner's terrain and reservoir-carve
modules need.
"""
import contextlib
import logging
import os

import numpy as np

LOG = logging.getLogger(__name__)


def _gdal():
    from osgeo import gdal
    gdal.UseExceptions()
    return gdal


@contextlib.contextmanager
def open_raster(path, update=False):
    """Open a GDAL raster dataset, close it on exit."""
    gdal = _gdal()
    ds = gdal.Open(str(path), gdal.GA_Update if update else gdal.GA_ReadOnly)
    if ds is None:
        raise FileNotFoundError("GDAL could not open {!r}".format(path))
    try:
        yield ds
    finally:
        ds = None


def read_band(path, band=1):
    """Read one band as a numpy array + its geotransform and projection."""
    with open_raster(path) as ds:
        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        arr = ds.GetRasterBand(band).ReadAsArray()
        nodata = ds.GetRasterBand(band).GetNoDataValue()
    return arr, gt, proj, nodata


def write_geotiff(path, arr, gt, proj, nodata=None, dtype=None):
    """Write a numpy array as a single-band GeoTIFF."""
    gdal = _gdal()
    if dtype is None:
        dtype = {np.float32: gdal.GDT_Float32, np.float64: gdal.GDT_Float64,
                 np.int16: gdal.GDT_Int16, np.int32: gdal.GDT_Int32,
                 np.uint8: gdal.GDT_Byte}.get(arr.dtype.type, gdal.GDT_Float32)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), arr.shape[1], arr.shape[0], 1, dtype,
                    ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(float(nodata))
    b.WriteArray(arr)
    b.FlushCache()
    ds = None
    LOG.debug("wrote %s (%d×%d)", path, arr.shape[1], arr.shape[0])


def raster_bounds(path):
    """(xmin, ymin, xmax, ymax) in the raster's CRS."""
    with open_raster(path) as ds:
        gt = ds.GetGeoTransform()
        w, h = ds.RasterXSize, ds.RasterYSize
    x0 = gt[0]
    y0 = gt[3] + h * gt[5]  # gt[5] is negative
    x1 = gt[0] + w * gt[1]
    y1 = gt[3]
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def raster_cell_m(path):
    """Approximate cell size in metres (from the geotransform, not the CRS)."""
    with open_raster(path) as ds:
        gt = ds.GetGeoTransform()
    return abs(gt[1])
