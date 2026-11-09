"""DamIT PMP Processing tools: NOAA Atlas 14 only.

damit_pmp:pointpf     Atlas 14 estimates at a point (PFDS), table + JSON with source and citation
damit_pmp:basinpf     Atlas 14 estimates at sample points in a basin, mean or max, table + JSON
damit_pmp:hyetograph  Alternating-block design hyetograph from an Atlas 14 depth table
damit_pmp:gridbasin   Basin mean / min / max of a local Atlas 14 GIS grid
"""
import csv
import json
import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureSink,
                       QgsGeometry, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingOutputNumber, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterPoint, QgsProcessingParameterRasterLayer, QgsProject, QgsWkbTypes)

from .. import _deps  # noqa: F401
from .. import atlas14 as A
from damit_core.lib import http, settings
from damit_core.lib.qtcompat import make_fields

SERIES = ["pds", "ams"]
UNITS = ["english", "metric"]
DATA = ["depth", "intensity"]
COMBINE = ["mean", "max"]
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
FOLDER = getattr(QgsProcessingParameterFile, "Folder", None) or QgsProcessingParameterFile.Behavior.Folder
DOUBLE = QgsProcessingParameterNumber.Double if hasattr(QgsProcessingParameterNumber, "Double") \
    else QgsProcessingParameterNumber.Type.Double
INTEGER = QgsProcessingParameterNumber.Integer if hasattr(QgsProcessingParameterNumber, "Integer") \
    else QgsProcessingParameterNumber.Type.Integer
NOTE = ("Source: NOAA Atlas 14 only (NOAA/NWS Precipitation Frequency Data Server, https://hdsc.nws.noaa.gov/pfds/). "
        "Atlas 14 gives precipitation-frequency estimates up to the 1000-year ARI; it is not a PMP study, and DamIT PMP "
        "0.1.0 uses no other precipitation source. A location outside Atlas 14 coverage fails with a message.")


