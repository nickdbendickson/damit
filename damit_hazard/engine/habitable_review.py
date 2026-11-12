"""The engineer's habitability review of structures: habitable_review.json in the dam folder (0.4.0).

Only an ND 911 address point is habitable by itself. Any other structure (NSI, USA Structures, ...) is
"unverified" until an engineer reviews it in Hazard; the review is saved here and read by every later classify run
and depth-velocity chart. Like the Runner's review.json (the class of record), the file is written ONLY by
sign_off() / the damit:reviewhabitable algorithm, an explicit engineer action; classify, the chart and the Screener
never write it (a test checks this). Names follow the DamSafety Hazard decisions: `reviewed_habitable` true / false.

    {"schema": "damit-habitable-review-v1",
     "reviews": {"<structure key>": {"reviewed_habitable": true, "decided_by": "A. Engineer",
                                     "decided_on": "2026-11-12", "note": "occupied farmhouse (site visit)"}},
     "history": [{"key": ..., "reviewed_habitable": true, "decided_by": ..., "decided_on": ..., "note": ...}]}

The structure key is "field:value" of a stable attribute of the layer (NSI bid / fd_id, nguid, crest_id ...;
receptors.review_key), else the receptor id of that run (the layer's feature id; only stable for the same layer).
Pure Python and the standard library.
"""
import datetime
import json
import csv
import os

REVIEW_FILE = "habitable_review.json"
SCHEMA = "damit-habitable-review-v1"
MAX_BYTES = 32 * 1024 * 1024
LEVELS_UP = 2                       # folders above the depth raster that are searched


def _text(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def load(path):
    """({key: entry}, [problems]). A missing file is ({}, []); an unreadable or invalid one is ({}, [why]):
    classify then carries on with no reviews and says why."""
    if not path or not os.path.isfile(path):
        return {}, []
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {}, ["{} is too large".format(os.path.basename(path))]
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return {}, ["{} unreadable: {}".format(os.path.basename(path), e)]
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("reviews"), dict):
        return {}, ["{} is not a {} file".format(os.path.basename(path), SCHEMA)]
    out, probs = {}, []
    for k, e in data["reviews"].items():
        if isinstance(e, dict) and isinstance(e.get("reviewed_habitable"), bool):
            out[str(k)] = e
        else:
            probs.append("review of {} has no true / false reviewed_habitable: ignored".format(k))
    return out, probs


def find(paths):
    """The habitable_review.json in the folder of the first path (a raster) or up to LEVELS_UP folders above it,
    else None."""
    for p in paths or []:
        d = os.path.dirname(os.path.abspath(str(p).split("|")[0]))
        for _ in range(LEVELS_UP + 1):
            f = os.path.join(d, REVIEW_FILE)
            if os.path.isfile(f):
                return f
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return None


def apply(receptors, reviews):
    """Set reviewed_habitable (and review_by / review_on / review_note) on the receptors that have a review;
    returns how many. Others keep reviewed_habitable None (unverified unless a 911 point)."""
    from . import receptors as R
    n = 0
    for r in receptors:
        r["reviewed_habitable"] = None
        e = reviews.get(R.review_key(r)) if r.get("kind") == "structure" else None
        if e is not None:
            r["reviewed_habitable"] = e["reviewed_habitable"]
            r["review_by"], r["review_on"], r["review_note"] = e.get("decided_by"), e.get("decided_on"), e.get("note")
            n += 1
    return n


def sign_off(path, keys, habitable, decided_by, note="", decided_on=None):
    """ENGINEER ACTION ONLY (never call it from run / classify / chart code). Save reviewed_habitable = habitable
    (True / False) for each structure key; habitable None removes the review of those keys. The file is rewritten
    atomically and every change is appended to its history. Returns the path."""
    keys = [str(k).strip() for k in keys if str(k).strip()]
    if not keys:
        raise ValueError("no structure keys given")
    by = _text(decided_by)
    if not by:
        raise ValueError("decided_by is required: who reviewed these structures")
    if habitable is not None and not isinstance(habitable, bool):
        raise ValueError("habitable must be True, False or None (remove)")
    on = decided_on or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(on)
    except (TypeError, ValueError):
        raise ValueError("decided_on must be a date YYYY-MM-DD")
    data = {"schema": SCHEMA, "reviews": {}, "history": []}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
        if not isinstance(old, dict) or old.get("schema") != SCHEMA:
            raise ValueError("{} exists and is not a {} file; not overwritten".format(path, SCHEMA))
        data["reviews"] = dict(old.get("reviews") or {})
        data["history"] = list(old.get("history") or [])
    for k in keys:
        entry = {"key": k, "reviewed_habitable": habitable, "decided_by": by, "decided_on": on,
                 "note": _text(note) or ""}
        data["history"].append(entry)
        if habitable is None:
            data["reviews"].pop(k, None)
        else:
            data["reviews"][k] = {x: entry[x] for x in ("reviewed_habitable", "decided_by", "decided_on", "note")}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def keys_from(text, csv_path=None):
    """Structure keys from the typed list (commas, semicolons, new lines) and the struct_key column of a CSV."""
    keys = [k.strip() for k in (text or "").replace(";", ",").replace("\n", ",").split(",") if k.strip()]
    if csv_path:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            if "struct_key" not in (rd.fieldnames or []):
                raise ValueError("{} has no struct_key column".format(os.path.basename(csv_path)))
            keys += [row["struct_key"].strip() for row in rd if (row.get("struct_key") or "").strip()]
    return list(dict.fromkeys(keys))
