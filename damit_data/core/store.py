"""Where DamIT Data keeps its downloads, and the manifest of what is there.

Layout: ``<root>/<area>/<source folder>/...`` with ``<area>`` a state postal code or
``extent_<hash>``, and ``<root>/damit_data_manifest.json``. The root is, first that applies: the
folder given to the tool, the DamIT ``data_folder`` setting, ``~/Documents/DamIT Data``.
A folder inside an ND Dam Suite offline pack (``ND_Dam_Suite_Pack``) is refused: DamIT Data never
writes into it.
"""
import datetime
import fnmatch
import json
import os
import tempfile

from damit_core.lib import settings

MANIFEST = "damit_data_manifest.json"
FORBIDDEN_PARTS = ("nd_dam_suite_pack",)


class StoreError(ValueError):
    pass


def root(folder=None):
    r = folder or settings.get("data_folder") or os.path.join(os.path.expanduser("~"), "Documents", "DamIT Data")
    r = os.path.abspath(r)
    check_writable_target(r)
    return r


def check_writable_target(path):
    parts = [p.lower() for p in os.path.abspath(path).split(os.sep)]
    for bad in FORBIDDEN_PARTS:
        if any(p == bad or p.startswith(bad) for p in parts):
            raise StoreError("DamIT Data does not write into an ND Dam Suite offline pack ({}). Pick another "
                             "folder.".format(path))
    return path


def target_dir(root_dir, plan):
    return os.path.join(root_dir, plan["area"], plan["folder"])


def read_manifest(root_dir):
    try:
        with open(os.path.join(root_dir, MANIFEST), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {"entries": {}}
    except (OSError, ValueError):
        return {"schema": "damit.data_manifest", "schema_version": 1, "entries": {}}


def write_manifest(root_dir, man):
    os.makedirs(root_dir, exist_ok=True)
    man.setdefault("schema", "damit.data_manifest")
    man.setdefault("schema_version", 1)
    fd, tmp = tempfile.mkstemp(prefix=".manifest_", dir=root_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(root_dir, MANIFEST))


def entry_key(plan):
    return "{}/{}".format(plan["area"], plan["id"])


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def layer_files(root_dir, entry):
    """Layer files of one manifest entry (relative paths in entry['files'] matching its globs)."""
    out = []
    for rel in entry.get("files") or []:
        name = os.path.basename(rel.rstrip("/"))
        if any(fnmatch.fnmatch(name.lower(), g.lower()) for g in entry.get("layer_globs") or ["*"]):
            out.append(os.path.join(root_dir, rel))
    return out


def all_layers(root_dir):
    man = read_manifest(root_dir)
    out = []
    for key in sorted(man.get("entries", {})):
        e = man["entries"][key]
        out.extend((key, p) for p in layer_files(root_dir, e) if os.path.exists(p))
    return out
