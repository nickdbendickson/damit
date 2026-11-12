"""Reading the dam record for damit:classify (0.2.1): flat or nested, given or found.

damit:classify's DAM_JSON is a FLAT record (top-level dam_id / nid_id, storage_acft, current_class, ...). The dam
folder's own dam.json (DamIT Crest, the Screener / Runner, dam_chain seed) nests the values under "fields"
({"format": ..., "fields": {...}, "sources": {...}, "status": [...]}). Both are read now, so nobody has to
hand-flatten it:

    load(path)      the flat record: the nested "fields" on top of any top-level values; a flat file is unchanged
    discover(paths) with no DAM_JSON given: the nearest dam.json above the result rasters (up to 4 folders up), else
                    the run watcher's flat copy ~/local-ai/watch/<dam id>_<run folder>/dam_record_hazard.json that
                    Lumo's run watcher (lumo_watch) writes beside its digest (never into the dam or run folder)

A record found this way is NOT trusted blindly: the caller did not ask for it, so a record that has no usable dam id
is skipped (the classify run still goes on without it), and the report names the file that was used. Pure Python and
the standard library; no QGIS import.
"""
import glob
import json
import os

NESTED_KEY = "fields"
WATCH_FLAT_NAME = "dam_record_hazard.json"
WATCH_DIR_ENV = "DAMIT_WATCH_DIR"            # default ~/local-ai/watch (the run watcher's output folder)
LEVELS_UP = 4                                # folders above a raster that are searched for dam.json
# Top-level keys of a nested dam.json that describe the file, not the dam.
_META_KEYS = (NESTED_KEY, "sources", "status", "format", "format_version")


def flatten(rec):
    """The flat dam record of a parsed JSON value. A record with a "fields" object gives those fields, over any
    other top-level values (the file's own bookkeeping keys are dropped); anything else is returned as it is."""
    if not isinstance(rec, dict):
        return rec
    nested = rec.get(NESTED_KEY)
    if not isinstance(nested, dict):
        return rec
    flat = {k: v for k, v in rec.items() if k not in _META_KEYS}
    flat.update(nested)
    return flat


def load(path):
    """(flat record, nested?) of a dam record file. Raises OSError / ValueError like json.load does."""
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    nested = isinstance(rec, dict) and isinstance(rec.get(NESTED_KEY), dict)
    flat = flatten(rec)
    if not isinstance(flat, dict):
        raise ValueError("a dam record is a JSON object, not a {}".format(type(flat).__name__))
    return flat, nested


def has_id(rec):
    return isinstance(rec, dict) and any(str(rec.get(k) or "").strip() for k in ("dam_id", "nid_id"))


def _dirs_above(paths, levels=LEVELS_UP):
    out = []
    for p in paths or []:
        p = os.path.abspath(str(p).split("|")[0])
        d = p if os.path.isdir(p) else os.path.dirname(p)
        for _ in range(levels + 1):
            if d not in out:
                out.append(d)
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return out


def watch_base(base=None):
    return base or os.environ.get(WATCH_DIR_ENV) or os.path.join(os.path.expanduser("~"), "local-ai", "watch")


def discover(raster_paths, base=None):
    """(path, kind) of a dam record found for these result rasters, or (None, None).

    1. dam.json in the rasters' folder or up to 4 folders above it (the dam folder, or the run folder's parent) with
       a dam id (nested or flat);
    2. the watcher's flat copy: <base>/<dam id>_<folder name>/dam_record_hazard.json, where <folder name> is one of
       those folders (the run folder) and <dam id> is the copy's own dam_id, so another dam's run of the same name is
       never used. The newest copy wins."""
    dirs = _dirs_above(raster_paths)
    for d in dirs:
        p = os.path.join(d, "dam.json")
        if os.path.isfile(p):
            try:
                rec, nested = load(p)
            except (OSError, ValueError):
                continue
            if has_id(rec):
                return p, "dam.json (nested fields)" if nested else "dam.json"
    wb = watch_base(base)
    if os.path.isdir(wb):
        hits = []
        for d in dirs:
            name = os.path.basename(d)
            if not name:
                continue
            for p in glob.glob(os.path.join(glob.escape(wb), "*_" + glob.escape(name), WATCH_FLAT_NAME)):
                try:
                    rec, _n = load(p)
                except (OSError, ValueError):
                    continue
                dam = str(rec.get("dam_id") or rec.get("nid_id") or "").strip()
                if dam and os.path.basename(os.path.dirname(p)) == "{}_{}".format(dam, name):
                    hits.append((os.path.getmtime(p), p))
        if hits:
            return max(hits)[1], "run watcher copy ({})".format(WATCH_FLAT_NAME)
    return None, None
