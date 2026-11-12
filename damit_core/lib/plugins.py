"""The DamIT plugins, their Processing provider IDs, and a suite / dependency check.

No DamSafety / ND suite plugin is part of the DamIT suite or required by it; the provider IDs
``nddam`` and ``ndbreach`` belong to those and are never targets of a DamIT hand-off.
"""
import configparser
import os
import re

# folder, display name, Processing provider id (None = no provider), role, required by Setup
SUITE = (
    ("damit_core", "DamIT Core", None, "shared library", True),
    ("damit_catalog", "DamIT Catalog", None, "Appendix A presets, methods and thresholds", True),
    ("damit_setup", "DamIT Setup", None, "start here: suite data folder and hand-off", False),
    ("damit_data", "DamIT Data", "damit_data", "offline structure / footprint / OSM layers", False),
    ("damit_screener", "DamIT Screener", "damit_screen", "preflight, screening chain, hand-off", False),
    ("damit_runner", "DamIT Runner", "damit_run", "prepares and records breach runs", False),
    ("damit_hazard", "DamIT Hazard", "damit", "suggested hazard class from finished runs", False),
    ("damit_hazardlite", "DamIT Hazard Lite", "damit_lite", "one-tool suggested class", False),
    ("damit_pmp", "DamIT PMP", "damit_pmp", "NOAA Atlas 14 precipitation frequency", False),
    ("damit_finder", "DamIT Finder", "damit_find", "dams, ponds and crossings not on the lists", False),
    ("damit_crest", "DamIT Crest", None, "desktop app (outside QGIS)", False),
)
FOREIGN_PROVIDERS = ("nddam", "ndbreach")
HANDOFF_TARGETS = {"preflight": "damit_screen:preflight", "runchain": "damit_screen:runchain",
                   "rundam": "damit_run:rundam", "classify": "damit:classify",
                   "classify_lite": "damit_lite:classify"}


def by_folder(folder):
    for row in SUITE:
        if row[0] == folder:
            return row
    return None


def by_name(name):
    for row in SUITE:
        if row[1] == name:
            return row
    return None


def is_foreign_algorithm(alg_id):
    """True for an nddam:* / ndbreach:* id: a DamIT hand-off refuses those, with no fallback."""
    return str(alg_id or "").split(":", 1)[0].strip().lower() in FOREIGN_PROVIDERS


def read_metadata(plugin_dir):
    path = os.path.join(plugin_dir, "metadata.txt")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            cp.read_file(fh)
    except (OSError, configparser.Error):
        return None
    return dict(cp["general"]) if cp.has_section("general") else None


def parse_version(text):
    nums = [int(x) for x in re.findall(r"\d+", str(text or ""))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def dependencies(meta):
    """plugin_dependencies as [(name, min_version or None)]."""
    out = []
    for part in (meta or {}).get("plugin_dependencies", "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, ver = part.partition("==")
        out.append((name.strip(), ver.strip() or None))
    return out


def plugin_dirs():
    """Folders QGIS loads plugins from (inside QGIS), else the folders on ``sys.path`` holding a
    DamIT plugin (a repository checkout)."""
    dirs = []
    try:
        import qgis.utils as qu
        dirs.extend(getattr(qu, "plugin_paths", []) or [])
    except Exception:                                    # noqa: BLE001 - outside QGIS
        pass
    import sys
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for d in [here] + list(sys.path):
        if d and os.path.isdir(os.path.join(d, "damit_core")) and d not in dirs:
            dirs.append(d)
    return dirs


def active_plugins():
    try:
        import qgis.utils as qu
        return set(getattr(qu, "active_plugins", []) or [])
    except Exception:                                    # noqa: BLE001
        return None


def check_suite(dirs=None, active=None):
    """One row per DamIT plugin: folder, name, provider, present, version, path, active,
    missing_deps (DamIT plugins it names that are absent), foreign_deps (non-DamIT names)."""
    dirs = plugin_dirs() if dirs is None else list(dirs)
    active = active_plugins() if active is None else set(active)
    found = {}
    for d in dirs:
        for row in SUITE:
            p = os.path.join(d, row[0])
            if row[0] not in found and os.path.isfile(os.path.join(p, "metadata.txt")):
                found[row[0]] = (p, read_metadata(p) or {})
    names = {by_folder(f)[1]: m.get("version") for f, (_, m) in found.items()}
    rows = []
    for folder, name, provider, role, required in SUITE:
        path, meta = found.get(folder, (None, None))
        missing, foreign = [], []
        for dep, minv in dependencies(meta):
            if not dep.startswith("DamIT "):
                foreign.append(dep)
            elif dep not in names or (minv and parse_version(names[dep]) < parse_version(minv)):
                missing.append(dep if not minv else "{} >= {}".format(dep, minv))
        rows.append({"folder": folder, "name": name, "provider": provider, "role": role,
                     "required": required, "present": path is not None,
                     "version": (meta or {}).get("version"), "path": path,
                     "active": None if active is None else folder in active,
                     "missing_deps": missing, "foreign_deps": foreign})
    return rows


def status_line(row):
    if not row["present"]:
        return "{} - not installed{}".format(row["name"], " (required)" if row["required"] else "")
    bits = ["{} {}".format(row["name"], row["version"] or "?")]
    if row.get("active") is False:
        bits.append("installed, not enabled")
    if row["missing_deps"]:
        bits.append("needs " + ", ".join(row["missing_deps"]))
    if row["foreign_deps"]:
        bits.append("depends on non-DamIT " + ", ".join(row["foreign_deps"]))
    return " - ".join(bits)


def problems(rows):
    """Blocking problems: a required plugin missing, or any missing / foreign dependency."""
    out = []
    for r in rows:
        if r["required"] and not r["present"]:
            out.append("{} is not installed ({}).".format(r["name"], r["role"]))
        if r["present"] and r["missing_deps"]:
            out.append("{} needs {}.".format(r["name"], ", ".join(r["missing_deps"])))
        if r["present"] and r["foreign_deps"]:
            out.append("{} depends on {} (not part of DamIT).".format(r["name"], ", ".join(r["foreign_deps"])))
    return out
