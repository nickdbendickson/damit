"""damit_pmp:watershed - the watershed of a dam point from a DEM (your DEM, or a fresh USGS 3DEP one).

The delineation is damit_pmp/watershed.py (numpy D8 on the runner's depression-filled DEM). The basin polygon feeds
damit_pmp:gridbasin / basinpf (Atlas 14 basin statistics) and the model domains of the rain-on-grid tools."""
import json
import os
import tempfile

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureSink, QgsGeometry,
                       QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingOutputNumber, QgsProcessingParameterFeatureSink, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterNumber, QgsProcessingParameterPoint,
                       QgsProcessingParameterRasterDestination, QgsProcessingParameterRasterLayer, QgsProject, QgsWkbTypes)

from .. import _deps  # noqa: F401
from .. import demfetch, watershed as W
from damit_core.lib.qtcompat import make_fields

DOUBLE = QgsProcessingParameterNumber.Double if hasattr(QgsProcessingParameterNumber, "Double") \
    else QgsProcessingParameterNumber.Type.Double
EPSG5070 = QgsCoordinateReferenceSystem("EPSG:5070")
FOLDER = getattr(QgsProcessingParameterFile, "Folder", None) or QgsProcessingParameterFile.Behavior.Folder
MAX_WIDEN = 2            # a fetched DEM is widened this many times (x1.5 each) when the basin reaches its edge


def read_dem(path):
    """(Grid, gdal dataset's CRS wkt) of a projected north-up DEM in metres."""
    from osgeo import gdal
    import numpy as np
    from ..runner_shared.grid import Grid
    gdal.UseExceptions()
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    wkt = ds.GetProjection()
    if not wkt:
        raise QgsProcessingException("the DEM has no coordinate system")
    crs = QgsCoordinateReferenceSystem.fromWkt(wkt)
    if crs.isGeographic():
        raise QgsProcessingException("the DEM is in degrees: reproject it to a projected CRS in metres (e.g. UTM or "
                                     "EPSG:5070) first so cell areas are real")
    if abs(gt[2]) > 1e-9 or abs(gt[4]) > 1e-9 or abs(abs(gt[1]) - abs(gt[5])) > 1e-6 * abs(gt[1]):
        raise QgsProcessingException("the DEM must be north-up with square cells")
    band = ds.GetRasterBand(1)
    a = band.ReadAsArray().astype("float64")
    nd = band.GetNoDataValue()
    if nd is not None:
        a[a == nd] = np.nan
    a[~np.isfinite(a)] = np.nan
    to_m = crs.mapUnitsToMeters() if hasattr(crs, "mapUnitsToMeters") else 1.0
    return Grid(a, gt[0], gt[3], abs(gt[1]) * to_m, crs_wkt=wkt), wkt, crs


def write_mask_tif(path, mask, grid, wkt):
    from osgeo import gdal
    gdal.UseExceptions()
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.nx, grid.ny, 1, gdal.GDT_Byte, ["COMPRESS=DEFLATE"])
    ds.SetGeoTransform((grid.x0, grid.dx, 0.0, grid.y0, 0.0, -grid.dx))
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(0)
    b.WriteArray(mask.astype("uint8"))
    ds = None


