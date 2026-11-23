"""Record that a classification was reviewed. The mark never writes or lowers a class."""

import csv
import hashlib
import json
import os
import zipfile

DECISIONS = ("Accepted", "Accepted with comments", "Returned")
# Keys a class could be read from. mark_reviewed restores them to the bytes it found.
CLASS_KEYS = ("suggested_class", "suggested_label", "hazard_class", "class",
              "nd_class", "tm11_class", "generic_label", "rule_class")
REVIEW_KEY = "hazard_review"
LOG_NAME = "Review_Log.csv"


def normalize_decision(value):
    t = " ".join(str(value or "").replace("_", " ").replace("/", " ").split()).lower()
    if not t:
        return None
    if t.startswith("return") or t in ("rejected", "reject", "not accepted"):
        return "Returned"
    if "comment" in t and t.startswith("accept"):
        return "Accepted with comments"
    if t.startswith("accept"):
        return "Accepted"
    for d in DECISIONS:
        if t == d.lower():
            return d
    return None


def manifest_sha256(package):
    if not package:
        raise ValueError("no package given")
    package = os.path.abspath(package)
    name = "MANIFEST.csv"
    if os.path.isdir(package):
        path = os.path.join(package, name)
        if not os.path.isfile(path):
            raise ValueError("{} has no {}".format(package, name))
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest(), path
    if os.path.isfile(package) and zipfile.is_zipfile(package):
        with zipfile.ZipFile(package) as zf:
            names = [n for n in zf.namelist() if n.replace("\\", "/").rsplit("/", 1)[-1] == name]
            names.sort(key=lambda n: n.count("/"))
            if not names:
                raise ValueError("{} holds no {}".format(package, name))
            data = zf.read(names[0])
        return hashlib.sha256(data).hexdigest(), "{}!{}".format(package, names[0])
    raise ValueError("{} is neither a package folder nor a zip".format(package))


def _load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("{} is not a JSON object".format(path))
    return data


def _dump(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def mark_reviewed(dam_folder, reviewer="", decision=None, comments="", package=None,
                  open_items=0, when=None):
    """Write hazard_review on dam.json. Class keys already in the file are put back unchanged.

    An empty reviewer (the chain passes only the dam folder) stores a production stamp,
    not an acceptance. Returned with open_items 0 is stored as one open item. Neither
    changes a class.
    """
    if not dam_folder or not os.path.isdir(dam_folder):
        raise ValueError("Dam folder not found: {}".format(dam_folder or "(none)"))
    path = os.path.join(dam_folder, "dam.json")
    rec = _load(path)
    before = {k: rec[k] for k in CLASS_KEYS if k in rec}
    who = " ".join(str(reviewer or "").split())
    dec = normalize_decision(decision) if decision else None
    notes = []
    if who and decision and dec is None:
        raise ValueError("Decision must be one of: {}".format(", ".join(DECISIONS)))
    n_open = int(open_items or 0)
    if dec == "Returned" and n_open < 1:
        n_open = 1
        notes.append("Returned is stored with at least one open item")
    sha = ""
    if package:
        sha, _where = manifest_sha256(package)
    if not who:
        entry = {"mark": "produced", "decision": None, "reviewer": "",
                 "note": "Classification produced. Not an acceptance. Class not changed.",
                 "open_items": n_open, "package_sha256": sha, "comments": comments or "",
                 "when": when or _now()}
    else:
        entry = {"mark": "reviewed", "decision": dec, "reviewer": who,
                 "note": "Review record only. Class not changed.",
                 "open_items": n_open, "package_sha256": sha, "comments": comments or "",
                 "when": when or _now()}
    if notes:
        entry["notes"] = notes
    rec[REVIEW_KEY] = entry
    for k, v in before.items():
        rec[k] = v
    for k in CLASS_KEYS:
        if k not in before:
            rec.pop(k, None)
    _dump(path, rec)
    log_dir = os.path.join(dam_folder, "_classification")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, LOG_NAME)
    new_file = not os.path.isfile(log_path)
    with open(log_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["When", "Reviewer", "Decision", "Open_Items", "Package_SHA256", "Comments"])
        w.writerow([entry["when"], entry["reviewer"], entry["decision"] or "",
                    entry["open_items"], sha, entry["comments"]])
    # the class keys we found are still the class keys on disk
    written = _load(path)
    for k, v in before.items():
        if written.get(k) != v:
            raise RuntimeError("mark_reviewed changed {}".format(k))
    for k in CLASS_KEYS:
        if k not in before and k in written:
            raise RuntimeError("mark_reviewed added a class key {}".format(k))
    return {"dam_json": path, "log_csv": log_path, "review": entry,
            "class_changed": False, "package_sha256": sha}


def _now():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
