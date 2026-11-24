# -*- coding: utf-8 -*-
"""The sampled evaluation of a DamIT Hazard classify run, kept on disk so the next
QGIS session can re-use the raster sampling (the expensive stage) when the inputs
have not changed.

Ported from DamSafety Hazard 2.25.10 evalcache.py and wired into damit:classify.
The file is <output>/QA/_evaluation_cache.bin. It holds a JSON header line (what
the evaluation was made from, plugin version, time) and the state, compressed.
The state is written with pickle, but read back with a restricted reader that
accepts only plain data (numbers, text, lists, dicts, sets, numpy arrays) and
the few QGIS objects the state may contain (geometries, rectangles, coordinate
systems), which are stored as WKB / text. Dates and datetimes are kept as ISO
text (the DamSafety Hazard 2.25.10 fix: 911 / NAIP dates used to refuse every
save). Nothing else can be loaded from it. Anything the writer does not know
makes it refuse to write - the run is never affected; the evaluation is simply
not kept on disk.

The state is inflated with a size cap, MAX_STATE_BYTES (a crafted file in an
outputs folder must not run QGIS out of memory). A state past the cap is a
cache miss, never a crash: load() says why and the run samples in full.

An evaluation is used again only when its key (evaluation_key - the raster
contents, the chosen layers and the settings that shape the sampling), the
plugin version and the age fit. Habitability reviews, the habitable rule, the
USA Structures check and the rail-trains lookup are applied after a cache hit,
so they are not part of the key.
"""

import datetime
import hashlib
import io
import json
import os
import pickle
import time
import zlib

try:
    import numpy as np
except ImportError:                                          # pragma: no cover
    np = None

MAGIC = b"DMEVAL1\n"
FILE_NAME = "_evaluation_cache.bin"
SUBDIR_QA = "QA"
FORMAT = 1
MAX_AGE_DAYS = 7.0
#: The largest pickled state load() inflates (and save() writes). The state is
#: per-receptor records (attributes, outline WKB, sampled values) and a few
#: numpy arrays - no rasters. 1 GiB leaves several times a large inventory,
#: while a crafted file stops there.
MAX_STATE_BYTES = 1024 ** 3

_PLAIN = (type(None), bool, int, float, str, bytes, list, tuple, dict, set, frozenset,
          complex, bytearray)
_NUMPY_NAMES = {"_reconstruct", "scalar", "ndarray", "dtype", "_frombuffer"}
_NUMPY_MODULES = {"numpy", "numpy.core.multiarray", "numpy._core.multiarray",
                  "numpy.core.numeric", "numpy._core.numeric"}


class NotSaved(Exception):
    """The state holds something this module does not write."""


class TooLarge(ValueError):
    """The saved state inflates past MAX_STATE_BYTES."""


def _inflate(blob, max_bytes=MAX_STATE_BYTES):
    """zlib.decompress(blob), refused with TooLarge once the output passes
    max_bytes; never allocates much more than max_bytes."""
    d = zlib.decompressobj()
    out = d.decompress(blob, max_bytes + 1)
    if len(out) > max_bytes or d.unconsumed_tail:
        raise TooLarge("the saved evaluation unpacks to more than {} bytes; refused".format(
            max_bytes))
    out += d.flush()
    if len(out) > max_bytes:
        raise TooLarge("the saved evaluation unpacks to more than {} bytes; refused".format(
            max_bytes))
    return out


def cache_path(out_folder):
    return os.path.join(out_folder, SUBDIR_QA, FILE_NAME)


def plugin_version():
    """Version string from this plugin's metadata.txt, or '0.0.0'."""
    import configparser
    here = os.path.dirname(os.path.abspath(__file__))
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with open(os.path.join(here, "metadata.txt"), encoding="utf-8") as fh:
            cp.read_file(fh)
        return cp.get("general", "version", fallback="0.0.0")
    except (OSError, configparser.Error):
        return "0.0.0"


def file_sig(path):
    """[abspath, size, mtime] of a file, or a missing-file placeholder."""
    if not path:
        return None
    try:
        st = os.stat(path)
        return [os.path.normcase(os.path.abspath(str(path))), int(st.st_size), int(st.st_mtime)]
    except OSError:
        return [str(path), None, None]