class Watershed(QgsProcessingAlgorithm):
    def name(self):
        return "watershed"

    def displayName(self):  # noqa: N802
        return "Watershed of a dam point from a DEM"

    def group(self):
        return "Watershed"

    def groupId(self):  # noqa: N802
        return "watershed"

    def createInstance(self):  # noqa: N802
        return type(self)()

    def shortHelpString(self):  # noqa: N802
        return ("Delineates the watershed draining to a dam point: the DEM is depression-filled (the runner's own priority "
                "flood, so a flat reservoir surface drains to its spill point), D8 flow directions and flow accumulation "
                "are computed, the pour point is snapped to the nearest stream cell (accumulation within 5% of the "
                "largest) within the snap radius, and every cell whose flow path reaches it is the basin. Give a DEM in a "
                "projected CRS in metres, or leave it empty to fetch a USGS 3DEP DEM (EPSG:5070, 10 m by default) "
                "around the point; a fetched DEM is widened (x1.5, up to twice) when the basin reaches its edge. Writes "
                "the basin polygon (use it as the BASIN of damit_pmp:gridbasin / basinpf), the snapped pour point, a "
                "basin mask and a JSON with the area in sq mi / km2 (compared with the NID drainage area if you give it). "
                "D8 on a filled lidar DEM follows the DEM, not culverts, ditches or storm sewers: check the basin on a map "
                "before you rely on it. DamIT PMP computes no PMP; Atlas 14 stays the only precipitation source.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterPoint("POINT", "Dam point (NID location or crest point)"))
        self.addParameter(QgsProcessingParameterRasterLayer("DEM", "DEM (projected, metres; empty = fetch USGS 3DEP)",
                                                            optional=True))
        self.addParameter(QgsProcessingParameterNumber("FETCH_RADIUS_KM", "3DEP fetch: half-width of the square around the "
                                                       "point (km)", DOUBLE, defaultValue=11.0, minValue=1.0, maxValue=60.0))
        self.addParameter(QgsProcessingParameterNumber("FETCH_CELL_M", "3DEP fetch: cell size (m)", DOUBLE,
                                                       defaultValue=10.0, minValue=1.0, maxValue=100.0))
        self.addParameter(QgsProcessingParameterNumber("SNAP_M", "Snap the pour point to the nearest stream cell within (m)",
                                                       DOUBLE, defaultValue=150.0, minValue=0.0, maxValue=2000.0))
        self.addParameter(QgsProcessingParameterNumber("NID_AREA_SQMI", "NID drainage area to compare with (sq mi; 0 = none)",
                                                       DOUBLE, defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFile("WORK_DIR", "Folder for a fetched DEM (empty = next to the JSON)",
                                                     behavior=FOLDER, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT_BASIN", "Watershed polygon",
                                                            QgsProcessing.TypeVectorPolygon))
        self.addParameter(QgsProcessingParameterFeatureSink("OUTPUT_POUR", "Snapped pour point",
                                                            QgsProcessing.TypeVectorPoint, optional=True,
                                                            createByDefault=False))
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT_MASK", "Watershed mask (1 = in the basin)",
                                                                  optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Watershed summary (JSON)",
                                                                "JSON files (*.json)"))
        self.addOutput(QgsProcessingOutputNumber("AREA_SQMI", "Watershed area (sq mi)"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        json_path = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        work = self.parameterAsString(P, "WORK_DIR", context) or os.path.join(
            os.path.dirname(os.path.abspath(json_path)), "watershed_dem")
        snap = self.parameterAsDouble(P, "SNAP_M", context)
        nid = self.parameterAsDouble(P, "NID_AREA_SQMI", context) or None
        pt = self.parameterAsPoint(P, "POINT", context)
        pcrs = self.parameterAsPointCrs(P, "POINT", context)
        dem_layer = self.parameterAsRasterLayer(P, "DEM", context) if P.get("DEM") not in (None, "") else None
        fetched = None
        if dem_layer is not None:
            dem_path = dem_layer.source()
        else:
            to5070 = QgsCoordinateTransform(pcrs, EPSG5070, QgsProject.instance())
            p5 = to5070.transform(QgsPointXY(pt))
            radius = self.parameterAsDouble(P, "FETCH_RADIUS_KM", context) * 1000.0
            cell = self.parameterAsDouble(P, "FETCH_CELL_M", context)
        res = None
        for attempt in range(MAX_WIDEN + 1):
            if dem_layer is None:
                feedback.pushInfo("Fetching USGS 3DEP DEM: {:.1f} km half-width, {:g} m cells".format(radius / 1000.0, cell))
                try:
                    fetched = demfetch.fetch(p5.x(), p5.y(), radius, cell, os.path.join(work, "r{:.0f}".format(radius)),
                                             log=feedback.pushInfo)
                except demfetch.DemFetchError as e:
                    raise QgsProcessingException(str(e))
                dem_path = fetched["path"]
            grid, wkt, crs = read_dem(dem_path)
            pt_dem = QgsCoordinateTransform(pcrs, crs, QgsProject.instance()).transform(QgsPointXY(pt))
            feedback.pushInfo("Delineating on {} x {} cells of {:g} m ...".format(grid.nx, grid.ny, grid.dx))
            try:
                res = W.delineate(grid, pt_dem.x(), pt_dem.y(), snap_m=snap)
            except W.WatershedError as e:
                raise QgsProcessingException(str(e))
            if res["touches_edge"] and dem_layer is None and attempt < MAX_WIDEN:
                radius *= 1.5
                feedback.pushInfo("The basin reaches the DEM edge: widening the DEM.")
                continue
            break
        for line in W.describe(res, nid):
            feedback.pushInfo(line)
        wkt_poly = W.mask_to_polygon_wkt(res["mask"], grid)
        fields = make_fields([("name", "String"), ("area_sqmi", "Double"), ("area_km2", "Double"),
                              ("nid_sqmi", "Double"), ("cell_m", "Double")])
        sink, dest = self.parameterAsSink(P, "OUTPUT_BASIN", context, fields, QgsWkbTypes.MultiPolygon, crs)
        f = QgsFeature(fields)
        geom = QgsGeometry.fromWkt(wkt_poly)
        geom.convertToMultiType()
        f.setGeometry(geom)
        f.setAttributes(["watershed of {:.5f},{:.5f}".format(pt.x(), pt.y()), round(res["area_sqmi"], 3),
                         round(res["area_m2"] / 1e6, 3), nid or 0.0, grid.dx])
        sink.addFeature(f, QgsFeatureSink.FastInsert)
        out = {"OUTPUT_BASIN": dest, "OUTPUT_JSON": json_path, "AREA_SQMI": round(res["area_sqmi"], 3)}
        if P.get("OUTPUT_POUR"):
            ps, pd = self.parameterAsSink(P, "OUTPUT_POUR", context, make_fields([("acc_cells", "Double"),
                                                                                    ("snapped_m", "Double")]), QgsWkbTypes.Point, crs)
            g = QgsFeature(ps.fields() if hasattr(ps, "fields") else make_fields([("acc_cells", "Double"), ("snapped_m", "Double")]))
            g.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*res["pour_xy"])))
            g.setAttributes([res["acc_cells"], round(res["snapped_from_m"], 1)])
            ps.addFeature(g, QgsFeatureSink.FastInsert)
            out["OUTPUT_POUR"] = pd
        if P.get("OUTPUT_MASK"):
            mp = self.parameterAsOutputLayer(P, "OUTPUT_MASK", context)
            write_mask_tif(mp, res["mask"], grid, wkt)
            out["OUTPUT_MASK"] = mp
        doc = {"schema": "damit.pmp.watershed", "schema_version": 1,
               "method": "priority-flood fill (runner), D8 steepest descent, flow accumulation, pour point snapped to the "
                         "nearest stream cell (accumulation >= {:.0%} of the window maximum) within {:g} m, upstream trace"
                         .format(W.SNAP_FRACTION, snap),
               "point": {"x": pt.x(), "y": pt.y(), "crs": pcrs.authid()},
               "pour_point": {"x": res["pour_xy"][0], "y": res["pour_xy"][1], "crs": crs.authid(),
                              "snapped_m": round(res["snapped_from_m"], 1), "acc_cells": res["acc_cells"]},
               "dem": {"path": dem_path, "cell_m": grid.dx, "cells": [grid.nx, grid.ny], "crs": crs.authid(),
                       "source": (fetched or {}).get("source") or "user DEM",
                       "citation": (fetched or {}).get("citation"), "fetched_extent": (fetched or {}).get("extent")},
               "area": {"sqmi": round(res["area_sqmi"], 3), "km2": round(res["area_m2"] / 1e6, 3),
                        "cells": int(res["mask"].sum())},
               "nid_area_sqmi": nid, "ratio_to_nid": round(res["area_sqmi"] / nid, 3) if nid else None,
               "touches_dem_edge": res["touches_edge"],
               "note": "D8 follows the DEM surface: culverts, ditches and storm sewers are not in it."}
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        return out


ALGORITHMS = [Watershed]
