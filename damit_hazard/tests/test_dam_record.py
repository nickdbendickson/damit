"""Dam record reading (0.2.1): a dam.json with nested "fields" is read as it is, and with no DAM_JSON a record is
found above the result rasters or in the run watcher's folder. Pure Python (no QGIS)."""
import json
import os
import shutil
import tempfile

from _helpers import ROOT  # noqa: F401
from damit_hazard.engine import core, dam_record as DR


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


NESTED = {"format": "nd_dam_suite/dam_record", "format_version": 1,
          "fields": {"dam_id": "ND00045", "name": "Test Dam", "height_ft": 37.0, "storage_acft": 250.0},
          "sources": {"_seed": {"tool": "x"}}, "status": []}


class _Tmp(object):
    def __enter__(self):
        self.d = tempfile.mkdtemp(prefix="damit_damrec_")
        return self.d

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)


def test_nested_fields_are_flattened_and_bookkeeping_dropped():
    flat = DR.flatten(NESTED)
    assert flat["dam_id"] == "ND00045" and flat["storage_acft"] == 250.0
    for k in ("fields", "sources", "status", "format", "format_version"):
        assert k not in flat, k
    # the nested fields win over a same-named top-level value; other top-level values stay
    flat = DR.flatten({"dam_id": "X", "is_new": True, "fields": {"dam_id": "ND00045"}})
    assert flat == {"dam_id": "ND00045", "is_new": True}


def test_a_flat_record_is_unchanged():
    rec = {"dam_id": "ND00199", "storage_acft": 300, "fields": "not a dict"}
    assert DR.flatten(rec) is rec
    rec = {"dam_id": "ND00199", "storage_acft": 300}
    assert DR.flatten(rec) is rec


def test_load_reports_nested_or_flat_and_refuses_a_non_object():
    with _Tmp() as d:
        flat, nested = DR.load(_w(os.path.join(d, "n.json"), NESTED))
        assert nested and flat["dam_id"] == "ND00045"
        flat, nested = DR.load(_w(os.path.join(d, "f.json"), {"dam_id": "ND00199"}))
        assert not nested and flat == {"dam_id": "ND00199"}
        try:
            DR.load(_w(os.path.join(d, "l.json"), [1, 2]))
        except ValueError:
            pass
        else:
            raise AssertionError("a JSON list is not a dam record")


def test_nested_record_passes_the_nid_rule_once_flattened():
    assert core.nid_rule(NESTED)[0]                 # the nested file read as-is has no top-level dam_id
    assert core.nid_rule(DR.flatten(NESTED)) == (None, None, "ND00045")


def test_discover_finds_the_dam_json_above_the_raster_nested_or_flat():
    with _Tmp() as d:
        dam = os.path.join(d, "dams", "ND00045")
        _w(os.path.join(dam, "dam.json"), NESTED)
        tif = os.path.join(dam, "run_1", "outputs", "Depth (Max).tif")
        os.makedirs(os.path.dirname(tif))
        open(tif, "wb").close()
        path, kind = DR.discover([tif], base=os.path.join(d, "nowatch"))
        assert path == os.path.join(dam, "dam.json") and "nested" in kind
        _w(os.path.join(dam, "dam.json"), {"dam_id": "ND00045"})
        path, kind = DR.discover([tif + "|layername=x"], base=os.path.join(d, "nowatch"))
        assert path == os.path.join(dam, "dam.json") and kind == "dam.json"


def test_discover_does_not_climb_past_four_folders():
    with _Tmp() as d:
        _w(os.path.join(d, "dam.json"), {"dam_id": "ND00045"})
        deep = os.path.join(d, "a", "b", "c", "d", "e", "x.tif")
        os.makedirs(os.path.dirname(deep))
        assert DR.discover([deep], base=os.path.join(d, "nowatch")) == (None, None)
        near = os.path.join(d, "a", "b", "c", "d", "x.tif")
        assert DR.discover([near], base=os.path.join(d, "nowatch"))[0] == os.path.join(d, "dam.json")


def test_a_dam_json_without_an_id_is_skipped_for_the_watcher_copy():
    with _Tmp() as d:
        run = os.path.join(d, "dams", "ND00045", "run_20261111_213034")
        _w(os.path.join(d, "dams", "ND00045", "dam.json"), {"fields": {"name": "no id"}})
        tif = os.path.join(run, "outputs", "Depth (Max).tif")
        os.makedirs(os.path.dirname(tif))
        watch = os.path.join(d, "watch")
        flat = _w(os.path.join(watch, "ND00045_run_20261111_213034", "dam_record_hazard.json"),
                  {"dam_id": "ND00045", "nid_id": "ND00045", "height_ft": 37})
        path, kind = DR.discover([tif], base=watch)
        assert path == flat and "run watcher copy" in kind


def test_the_watcher_copy_must_belong_to_the_same_dam_and_run():
    with _Tmp() as d:
        run = os.path.join(d, "x", "run_1")
        tif = os.path.join(run, "outputs", "Depth (Max).tif")
        os.makedirs(os.path.dirname(tif))
        watch = os.path.join(d, "watch")
        # another dam's run of the same name: folder says ND00046, the copy says ND00045
        _w(os.path.join(watch, "ND00046_run_1", "dam_record_hazard.json"), {"dam_id": "ND00045"})
        assert DR.discover([tif], base=watch) == (None, None)
        # another run
        _w(os.path.join(watch, "ND00045_run_2", "dam_record_hazard.json"), {"dam_id": "ND00045"})
        assert DR.discover([tif], base=watch) == (None, None)
        good = _w(os.path.join(watch, "ND00045_run_1", "dam_record_hazard.json"), {"dam_id": "ND00045"})
        assert DR.discover([tif], base=watch)[0] == good


def test_watch_folder_can_come_from_the_environment():
    with _Tmp() as d:
        tif = os.path.join(d, "x", "run_1", "outputs", "Depth (Max).tif")
        os.makedirs(os.path.dirname(tif))
        good = _w(os.path.join(d, "w", "ND00045_run_1", "dam_record_hazard.json"), {"dam_id": "ND00045"})
        old = os.environ.get(DR.WATCH_DIR_ENV)
        os.environ[DR.WATCH_DIR_ENV] = os.path.join(d, "w")
        try:
            assert DR.discover([tif])[0] == good
        finally:
            if old is None:
                os.environ.pop(DR.WATCH_DIR_ENV, None)
            else:
                os.environ[DR.WATCH_DIR_ENV] = old


def test_nothing_found_is_none():
    with _Tmp() as d:
        tif = os.path.join(d, "a", "x.tif")
        os.makedirs(os.path.dirname(tif))
        assert DR.discover([tif], base=os.path.join(d, "none")) == (None, None)
        assert DR.discover([], base=d) == (None, None)
