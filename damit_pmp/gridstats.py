"""Basin statistics of a local NOAA Atlas 14 GIS grid (GDAL + numpy).

The PFDS GIS data page publishes Atlas 14 grids (ASCII grid / GeoTIFF) per volume, frequency and
duration, with values in thousandths of an inch (scale 0.001). The user downloads the grid once;
this module reads it, masks it with the basin, and returns mean / min / max in inches.
"""
import os
import re

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

# e.g. mw100yr24ha.asc, orb_100yr24ha.tif, sw1000yr60da_ams.asc
_NAME = re.compile(r"^(?P<region>[a-z]+)_?(?P<freq>\d+)yr(?P<dur>\d+)(?P<unit>[mhd])a(?P<ams>_ams)?", re.I)


def parse_name(path):
    m = _NAME.match(os.path.basename(path))
    if not m:
        return {}
    unit = {"m": "min", "h": "hr", "d": "day"}[m.group("unit").lower()]
    return {"region_code": m.group("region").lower(), "frequency_years": int(m.group("freq")),
            "duration": "{}-{}".format(int(m.group("dur")), unit), "series": "ams" if m.group("ams") else "pds"}


def basin_stats(raster_path, basin_wkt, basin_epsg_wkt, scale=0.001):
    ds = gdal.Open(raster_path)
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    srs = osr.SpatialReference()
    if ds.GetProjection():
        srs.ImportFromWkt(ds.GetProjection())
    else:
        srs.ImportFromEPSG(4326)                                 # PFDS ASCII grids are geographic (NAD83)
    bsrs = osr.SpatialReference()
    bsrs.ImportFromWkt(basin_epsg_wkt)
    for s in (srs, bsrs):
        try:
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except AttributeError:                                   # pragma: no cover - GDAL < 3
            pass
    geom = ogr.CreateGeometryFromWkt(basin_wkt)
    if not srs.IsSame(bsrs):
        geom.Transform(osr.CoordinateTransformation(bsrs, srs))
    gt = ds.GetGeoTransform()
    minx, maxx, miny, maxy = geom.GetEnvelope()
    c0 = max(int((minx - gt[0]) / gt[1]), 0)
    c1 = min(int((maxx - gt[0]) / gt[1]) + 1, ds.RasterXSize)
    r0 = max(int((maxy - gt[3]) / gt[5]), 0)
    r1 = min(int((miny - gt[3]) / gt[5]) + 1, ds.RasterYSize)
    if c1 <= c0 or r1 <= r0:
        raise ValueError("the basin is outside the Atlas 14 grid {}".format(os.path.basename(raster_path)))
    w, h = c1 - c0, r1 - r0
    mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((gt[0] + c0 * gt[1], gt[1], 0, gt[3] + r0 * gt[5], 0, gt[5]))
    mem.SetProjection(srs.ExportToWkt())
    vds = ogr.GetDriverByName("Memory").CreateDataSource("")
    lyr = vds.CreateLayer("b", srs, ogr.wkbUnknown)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(geom)
    lyr.CreateFeature(f)
    gdal.RasterizeLayer(mem, [1], lyr, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    mask = mem.GetRasterBand(1).ReadAsArray() == 1
    a = band.ReadAsArray(c0, r0, w, h).astype("float64")
    valid = mask & np.isfinite(a)
    if nodata is not None:
        valid &= a != nodata
    valid &= a >= 0
    if not valid.any():
        raise ValueError("no Atlas 14 grid cells with values inside the basin (outside Atlas 14 coverage?)")
    v = a[valid] * scale
    return {"cells": int(valid.sum()), "mean": round(float(v.mean()), 4), "min": round(float(v.min()), 4),
            "max": round(float(v.max()), 4)}
