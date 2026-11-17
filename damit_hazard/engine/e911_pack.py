"""Locate the official ND E911 (NDGISHUB_address_points) layer in the configured offline pack.

ADDRESS_POINTS on damit:classify is optional: when it is empty, classify reads this official
layer from the pack the suite is already configured to use. No box path is hard-coded. The pack
and ND_Dam_Suite_Pack are never written.
"""
import json
import os
import sqlite3
import zlib

DATASET = "NDGISHUB_address_points"
GPKG_REL = os.path.join("structures", DATASET + ".gpkg")
SQLITE_NAME = "nd_offline_pack.sqlite"
SUITE_PACK_DIR = "ND_Dam_Suite_Pack"
FORMAT1_DIR = "nd_offline_pack"
# Environment variables the suite already uses for the pack / suite data folder.
ENV_PACKS = (
    "ND_DAM_HAZARD_OFFLINE_PACK",
    "NDSUITE_PACK",
    "NDSUITE_DATA",
    "DAMIT_DATA",
    "DAMIT_DATA_FOLDER",
    "ND_DAM_SUITE",
    "NDSUITE_HOME",
)
QGIS_KEYS = (
    "ND_Dam_Hazard_Helper/offline_pack",
    "ndsuite/pack_path",
    "ndsuite/data_folder",
    "damit/data_folder",
)
CONFIG_FILES = (
    (os.path.join("~", ".ndsuite", "config.json"),
     ("ndsuite/pack_path", "ndsuite/data_folder", "pack_path", "data_folder")),
    (os.path.join("~", ".damit", "config.json"),
     ("damit/data_folder", "data_folder", "pack_path")),
    (os.path.join("~", ".config", "damit", "settings.json"),
     ("data_folder", "pack_path")),
)


def _abs_existing(raw):
    p = os.path.expanduser(str(raw or "").strip())
    if not p:
        return ""
    p = os.path.abspath(p)
    return p if os.path.exists(p) else ""


def _qgis_values():
    out = []
    try:
        from qgis.core import QgsSettings
        st = QgsSettings()
    except Exception:
        return out
    for key in QGIS_KEYS:
        try:
            v = _abs_existing(st.value(key, "") or "")
        except Exception:
            v = ""
        if v:
            out.append(v)
    return out


def _config_values():
    out = []
    for path, keys in CONFIG_FILES:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in keys:
            v = _abs_existing(data.get(key))
            if v:
                out.append(v)
    return out


def configured_pack_paths():
    """Existing pack / suite-data paths already set for this computer. No hard-coded box paths."""
    found = []
    for env in ENV_PACKS:
        v = _abs_existing(os.environ.get(env, ""))
        if v:
            found.append(v)
    found.extend(_qgis_values())
    found.extend(_config_values())
    try:
        from damit_core.lib import settings as DS
        v = _abs_existing(DS.get("data_folder"))
        if v:
            found.append(v)
    except Exception:
        pass
    try:
        from damsuite import suitedata as SD
        for cand in (SD.pack_location(), SD.data_folder(), SD.active_pack()):
            v = _abs_existing(cand)
            if v:
                found.append(v)
    except Exception:
        pass
    out, seen = [], set()
    for p in found:
        try:
            key = os.path.normcase(os.path.realpath(p))
        except OSError:
            key = os.path.normcase(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _as_dir(path):
    if os.path.isdir(path):
        return path
    if os.path.isfile(path):
        return os.path.dirname(path)
    return ""


def _gpkg_at(root):
    """Official address-point GeoPackage under a pack or suite-data folder, if it exists."""
    if not root:
        return ""
    candidates = []
    if os.path.isfile(root) and root.lower().endswith(".gpkg") and DATASET.lower() in os.path.basename(root).lower():
        return root
    folder = _as_dir(root)
    if not folder:
        return ""
    candidates.extend((
        os.path.join(folder, GPKG_REL),
        os.path.join(folder, SUITE_PACK_DIR, GPKG_REL),
        os.path.join(folder, DATASET + ".gpkg"),
        os.path.join(os.path.dirname(folder), SUITE_PACK_DIR, GPKG_REL),
    ))
    # NDSUITE_DATA often points at the parent of both ND_Dam_Suite_Pack and nd_offline_pack
    parent = os.path.dirname(folder)
    if parent:
        candidates.append(os.path.join(parent, SUITE_PACK_DIR, GPKG_REL))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""


def _sqlite_at(root):
    if not root:
        return ""
    if os.path.isfile(root) and root.lower().endswith(".sqlite"):
        return root
    folder = _as_dir(root)
    if not folder:
        return ""
    for p in (
        os.path.join(folder, SQLITE_NAME),
        os.path.join(folder, FORMAT1_DIR, SQLITE_NAME),
        os.path.join(os.path.dirname(folder), FORMAT1_DIR, SQLITE_NAME),
    ):
        if os.path.isfile(p):
            return p
    return ""


def resolve_e911_source(paths=None):
    """The first configured pack that holds NDGISHUB_address_points.

    Returns a dict {kind, path, pack} where kind is 'gpkg' or 'sqlite', or None.
    A format-2 GeoPackage is preferred when both layouts are present (same official layer,
    opened directly by QGIS). The pack is never written.
    """
    for raw in (paths if paths is not None else configured_pack_paths()):
        gpkg = _gpkg_at(raw)
        if gpkg:
            return {"kind": "gpkg", "path": gpkg, "pack": raw, "dataset": DATASET}
        sqlite = _sqlite_at(raw)
        if sqlite and _sqlite_has_dataset(sqlite, DATASET):
            return {"kind": "sqlite", "path": sqlite, "pack": raw, "dataset": DATASET}
    return None


def _sqlite_ro(path):
    # Read-only URI; encode characters that would cut a file: URI short.
    from pathlib import Path
    uri = Path(os.path.abspath(path)).as_uri()
    if uri.startswith("file://") and not uri.startswith("file:///"):
        uri = "file:////" + uri[len("file://"):]
    return uri + "?mode=ro"


def _sqlite_has_dataset(path, name):
    try:
        con = sqlite3.connect(_sqlite_ro(path), uri=True)
        try:
            con.execute("PRAGMA query_only=ON")
            row = con.execute("SELECT 1 FROM datasets WHERE name=? AND status IN ('complete', 'incomplete')",
                              (name,)).fetchone()
            return bool(row)
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError):
        return False


