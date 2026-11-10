"""Shared parameters and QGIS -> record conversion for the damit_screen tools."""
import json
import os
import shutil

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingParameterBoolean,
                       QgsProcessingParameterEnum, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFile, QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterString, QgsRasterLayer)

from ..compat import FILE_FOLDER, VECTOR_ANY, VECTOR_POINT
from ..core import catalog_bridge as CB
from ..core import steps as ST
from ..core import workflow as WF

MODES = ["preset", "custom"]


def _preset_help():
    try:
        cat = CB.load_catalog()
        return ", ".join("{} = {}".format(k, v.get("label", k)) for k, v in cat.presets.items())
    except Exception as e:                                       # noqa
        return "(DamIT Catalog not available: {})".format(e)


def _ids(text):
    return [t.strip() for t in (text or "").replace(";", ",").split(",") if t.strip()]


def _field_map(text):
    out = {}
    for part in _ids(text):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _py(v):
    """QGIS attribute value (NULL -> None) -> plain Python."""
    if v is None:
        return None
    try:
        if hasattr(v, "isNull") and v.isNull():
            return None
    except Exception:                                            # noqa
        pass
    if isinstance(v, (bool, int, float, str)):
        return v
    try:
        return v.toPyObject() if hasattr(v, "toPyObject") else str(v)
    except Exception:                                            # noqa
        return str(v)


def source_records(source):
    """Features -> dicts with '_x', '_y' (point or centroid) and '_crs'."""
    if source is None:
        return [], []
    names = [f.name() for f in source.fields()]
    crs = source.sourceCrs().authid() if source.sourceCrs().isValid() else ""
    out = []
    for f in source.getFeatures():
        rec = {n: _py(f.attribute(n)) for n in names}
        g = f.geometry()
        if g is not None and not g.isEmpty():
            p = g.centroid().asPoint()
            rec["_x"], rec["_y"] = p.x(), p.y()
        rec["_crs"] = crs
        out.append(rec)
    return out, names


def receptor_records(source):
    recs, names = source_records(source)
    for r in recs:
        r.setdefault("id", r.get("fid"))
    return recs, names


def terrain_info(path):
    if not path or not os.path.exists(path):
        return None
    lyr = QgsRasterLayer(path, "dem")
    if not lyr.isValid():
        return None
    e = lyr.extent()
    return {"crs": lyr.crs().authid(), "extent": (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum())}


class DamitAlgorithm(QgsProcessingAlgorithm):
    """Base: the common inputs of every damit_screen tool."""
    _name = ""
    _display = ""
    _help = ""
    needs_dams = True

    def name(self):
        return self._name

    def displayName(self):  # noqa: N802
        return self._display

    def group(self):
        return "DamIT screening"

    def groupId(self):  # noqa: N802
        return "damit_screening"

    def shortHelpString(self):  # noqa: N802
        return (self._help + "\n\nPresets: " + _preset_help() + "\n\nSuggested classifications only; the "
                "engineer of record and the regulating agency make the determination. DamIT Screener 0.3.0 runs a 2D "
                "screening flood (the built-in engine in this process, or LISFLOOD-FP with engine2d = lisflood) and "
                "downloads larger clips from the USGS 3DEP service; it never starts ANUGA, HEC-RAS or Wine.")

    def createInstance(self):  # noqa: N802
        return type(self)()

    def add_common(self):
        P = self.addParameter
        P(QgsProcessingParameterFile("WORK", "Work folder", behavior=FILE_FOLDER))
        P(QgsProcessingParameterFeatureSource("DAMS", "Dams (points)", [VECTOR_POINT], optional=not self.needs_dams))
        P(QgsProcessingParameterString("FIELD_MAP", "Dam field map (damit_field=layer_field, comma separated)",
                                       defaultValue="", optional=True))
        P(QgsProcessingParameterEnum("MODE", "Mode", MODES, defaultValue=0))
        P(QgsProcessingParameterString("PRESET", "Preset ID (preset mode; see help)", defaultValue="", optional=True))
        P(QgsProcessingParameterString("SCENARIOS", "Scenario IDs (S-codes, comma separated; empty = preset's)",
                                       defaultValue="", optional=True))
        P(QgsProcessingParameterString("METHODS", "Method IDs (custom mode, comma separated)", defaultValue="",
                                       optional=True))
        P(QgsProcessingParameterFeatureSource("RECEPTORS", "Receptors (structures, roads, rail, ...)", [VECTOR_ANY],
                                              optional=True))
        P(QgsProcessingParameterRasterLayer("TERRAIN", "Terrain (DEM)", optional=True))
        P(QgsProcessingParameterBoolean("APPLY_ADVISORIES", "Apply advisory-strength results (opt in)",
                                        defaultValue=False))
        P(QgsProcessingParameterString("SETTINGS", "Settings JSON (file path or text); the fields above win "
                                       "where given, the JSON fills the rest", defaultValue="", optional=True, multiLine=True))

    def gather(self, params, context):
        try:
            s = WF.settings_from(self.parameterAsString(params, "SETTINGS", context))
        except ValueError as e:
            raise QgsProcessingException("Settings are not valid JSON: {}".format(e))
        if params.get("MODE") is not None:
            s["mode"] = MODES[self.parameterAsEnum(params, "MODE", context)]
        for key, pkey in (("preset", "PRESET"),):
            v = self.parameterAsString(params, pkey, context)
            if v:
                s[key] = v.strip()
        sc = _ids(self.parameterAsString(params, "SCENARIOS", context))
        if sc:
            s["scenarios"] = sc
        me = _ids(self.parameterAsString(params, "METHODS", context))
        if me:
            s["custom_methods"] = me
        fm = _field_map(self.parameterAsString(params, "FIELD_MAP", context))
        if fm:
            s["field_map"] = dict(s.get("field_map") or {}, **fm)
        if self.parameterAsBool(params, "APPLY_ADVISORIES", context):
            s["apply_advisories"] = True
        lyr = self.parameterAsRasterLayer(params, "TERRAIN", context)
        if lyr is not None:
            s["terrain"] = lyr.source()
        work = self.parameterAsString(params, "WORK", context)
        src = self.parameterAsSource(params, "DAMS", context)
        dams, problems = (None, [])
        if src is not None:
            raw, _ = source_records(src)
            dams, problems = ST.prepare(raw, s.get("field_map"))
        rsrc = self.parameterAsSource(params, "RECEPTORS", context)
        recs, rnames = (None, None)
        if rsrc is not None:
            recs, rnames = receptor_records(rsrc)
        return work, s, dams, problems, recs, rnames


def disk_free_mb(path):
    try:
        os.makedirs(path, exist_ok=True)
        return shutil.disk_usage(path).free / 1024.0 ** 2
    except OSError:
        return None


def dump(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    return path
