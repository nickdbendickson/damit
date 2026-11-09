"""DamIT Setup logic (pure Python): folder scan, suite check, settings fill, hand-off.

The scan is jurisdiction-neutral: it recognizes layers by file / folder name (dams, terrain,
structures, roads, rail) and the folders DamIT Data writes (<STATE>/nsi, microsoft_footprints,
osm, usa_structures). It never requires a North Dakota pack. Hand-off targets are DamIT tools only.
"""
import json
import os
import re

from . import _deps  # noqa: F401
from damit_core.lib import dam_record, plugins, settings

VECTOR_EXT = (".gpkg", ".shp", ".geojson", ".json", ".fgb", ".csv", ".sqlite")
RASTER_EXT = (".tif", ".tiff", ".vrt", ".img", ".asc")
MAX_DEPTH = 4
MAX_FILES = 20000

# slot -> (regex on the lower-case relative path, extensions, what it is for, required)
SLOTS = (
    ("dams", r"(^|[/_\-. ])(dams?|nid|dam_points|inventory)([/_\-. ]|$)", VECTOR_EXT,
     "dam points for DamIT Screener", True),
    ("terrain", r"(dem|dtm|terrain|elev|lidar|3dep)", RASTER_EXT, "terrain (DEM)", False),
    ("structures", r"(nsi|structure|building|footprint|microsoft|overture|usa_structures)", VECTOR_EXT,
     "structures / building footprints (receptors)", False),
    ("roads", r"(road|street|highway|hpms)", VECTOR_EXT, "roads (receptors)", False),
    ("rail", r"(rail|narn)", VECTOR_EXT, "railroads (receptors)", False),
)
SETTING_FOR_SLOT = {"dams": "dams_layer", "terrain": "terrain", "structures": "structures_layer",
                    "roads": "roads_layer", "rail": "rail_layer"}
SCREEN_SETTINGS = "damit_screen_settings.json"
TARGETS = (plugins.HANDOFF_TARGETS["preflight"], plugins.HANDOFF_TARGETS["runchain"],
           plugins.HANDOFF_TARGETS["rundam"])


def scan(folder):
    """{slot: [paths, best first]} and notes. Read-only; skips hidden folders and .part files."""
    found = {s[0]: [] for s in SLOTS}
    notes = []
    if not folder or not os.path.isdir(folder):
        return found, ["Folder not found: {}".format(folder)]
    root = os.path.abspath(folder)
    count = 0
    for base, dirs, files in os.walk(root):
        rel_base = os.path.relpath(base, root)
        depth = 0 if rel_base == "." else rel_base.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not d.endswith(".gdb")) \
            if depth < MAX_DEPTH else []
        for f in sorted(files):
            count += 1
            if count > MAX_FILES:
                notes.append("Stopped after {} files; pick a smaller folder.".format(MAX_FILES))
                return found, notes
            low = f.lower()
            if low.startswith(".") or low.startswith(".part_"):
                continue
            ext = os.path.splitext(low)[1]
            rel = (os.path.join(rel_base, f) if rel_base != "." else f).lower().replace(os.sep, "/")
            for slot, rx, exts, _what, _req in SLOTS:
                if ext in exts and re.search(rx, rel):
                    found[slot].append(os.path.join(base, f))
                    break
    for slot in found:
        found[slot].sort(key=lambda p: (p.count(os.sep), len(p)))
    return found, notes


def scan_lines(found):
    """('ok'|'missing', slot, text) per slot."""
    out = []
    for slot, _rx, _exts, what, required in SLOTS:
        paths = found.get(slot) or []
        if paths:
            more = " (+{} more)".format(len(paths) - 1) if len(paths) > 1 else ""
            out.append(("ok", slot, "{}: {}{}".format(what, paths[0], more)))
        else:
            out.append(("missing", slot, "{}: not found{}".format(
                what, " - required to screen dams" if required else " - optional")))
    return out


def problem(data_folder, work_folder, found, suite_rows):
    """The first reason Continue is off, or ''."""
    if not data_folder:
        return "Pick the suite data folder."
    if not os.path.isdir(data_folder):
        return "Suite data folder not found: {}".format(data_folder)
    if not work_folder:
        return "Pick a work folder for runs."
    if _inside(work_folder, data_folder):
        return "The work folder must not be inside the suite data folder (results never go there)."
    probs = plugins.problems(suite_rows)
    if probs:
        return probs[0]
    if not found.get("dams"):
        return "No dam layer found in the suite data folder (a file or folder named dams / nid ...)."
    return ""


def _inside(child, parent):
    c, p = os.path.abspath(child), os.path.abspath(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def fill_settings(data_folder, work_folder, found, state="", preset=""):
    """Save the folder choices (always) and fill empty layer / state / preset settings from the
    scan. Returns the keys written."""
    written = []
    for k, v in (("data_folder", data_folder), ("work_folder", work_folder)):
        if v and settings.get(k) != v:
            settings.set(k, v)
            written.append(k)
    fill = {SETTING_FOR_SLOT[s]: (found.get(s) or [""])[0] for s in SETTING_FOR_SLOT}
    fill.update({"state": state, "preset": preset})
    written.extend(settings.fill_empty(fill))
    return written


def screener_settings(preset="", mode="preset", terrain="", field_map=None, catalog_dir=""):
    """A DamIT Screener SETTINGS document (keys of damit_screener.core.workflow.DEFAULT_SETTINGS)."""
    doc = {"mode": mode, "preset": preset if mode == "preset" else "", "terrain": terrain or "",
           "field_map": dict(field_map or {}), "catalog_dir": catalog_dir or ""}
    return doc


def write_screener_settings(work_folder, doc):
    os.makedirs(work_folder, exist_ok=True)
    path = os.path.join(work_folder, SCREEN_SETTINGS)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    return path


def preflight_params(work_folder, dams="", terrain="", receptors="", preset="", mode="preset",
                     field_map=None, settings_path=""):
    """Parameters for damit_screen:preflight (MODE 0 = preset, 1 = custom)."""
    p = {"WORK": work_folder, "MODE": 1 if mode == "custom" else 0, "PRESET": preset if mode == "preset" else "",
         "FIELD_MAP": dam_record.field_map_string(field_map or {})}
    if dams:
        p["DAMS"] = dams
    if terrain:
        p["TERRAIN"] = terrain
    if receptors:
        p["RECEPTORS"] = receptors
    if settings_path:
        p["SETTINGS"] = settings_path
    return p


def handoff_target(alg_id):
    """The algorithm id to open, checked: DamIT targets only; nddam / ndbreach refused."""
    if plugins.is_foreign_algorithm(alg_id):
        raise ValueError("{} is not a DamIT tool; DamIT Setup hands off to {} only.".format(
            alg_id, ", ".join(TARGETS)))
    if alg_id not in TARGETS:
        raise ValueError("unknown hand-off target {!r}; use one of {}".format(alg_id, ", ".join(TARGETS)))
    return alg_id
