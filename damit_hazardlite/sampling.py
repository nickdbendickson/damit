"""Raster sampling for DamIT Hazard Lite (GDAL + QGIS geometry; window reads, one receptor at a
time, so a large raster is never read whole)."""
import math

from osgeo import gdal
from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject, QgsRectangle, QgsUnitTypes,
                       QgsWkbTypes)

gdal.UseExceptions()


class SamplingError(ValueError):
    pass


class Raster(object):
    def __init__(self, path, scale=1.0):
        try:
            self.ds = gdal.Open(path)
        except RuntimeError as e:
            raise SamplingError("cannot open raster {}: {}".format(path, e))
        self.band = self.ds.GetRasterBand(1)
        self.nodata = self.band.GetNoDataValue()
        gt = self.ds.GetGeoTransform()
        if gt[2] or gt[4]:
            raise SamplingError("rotated rasters are not supported: {}".format(path))
        self.x0, self.dx, self.y0, self.dy = gt[0], gt[1], gt[3], gt[5]
        self.nx, self.ny = self.ds.RasterXSize, self.ds.RasterYSize
        self.scale = scale
        self.extent = QgsRectangle(self.x0, self.y0 + self.dy * self.ny, self.x0 + self.dx * self.nx, self.y0)

    def same_grid(self, other):
        return (self.nx, self.ny) == (other.nx, other.ny) and all(
            abs(a - b) < 1e-6 * max(1.0, abs(a)) for a, b in ((self.x0, other.x0), (self.y0, other.y0),
                                                            (self.dx, other.dx), (self.dy, other.dy)))

    def window(self, rect):
        """(col0, row0, ncols, nrows) of the cells meeting rect, clipped; None when outside."""
        c0 = int(math.floor((rect.xMinimum() - self.x0) / self.dx))
        c1 = int(math.floor((rect.xMaximum() - self.x0) / self.dx))
        r0 = int(math.floor((rect.yMaximum() - self.y0) / self.dy))
        r1 = int(math.floor((rect.yMinimum() - self.y0) / self.dy))
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, self.nx - 1), min(r1, self.ny - 1)
        if c1 < c0 or r1 < r0:
            return None
        return c0, r0, c1 - c0 + 1, r1 - r0 + 1

    def read(self, win):
        a = self.band.ReadAsArray(*win).astype("float64")
        if self.nodata is not None:
            a[a == self.nodata] = float("nan")
        return a * self.scale

    def centre(self, col, row):
        return self.x0 + (col + 0.5) * self.dx, self.y0 + (row + 0.5) * self.dy

    def cell_of(self, x, y):
        return int(math.floor((x - self.x0) / self.dx)), int(math.floor((y - self.y0) / self.dy))


def feet_to_map_units(crs):
    if crs.isGeographic():
        raise SamplingError("the depth raster is in a geographic CRS ({}); DamIT Hazard Lite needs a projected "
                            "CRS for its sampling distances.".format(crs.authid()))
    f = QgsUnitTypes.fromUnitToUnitFactor(
        QgsUnitTypes.DistanceFeet if hasattr(QgsUnitTypes, "DistanceFeet") else QgsUnitTypes.DistanceUnit.Feet,
        crs.mapUnits())
    return f


def transformer(src_crs, raster_crs):
    if src_crs == raster_crs:
        return None
    return QgsCoordinateTransform(src_crs, raster_crs, QgsProject.instance())


def sample(geom, depth, vel, ft, kind, prof, xform=None):
    """(depth list ft, velocity list ft/s or None, in_domain) for one receptor geometry.
    Polygons: every cell centre inside the outline grown by edge_ring_ft. Points: inside a disc of
    point_radius_ft. Lines: one cell every line_step_ft along the line."""
    g = QgsGeometry(geom)
    if xform is not None:
        g.transform(xform)
    if g.isEmpty():
        return [], None, False
    if not g.boundingBox().intersects(depth.extent):
        return [], None, False
    gtype = QgsWkbTypes.geometryType(g.wkbType())
    line = gtype == (QgsWkbTypes.LineGeometry if hasattr(QgsWkbTypes, "LineGeometry")
                     else QgsWkbTypes.GeometryType.LineGeometry) or kind in ("road", "rail")
    cells = []
    if line:
        step = max(prof["line_step_ft"] * ft, 1e-9)
        dens = g.densifyByDistance(step)
        seen = set()
        for v in dens.vertices():
            c = depth.cell_of(v.x(), v.y())
            if 0 <= c[0] < depth.nx and 0 <= c[1] < depth.ny and c not in seen:
                seen.add(c)
                cells.append(c)
    else:
        point = gtype == (QgsWkbTypes.PointGeometry if hasattr(QgsWkbTypes, "PointGeometry")
                          else QgsWkbTypes.GeometryType.PointGeometry)
        grown = g.buffer((prof["point_radius_ft"] if point else prof["edge_ring_ft"]) * ft, 8)
        win = depth.window(grown.boundingBox())
        if win is not None:
            eng = QgsGeometry.createGeometryEngine(grown.constGet())
            eng.prepareGeometry()
            for r in range(win[1], win[1] + win[3]):
                for c in range(win[0], win[0] + win[2]):
                    x, y = depth.centre(c, r)
                    if eng.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y)).constGet()):
                        cells.append((c, r))
        if not cells:
            p = g.centroid().asPoint()
            c = depth.cell_of(p.x(), p.y())
            if 0 <= c[0] < depth.nx and 0 <= c[1] < depth.ny:
                cells.append(c)
    if not cells:
        return [], None, False
    return _values(depth, cells), (_values(vel, cells) if vel is not None else None), True


def _values(r, cells):
    c0 = min(c for c, _ in cells)
    r0 = min(rr for _, rr in cells)
    c1 = max(c for c, _ in cells)
    r1 = max(rr for _, rr in cells)
    a = r.read((c0, r0, c1 - c0 + 1, r1 - r0 + 1))
    return [float(a[rr - r0, c - c0]) for c, rr in cells]
