"""GDAL / OGR input and output for the DamIT flood models.

Every read happens with GDAL_PAM_ENABLED=NO (no .aux.xml is ever written beside a source raster) and every write
goes to a new file in a folder the caller owns. The model grid is metric: the DEM's own CRS when it is projected
in metres, else NAD83 / UTM for the dam's longitude."""
import contextlib
import json
import math
import os

import numpy as np

from .geom import Grid, NODATA


def _gdal():
    from osgeo import gdal, ogr, osr      # GDAL ships with QGIS
    gdal.UseExceptions()
    return gdal, ogr, osr


@contextlib.contextmanager
def pam_off():
    gdal, _, _ = _gdal()
    old = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
    try:
        yield
    finally:
        gdal.SetConfigOption("GDAL_PAM_ENABLED", old)


def srs_from(text):
    _, _, osr = _gdal()
    s = osr.SpatialReference()
    s.SetFromUserInput(str(text))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def utm_wkt(lon, lat):
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    epsg = (26900 + zone) if lat >= 0 else (32700 + zone)       # NAD83 / UTM north; WGS 84 south
    return srs_from("EPSG:{}".format(epsg)).ExportToWkt()


def dem_info(path):
    """{'wkt', 'bounds', 'cell', 'metric', 'z_unit', 'size'} of a DEM, read with PAM off."""
    gdal, _, osr = _gdal()
    with pam_off():
        ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        if ds is None:
            raise IOError("cannot open the DEM {}".format(path))
        gt = ds.GetGeoTransform()
        wkt = ds.GetProjection()
        band = ds.GetRasterBand(1)
        unit = (band.GetUnitType() or "").strip().lower()
        vert = ""
        if not unit:
            from ..core import dem_zunit as ZU
            vert = ZU.vertical_unit(ds) or ""
        nx, ny = ds.RasterXSize, ds.RasterYSize
        ds = None
    s = srs_from(wkt) if wkt else None
    metric = bool(s is not None and s.IsProjected() and abs(s.GetLinearUnits() - 1.0) < 1e-9)
    xs = (gt[0], gt[0] + nx * gt[1])
    ys = (gt[3], gt[3] + ny * gt[5])
    return {"wkt": wkt, "bounds": (min(xs), min(ys), max(xs), max(ys)), "cell": abs(gt[1]), "metric": metric,
            "z_unit": unit, "z_vert": vert, "size": (nx, ny)}


def model_wkt(dem_path, lonlat):
    info = dem_info(dem_path)
    if info["metric"]:
        return info["wkt"]
    return utm_wkt(*lonlat)


class DemZError(ValueError):
    """The DEM records no elevation unit that can be trusted. Reading it as metres publishes a depth of 0."""


def z_scale(info, z_units="auto"):
    """Metres per DEM elevation unit.

    z_units 'm' / 'ft' / 'us_ft' (and the other names dem_zunit.unit_choice accepts), or 'auto'
    from the band unit, else a compound CRS vertical unit. Auto with nothing recorded raises
    DemZError. A blank band unit is not metres: that is what zeroed a feet DEM (ground 1600
    read as 1600 m, pool at the top of dam in real metres, depth clipped to 0).
    """
    from ..core import dem_zunit as ZU
    u = (z_units or "auto").strip().lower()
    if u != "auto":
        choice = ZU.US_FEET if u == "us_feet" else ZU.unit_choice(u)
        if not choice:
            raise DemZError("Z_UNITS {!r} is not metres, feet, or US survey feet".format(z_units))
        return ZU.TO_M[choice]
    raw = (info.get("z_unit") or "").strip()
    if raw:
        choice = ZU.unit_choice(raw)
        if not choice:
            raise DemZError("the DEM's band unit {!r} is not feet or metres. Set Z_UNITS to "
                            "m, ft, or us_ft.".format(raw))
        return ZU.TO_M[choice]
    choice = info.get("z_vert") or ""
    if choice in ZU.TO_M:
        return ZU.TO_M[choice]
    raise DemZError("no elevation unit is recorded on the DEM (no band unit, no vertical CRS). "
                    "Set Z_UNITS to m, ft, or us_ft. A blank unit is not read as metres.")


def transform_points(points, src, dst):
    _, _, osr = _gdal()
    ct = osr.CoordinateTransformation(srs_from(src), srs_from(dst))
    out = []
    for x, y in points:
        p = ct.TransformPoint(float(x), float(y))
        out.append((p[0], p[1]))
    return out


def extent_in(path, dst_wkt):
    """The DEM's extent in dst_wkt (from its corners and edge midpoints)."""
    info = dem_info(path)
    x0, y0, x1, y1 = info["bounds"]
    pts = [(x, y) for x in np.linspace(x0, x1, 5) for y in np.linspace(y0, y1, 5)]
    q = transform_points(pts, info["wkt"], dst_wkt) if info["wkt"] else pts
    xs = [p[0] for p in q]
    ys = [p[1] for p in q]
    return (min(xs), min(ys), max(xs), max(ys))


