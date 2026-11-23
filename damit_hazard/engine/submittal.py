"""A submittal package is a zip of files plus MANIFEST.csv of their SHA-256.

Reviewing the package checks those hashes. A checklist summary counts answers. None of
these writes a hazard class.
"""

import csv
import hashlib
import io
import os
import zipfile

MANIFEST = "MANIFEST.csv"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rows_for(folder, names):
    rows = []
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        rows.append((name.replace("\\", "/"), _sha256(path), os.path.getsize(path)))
    return rows


def build_package(folder, out_zip, names=None):
    """Zip the named files (default: the classify report set that is present)."""
    if names is None:
        names = ["damit_hazard_report.md", "damit_hazard_report.html",
                 "damit_hazard_report.json", "damit_hazard_receptors.gpkg"]
    rows = _rows_for(folder, names)
    if not rows:
        raise ValueError("no submittal files in {}".format(folder))
    os.makedirs(os.path.dirname(os.path.abspath(out_zip)) or ".", exist_ok=True)
    manifest = io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["Name", "SHA256", "Bytes"])
    for row in rows:
        w.writerow(row)
    text = manifest.getvalue()
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, text)
        for name, _sha, _n in rows:
            zf.write(os.path.join(folder, name), name)
    return {"zip": out_zip, "files": [r[0] for r in rows], "manifest": MANIFEST,
            "class_changed": False}


def verify_package(path):
    """Check MANIFEST.csv against the package. Mismatches are listed. No class is written."""
    if os.path.isdir(path):
        manifest_path = os.path.join(path, MANIFEST)
        if not os.path.isfile(manifest_path):
            raise ValueError("no {}".format(MANIFEST))
        with open(manifest_path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        def read(name):
            with open(os.path.join(path, name), "rb") as fh:
                return fh.read()
    elif os.path.isfile(path) and zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        names = zf.namelist()
        man = next((n for n in names if n.replace("\\", "/").rsplit("/", 1)[-1] == MANIFEST), None)
        if man is None:
            raise ValueError("zip has no {}".format(MANIFEST))
        rows = list(csv.DictReader(io.StringIO(zf.read(man).decode("utf-8"))))
        def read(name, zf=zf):
            return zf.read(name)
    else:
        raise ValueError("{} is not a package".format(path))
    mismatches = []
    checked = []
    for row in rows:
        name = row.get("Name") or row.get("name") or ""
        want = (row.get("SHA256") or row.get("sha256") or "").strip().lower()
        try:
            data = read(name)
        except (KeyError, OSError):
            mismatches.append({"name": name, "reason": "missing"})
            continue
        got = hashlib.sha256(data).hexdigest()
        checked.append(name)
        if want and got != want:
            mismatches.append({"name": name, "reason": "sha256 differs"})
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches,
            "class_changed": False}


def summarize_checklist(rows):
    """rows: {item, answer, notes}. answer yes / no / na. A no is an open item, not a class."""
    counts = {"yes": 0, "no": 0, "na": 0, "other": 0}
    open_items = []
    for row in rows or []:
        ans = " ".join(str(row.get("answer") or row.get("Answer") or "").split()).lower()
        item = row.get("item") or row.get("Item") or ""
        if ans in ("yes", "y", "true"):
            counts["yes"] += 1
        elif ans in ("no", "n", "false"):
            counts["no"] += 1
            open_items.append({"item": item, "notes": row.get("notes") or row.get("Notes") or ""})
        elif ans in ("na", "n/a", "not applicable"):
            counts["na"] += 1
        else:
            counts["other"] += 1
            open_items.append({"item": item, "notes": "answer not yes, no or na"})
    return {"counts": counts, "open_items": open_items, "n_open": len(open_items),
            "class_changed": False}
