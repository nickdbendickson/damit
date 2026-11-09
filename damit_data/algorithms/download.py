"""damit_data:download and damit_data:status."""
import json
import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProcessingAlgorithm,
                       QgsProcessingException, QgsProcessingOutputFile, QgsProcessingOutputFolder,
                       QgsProcessingOutputNumber, QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent, QgsProcessingParameterFile, QgsProcessingParameterNumber,
                       QgsProcessingParameterString, QgsProject)

from .. import _deps  # noqa: F401
from ..core import sources, store, update
from damit_core.lib import http, states

STATE_CHOICES = ["(none - use the extent)"] + ["{} - {}".format(s["postal"], s["name"]) for s in states.table()]
FOLDER = getattr(QgsProcessingParameterFile, "Folder", None)
if FOLDER is None:                                   # QGIS 4 scoped enum
    FOLDER = QgsProcessingParameterFile.Behavior.Folder


class _FB(update.Feedback):
    def __init__(self, feedback):
        self.f = feedback

    def log(self, text):
        self.f.pushInfo(text)

    def progress(self, pct):
        self.f.setProgress(pct)

    def cancelled(self):
        return self.f.isCanceled()


class DownloadAlgorithm(QgsProcessingAlgorithm):
    http_client = None          # tests set a fake client

    def name(self):
        return "download"

    def displayName(self):  # noqa: N802
        return "Download / update offline layers"

    def shortHelpString(self):  # noqa: N802
        return ("Keeps a local copy of public structure and footprint layers for a US state (or, for NSI, an "
                "extent): USACE NSI (API, county by county for a state), Microsoft US Building Footprints, "
                "OpenStreetMap (Geofabrik GeoPackage) and, with a pasted link, FEMA / ORNL USA Structures. "
                "Only changed sources are downloaded again; updates are staged and verified before they "
                "replace the local copy. Statewide files can be hundreds of MB: MAX_MB refuses larger ones. "
                "Never writes into an ND Dam Suite offline pack.")

    def createInstance(self):  # noqa: N802
        return DownloadAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterEnum("STATE", "State", STATE_CHOICES, defaultValue=0))
        self.addParameter(QgsProcessingParameterExtent("EXTENT", "Extent (NSI only; instead of the whole state)",
                                                       optional=True))
        self.addParameter(QgsProcessingParameterEnum("SOURCES", "Sources", [sources.SOURCES[s]["name"] for s in sources.ORDER],
                                                     allowMultiple=True, defaultValue=[0]))
        self.addParameter(QgsProcessingParameterString("USA_STRUCTURES_URL", "USA Structures download link (https)",
                                                       defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterFile("FOLDER", "Data folder (empty = DamIT data_folder setting)",
                                                     behavior=FOLDER, optional=True))
        self.addParameter(QgsProcessingParameterBoolean("FORCE", "Download again even if unchanged", defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber("MAX_MB", "Refuse downloads larger than (MB)",
                                                       QgsProcessingParameterNumber.Double
                                                       if hasattr(QgsProcessingParameterNumber, "Double")
                                                       else QgsProcessingParameterNumber.Type.Double,
                                                       defaultValue=1500, minValue=1))
        self.addOutput(QgsProcessingOutputFolder("OUTPUT_FOLDER", "Data folder"))
        self.addOutput(QgsProcessingOutputFile("MANIFEST", "Manifest"))
        self.addOutput(QgsProcessingOutputNumber("UPDATED", "Sources updated"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        si = self.parameterAsEnum(parameters, "STATE", context)
        state = states.table()[si - 1]["postal"] if si > 0 else None
        bbox = None
        if parameters.get("EXTENT") not in (None, ""):
            rect = self.parameterAsExtent(parameters, "EXTENT", context)
            crs = self.parameterAsExtentCrs(parameters, "EXTENT", context)
            if rect is not None and not rect.isEmpty():
                wgs = QgsCoordinateReferenceSystem("EPSG:4326")
                if crs.isValid() and crs != wgs:
                    rect = QgsCoordinateTransform(crs, wgs, QgsProject.instance()).transformBoundingBox(rect)
                bbox = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
        chosen = [sources.ORDER[i] for i in self.parameterAsEnums(parameters, "SOURCES", context)]
        if not chosen:
            raise QgsProcessingException("Pick at least one source.")
        try:
            root = store.root(self.parameterAsString(parameters, "FOLDER", context) or None)
        except store.StoreError as e:
            raise QgsProcessingException(str(e))
        url = self.parameterAsString(parameters, "USA_STRUCTURES_URL", context)
        client = self.http_client or http.Client()
        force = self.parameterAsBool(parameters, "FORCE", context)
        max_mb = self.parameterAsDouble(parameters, "MAX_MB", context)
        updated, errors = 0, []
        for sid in chosen:
            try:
                p = sources.plan(sid, state=state, bbox=bbox if sid == "nsi" else None, url=url)
                r = update.update(p, client, root, force=force, feedback=_FB(feedback), max_mb=max_mb)
            except (sources.SourceError, update.UpdateError, store.StoreError) as e:
                errors.append(str(e))
                feedback.reportError(str(e))
                continue
            feedback.pushInfo(r["message"])
            updated += r["status"] == "updated"
        if errors and len(errors) == len(chosen):
            raise QgsProcessingException("Nothing downloaded: " + " | ".join(errors))
        return {"OUTPUT_FOLDER": root, "MANIFEST": os.path.join(root, store.MANIFEST), "UPDATED": updated}


class StatusAlgorithm(QgsProcessingAlgorithm):
    def name(self):
        return "status"

    def displayName(self):  # noqa: N802
        return "Offline layers status"

    def shortHelpString(self):  # noqa: N802
        return "Lists what DamIT Data holds in the data folder (manifest), with versions and when each was checked."

    def createInstance(self):  # noqa: N802
        return StatusAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile("FOLDER", "Data folder (empty = DamIT data_folder setting)",
                                                     behavior=FOLDER, optional=True))
        self.addOutput(QgsProcessingOutputNumber("ENTRIES", "Entries"))
        self.addOutput(QgsProcessingOutputFile("MANIFEST", "Manifest"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        try:
            root = store.root(self.parameterAsString(parameters, "FOLDER", context) or None)
        except store.StoreError as e:
            raise QgsProcessingException(str(e))
        man = store.read_manifest(root)
        for key, e in sorted(man.get("entries", {}).items()):
            feedback.pushInfo("{}: {} files, version {}, checked {}".format(key, len(e.get("files") or []),
                                                                           e.get("version") or "?", e.get("checked")))
        feedback.pushInfo(json.dumps({"layers": [p for _, p in store.all_layers(root)]}, indent=1))
        return {"ENTRIES": len(man.get("entries", {})), "MANIFEST": os.path.join(root, store.MANIFEST)}


ALGORITHMS = (DownloadAlgorithm, StatusAlgorithm)
