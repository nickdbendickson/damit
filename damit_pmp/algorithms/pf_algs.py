"""DamIT PMP Processing tools: NOAA Atlas 14 only.

damit_pmp:pointpf     Atlas 14 estimates at a point (PFDS), table + JSON with source and citation
damit_pmp:basinpf     Atlas 14 estimates at sample points in a basin, mean or max, table + JSON
damit_pmp:hyetograph  Alternating-block design hyetograph from an Atlas 14 depth table
damit_pmp:gridbasin   Basin mean / min / max of an Atlas 14 GIS grid (a local file, or fetched from NOAA)
damit_pmp:fetchgrid   Download an Atlas 14 precipitation-frequency GIS grid from NOAA, clip, GeoTIFF in inches
damit_pmp:raingrid    Rain-on-grid files from a hyetograph: LISFLOOD-FP .rain (mm/hr) and an ANUGA series (m/s)
"""
import csv
import json
import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureSink,
                       QgsGeometry, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingOutputNumber, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterDefinition, QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterExtent, QgsProcessingParameterFileDestination,
                       QgsProcessingParameterNumber, QgsProcessingParameterPoint,
                       QgsProcessingParameterRasterDestination, QgsProcessingParameterRasterLayer, QgsProject,
                       QgsWkbTypes)

from .. import _deps  # noqa: F401
from .. import atlas14 as A
from .. import gisgrid as G
from .. import rainexport as R
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
        "uses no other precipitation source. A location outside Atlas 14 coverage fails with a message.")
FREQ_HELP = "Frequency in years (ARI for PDS: 1, 2, 5, 10, 25, 50, 100, 200, 500, 1000; 1/AEP for AMS: 2 ... 1000)"
BOUNDS = [b for b, _ in G.BOUNDS]
BOUND_LABELS = ["Estimate", "Lower 90% confidence limit", "Upper 90% confidence limit"]
REGION_LABELS = ["Auto (from the point / extent, via PFDS)"] + ["{}: Volume {} - {}".format(c, v, n) for c, v, n in G.REGIONS]
REGION_IDS = [None] + list(G.REGION_CODES)


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


# one list for every duration choice (atlas14.DURATION_LABELS): STORM index i is DURATION index i, in every tool
DURATION_LABELS = A.DURATION_LABELS
STORM = DURATION_LABELS


class Hyetograph(_Base):
    def name(self):
        return "hyetograph"

    def displayName(self):  # noqa: N802
        return "Design hyetograph from Atlas 14 (alternating block)"

    def shortHelpString(self):  # noqa: N802
        return ("Builds a design hyetograph by the alternating block method from the Atlas 14 depth-duration curve "
                "(JSON from damit_pmp:pointpf / :basinpf): storm total = the Atlas 14 depth for the storm duration "
                "at the chosen frequency; sub-durations are log-log interpolated between published Atlas 14 "
                "durations. Any of the 10 Atlas 14 frequencies and any of the 19 Atlas 14 durations can be chosen (STORM uses the same list and indices as DURATION in fetchgrid / gridbasin); a storm shorter than the time step, or not a whole number of steps, stops with a message saying which STEP_MIN to use. "
                "Not an Atlas 14 temporal distribution. Feed the CSV to damit_pmp:raingrid for LISFLOOD-FP / ANUGA "
                "rain-on-grid files. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile("INPUT_JSON", "Atlas 14 estimates (JSON from pointpf / basinpf)",
                                                     extension="json"))
        self.addParameter(QgsProcessingParameterNumber("FREQUENCY", FREQ_HELP,
                                                       INTEGER, defaultValue=100, minValue=1, maxValue=1000))
        self.addParameter(QgsProcessingParameterEnum("STORM", "Storm duration (the 19 Atlas 14 durations, same list and indices as DURATION in fetchgrid)", STORM,
                                                     defaultValue=A.DEFAULT_DURATION_INDEX))
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
        storm_label = STORM[self.parameterAsEnum(P, "STORM", context)]
        storm = A.duration_minutes(storm_label)
        try:
            A.check_storm(storm, self.parameterAsInt(P, "STEP_MIN", context), storm_label)
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
            fh.write("# damit_pmp hyetograph: frequency_years={}; storm_min={}; step_min={}; series={}; depth_unit={}\n".format(
                self.parameterAsInt(P, "FREQUENCY", context), storm, self.parameterAsInt(P, "STEP_MIN", context),
                pf["series"], pf["unit_label"]))
        return {"OUTPUT_CSV": out, "TOTAL": rows[-1][2]}


