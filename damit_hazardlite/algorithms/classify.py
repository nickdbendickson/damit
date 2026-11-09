"""damit_lite:classify - suggested hazard class from depth / velocity rasters and structure, road
and rail layers, with DamIT Catalog presets or custom methods."""
import csv
import json
import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsFeatureSink, QgsGeometry, QgsProcessing,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingOutputNumber, QgsProcessingOutputString, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField, QgsProcessingParameterFile,
                       QgsProcessingParameterFolderDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString, QgsWkbTypes)

from .. import _deps  # noqa: F401
from .. import engine as E
from .. import sampling as S
from damit_core.lib import catalog_access
from damit_core.lib.qtcompat import make_fields

MODES = ["preset", "custom"]
DEPTH_UNITS = ["feet", "metres"]
VEL_UNITS = ["ft/s", "m/s"]
DIMENSIONS = ["not given", "1D", "2D"]
HYDRAULICS = ["breach_model", "simplified", "none"]
OUT_FIELDS = [("rid", "String"), ("rtype", "String"), ("name", "String"), ("hazard_type", "String"),
              ("depth_ft", "Double"), ("vel_fps", "Double"), ("dv_ft2s", "Double"), ("wet", "Int"),
              ("in_domain", "Int"), ("class", "Int"), ("methods", "String")]
CSV_COLS = ["id", "receptor_type", "name", "hazard_type", "structure_type", "habitable", "road_class", "aadt",
            "trains_per_day", "passenger", "active", "m1_zone", "occupants", "in_domain", "wet", "cells", "wet_cells",
            "depth_ground_ft", "velocity_fps", "dv_ft2s", "velocity_unknown", "class", "methods"]


def _number(name, label, default=None, optional=True):
    t = QgsProcessingParameterNumber.Double if hasattr(QgsProcessingParameterNumber, "Double") \
        else QgsProcessingParameterNumber.Type.Double
    return QgsProcessingParameterNumber(name, label, t, defaultValue=default, optional=optional)


def _ids(text):
    return [t.strip() for t in (text or "").replace(";", ",").split(",") if t.strip()]


