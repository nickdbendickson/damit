"""DamIT Hazard evaluation cache (ported from DamSafety Hazard 2.25.10).

outputs/QA/_evaluation_cache.bin is inflated with a size cap (evalcache.MAX_STATE_BYTES),
so a crafted file in an outputs folder cannot run QGIS out of memory. A state past the
cap is a cache miss with a reason, never an exception; save() does not write a state
load() would refuse. Dates and datetimes are kept as ISO text (the 2.25.10 fix).

QGIS-free. Loaded as a package member. Invoked by damit_hazard/tests/run_tests.py.
"""
import datetime
import io
import json
import os
import pickle
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from damit_hazard import evalcache as EC  # noqa: E402

KEY, VER = "k1", "9.9.9"


class _Tmp:
    def __enter__(self):
        self.td = tempfile.TemporaryDirectory()
        self.out = self.td.name
        return self

    def __exit__(self, *a):
        self.td.cleanup()


class _Cap:
    def __init__(self, n):
        self.n = n

    def __enter__(self):
        self._orig = EC.MAX_STATE_BYTES
        EC.MAX_STATE_BYTES = self.n

    def __exit__(self, *a):
        EC.MAX_STATE_BYTES = self._orig


def _write_raw(path, blob, key=KEY, version=VER, saved_at=None):
    head = json.dumps({"format": EC.FORMAT, "key": key, "version": version, "when": "t",
                       "saved_at": time.time() if saved_at is None else saved_at,
                       "size": len(blob), "note": ""}).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(EC.MAGIC + head + b"\n" + blob)


def _pickled(state):
    buf = io.BytesIO()
    pickle.dump({"format": EC.FORMAT, "state": state}, buf, protocol=4)
    return buf.getvalue()


def test_cap_is_sane():
    assert EC.MAX_STATE_BYTES == 1024 ** 3
    assert issubclass(EC.TooLarge, ValueError)
    assert EC.MAGIC == b"DMEVAL1\n"


def test_round_trip_plain_state():
    state = {"structs": [{"id": i, "depth": float(i) / 3} for i in range(500)],
             "names": {"a", "b"}, "raster_paths": []}
    with _Tmp() as t:
        path, size = EC.save(t.out, KEY, state, "when", VER)
        assert path == EC.cache_path(t.out) and size > 0, size
        got, when, why = EC.load(t.out, KEY, VER)
        assert why is None, why
        assert when == "when"
        assert got["structs"] == state["structs"] and got["names"] == state["names"]


def test_dates_round_trip():
    """The DamSafety Hazard 2.25.10 fix: dates in the state must save, not 'cannot keep a date'."""
    day = datetime.date(2024, 6, 15)
    stamp = datetime.datetime(2024, 6, 15, 13, 45, 0)
    state = {"flight_date": day, "recorded_at": stamp,
             "rows": [{"id": 1, "naip_date": day, "when": stamp}]}
    with _Tmp() as t:
        path, info = EC.save(t.out, KEY, state, "when", VER)
        assert path, info
        got, when, why = EC.load(t.out, KEY, VER)
        assert why is None, why
        assert got["flight_date"] == day
        assert got["recorded_at"] == stamp
        assert got["rows"][0]["naip_date"] == day
        assert got["rows"][0]["when"] == stamp


def test_numpy_array_round_trip():
    try:
        import numpy as np
    except ImportError:
        return
    state = {"arr": __import__("numpy").arange(1000, dtype="float64")}
    with _Tmp() as t:
        path, size = EC.save(t.out, KEY, state, "when", VER)
        assert path and size > 0
        got, when, why = EC.load(t.out, KEY, VER)
        assert why is None, why
        assert (got["arr"] == state["arr"]).all()


def test_bomb_is_a_cache_miss_not_a_crash():
    raw = _pickled({"blob": b"\0" * (8 * 1024 ** 2)})        # ~8 MiB that packs to a few KB
    blob = zlib.compress(raw, 9)
    assert len(blob) < 64 * 1024
    with _Tmp() as t, _Cap(1024 ** 2):
        _write_raw(EC.cache_path(t.out), blob)
        state, when, why = EC.load(t.out, KEY, VER)
        assert state is None and when is None
        assert why and why.startswith("too large"), why


def test_save_refuses_a_state_past_the_cap():
    state = {"blob": b"x" * 5000}
    with _Tmp() as t, _Cap(1000):
        path, info = EC.save(t.out, KEY, state, "when", VER)
        assert path is None, path
        assert "over the" in str(info) or "MB" in str(info)
        assert not os.path.isfile(EC.cache_path(t.out))


def test_unknown_object_is_not_saved():
    class Weird(object):
        pass
    with _Tmp() as t:
        path, info = EC.save(t.out, KEY, {"x": Weird()}, "when", VER)
        assert path is None
        assert "cannot keep" in str(info)
        assert not os.path.isfile(EC.cache_path(t.out))


def test_key_version_age_and_incomplete_are_misses():
    state = {"ok": True}
    with _Tmp() as t:
        path, _ = EC.save(t.out, KEY, state, "when", VER)
        assert path
        got, _, why = EC.load(t.out, "other-key", VER)
        assert got is None and "changed" in why
        got, _, why = EC.load(t.out, KEY, "0.0.1")
        assert got is None and "version" in why
        got, _, why = EC.load(t.out, KEY, VER, max_age_days=0.0, now=time.time() + 10 * 86400)
        assert got is None and "days old" in why
        # incomplete: truncate the blob
        with open(path, "r+b") as fh:
            fh.seek(0, os.SEEK_END)
            fh.truncate(fh.tell() - 8)
        got, _, why = EC.load(t.out, KEY, VER)
        assert got is None and why


def test_evaluation_key_is_stable_and_sensitive():
    a = EC.evaluation_key({"rasters": [["main", {"depth": ["a", 10, 1]}]], "metres": True})
    b = EC.evaluation_key({"metres": True, "rasters": [["main", {"depth": ["a", 10, 1]}]]})
    c = EC.evaluation_key({"rasters": [["main", {"depth": ["a", 11, 1]}]], "metres": True})
    assert a == b and a != c and len(a) == 64


def test_files_exist_and_discard():
    with _Tmp() as t:
        missing = os.path.join(t.out, "gone.tif")
        present = os.path.join(t.out, "here.tif")
        open(present, "wb").close()
        assert EC.files_exist({"raster_paths": [present]})
        assert not EC.files_exist({"raster_paths": [present, missing]})
        EC.save(t.out, KEY, {"ok": 1}, "when", VER)
        assert os.path.isfile(EC.cache_path(t.out))
        assert EC.discard(t.out)
        assert not os.path.isfile(EC.cache_path(t.out))
        assert EC.load(t.out, KEY, VER) == (None, None, None)


def test_plugin_version_reads_metadata():
    v = EC.plugin_version()
    assert v and v[0].isdigit(), v


def test_no_offline_pack_setting():
    """Hazard's offline_pack setting stays empty / is not introduced by the cache."""
    with open(os.path.join(os.path.dirname(HERE), "evalcache.py"), encoding="utf-8") as fh:
        src = fh.read()
    # the cache must not invent or default an offline pack path
    assert "offline_pack" not in src