# ---------------------------------------------------------------------------------------------------------
# Atlas 14 GIS grids



class _GridChoice(_Base):
    """The return period / duration / series / bound / region choices shared by fetchgrid and gridbasin."""
    grid_downloader = None                # tests set a fake: download(url, dest)

    def _choice_params(self, advanced=False):
        flag = QgsProcessingParameterDefinition.FlagAdvanced if advanced and \
            hasattr(QgsProcessingParameterDefinition, "FlagAdvanced") else None
        defs = [QgsProcessingParameterEnum("REGION", "Atlas 14 volume folder (Auto = from the point / extent, asks PFDS)",
                                           REGION_LABELS, defaultValue=0),
                QgsProcessingParameterEnum("SERIES", "Series (pds = partial duration / ARI, ams = annual maximum / AEP)",
                                           SERIES, defaultValue=0),
                QgsProcessingParameterNumber("FREQUENCY", FREQ_HELP, INTEGER, defaultValue=100, minValue=1, maxValue=1000),
                QgsProcessingParameterEnum("DURATION", "Duration (the 19 Atlas 14 durations, 5 minutes - 60 days)",
                                           DURATION_LABELS, defaultValue=A.DEFAULT_DURATION_INDEX),
                QgsProcessingParameterEnum("BOUND", "Estimate or 90% confidence bound", BOUND_LABELS, defaultValue=0),
                QgsProcessingParameterFile("CACHE_DIR", "Download cache folder (empty = DamIT pfds_cache setting or next "
                                           "to the output)", behavior=FOLDER, optional=True),
                QgsProcessingParameterBoolean("OFFLINE", "Offline (cached downloads / PFDS answers only)", defaultValue=False)]
        for d in defs:
            if flag is not None and d.name() in ("REGION", "SERIES", "BOUND", "CACHE_DIR", "OFFLINE"):
                d.setFlags(d.flags() | flag)
            self.addParameter(d)

    def _choice(self, P, context):
        return {"region": REGION_IDS[self.parameterAsEnum(P, "REGION", context)],
                "series": SERIES[self.parameterAsEnum(P, "SERIES", context)],
                "years": self.parameterAsInt(P, "FREQUENCY", context),
                "duration": DURATION_LABELS[self.parameterAsEnum(P, "DURATION", context)],
                "bound": BOUNDS[self.parameterAsEnum(P, "BOUND", context)],
                "offline": self.parameterAsBool(P, "OFFLINE", context)}

    def _cache(self, P, context, out_path):
        return self.parameterAsString(P, "CACHE_DIR", context) or settings.get("pfds_cache") or \
            os.path.join(os.path.dirname(os.path.abspath(out_path)), "pfds_cache")

    def _fetch_grid(self, ch, cache, det_point, window, mask_wkt, feedback):
        """Fetch (or reuse) the zip and clip it. det_point = (lat, lon) used only to find the region.
        Returns (array, gt, record). Raises QgsProcessingException with a plain message."""
        client = self.http_client or http.Client()
        region, pf = ch["region"], None
        try:
            G.check_choice(region or "mw", ch["years"], ch["duration"], ch["bound"], ch["series"])
            if region is None:
                if det_point is None:
                    raise QgsProcessingException("Give a point, an extent or a basin so the Atlas 14 region can be found, "
                                                 "or choose the region.")
                pf, _ = A.fetch(det_point[0], det_point[1], client, cache, offline=ch["offline"])
                region = G.region_from_pfds(pf)
                feedback.pushInfo("PFDS: {} (volume {} version {}) -> GIS folder {}".format(
                    pf["region"], pf["volume"], pf["version"], region))
                G.check_choice(region, ch["years"], ch["duration"], ch["bound"], ch["series"])

            def download(url, dest):
                feedback.pushInfo("Downloading {}".format(url))
                if type(self).grid_downloader is not None:          # a plain function on the class: not bound
                    return type(self).grid_downloader(url, dest)
                return http.download_file(url, dest, timeout=300, max_bytes=300 * 10 ** 6, cancelled=feedback.isCanceled)

            zpath, rec = G.fetch_zip(region, ch["years"], ch["duration"], ch["bound"], ch["series"], cache, download,
                                     offline=ch["offline"])
            feedback.pushInfo("{} ({} bytes, {})".format(rec["url"], rec["bytes"], "cached" if rec["from_cache"] else "downloaded"))
            arr, gt, _ = G.read_clip(zpath, window, mask_wkt)
            meta = G.zip_metadata(zpath)
        except A.CoverageError as e:
            raise QgsProcessingException(str(e))
        except A.Atlas14Error as e:
            raise QgsProcessingException(str(e))
        except IOError as e:
            raise QgsProcessingException("Atlas 14 GIS download failed ({}). Use OFFLINE with a cached zip, or check the "
                                         "network.".format(e))
        rec.update({"region": region, "series": ch["series"], "frequency_years": ch["years"], "duration": ch["duration"],
                    "bound": ch["bound"], "zip_metadata": meta})
        if pf is not None:
            rec["pfds_region"] = {"region": pf["region"], "volume": pf["volume"], "version": pf["version"],
                                  "citation": A.citation(pf)}
        return arr, gt, rec