class ClassifyLite(QgsProcessingAlgorithm):
    def name(self):
        return "classify"

    def displayName(self):  # noqa: N802
        return "Suggest hazard class (lite)"

    def shortHelpString(self):  # noqa: N802
        return ("Samples a maximum-depth raster (and optional maximum-velocity raster) at structures, roads and "
                "railroads and suggests a hazard class with a DamIT Catalog preset (any of its jurisdictions, "
                "USBR_TM11 accepted for USBR) or custom method IDs. Classes, thresholds, wet depth and sampling "
                "distances all come from DamIT Catalog, the same source DamIT Hazard (damit:classify) uses. "
                "Lite screens only methods about structures, roads and rail; others are listed for review. "
                "M1 chart zones are read from a field (M1_ZONE_FIELD) and are not computed here. "
                "It runs no flood model. Suggestion only: the engineer of record and the regulating agency decide.")

    def createInstance(self):  # noqa: N802
        return ClassifyLite()

    def initAlgorithm(self, config=None):  # noqa: N802
        A = self.addParameter
        A(QgsProcessingParameterRasterLayer("DEPTH", "Maximum depth raster"))
        A(QgsProcessingParameterEnum("DEPTH_UNITS", "Depth units", DEPTH_UNITS, defaultValue=0))
        A(QgsProcessingParameterRasterLayer("VELOCITY", "Maximum velocity raster (same grid)", optional=True))
        A(QgsProcessingParameterEnum("VELOCITY_UNITS", "Velocity units", VEL_UNITS, defaultValue=0))
        A(QgsProcessingParameterFeatureSource("STRUCTURES", "Structures (points or outlines)",
                                              [QgsProcessing.TypeVectorPoint, QgsProcessing.TypeVectorPolygon], optional=True))
        A(QgsProcessingParameterField("STRUCTURE_TYPE_FIELD", "Structure type / occupancy field (e.g. NSI occtype)",
                                      parentLayerParameterName="STRUCTURES", optional=True))
        A(QgsProcessingParameterField("HABITABLE_FIELD", "Habitable field (yes / no)", parentLayerParameterName="STRUCTURES",
                                      optional=True))
        A(QgsProcessingParameterField("OCCUPANTS_FIELD", "Occupants field", parentLayerParameterName="STRUCTURES",
                                      optional=True))
        A(QgsProcessingParameterField("M1_ZONE_FIELD", "M1 chart zone field (high_danger / judgment / low_danger)",
                                      parentLayerParameterName="STRUCTURES", optional=True))
        A(QgsProcessingParameterFeatureSource("ROADS", "Roads (lines)", [QgsProcessing.TypeVectorLine], optional=True))
        A(QgsProcessingParameterField("ROAD_CLASS_FIELD", "Road class field (interstate, us_state_highway, OSM highway ...)",
                                      parentLayerParameterName="ROADS", optional=True))
        A(QgsProcessingParameterField("AADT_FIELD", "AADT field", parentLayerParameterName="ROADS", optional=True))
        A(QgsProcessingParameterFeatureSource("RAIL", "Railroads (lines)", [QgsProcessing.TypeVectorLine], optional=True))
        A(QgsProcessingParameterField("TRAINS_FIELD", "Trains per day field", parentLayerParameterName="RAIL", optional=True))
        A(QgsProcessingParameterField("PASSENGER_FIELD", "Passenger line field (yes / no)", parentLayerParameterName="RAIL",
                                      optional=True))
        A(QgsProcessingParameterField("ACTIVE_FIELD", "Active line field (yes / no)", parentLayerParameterName="RAIL",
                                      optional=True))
        A(QgsProcessingParameterEnum("MODE", "Mode", MODES, defaultValue=0))
        A(QgsProcessingParameterString("PRESET", "Preset ID (DamIT Catalog, e.g. ND, NE, USBR, FEMA333)", optional=True))
        A(QgsProcessingParameterString("METHODS", "Method IDs (custom mode, comma separated)", optional=True))
        A(QgsProcessingParameterString("SCENARIOS", "Scenario IDs (S-codes; empty = the preset's)", optional=True))
        A(QgsProcessingParameterEnum("MODEL_DIMENSION", "Model the rasters come from", DIMENSIONS, defaultValue=0))
        A(QgsProcessingParameterEnum("HYDRAULICS_SOURCE", "Hydraulics source", HYDRAULICS, defaultValue=0))
        A(_number("STORAGE_ACFT", "Storage at top of dam (ac-ft, for R8)"))
        A(QgsProcessingParameterBoolean("APPLY_ADVISORIES", "Apply advisory-strength results (opt in)", defaultValue=False))
        A(QgsProcessingParameterFile("CATALOG_DIR", "Edited DamIT Catalog data folder (optional)",
                                     behavior=getattr(QgsProcessingParameterFile, "Folder", None)
                                     or QgsProcessingParameterFile.Behavior.Folder, optional=True))
        A(QgsProcessingParameterFolderDestination("OUTPUT_FOLDER", "Output folder"))
        A(QgsProcessingParameterFeatureSink("OUTPUT", "Receptors (sampled, with class)", QgsProcessing.TypeVectorPoint))
        self.addOutput(QgsProcessingOutputNumber("SUGGESTED_ORDINAL", "Suggested ordinal"))
        self.addOutput(QgsProcessingOutputString("SUGGESTED_LABEL", "Suggested label"))
        self.addOutput(QgsProcessingOutputFile("RESULT_JSON", "Result (JSON)"))
        self.addOutput(QgsProcessingOutputFile("SUMMARY_MD", "Summary (Markdown)"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        P = parameters
        try:
            cat = catalog_access.load(self.parameterAsString(P, "CATALOG_DIR", context) or None)
            prof = E.profile(cat)
        except Exception as e:                                   # noqa: BLE001
            raise QgsProcessingException("DamIT Catalog: {}".format(e))
        mode = MODES[self.parameterAsEnum(P, "MODE", context)]
        preset = self.parameterAsString(P, "PRESET", context).strip()
        methods = _ids(self.parameterAsString(P, "METHODS", context))
        if mode == "preset" and not preset:
            raise QgsProcessingException("Preset mode needs a PRESET ID; available: {}".format(", ".join(cat.preset_ids())))
        if mode == "custom" and not methods:
            raise QgsProcessingException("Custom mode needs METHODS (method IDs, e.g. M2,M6,M8a).")
        try:
            config = E.resolve(cat, mode, preset, methods, _ids(self.parameterAsString(P, "SCENARIOS", context)))
        except Exception as e:                                   # noqa: BLE001
            raise QgsProcessingException(str(e))
        vocab = E.load_vocab()
        dlyr = self.parameterAsRasterLayer(P, "DEPTH", context)
        depth = S.Raster(dlyr.source(), E.FT_PER_M if self.parameterAsEnum(P, "DEPTH_UNITS", context) == 1 else 1.0)
        vlyr = self.parameterAsRasterLayer(P, "VELOCITY", context)
        vel = None
        if vlyr is not None:
            vel = S.Raster(vlyr.source(), E.FT_PER_M if self.parameterAsEnum(P, "VELOCITY_UNITS", context) == 1 else 1.0)
            if not depth.same_grid(vel):
                raise QgsProcessingException("The velocity raster must be on the depth raster's grid.")
        rcrs = dlyr.crs()
        try:
            ft = S.feet_to_map_units(rcrs)
        except S.SamplingError as e:
            raise QgsProcessingException(str(e))
        fields = {
            "structure": {"type": self._f(P, "STRUCTURE_TYPE_FIELD", context), "habitable": self._f(P, "HABITABLE_FIELD", context),
                          "occupants": self._f(P, "OCCUPANTS_FIELD", context), "m1_zone": self._f(P, "M1_ZONE_FIELD", context)},
            "road": {"road_class": self._f(P, "ROAD_CLASS_FIELD", context), "aadt": self._f(P, "AADT_FIELD", context)},
            "rail": {"trains_per_day": self._f(P, "TRAINS_FIELD", context), "passenger": self._f(P, "PASSENGER_FIELD", context),
                     "active": self._f(P, "ACTIVE_FIELD", context)}}
        records, geoms = [], {}
        layers = (("structure", "STRUCTURES"), ("road", "ROADS"), ("rail", "RAIL"))
        if all(self.parameterAsSource(P, k, context) is None for _, k in layers):
            raise QgsProcessingException("Give at least one receptor layer (structures, roads or rail).")
        for kind, key in layers:
            src = self.parameterAsSource(P, key, context)
            if src is None:
                continue
            xf = S.transformer(src.sourceCrs(), rcrs)
            names = [f.name() for f in src.fields()]
            name_field = next((n for n in names if n.lower() in ("name", "fullname", "road_name", "rr_name")), None)
            for i, feat in enumerate(src.getFeatures()):
                if feedback.isCanceled():
                    raise QgsProcessingException("Cancelled.")
                attrs = dict(zip(names, feat.attributes()))
                rid = "{}:{}".format(kind, feat.id())
                d, v, inside = S.sample(feat.geometry(), depth, vel, ft, kind, prof, xf)
                cells = E.reduce_cells(d, v, prof["wet_min_depth_ft"])
                if kind == "structure":
                    rec = E.structure_record(rid, cells, attrs, prof, vocab, fields["structure"])
                elif kind == "road":
                    rec = E.road_record(rid, cells, attrs, vocab, dict(fields["road"], name=name_field))
                else:
                    rec = E.rail_record(rid, cells, attrs, vocab, fields["rail"])
                if name_field and "name" not in rec:
                    rec["name"] = attrs.get(name_field)
                rec["in_domain"] = bool(inside)
                records.append(rec)
                g = QgsGeometry(feat.geometry())
                if xf is not None:
                    g.transform(xf)
                geoms[rid] = g
        summary = {"hydraulics_source": HYDRAULICS[self.parameterAsEnum(P, "HYDRAULICS_SOURCE", context)]}
        dim = DIMENSIONS[self.parameterAsEnum(P, "MODEL_DIMENSION", context)]
        if dim != "not given":
            summary["model_dimension"] = dim
        if P.get("STORAGE_ACFT") not in (None, ""):
            summary["storage_acft"] = self.parameterAsDouble(P, "STORAGE_ACFT", context)
        res = E.classify(cat, config, records, summary, self.parameterAsBool(P, "APPLY_ADVISORIES", context), prof)
        out = self.parameterAsString(P, "OUTPUT_FOLDER", context)
        os.makedirs(out, exist_ok=True)
        for r in records:
            r["class"] = E.receptor_class(res, r["id"])
            r["methods"] = ",".join(sorted({h["method"] for h in res["hits"] if h["receptor"] == r["id"]}))
        inputs = {"depth": dlyr.source(), "velocity": vlyr.source() if vlyr is not None else "",
                  "model_dimension": dim, "hydraulics_source": summary["hydraulics_source"]}
        rj = os.path.join(out, "hazard_lite.json")
        with open(rj, "w", encoding="utf-8") as fh:
            json.dump({"result": res, "inputs": inputs, "config": {"mode": config.get("mode"),
                       "preset_id": config.get("preset_id"), "methods": sorted(config.get("methods", {}))},
                       "receptors": records}, fh, indent=1, default=str)
        with open(os.path.join(out, "receptors.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, CSV_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(records)
        md = os.path.join(out, "hazard_lite_summary.md")
        with open(md, "w", encoding="utf-8") as fh:
            fh.write(E.summary_markdown(res, records, config, inputs))
        sink, dest = self.parameterAsSink(P, "OUTPUT", context, make_fields(OUT_FIELDS),
                                          QgsWkbTypes.Point, rcrs if rcrs.isValid() else QgsCoordinateReferenceSystem())
        for r in records:
            f = QgsFeature()
            g = geoms[r["id"]]
            f.setGeometry(g.pointOnSurface() if not g.isEmpty() else g)
            f.setAttributes([r["id"], r["receptor_type"], str(r.get("name") or ""), str(r.get("hazard_type") or ""),
                             r.get("depth_ground_ft"), r.get("velocity_fps"), r.get("dv_ft2s"), int(bool(r.get("wet"))),
                             int(bool(r.get("in_domain"))), r.get("class"), r.get("methods")])
            sink.addFeature(f, QgsFeatureSink.FastInsert)
        feedback.pushInfo("Suggested class: {} ({}).".format(res["suggested_label"], res["suggested_ordinal"]))
        return {"OUTPUT": dest, "SUGGESTED_ORDINAL": res["suggested_ordinal"], "SUGGESTED_LABEL": res["suggested_label"],
                "RESULT_JSON": rj, "SUMMARY_MD": md, "OUTPUT_FOLDER": out}

    def _f(self, P, key, context):
        get = getattr(self, "parameterAsStrings", None) or self.parameterAsFields   # QGIS >= 3.32 / older
        v = get(P, key, context)
        return v[0] if v else None