def evaluation_key(parts):
    """Stable sha256 of the dict that shapes the sampling stage."""
    try:
        blob = json.dumps(parts, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ----------------------------------------------------------- QGIS objects --
def _crs_token(crs):
    auth = crs.authid() if crs.isValid() else ""
    if auth:
        return ("crs", "auth", auth)
    return ("crs", "wkt", crs.toWkt() if crs.isValid() else "")


def _crs_from(token):
    from qgis.core import QgsCoordinateReferenceSystem
    if token[1] == "auth" or not token[2]:
        return QgsCoordinateReferenceSystem(token[2])
    crs = QgsCoordinateReferenceSystem()
    for name in ("createFromWkt", "createFromString"):
        fn = getattr(crs, name, None)
        if fn is None:
            continue
        try:
            fn(token[2]) if name == "createFromWkt" else fn("WKT:" + token[2])
        except Exception:
            continue
        if crs.isValid():
            return crs
    return QgsCoordinateReferenceSystem("WKT:" + token[2])


def _geom_from(data):
    from qgis.core import QgsGeometry
    if not data:
        return QgsGeometry()
    try:
        return QgsGeometry.fromWkb(data)
    except Exception:
        g = QgsGeometry()
        try:
            g.fromWkb(data)
        except Exception:
            return QgsGeometry()
        return g


def _plain_attr(v):
    """A pickle-safe stand-in for a QGIS / Qt attribute value."""
    if v is None or isinstance(v, (bool, int, float, str, bytes)):
        return v
    if isinstance(v, datetime.datetime) or isinstance(v, datetime.date):
        return v
    try:
        from qgis.PyQt.QtCore import QDate, QDateTime, QVariant
        if isinstance(v, QDate):
            return None if not v.isValid() else datetime.date(v.year(), v.month(), v.day())
        if isinstance(v, QDateTime):
            if not v.isValid():
                return None
            if hasattr(v, "toPyDateTime"):
                return v.toPyDateTime()
            d, t = v.date(), v.time()
            return datetime.datetime(d.year(), d.month(), d.day(), t.hour(), t.minute(), t.second())
        if isinstance(v, QVariant):
            if v.isNull() if hasattr(v, "isNull") else False:
                return None
            return _plain_attr(v.value() if hasattr(v, "value") else None)
    except ImportError:
        pass
    try:
        if hasattr(v, "isNull") and v.isNull():
            return None
    except Exception:
        pass
    if isinstance(v, (list, tuple)):
        return type(v)(_plain_attr(x) for x in v)
    return str(v)


def pack_geoms(geoms):
    """{rid: (layer_key, wkb, plain attrs, field names)} from classify's geoms map."""
    out = {}
    for rid, item in (geoms or {}).items():
        key, geom, attrs, names = item
        wkb = b""
        try:
            if geom is not None and hasattr(geom, "asWkb") and not (hasattr(geom, "isNull") and geom.isNull()):
                wkb = bytes(geom.asWkb())
        except Exception:
            wkb = b""
        out[rid] = (key, wkb, [_plain_attr(a) for a in list(attrs)], list(names))
    return out


def unpack_geoms(packed):
    """Restore classify's geoms map (QgsGeometry objects) from pack_geoms() output."""
    out = {}
    for rid, item in (packed or {}).items():
        key, wkb, attrs, names = item
        out[rid] = (key, _geom_from(wkb), list(attrs), list(names))
    return out


class _Pickler(pickle.Pickler):
    def __init__(self, fh):
        pickle.Pickler.__init__(self, fh, protocol=4)

    def persistent_id(self, obj):
        t = type(obj)
        if t in _PLAIN or (np is not None and (isinstance(obj, (np.generic, np.dtype)) or t is np.ndarray)):
            if np is not None and t is np.ndarray and obj.dtype.hasobject:
                raise NotSaved("array of objects")
            return None
        if getattr(obj, "__module__", None) in _NUMPY_MODULES and \
                getattr(obj, "__name__", None) in _NUMPY_NAMES:
            return None
        # 2.25.10 (DamSafety Hazard, 2026-11-23): 911 record and NAIP flight dates
        # sit in the state, so every save was refused ("cannot keep a date"); kept
        # as ISO text and read back as the same objects.
        if t is datetime.datetime:
            return ("dt", obj.isoformat())
        if t is datetime.date:
            return ("date", obj.isoformat())
        try:
            from qgis.core import (QgsGeometry, QgsRectangle, QgsPointXY,
                                   QgsCoordinateReferenceSystem)
        except ImportError:
            raise NotSaved("cannot keep a {}".format(t.__name__))
        if isinstance(obj, QgsGeometry):
            return ("geom", bytes(obj.asWkb()) if not obj.isNull() else b"")
        if isinstance(obj, QgsRectangle):
            return ("rect", obj.xMinimum(), obj.yMinimum(), obj.xMaximum(), obj.yMaximum())
        if isinstance(obj, QgsPointXY):
            return ("pt", obj.x(), obj.y())
        if isinstance(obj, QgsCoordinateReferenceSystem):
            return _crs_token(obj)
        raise NotSaved("cannot keep a {}".format(t.__name__))


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in _NUMPY_MODULES and name in _NUMPY_NAMES:
            import importlib
            return getattr(importlib.import_module(module), name)
        if module == "builtins" and name in ("set", "frozenset", "complex", "bytearray"):
            import builtins
            return getattr(builtins, name)
        raise pickle.UnpicklingError("{}.{} is not allowed in an evaluation cache".format(
            module, name))

    def persistent_load(self, pid):
        kind = pid[0]
        if kind == "geom":
            return _geom_from(pid[1])
        if kind == "rect":
            from qgis.core import QgsRectangle
            return QgsRectangle(*pid[1:5])
        if kind == "pt":
            from qgis.core import QgsPointXY
            return QgsPointXY(pid[1], pid[2])
        if kind == "crs":
            return _crs_from(pid)
        if kind == "date":
            return datetime.date.fromisoformat(pid[1])
        if kind == "dt":
            return datetime.datetime.fromisoformat(pid[1])
        raise pickle.UnpicklingError("unknown object kind")


def save(out_folder, key, state, when, version, note=None):
    """Write the evaluation to the outputs folder. Returns (path, size) or
    (None, reason): never raises."""
    path = cache_path(out_folder)
    try:
        buf = io.BytesIO()
        _Pickler(buf).dump({"format": FORMAT, "state": state})
        if buf.tell() > MAX_STATE_BYTES:
            return None, "the evaluation is {:.0f} MB, over the {:.0f} MB the cache reads back".format(
                buf.tell() / 1048576.0, MAX_STATE_BYTES / 1048576.0)
        blob = zlib.compress(buf.getvalue(), 1)
        head = json.dumps({"format": FORMAT, "key": key, "version": version, "when": when,
                           "saved_at": time.time(), "size": len(blob),
                           "note": note or ""}, sort_keys=True).encode("utf-8")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(MAGIC + head + b"\n" + blob)
        os.replace(tmp, path)
        return path, len(blob)
    except NotSaved as e:
        return None, str(e)
    except (OSError, pickle.PicklingError, TypeError, ValueError, RecursionError,
            MemoryError) as e:
        return None, "{}: {}".format(type(e).__name__, e)


def read_header(out_folder):
    """The JSON header of the saved evaluation, or None."""
    path = cache_path(out_folder)
    try:
        with open(path, "rb") as fh:
            if fh.read(len(MAGIC)) != MAGIC:
                return None
            head = json.loads(fh.readline().decode("utf-8"))
        return head if isinstance(head, dict) else None
    except (OSError, ValueError):
        return None


def load(out_folder, key, version, max_age_days=MAX_AGE_DAYS, now=None):
    """(state, when, why). state is None on a miss; why then says why (or is None
    when there is no file)."""
    path = cache_path(out_folder)
    if not os.path.isfile(path):
        return None, None, None
    try:
        with open(path, "rb") as fh:
            if fh.read(len(MAGIC)) != MAGIC:
                return None, None, "not an evaluation cache"
            head = json.loads(fh.readline().decode("utf-8"))
            if not isinstance(head, dict):
                return None, None, "unreadable header"
            if head.get("key") != key:
                return None, None, "inputs or sampling settings have changed"
            if str(head.get("version")) != str(version):
                return None, None, "saved by plugin version {} (this is {})".format(
                    head.get("version"), version)
            saved_at = head.get("saved_at")
            if max_age_days is not None and saved_at:
                age_days = ((now if now is not None else time.time()) - float(saved_at)) / 86400.0
                if age_days > max_age_days:
                    return None, None, "{:.0f} days old (limit {:g})".format(age_days, max_age_days)
            blob = fh.read()
            if len(blob) != head.get("size"):
                return None, None, "incomplete file"
        try:
            raw = _inflate(blob, MAX_STATE_BYTES)
        except TooLarge:
            return None, None, "too large to read back (over {:.0f} MB unpacked)".format(
                MAX_STATE_BYTES / 1048576.0)
        data = _Unpickler(io.BytesIO(raw)).load()
        state = data["state"] if isinstance(data, dict) else None
        if not isinstance(state, dict):
            return None, None, "unreadable"
        return state, head.get("when") or "?", None
    except (OSError, ValueError, KeyError, zlib.error, pickle.UnpicklingError, EOFError,
            AttributeError, ImportError, IndexError, TypeError, MemoryError) as e:
        return None, None, "unreadable ({}: {})".format(type(e).__name__, e)


def discard(out_folder):
    try:
        os.remove(cache_path(out_folder))
        return True
    except OSError:
        return False


def files_exist(state):
    """Files the cached state points at that must still be there for the
    re-used evaluation to work."""
    for path in (state or {}).get("raster_paths") or []:
        if path and not os.path.isfile(path):
            return False
    return True