def _extent_4326(layer, context=None):
    """(xmin, ymin, xmax, ymax) of a raster or vector layer in EPSG:4326, or None."""
    try:
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
    except ImportError:
        return None
    ext = layer.extent()
    if ext is None or ext.isEmpty():
        return None
    src = layer.crs()
    dst = QgsCoordinateReferenceSystem("EPSG:4326")
    if not src.isValid():
        return None
    if src != dst:
        try:
            xf = QgsCoordinateTransform(src, dst, context.transformContext() if context is not None
                                        else QgsProject.instance().transformContext())
            ext = xf.transformBoundingBox(ext)
        except Exception:
            return None
    pad = 0.01  # ~1 km; keeps edge receptors if the raster CRS transform is slightly off
    return (ext.xMinimum() - pad, ext.yMinimum() - pad, ext.xMaximum() + pad, ext.yMaximum() + pad)


def _open_gpkg(path, extent_layer=None, context=None):
    from qgis.core import QgsFeatureRequest, QgsVectorLayer
    lyr = QgsVectorLayer(path, DATASET, "ogr")
    if not lyr.isValid():
        return None, "could not open {}".format(path)
    try:
        lyr.setReadOnly(True)
    except Exception:
        pass
    # Never hand the statewide layer to classify. Clip to the raster extent, or refuse.
    if extent_layer is None:
        return None, ("offline pack GeoPackage {} has {} but no raster extent was given to clip it; "
                      "pass ADDRESS_POINTS or a depth raster".format(path, DATASET))
    ext4326 = _extent_4326(extent_layer, context)
    if not ext4326:
        return None, "could not transform the raster extent to clip {}".format(path)
    rec = _rect_for_layer(lyr, ext4326, context)
    if rec is None:
        return None, "could not clip {} to the raster extent".format(path)
    clip = _materialize(lyr, QgsFeatureRequest().setFilterRect(rec), "pack_e911")
    if clip is None:
        return None, "could not materialize a clip of {}".format(path)
    return clip, "offline pack GeoPackage {} ({} features in the raster extent)".format(
        path, clip.featureCount())


def _rect_for_layer(lyr, ext4326, context):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle
    xmin, ymin, xmax, ymax = ext4326
    rec = QgsRectangle(xmin, ymin, xmax, ymax)
    src = QgsCoordinateReferenceSystem("EPSG:4326")
    dst = lyr.crs()
    if dst.isValid() and src != dst:
        try:
            xf = QgsCoordinateTransform(src, dst, context.transformContext() if context is not None
                                        else QgsProject.instance().transformContext())
            rec = xf.transformBoundingBox(rec)
        except Exception:
            return rec
    return rec


