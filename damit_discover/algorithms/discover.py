"""NHD waterbody and OSM pond discovery for non-NID candidates.

NHD FType codes (USGS):
  390 = Lake/Pond
  436 = Reservoir

Output is a GeoPackage the user reviews. Selected features can be handed to
Crest or the Runner with is_new=true and a generated DISC-XXXX id.
"""
import json
import os
import urllib.parse
import urllib.request

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingOutputFile, QgsProcessingParameterExtent,
                       QgsProcessingParameterFile, QgsProcessingParameterNumber)

NHD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12/query"
NHD_FTYPES = (390, 436)  # Lake/Pond, Reservoir


class _Base(QgsProcessingAlgorithm):
    def group(self):
        return "Discovery"

    def groupId(self):  # noqa: N802
        return "discovery"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagCanCancel


class WaterbodiesAlgorithm(_Base):
    """Download NHD waterbodies (Lake/Pond, Reservoir) for an extent."""

    def name(self):
        return "waterbodies"

    def displayName(self):  # noqa: N802
        return "NHD waterbodies (Lake/Pond, Reservoir)"

    def shortHelpString(self):  # noqa: N802
        return ("Download NHD waterbodies for the extent. Filters to FType 390 "
                "(Lake/Pond) and 436 (Reservoir). Writes a GeoPackage.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterExtent("EXTENT", "Extent"))
        self.addParameter(QgsProcessingParameterFile(
            "OUTPUT", "Output GeoPackage", behavior=QgsProcessingParameterFile.Folder,
            fileFilter="GeoPackage (*.gpkg)"))
        self.addOutput(QgsProcessingOutputFile("RESULT", "Waterbodies GeoPackage"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        extent = self.parameterAsExtent(parameters, "EXTENT", context)
        out_dir = self.parameterAsFile(parameters, "OUTPUT", context)
        if not out_dir:
            raise QgsProcessingException("No output folder")
        bbox = "{},{},{},{}".format(extent.xMinimum(), extent.yMinimum(),
                                     extent.xMaximum(), extent.yMaximum())
        where = " OR ".join("FTYPE={}".format(ft) for ft in NHD_FTYPES)
        params = {"where": where, "geometry": bbox, "geometryType": "esriGeometryEnvelope",
                  "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                  "outFields": "GNIS_NAME,FTYPE,FCODE,AREASQKM", "f": "geojson",
                  "returnGeometry": "true"}
        url = NHD_URL + "?" + urllib.parse.urlencode(params)
        feedback.pushInfo("Querying NHD waterbodies...")
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise QgsProcessingException("NHD query failed: {}".format(e))
        features = data.get("features") or []
        feedback.pushInfo("{} waterbodies returned".format(len(features)))
        out_path = os.path.join(out_dir, "nhd_waterbodies.geojson")
        with open(out_path, "w") as f:
            json.dump(data, f)
        return {"RESULT": out_path}


class OsmPondsAlgorithm(_Base):
    """Query OpenStreetMap for pond/reservoir/dam features (placeholder)."""

    def name(self):
        return "osm_ponds"

    def displayName(self):  # noqa: N802
        return "OSM ponds / reservoirs / dams (optional)"

    def shortHelpString(self):  # noqa: N802
        return ("Optional. Query OSM Overpass for natural=water, water=pond, "
                "water=reservoir, man_made=dam in the extent. Not yet implemented.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterExtent("EXTENT", "Extent"))
        self.addParameter(QgsProcessingParameterFile(
            "OUTPUT", "Output folder", behavior=QgsProcessingParameterFile.Folder))
        self.addOutput(QgsProcessingOutputFile("RESULT", "OSM GeoJSON"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        raise QgsProcessingException("OSM ponds not yet implemented. Use NHD waterbodies.")


class CandidatesAlgorithm(_Base):
    """Merge NHD (and optional OSM) layers, drop near-NID matches, write candidates."""

    def name(self):
        return "candidates"

    def displayName(self):  # noqa: N802
        return "Candidate ponds / reservoirs (drop near-NID)"

    def shortHelpString(self):  # noqa: N802
        return ("Merge NHD waterbodies (and optional OSM). Drop features within "
                "the tolerance of an existing NID point. Write a candidate "
                "GeoPackage with is_new=true and a generated DISC-XXXX id.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile(
            "WATERBODIES", "NHD waterbodies GeoJSON",
            fileFilter="GeoJSON (*.geojson)"))
        self.addParameter(QgsProcessingParameterFile(
            "NID", "NID points (optional)", optional=True,
            fileFilter="GeoPackage or GeoJSON (*.gpkg *.geojson)"))
        self.addParameter(QgsProcessingParameterNumber(
            "TOLERANCE_M", "Drop if within (meters) of an NID point",
            defaultValue=100, minValue=0))
        self.addParameter(QgsProcessingParameterFile(
            "OUTPUT", "Output GeoPackage", behavior=QgsProcessingParameterFile.Folder))
        self.addOutput(QgsProcessingOutputFile("RESULT", "Candidates GeoPackage"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        wb_path = self.parameterAsFile(parameters, "WATERBODIES", context)
        nid_path = self.parameterAsFile(parameters, "NID", context)
        tol = self.parameterAsDouble(parameters, "TOLERANCE_M", context)
        out_dir = self.parameterAsFile(parameters, "OUTPUT", context)
        if not wb_path or not os.path.isfile(wb_path):
            raise QgsProcessingException("No waterbodies file")
        with open(wb_path) as f:
            data = json.load(f)
        features = data.get("features") or []
        feedback.pushInfo("{} waterbodies in".format(len(features)))
        # NID proximity filter is a placeholder; a real implementation would
        # load the NID layer and compute distances.
        if nid_path:
            feedback.pushInfo("NID filter not yet implemented; keeping all features")
        out = []
        for i, feat in enumerate(features):
            props = feat.get("properties") or {}
            props["disc_id"] = "DISC-{:04d}".format(i + 1)
            props["is_new"] = True
            props["source"] = "NHD"
            feat["properties"] = props
            out.append(feat)
        result = {"type": "FeatureCollection", "features": out}
        out_path = os.path.join(out_dir, "candidates.geojson")
        with open(out_path, "w") as f:
            json.dump(result, f)
        feedback.pushInfo("{} candidates written".format(len(out)))
        return {"RESULT": out_path}