def read_window(path, bounds, cell, dst_wkt, z_units="auto", resample="bilinear"):
    """The DEM warped onto a north-up grid of `cell` m covering `bounds` (metres, dst_wkt); no-data is NaN; z in
    metres. Read with PAM off; nothing is written beside the source."""
    gdal, _, _ = _gdal()
    xmin, ymin, xmax, ymax = bounds
    nx = max(int(round((xmax - xmin) / cell)), 1)
    ny = max(int(round((ymax - ymin) / cell)), 1)
    xmax, ymin = xmin + nx * cell, ymax - ny * cell
    info = dem_info(path)
    with pam_off():
        src = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        out = gdal.Warp("", src, format="MEM", outputBounds=(xmin, ymin, xmax, ymax), width=nx, height=ny,
                        dstSRS=dst_wkt, resampleAlg=resample, dstNodata=NODATA, outputType=gdal.GDT_Float64,
                        multithread=False)
        a = out.GetRasterBand(1).ReadAsArray().astype(float)
        nod = out.GetRasterBand(1).GetNoDataValue()
        out = src = None
    bad = ~np.isfinite(a) | (a <= NODATA + 1)
    if nod is not None:
        bad |= a == nod
    a = np.where(bad, np.nan, a * z_scale(info, z_units))
    return Grid(a, xmin, ymax, cell)


def write_tif(path, grid_or_array, wkt, ref=None, nodata=NODATA):
    """A float32 GeoTIFF (no-data -9999); `ref` gives the georeferencing when an array is passed."""
    gdal, _, _ = _gdal()
    g = grid_or_array if isinstance(grid_or_array, Grid) else ref.like(grid_or_array)
    a = np.where(np.isfinite(g.data), g.data, nodata).astype(np.float32)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".part.tif"
    with pam_off():
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(tmp, g.nx, g.ny, 1, gdal.GDT_Float32, options=["COMPRESS=DEFLATE", "TILED=YES"])
        ds.SetGeoTransform(g.gt())
        ds.SetProjection(wkt)
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(nodata)
        b.WriteArray(a)
        ds.FlushCache()
        ds = None
    os.replace(tmp, path)
    return path


def read_tif(path):
    """(Grid, wkt) of a GeoTIFF (north-up), no-data as NaN, read with PAM off."""
    gdal, _, _ = _gdal()
    with pam_off():
        ds = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        gt = ds.GetGeoTransform()
        b = ds.GetRasterBand(1)
        a = b.ReadAsArray().astype(float)
        nod = b.GetNoDataValue()
        wkt = ds.GetProjection()
        ds = None
    if nod is not None:
        a[a == nod] = np.nan
    return Grid(a, gt[0], gt[3], gt[1]), wkt


def polygonize(path, classes, ref, wkt, layer="flood", field="class", labels=None):
    """Polygons of an integer class grid (0 = none) written to a new GeoJSON (in the model CRS, the 'crs'
    member set). `labels` maps a class to a text attribute."""
    gdal, ogr, osr = _gdal()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    mem = gdal.GetDriverByName("MEM").Create("", ref.nx, ref.ny, 1, gdal.GDT_Int16)
    mem.SetGeoTransform(ref.gt())
    mem.SetProjection(wkt)
    band = mem.GetRasterBand(1)
    band.WriteArray(np.asarray(classes, dtype=np.int16))
    band.SetNoDataValue(0)
    tmp = path + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    drv = ogr.GetDriverByName("GeoJSON")
    ds = drv.CreateDataSource(tmp)
    s = srs_from(wkt)
    lyr = ds.CreateLayer(layer, srs=s, geom_type=ogr.wkbPolygon, options=["RFC7946=NO", "WRITE_NAME=NO"])
    lyr.CreateField(ogr.FieldDefn(field, ogr.OFTInteger))
    if labels:
        fd = ogr.FieldDefn("label", ogr.OFTString)
        lyr.CreateField(fd)
    gdal.Polygonize(band, band, lyr, 0, [], callback=None)
    if labels:
        lyr.ResetReading()
        for f in lyr:
            f.SetField("label", str(labels.get(f.GetField(field), "")))
            lyr.SetFeature(f)
    ds = None
    mem = None
    os.replace(tmp, path)
    return path


def read_geojson_coords(path, kind=None):
    """The coordinates of a GeoJSON file's first feature (lon/lat for EPSG:4326 files): a point -> (x, y), a line
    -> [(x, y), ...]; None when there is none."""
    try:
        with open(path, encoding="utf-8") as fh:
            gj = json.load(fh)
    except (OSError, ValueError):
        return None
    feats = gj.get("features") if gj.get("type") == "FeatureCollection" else [gj]
    for f in feats or []:
        g = (f or {}).get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        if not c:
            continue
        if t == "Point" and kind in (None, "point"):
            return (float(c[0]), float(c[1]))
        if t == "LineString" and kind in (None, "line"):
            return [(float(p[0]), float(p[1])) for p in c]
        if t == "MultiLineString" and kind in (None, "line"):
            from . import damfolder
            line, _note = damfolder.pick_dam_line([[p[:2] for p in part] for part in c], multi=True)
            if line:
                return line
    return None


def sample(grid, points_xy):
    """Grid values at (x, y) points (NaN outside)."""
    out = []
    for x, y in points_xy:
        r, c = grid.rc(x, y)
        out.append(float(grid.data[r, c]) if grid.inside(r, c) else float("nan"))
    return out