def _geom_wgs84(src_geom, crs):
    g = QgsGeometry(src_geom)
    if crs.isValid() and crs != WGS84:
        g.transform(QgsCoordinateTransform(crs, WGS84, QgsProject.instance()))
    return g


class FetchGrid(_GridChoice):
    def name(self):
        return "fetchgrid"

    def displayName(self):  # noqa: N802
        return "Fetch an Atlas 14 precipitation-frequency grid (GIS format)"

    def shortHelpString(self):  # noqa: N802
        return ("Downloads the NOAA Atlas 14 'PF in GIS format' grid for one frequency and duration from the PFDS GIS data "
                "source (https://hdsc.nws.noaa.gov/pub/hdsc/data/<region>/<region><ARI>yr<dur><a|al|au>[_ams].zip, "
                "the same files as https://hdsc.nws.noaa.gov/pfds/pfds_gis.html), clips it to the point buffer, extent "
                "or basin you give, and writes a GeoTIFF in INCHES (NOAA's integer thousandths of an inch x 0.001; "
                "Float32, NAD83 geographic, nodata -9999) plus a JSON sidecar (<tif>.json) with the source URL, fetch "
                "time, SHA-256, Atlas 14 volume and citation. Choose any of the 10 ARIs (PDS) or 9 AEPs (AMS), any of "
                "the 19 durations, and the estimate or its 90% lower / upper bound. The region comes from the point / "
                "extent (via a PFDS point query) unless you choose it. Without a clip area the whole regional grid "
                "(about 25 MB of cells) is written. Downloads (3-4 MB zips) are cached; OFFLINE uses the cache only. "
                "Outside Atlas 14 coverage, or for a file NOAA does not publish, it stops with a message. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterPoint("POINT", "Point (finds the region; clipped to a buffer when no "
                                                      "extent or basin is given)", optional=True))
        self.addParameter(QgsProcessingParameterExtent("EXTENT", "Clip extent", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource("BASIN", "Clip to basin (polygons)",
                                                              [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterBoolean("MASK_TO_BASIN", "Blank cells outside the basin polygons",
                                                        defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber("BUFFER_KM", "Buffer around the point (km)", DOUBLE,
                                                       defaultValue=5.0, minValue=0.0, maxValue=500.0))
        self._choice_params()
        self.addParameter(QgsProcessingParameterRasterDestination("OUTPUT", "Atlas 14 grid (GeoTIFF, inches)"))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Source record (JSON; default <GeoTIFF>.json)",
                                                                "JSON files (*.json)", optional=True, createByDefault=False))
        self.addOutput(QgsProcessingOutputNumber("MEAN", "Mean of the clipped grid (in)"))
        self.addOutput(QgsProcessingOutputNumber("POINT_VALUE", "Value at the point (in), -1 if no point"))
        self.addOutput(QgsProcessingOutputString("URL", "NOAA file"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        ch = self._choice(P, context)
        out = self.parameterAsOutputLayer(P, "OUTPUT", context)
        side = self.parameterAsFileOutput(P, "OUTPUT_JSON", context) or G.sidecar_path(out)
        cache = self._cache(P, context, out)
        pt = None
        if P.get("POINT") not in (None, ""):
            pt = _to_wgs84(self.parameterAsPoint(P, "POINT", context), self.parameterAsPointCrs(P, "POINT", context))
        window, det, mask_wkt = None, None, None
        basin = self.parameterAsSource(P, "BASIN", context) if P.get("BASIN") not in (None, "") else None
        if basin is not None:
            geoms = [f.geometry() for f in basin.getFeatures() if not f.geometry().isEmpty()]
            if not geoms:
                raise QgsProcessingException("The basin layer has no polygon.")
            g = _geom_wgs84(QgsGeometry.unaryUnion(geoms), basin.sourceCrs())
            bb = g.boundingBox()
            window = (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum())
            c = g.pointOnSurface().asPoint()
            det = (c.y(), c.x())
            if self.parameterAsBool(P, "MASK_TO_BASIN", context):
                mask_wkt = g.asWkt()
        elif P.get("EXTENT") not in (None, ""):
            bb = self.parameterAsExtent(P, "EXTENT", context, WGS84)
            if bb.isNull() or bb.isEmpty():
                raise QgsProcessingException("The clip extent is empty.")
            window = (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum())
            det = (bb.center().y(), bb.center().x())
        elif pt is not None:
            km = self.parameterAsDouble(P, "BUFFER_KM", context)
            import math
            dlat = km / 111.32
            dlon = km / (111.32 * max(math.cos(math.radians(pt.y())), 0.01))
            window = (pt.x() - dlon, pt.y() - dlat, pt.x() + dlon, pt.y() + dlat)
        if pt is not None and det is None:
            det = (pt.y(), pt.x())
        elif pt is not None:
            det = (pt.y(), pt.x())                      # an explicit point is the best region probe
        arr, gt, rec = self._fetch_grid(ch, cache, det, window, mask_wkt, feedback)
        G.write_geotiff(out, arr, gt)
        st = G.array_stats(arr)
        pv = G.value_at(arr, gt, pt.x(), pt.y()) if pt is not None else None
        vol = rec.get("pfds_region") or {}
        zm = rec.get("zip_metadata") or {}
        doc = {"schema": "damit.pmp.atlas14_gis", "schema_version": 1, "units": "in", "value_scale": 1.0,
               "grid_values": "NOAA integer thousandths of an inch x 0.001 = inches", "crs": "EPSG:4269 (NAD83 geographic)",
               "nodata": G.NODATA_OUT, "raster": out,
               "source": "NOAA Atlas 14 GIS grid, NOAA/NWS Hydrometeorological Design Studies Center ({})".format(G.GIS_PAGE),
               "url": rec["url"], "fetched": rec["fetched"], "from_cache": rec["from_cache"], "zip": rec["zip"],
               "zip_bytes": rec["bytes"], "sha256": rec["sha256"], "region": rec["region"], "series": ch["series"],
               "frequency_years": ch["years"], "duration": ch["duration"], "bound": ch["bound"],
               "clip": {"window_lon_lat": window, "masked_to_basin": bool(mask_wkt),
                        "buffer_km": self.parameterAsDouble(P, "BUFFER_KM", context) if (window and basin is None
                                                                                          and P.get("EXTENT") in (None, "")) else None},
               "stats_in": st, "point": ({"lon": pt.x(), "lat": pt.y(), "value_in": pv} if pt is not None else None),
               "atlas14_volume": vol or None, "grid_metadata": zm,
               "citation": vol.get("citation") or G.citation(rec["region"], zm.get("pubdate")),
               "note": NOTE}
        with open(side, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        feedback.pushInfo("mean {} in, min {}, max {} ({} cells){}".format(
            st["mean"], st["min"], st["max"], st["cells"], "; point {} in".format(pv) if pv is not None else ""))
        return {"OUTPUT": out, "OUTPUT_JSON": side, "MEAN": st["mean"], "POINT_VALUE": pv if pv is not None else -1.0,
                "URL": rec["url"]}


class GridBasin(_GridChoice):
    def name(self):
        return "gridbasin"

    def displayName(self):  # noqa: N802
        return "Basin statistics of an Atlas 14 grid"

    def shortHelpString(self):  # noqa: N802
        return ("Mean, minimum and maximum of a NOAA Atlas 14 GIS grid over the basin. Give a grid you have (NOAA's file, "
                "values in thousandths of an inch, SCALE 0.001; the frequency and duration are read from the standard "
                "file name, e.g. mw100yr24ha.asc, or a damit_pmp:fetchgrid GeoTIFF, already in inches) OR leave GRID "
                "empty and choose the frequency, duration, series, bound and region (as in damit_pmp:fetchgrid): the "
                "tool then fetches the NOAA grid itself (cached) and reports the basin statistics. The basin is a "
                "polygon you supply; Atlas 14 values are point estimates (no areal reduction). " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer("GRID", "NOAA Atlas 14 grid (empty = fetch from NOAA with the "
                                                            "choices below)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource("BASIN", "Basin (polygons)", [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterNumber("SCALE", "Grid value to inches (NOAA files 0.001; fetchgrid "
                                                       "GeoTIFFs are read as 1)", DOUBLE, defaultValue=0.001))
        self._choice_params(advanced=False)
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Statistics (JSON)", "JSON files (*.json)"))
        self.addOutput(QgsProcessingOutputNumber("MEAN", "Basin mean"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        from .. import gridstats
        src = self.parameterAsSource(P, "BASIN", context)
        geoms = [f.geometry() for f in src.getFeatures() if not f.geometry().isEmpty()]
        if not geoms:
            raise QgsProcessingException("The basin layer has no polygon.")
        g = QgsGeometry.unaryUnion(geoms)
        out = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        grid = self.parameterAsRasterLayer(P, "GRID", context) if P.get("GRID") not in (None, "") else None
        fetch = None
        if grid is not None:
            scale = gridstats.grid_scale(grid.source(), self.parameterAsDouble(P, "SCALE", context))
            try:
                st = gridstats.basin_stats(grid.source(), g.asWkt(), src.sourceCrs().toWkt(), scale)
            except (ValueError, RuntimeError) as e:
                raise QgsProcessingException(str(e))
            name = gridstats.parse_name(grid.source())
            side = G.read_sidecar(grid.source())
            if side:
                name = dict(name, **{k: side[k] for k in ("region", "frequency_years", "duration", "series", "bound")
                                     if k in side})
            gname, gsrc = grid.source(), ("NOAA Atlas 14 GIS grid supplied by the user (https://hdsc.nws.noaa.gov/pfds/)"
                                          if not side else "damit_pmp:fetchgrid GeoTIFF; NOAA file " + str(side.get("url")))
        else:
            ch = self._choice(P, context)
            wg = _geom_wgs84(g, src.sourceCrs())
            bb = wg.boundingBox()
            c = wg.pointOnSurface().asPoint()
            arr, gt, fetch = self._fetch_grid(ch, self._cache(P, context, out), (c.y(), c.x()),
                                              (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()), wg.asWkt(),
                                              feedback)
            try:
                st = G.array_stats(arr)
            except ValueError:
                raise QgsProcessingException("no Atlas 14 grid cells with values inside the basin (outside Atlas 14 coverage?)")
            name = {"region_code": fetch["region"], "frequency_years": ch["years"], "duration": ch["duration"],
                    "series": ch["series"]}
            if ch["bound"] != "estimate":
                name["bound"] = ch["bound"]
            gname, gsrc = fetch["url"], "NOAA Atlas 14 GIS grid fetched by damit_pmp ({})".format(G.GIS_PAGE)
        doc = {"schema": "damit.pmp.atlas14_grid", "schema_version": 1, "grid": gname,
               "grid_name": name, "units": "in", "stats": st, "source": gsrc,
               "areal_reduction": "none (Atlas 14 point estimates)", "note": NOTE}
        if fetch:
            doc["fetch"] = {k: fetch[k] for k in ("url", "fetched", "from_cache", "sha256", "zip") if k in fetch}
            doc["fetch"]["pfds_region"] = fetch.get("pfds_region")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        return {"OUTPUT_JSON": out, "MEAN": st["mean"]}


# ---------------------------------------------------------------------------------------------------------
# Rain-on-grid export

TIME_UNITS = list(R.TIME_UNITS)


class RainGrid(_Base):
    def name(self):
        return "raingrid"

    def displayName(self):  # noqa: N802
        return "Rain-on-grid files for LISFLOOD-FP and ANUGA"

    def shortHelpString(self):  # noqa: N802
        return ("Writes the design storm as rain-on-grid input: (a) a LISFLOOD-FP .rain file (spatially uniform rainfall "
                "RATE in mm/hr against time, layout of the LISFLOOD-FP manual: comment line, '<n> seconds', then "
                "'rate time' rows; each hyetograph block is held constant, linear interpolation) for the `rainfall` "
                "keyword of the .par file; (b) an ANUGA series CSV (time_s, rate_m_per_s; 1 mm/hr = 2.7778e-7 m/s) with a "
                "README showing anuga.Rate_operator use; (c) a JSON record with the units, totals and mass check. The "
                "storm is a hyetograph CSV from damit_pmp:hyetograph, or built here from a pointpf / basinpf JSON with "
                "FREQUENCY (any Atlas 14 ARI / AEP), STORM duration and STEP_MIN. Optionally the storm total is "
                "rescaled to an Atlas 14 grid (damit_pmp:fetchgrid output or NOAA file for the SAME frequency and "
                "duration) at a point or as the mean over a basin, and a FACTOR_RASTER (grid / reference depth) is "
                "written for spatially varying use. The LISFLOOD-FP dynamic-rain NetCDF is not written (its layout "
                "could not be verified without the solver; see the README). Nothing is launched. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile("INPUT_CSV", "Hyetograph (CSV from damit_pmp:hyetograph; empty = "
                                                     "build one from the JSON below)", extension="csv", optional=True))
        self.addParameter(QgsProcessingParameterFile("INPUT_JSON", "Atlas 14 estimates (JSON from pointpf / basinpf; used "
                                                     "when no hyetograph CSV is given)", extension="json", optional=True))
        self.addParameter(QgsProcessingParameterNumber("FREQUENCY", FREQ_HELP + " (JSON route)", INTEGER,
                                                       defaultValue=100, minValue=1, maxValue=1000))
        self.addParameter(QgsProcessingParameterEnum("STORM", "Storm duration (JSON route; the 19 Atlas 14 durations, same indices as DURATION in fetchgrid)", STORM,
                                                     defaultValue=A.DEFAULT_DURATION_INDEX))
        self.addParameter(QgsProcessingParameterNumber("STEP_MIN", "Time step (minutes; JSON route)", INTEGER,
                                                       defaultValue=60, minValue=5, maxValue=1440))
        self.addParameter(QgsProcessingParameterRasterLayer("SCALE_GRID", "Rescale the storm to this Atlas 14 grid "
                                                            "(same frequency and duration)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource("SCALE_BASIN", "... mean over this basin (polygons)",
                                                              [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterPoint("SCALE_POINT", "... or value at this point (used when no basin)",
                                                      optional=True))
        self.addParameter(QgsProcessingParameterEnum("TIME_UNIT", "Time unit written in the .rain file", TIME_UNITS,
                                                     defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber("RAMP_S", "Seconds each block ramps to the next (>= 1)", INTEGER,
                                                       defaultValue=1, minValue=1, maxValue=600))
        self.addParameter(QgsProcessingParameterNumber("SIM_TIME_H", "Hold 0 mm/hr until this simulation time (hours; 0 = "
                                                       "end of storm)", DOUBLE, defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_RAIN", "LISFLOOD-FP rainfall file (.rain, mm/hr)",
                                                                "LISFLOOD-FP rain files (*.rain)"))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_ANUGA", "ANUGA rate series (CSV, m/s)",
                                                                "CSV files (*.csv)"))
        self.addParameter(QgsProcessingParameterFileDestination("OUTPUT_JSON", "Record (JSON)", "JSON files (*.json)"))
        self.addParameter(QgsProcessingParameterRasterDestination("FACTOR_RASTER", "Spatial factor raster (grid / reference "
                                                                  "depth)", optional=True, createByDefault=False))
        self.addOutput(QgsProcessingOutputNumber("TOTAL_MM", "Storm total (mm)"))
        self.addOutput(QgsProcessingOutputNumber("PEAK_MM_HR", "Peak rate (mm/hr)"))

    def _blocks(self, P, context):
        csv_path = self.parameterAsFile(P, "INPUT_CSV", context) if P.get("INPUT_CSV") not in (None, "") else ""
        meta = {}
        if csv_path:
            try:
                blocks, unit = R.read_hyetograph(csv_path)
            except (OSError, ValueError) as e:
                raise QgsProcessingException(str(e))
            with open(csv_path, encoding="utf-8") as fh:
                for ln in fh:
                    if ln.startswith("# damit_pmp hyetograph:"):
                        meta = dict(kv.strip().split("=", 1) for kv in ln.split(":", 1)[1].split(";") if "=" in kv)
            return blocks, "hyetograph CSV " + os.path.basename(csv_path), meta
        js = self.parameterAsFile(P, "INPUT_JSON", context) if P.get("INPUT_JSON") not in (None, "") else ""
        if not js:
            raise QgsProcessingException("Give a hyetograph CSV or an Atlas 14 JSON (pointpf / basinpf).")
        try:
            with open(js, encoding="utf-8") as fh:
                pf = json.load(fh)["atlas14"]
        except (OSError, ValueError, KeyError) as e:
            raise QgsProcessingException("Not a DamIT PMP Atlas 14 JSON ({}): {}".format(js, e))
        storm_label = STORM[self.parameterAsEnum(P, "STORM", context)]
        storm = A.duration_minutes(storm_label)
        years, step = self.parameterAsInt(P, "FREQUENCY", context), self.parameterAsInt(P, "STEP_MIN", context)
        try:
            A.check_storm(storm, step, storm_label)
            rows = A.alternating_block(pf, years, storm, step)
        except A.Atlas14Error as e:
            raise QgsProcessingException(str(e))
        meta = {"frequency_years": str(years), "storm_min": str(storm), "step_min": str(step), "series": pf["series"]}
        return R.blocks_from_rows([(t, d) for t, d, _ in rows], pf["unit_label"] if pf["unit_label"] in ("in", "mm") else "in"), \
            "Atlas 14 JSON {} ({}-year, {})".format(os.path.basename(js), years, storm_label), meta

    def _target_depth(self, P, context):
        """(depth in, description) from the scale grid at a basin (mean) or a point, or (None, None)."""
        if P.get("SCALE_GRID") in (None, ""):
            return None, None, None
        from .. import gridstats
        grid = self.parameterAsRasterLayer(P, "SCALE_GRID", context)
        scale = gridstats.grid_scale(grid.source(), 0.001)
        basin = self.parameterAsSource(P, "SCALE_BASIN", context) if P.get("SCALE_BASIN") not in (None, "") else None
        try:
            if basin is not None:
                geoms = [f.geometry() for f in basin.getFeatures() if not f.geometry().isEmpty()]
                g = QgsGeometry.unaryUnion(geoms)
                v = gridstats.basin_stats(grid.source(), g.asWkt(), basin.sourceCrs().toWkt(), scale)["mean"]
                how = "basin mean"
            elif P.get("SCALE_POINT") not in (None, ""):
                crs = self.parameterAsPointCrs(P, "SCALE_POINT", context)
                pt = self.parameterAsPoint(P, "SCALE_POINT", context)
                v = gridstats.point_value(grid.source(), pt.x(), pt.y(), crs.toWkt(), scale)
                how = "point value"
                if v is None:
                    raise QgsProcessingException("The scale point is outside the grid or on an empty cell.")
            else:
                raise QgsProcessingException("SCALE_GRID needs a SCALE_BASIN or a SCALE_POINT to read the depth from.")
        except (ValueError, RuntimeError) as e:
            raise QgsProcessingException(str(e))
        return v, "{} of {}".format(how, os.path.basename(grid.source())), (grid, scale)

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        blocks, desc, meta = self._blocks(P, context)
        storm_min = round(blocks[-1][1])
        total_in = R.total_mm(blocks) / R.MM_PER_IN
        extra = {"hyetograph": meta}
        target, how, gs = self._target_depth(P, context)
        if target is not None:
            side = G.read_sidecar(gs[0].source())
            info = dict(side or {})
            if not info:
                from .. import gridstats
                info = gridstats.parse_name(gs[0].source())
                if info:
                    info = {"frequency_years": info.get("frequency_years"), "duration": info.get("duration")}
            if info.get("duration"):
                gmin = dict(A.DURATIONS).get(info["duration"])
                if gmin is not None and gmin != storm_min:
                    raise QgsProcessingException("The scale grid is for the {} duration but the storm is {} min "
                                                 "({}).".format(info["duration"], storm_min, desc))
            if info.get("frequency_years") and meta.get("frequency_years") and \
                    str(info["frequency_years"]) != str(meta["frequency_years"]):
                raise QgsProcessingException("The scale grid is the {}-year grid but the storm is the {}-year storm.".format(
                    info["frequency_years"], meta["frequency_years"]))
            if target <= 0:
                raise QgsProcessingException("The grid depth is not positive.")
            factor = target / total_in
            blocks = R.scale_blocks(blocks, factor)
            extra["rescaled_to_grid"] = {"grid": gs[0].source(), "how": how, "grid_depth_in": target,
                                         "hyetograph_total_in": round(total_in, 4), "factor": round(factor, 6)}
            feedback.pushInfo("Storm rescaled to {} = {:.3f} in (factor {:.4f})".format(how, target, factor))
        sim_h = self.parameterAsDouble(P, "SIM_TIME_H", context)
        unit = TIME_UNITS[self.parameterAsEnum(P, "TIME_UNIT", context)]
        rain_path = self.parameterAsFileOutput(P, "OUTPUT_RAIN", context)
        anuga_path = self.parameterAsFileOutput(P, "OUTPUT_ANUGA", context)
        json_path = self.parameterAsFileOutput(P, "OUTPUT_JSON", context)
        try:
            rec = R.export(blocks, rain_path, anuga_path, unit, self.parameterAsInt(P, "RAMP_S", context),
                           sim_h * 3600.0 if sim_h > 0 else None, source="NOAA Atlas 14 - " + desc,
                           desc="{:.3f} in over {:g} h, alternating-block hyetograph ({})".format(
                               R.total_mm(blocks) / R.MM_PER_IN, blocks[-1][1] / 60.0, desc), extra=extra)
        except R.RainError as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("{} points, {:.2f} mm, peak {:.2f} mm/hr, mass error {:.5f} %".format(
            rec["points"], rec["total_depth_mm"], rec["peak_rate_mm_hr"], rec["series_depth_error_pct"]))
        out = {"OUTPUT_RAIN": rain_path, "OUTPUT_ANUGA": anuga_path, "OUTPUT_JSON": json_path,
               "TOTAL_MM": rec["total_depth_mm"], "PEAK_MM_HR": rec["peak_rate_mm_hr"]}
        fr = self.parameterAsOutputLayer(P, "FACTOR_RASTER", context) if P.get("FACTOR_RASTER") not in (None, "") else ""
        if fr:
            if gs is None:
                raise QgsProcessingException("FACTOR_RASTER needs SCALE_GRID.")
            self._factor_raster(gs[0].source(), gs[1], target, fr)
            rec["factor_raster"] = fr
            rec["factor_raster_note"] = ("cell depth / reference depth ({:.4f} in, {}); multiply the uniform rate by it "
                                         "for a spatially varying storm (ANUGA: a Quantity / function of x, y; "
                                         "LISFLOOD-FP: build the dynamic-rain .nc from it yourself)".format(target, how))
            out["FACTOR_RASTER"] = fr
        R.dump_json(json_path, rec)
        return out

    @staticmethod
    def _factor_raster(grid_path, scale, ref_in, out_path):
        import numpy as np
        from osgeo import gdal
        ds = gdal.Open(grid_path)
        b = ds.GetRasterBand(1)
        a = b.ReadAsArray().astype("float64")
        nd = b.GetNoDataValue()
        valid = np.isfinite(a) & (a >= 0)
        if nd is not None:
            valid &= a != nd
        f = np.where(valid, a * scale / ref_in, G.NODATA_OUT).astype("float32")
        drv = gdal.GetDriverByName("GTiff")
        o = drv.Create(out_path, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32, ["COMPRESS=DEFLATE", "PREDICTOR=3"])
        o.SetGeoTransform(ds.GetGeoTransform())
        o.SetProjection(ds.GetProjection())
        ob = o.GetRasterBand(1)
        ob.SetNoDataValue(G.NODATA_OUT)
        ob.WriteArray(f)
        ob.FlushCache()
        o = None


ALGORITHMS = (PointPF, BasinPF, Hyetograph, GridBasin, FetchGrid, RainGrid)