def _materialize(lyr, request, name):
    from qgis.core import QgsFeature, QgsVectorLayer, QgsWkbTypes
    wkb = QgsWkbTypes.displayString(lyr.wkbType()) or "Point"
    crs = lyr.crs().authid() or "EPSG:4326"
    mem = QgsVectorLayer("{}?crs={}".format(wkb, crs), name, "memory")
    if not mem.isValid():
        return None
    mem.dataProvider().addAttributes(list(lyr.fields()))
    mem.updateFields()
    feats = []
    for feat in lyr.getFeatures(request):
        nf = QgsFeature(mem.fields())
        nf.setGeometry(feat.geometry())
        nf.setAttributes(feat.attributes())
        feats.append(nf)
    mem.dataProvider().addFeatures(feats)
    return mem


def _sqlite_query(path, extent4326):
    """GeoJSON features of NDGISHUB_address_points that intersect extent4326 (xmin,ymin,xmax,ymax)."""
    con = sqlite3.connect(_sqlite_ro(path), uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        info = con.execute("SELECT maxw, maxh FROM datasets WHERE name=?", (DATASET,)).fetchone()
        maxw = (info[0] or 0.0) if info else 0.0
        xmin, ymin, xmax, ymax = [float(v) for v in extent4326]
        box = "minx BETWEEN ? AND ? AND maxx >= ? AND miny <= ? AND maxy >= ?"
        args = (xmin - maxw - 1e-9, xmax, xmin, ymax, ymin)
        table = "ds_" + DATASET
        rows = con.execute("SELECT feat FROM {} WHERE {} ORDER BY fid".format(table, box), args).fetchall()
        out = []
        for (blob,) in rows:
            f = json.loads(zlib.decompress(blob).decode("utf-8"))
            geom = (f or {}).get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) >= 2:
                x, y = float(coords[0]), float(coords[1])
                if not (xmin <= x <= xmax and ymin <= y <= ymax):
                    continue
            out.append(f)
        return out
    finally:
        con.close()


def _layer_from_geojson_features(features, name="pack_e911"):
    from qgis.core import QgsFeature, QgsField, QgsFields, QgsGeometry, QgsVectorLayer
    from qgis.PyQt.QtCore import QVariant
    if not features:
        mem = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
        return mem if mem.isValid() else None
    # union of property names, official schema first
    keys, seen = [], set()
    for f in features:
        for k in (f.get("properties") or {}):
            if k not in seen:
                seen.add(k)
                keys.append(k)
    parts = ["Point?crs=EPSG:4326"] + ["field={}:string".format(k) for k in keys]
    mem = QgsVectorLayer("&".join(parts), name, "memory")
    if not mem.isValid():
        return None
    # ensure fields exist (memory URI field= can truncate odd names)
    dp = mem.dataProvider()
    have = {f.name() for f in mem.fields()}
    add = [QgsField(k, QVariant.String) for k in keys if k not in have]
    if add:
        dp.addAttributes(add)
        mem.updateFields()
    names = [f.name() for f in mem.fields()]
    feats = []
    for f in features:
        props = f.get("properties") or {}
        nf = QgsFeature(mem.fields())
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) >= 2:
            nf.setGeometry(QgsGeometry.fromWkt("POINT({} {})".format(float(coords[0]), float(coords[1]))))
        nf.setAttributes([None if props.get(n) is None else str(props.get(n)) for n in names])
        feats.append(nf)
    dp.addFeatures(feats)
    return mem


def load_e911_layer(extent_layer=None, context=None, paths=None):
    """Open the official E911 layer from the configured pack, clipped to extent_layer when given.

    Returns (QgsVectorLayer or None, note). The pack is opened read-only and is never written.
    Temporary memory layers live in this process only.
    """
    src = resolve_e911_source(paths)
    if src is None:
        return None, "no official ND E911 layer (NDGISHUB_address_points) in the configured offline pack"
    if src["kind"] == "gpkg":
        return _open_gpkg(src["path"], extent_layer, context)
    ext = _extent_4326(extent_layer, context) if extent_layer is not None else None
    if ext is None:
        # do not load all 400k+ points unclipped
        return None, ("offline pack SQLite {} has {} but no raster extent was given to clip it; "
                      "pass ADDRESS_POINTS or a depth raster".format(src["path"], DATASET))
    try:
        feats = _sqlite_query(src["path"], ext)
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        return None, "could not read {} from {}: {}".format(DATASET, src["path"], e)
    lyr = _layer_from_geojson_features(feats)
    if lyr is None:
        return None, "could not build an in-memory layer from {}".format(src["path"])
    return lyr, "offline pack SQLite {} ({} features in the raster extent)".format(src["path"], lyr.featureCount())


def describe_source(note, used="pack"):
    if used == "parameter":
        return "Address points: ADDRESS_POINTS parameter ({})".format(note)
    if used == "pack":
        return "Address points: official ND E911 from the configured offline pack ({})".format(note)
    return "Address points: none ({})".format(note)