class _Base(QgsProcessingAlgorithm):
    http_client = None                    # tests set a fake client
    pause_s = 1.0

    def group(self):
        return "NOAA Atlas 14"

    def groupId(self):  # noqa: N802
        return "atlas14"

    def createInstance(self):  # noqa: N802
        return type(self)()

    def _pfds_params(self):
        self.addParameter(QgsProcessingParameterEnum("SERIES", "Series (pds = partial duration / ARI, ams = annual maximum / AEP)",
                                                     SERIES, defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum("UNITS", "Units", UNITS, defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum("DATA", "Estimate", DATA, defaultValue=0))
        self.addParameter(QgsProcessingParameterFile("CACHE_DIR", "PFDS answer cache folder (empty = DamIT pfds_cache "
                                                     "setting or next to the outputs)", behavior=FOLDER, optional=True))
        self.addParameter(QgsProcessingParameterBoolean("OFFLINE", "Offline (cached answers only)", defaultValue=False))

    def _pfds(self, P, context, out_path):
        cache = self.parameterAsString(P, "CACHE_DIR", context) or settings.get("pfds_cache") or \
            os.path.join(os.path.dirname(os.path.abspath(out_path)), "pfds_cache")
        return {"http": self.http_client or http.Client(), "cache_dir": cache,
                "data": DATA[self.parameterAsEnum(P, "DATA", context)],
                "units": UNITS[self.parameterAsEnum(P, "UNITS", context)],
                "series": SERIES[self.parameterAsEnum(P, "SERIES", context)],
                "offline": self.parameterAsBool(P, "OFFLINE", context)}


def _to_wgs84(pt, crs):
    if crs.isValid() and crs != WGS84:
        return QgsCoordinateTransform(crs, WGS84, QgsProject.instance()).transform(pt)
    return pt


def write_outputs(csv_path, json_path, pf, sources, extra=None):
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    rows = A.table_rows(pf)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        cols = ["duration", "minutes", "frequency_years", "series", "value", "lower90", "upper90", "units"]
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        fh.write("# {}\n".format(A.citation(pf)))
    doc = {"schema": "damit.pmp.atlas14", "schema_version": 1, "atlas14": pf, "sources": sources,
           "citation": A.citation(pf), "note": NOTE}
    doc.update(extra or {})
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    return doc


def _run_fetch(points, kw, pause_s, feedback):
    try:
        return A.fetch_many(points, kw["http"], kw["cache_dir"], pause_s=pause_s, data=kw["data"], units=kw["units"],
                            series=kw["series"], offline=kw["offline"])
    except A.Atlas14Error as e:
        raise QgsProcessingException(str(e))
    except IOError as e:
        raise QgsProcessingException("PFDS request failed: {}".format(e))


class PointPF(_Base):
    def name(self):
        return "pointpf"

    def displayName(self):  # noqa: N802
        return "Atlas 14 estimates at a point"

    def shortHelpString(self):  # noqa: N802
        return ("NOAA Atlas 14 precipitation-frequency estimates (19 durations, 5 min - 60 days; PDS 1 - 1000-year "
                "ARI or AMS 1/2 - 1/1000 AEP; 90% bounds) at one point, from PFDS. Writes a CSV table and a JSON "
                "file with the Atlas 14 volume, version, region and citation. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterPoint("POINT", "Point"))
        self._pfds_params()
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_CSV", "Table (CSV)", "CSV files (*.csv)"))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Estimates and source (JSON)", "JSON files (*.json)"))
        self.addOutput(QgsProcessingOutputString("VOLUME", "Atlas 14 volume and version"))
        self.addOutput(QgsProcessingOutputNumber("DEPTH_100YR_24HR", "100-year 24-hour estimate (PDS / AMS 1%)"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        pt = _to_wgs84(self.parameterAsPoint(P, "POINT", context), self.parameterAsPointCrs(P, "POINT", context))
        csv_path = self.parameterAsFileOutput(P, "OUTPUT_CSV", context)
        json_path = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        kw = self._pfds(P, context, json_path)
        (pf, src), = _run_fetch([(pt.y(), pt.x())], kw, self.pause_s, feedback)
        write_outputs(csv_path, json_path, pf, [src], {"location": {"lat": pt.y(), "lon": pt.x()}})
        feedback.pushInfo(A.citation(pf))
        v = pf["quantiles"][A.duration_index("24-hr")][A.freq_index(pf, 100)]
        return {"OUTPUT_CSV": csv_path, "OUTPUT_JSON": json_path,
                "VOLUME": "Volume {} Version {} ({})".format(pf["volume"], pf["version"], pf["region"]),
                "DEPTH_100YR_24HR": v}


def sample_points(geom_wgs84, max_points):
    """pointOnSurface plus up to max_points-1 grid points inside the basin (WGS84 geometry)."""
    pts = [geom_wgs84.pointOnSurface().asPoint()]
    if max_points <= 1:
        return pts
    bb = geom_wgs84.boundingBox()
    n = 2
    inside = []
    while n <= 12:
        inside = []
        for i in range(n):
            for j in range(n):
                p = QgsPointXY(bb.xMinimum() + (i + 0.5) * bb.width() / n, bb.yMinimum() + (j + 0.5) * bb.height() / n)
                if geom_wgs84.contains(p):
                    inside.append(p)
        if len(inside) >= max_points - 1:
            break
        n += 1
    if len(inside) > max_points - 1:
        step = len(inside) / float(max_points - 1)
        inside = [inside[int(k * step)] for k in range(max_points - 1)]
    return pts + inside


class BasinPF(_Base):
    def name(self):
        return "basinpf"

    def displayName(self):  # noqa: N802
        return "Atlas 14 estimates for a basin (sampled points)"

    def shortHelpString(self):  # noqa: N802
        return ("Queries PFDS at a point on the basin and up to MAX_POINTS - 1 evenly spread points inside it (one "
                "polite request per second, answers cached) and combines the Atlas 14 tables cell by cell (mean or "
                "max). Point estimates are not areally reduced: Atlas 14 publishes point values only. For a basin "
                "mean over the Atlas 14 grid use damit_pmp:gridbasin with a downloaded Atlas 14 grid. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFeatureSource("BASIN", "Basin (polygons; all features together)",
                                                              [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterNumber("MAX_POINTS", "Sample points (max)", INTEGER, defaultValue=9,
                                                       minValue=1, maxValue=50))
        self.addParameter(QgsProcessingParameterEnum("COMBINE", "Combine", COMBINE, defaultValue=0))
        self._pfds_params()
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_CSV", "Table (CSV)", "CSV files (*.csv)"))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Estimates and sources (JSON)", "JSON files (*.json)"))
        self.addParameter(QgsProcessingParameterFeatureSink("POINTS", "Sample points", QgsProcessing.TypeVectorPoint,
                                                            optional=True, createByDefault=True))
        self.addOutput(QgsProcessingOutputString("VOLUME", "Atlas 14 volume(s)"))
        self.addOutput(QgsProcessingOutputNumber("DEPTH_100YR_24HR", "100-year 24-hour estimate (combined)"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        src = self.parameterAsSource(P, "BASIN", context)
        geoms = [f.geometry() for f in src.getFeatures() if not f.geometry().isEmpty()]
        if not geoms:
            raise QgsProcessingException("The basin layer has no polygon.")
        g = QgsGeometry.unaryUnion(geoms)
        if src.sourceCrs().isValid() and src.sourceCrs() != WGS84:
            g.transform(QgsCoordinateTransform(src.sourceCrs(), WGS84, QgsProject.instance()))
        pts = sample_points(g, self.parameterAsInt(P, "MAX_POINTS", context))
        csv_path = self.parameterAsFileOutput(P, "OUTPUT_CSV", context)
        json_path = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        kw = self._pfds(P, context, json_path)
        feedback.pushInfo("{} PFDS point(s)".format(len(pts)))
        got = _run_fetch([(p.y(), p.x()) for p in pts], kw, self.pause_s, feedback)
        how = COMBINE[self.parameterAsEnum(P, "COMBINE", context)]
        try:
            pf = A.combine([x[0] for x in got], how)
        except A.Atlas14Error as e:
            raise QgsProcessingException(str(e))
        write_outputs(csv_path, json_path, pf, [x[1] for x in got],
                      {"basin": {"points": [{"lat": p.y(), "lon": p.x()} for p in pts], "combine": how,
                                 "areal_reduction": "none (Atlas 14 point estimates)"}})
        di, fi = A.duration_index("24-hr"), A.freq_index(pf, 100)
        out = {"OUTPUT_CSV": csv_path, "OUTPUT_JSON": json_path, "VOLUME": ", ".join(pf["volumes"]),
               "DEPTH_100YR_24HR": pf["quantiles"][di][fi]}
        sink, dest = self.parameterAsSink(P, "POINTS", context, make_fields(
            [("lat", "Double"), ("lon", "Double"), ("volume", "String"), ("d100_24h", "Double")]), QgsWkbTypes.Point, WGS84)
        if sink is not None:
            for p, (one, s) in zip(pts, got):
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPointXY(p))
                f.setAttributes([p.y(), p.x(), "{} v{}".format(one["volume"], one["version"]), one["quantiles"][di][fi]])
                sink.addFeature(f, QgsFeatureSink.FastInsert)
            out["POINTS"] = dest
        return out


STORM = [d for d, m in A.DURATIONS if 60 <= m <= 14400]       # 1 hour - 10 days


class Hyetograph(_Base):
    def name(self):
        return "hyetograph"

    def displayName(self):  # noqa: N802
        return "Design hyetograph from Atlas 14 (alternating block)"

    def shortHelpString(self):  # noqa: N802
        return ("Builds a design hyetograph by the alternating block method from the Atlas 14 depth-duration curve "
                "(JSON from damit_pmp:pointpf / :basinpf): storm total = the Atlas 14 depth for the storm duration "
                "at the chosen frequency; sub-durations are log-log interpolated between published Atlas 14 "
                "durations. Not an Atlas 14 temporal distribution. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile("INPUT_JSON", "Atlas 14 estimates (JSON from pointpf / basinpf)",
                                                     extension="json"))
        self.addParameter(QgsProcessingParameterNumber("FREQUENCY", "Frequency (years: ARI for PDS, 1/AEP for AMS)",
                                                       INTEGER, defaultValue=100, minValue=1, maxValue=1000))
        self.addParameter(QgsProcessingParameterEnum("STORM", "Storm duration", STORM, defaultValue=STORM.index("24-hr")))
        self.addParameter(QgsProcessingParameterNumber("STEP_MIN", "Time step (minutes)", INTEGER, defaultValue=60,
                                                       minValue=5, maxValue=1440))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_CSV", "Hyetograph (CSV)", "CSV files (*.csv)"))
        self.addOutput(QgsProcessingOutputNumber("TOTAL", "Storm total"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        path = self.parameterAsFile(P, "INPUT_JSON", context)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            pf = doc["atlas14"]
        except (OSError, ValueError, KeyError) as e:
            raise QgsProcessingException("Not a DamIT PMP Atlas 14 JSON ({}): {}".format(path, e))
        storm = A.DURATIONS[A.duration_index(STORM[self.parameterAsEnum(P, "STORM", context)])][1]
        try:
            rows = A.alternating_block(pf, self.parameterAsInt(P, "FREQUENCY", context), storm,
                                       self.parameterAsInt(P, "STEP_MIN", context))
        except A.Atlas14Error as e:
            raise QgsProcessingException(str(e))
        out = self.parameterAsFileOutput(P, "OUTPUT_CSV", context)
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t_end_min", "incremental_" + pf["unit_label"], "cumulative_" + pf["unit_label"]])
            w.writerows(rows)
            fh.write("# alternating block on NOAA Atlas 14 depths; {}\n".format(doc.get("citation") or A.citation(pf)))
        return {"OUTPUT_CSV": out, "TOTAL": rows[-1][2]}


class GridBasin(_Base):
    def name(self):
        return "gridbasin"

    def displayName(self):  # noqa: N802
        return "Basin statistics of an Atlas 14 grid"

    def shortHelpString(self):  # noqa: N802
        return ("Mean, minimum and maximum of a NOAA Atlas 14 GIS grid (downloaded from the PFDS GIS data page; "
                "values in thousandths of an inch, SCALE 0.001) over the basin. The frequency and duration are read "
                "from the Atlas 14 file name when it has the standard form (e.g. mw100yr24ha.asc). " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer("GRID", "NOAA Atlas 14 grid"))
        self.addParameter(QgsProcessingParameterFeatureSource("BASIN", "Basin (polygons)", [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterNumber("SCALE", "Grid value to inches", DOUBLE, defaultValue=0.001))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Statistics (JSON)", "JSON files (*.json)"))
        self.addOutput(QgsProcessingOutputNumber("MEAN", "Basin mean"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        from .. import gridstats
        grid = self.parameterAsRasterLayer(P, "GRID", context)
        src = self.parameterAsSource(P, "BASIN", context)
        g = QgsGeometry.unaryUnion([f.geometry() for f in src.getFeatures()])
        try:
            st = gridstats.basin_stats(grid.source(), g.asWkt(), src.sourceCrs().toWkt(),
                                       self.parameterAsDouble(P, "SCALE", context))
        except (ValueError, RuntimeError) as e:
            raise QgsProcessingException(str(e))
        doc = {"schema": "damit.pmp.atlas14_grid", "schema_version": 1, "grid": grid.source(),
               "grid_name": gridstats.parse_name(grid.source()), "units": "in", "stats": st,
               "source": "NOAA Atlas 14 GIS grid supplied by the user (https://hdsc.nws.noaa.gov/pfds/)",
               "areal_reduction": "none (Atlas 14 point estimates)", "note": NOTE}
        out = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        return {"OUTPUT_JSON": out, "MEAN": st["mean"]}


ALGORITHMS = (PointPF, BasinPF, Hyetograph, GridBasin)
