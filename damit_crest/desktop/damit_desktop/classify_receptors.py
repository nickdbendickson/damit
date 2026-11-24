"""The real receptors the classify algorithm judged, read back from its GeoPackage(s), for the Dashboard and the printed
report: every receptor with a hit or water on it, with a name and a point to zoom the map to.

- DamIT profile: damit:classify's damit_hazard_receptors.gpkg (tables structures / roads / rail, lon/lat), names
  joined from the classify_inputs layers the desk wrote; the "needs ruling" summary from damit_hazard_report.json.
- North Dakota profile: ndhazard:classify (DamSafety Hazard) writes one GeoPackage per layer in
  <dam folder>/outputs/Classification: Habitable_Structures.gpkg, Roads_Inundated.gpkg and Rail_Inundated.gpkg, in
  EPSG:5070, with the ND class per feature (ND_Outcome on structures, ND_Class on roads and rail) and its basis.
  Read from a real ndhazard:classify 2.25.8 run on Absaraka ND00199 (2026-11-22). Any one of the three names reads
  all three; the "needs ruling" summary is worked out from the features themselves (nd_ruling).

Absaraka desk test 2026-11-21: classify counted 230 wet structures while the Dashboard and the report table listed only
the desk's own 4 address points. Read-only; only those file names, and only inside a work folder.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

from damit_desktop.browser_io import BrowserIOError
from damit_desktop.qgis_run import allowed_work_roots, unruled_top
from damit_desktop.real_receptors import to_lonlat

GPKG_NAME = "damit_hazard_receptors.gpkg"
#: ndhazard:classify's receptor layers (outputs/Classification) -> the desk's layer name.
ND_FILES = {"Habitable_Structures.gpkg": "STRUCTURES", "Roads_Inundated.gpkg": "ROADS", "Rail_Inundated.gpkg": "RAIL"}
#: Every receptor file this module reads.
RECEPTOR_FILES = (GPKG_NAME, *ND_FILES)
#: ND_Outcome of a habitable structure -> the ND class it gives (REG_05.2026 5.2.1.1 / 5.2.2: judgment-zone houses are
#: Medium by rule). "Below consequence depth" is wet with no class; "Not inundated" is dry and not listed.
ND_OUTCOME_CLASS = {"probable loss of life": "High", "judgment zone": "Medium", "inundated (economic loss)": "Medium"}
#: ND class word -> the desk's ordinal (hazard_class: Low 1, Medium / Significant 2, High 3).
ND_ORDINAL = {"low": 1, "medium": 2, "significant": 2, "high": 3}
#: Flags the ND reader sets on a feature whose class rests on a value the engineer still has to rule on.
ND_UNRULED = ("aadt_assumed", "crossing_unconfirmed", "habitability_unverified")
_LONLAT_EPSG = (4326, 4269, 4258, 4617, 4283)
#: GeoPackage table -> (layer name used by the desk, classify_inputs file)
TABLES = {"structures": ("STRUCTURES", "structures.geojson"), "roads": ("ROADS", "roads.geojson"),
          "rail": ("RAIL", "rail.geojson")}
#: The most receptors sent back (strongest class, then deepest, first); the GeoPackage keeps them all.
MAX_ROWS = 2000
#: USACE NSI occupancy codes in words (the prefix before the first hyphen).
OCCUPANCY = {"RES1": "single-family home", "RES2": "mobile home", "RES3": "multi-family", "RES4": "lodging",
             "RES5": "institutional dormitory", "RES6": "nursing home", "COM": "commercial", "IND": "industrial",
             "AGR1": "agricultural", "REL1": "church", "GOV1": "government", "GOV2": "emergency response",
             "EDU1": "school", "EDU2": "college"}
_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


class ReceptorsError(BrowserIOError):
    pass


def gpkg_path(requested: str) -> Path:
    """The GeoPackage asked for, only when it is one of RECEPTOR_FILES inside an allowed work folder."""
    if not isinstance(requested, str) or not requested.strip() or "\x00" in requested:
        raise ReceptorsError("no GeoPackage given")
    path = Path(requested.strip()).expanduser().resolve()
    if path.name not in RECEPTOR_FILES:
        raise ReceptorsError(f"only {', '.join(RECEPTOR_FILES)} are read here")
    if not any(path == r or r in path.parents for r in allowed_work_roots()):
        raise ReceptorsError("the GeoPackage must be inside the work folder")
    if not path.is_file():
        alg = "ndhazard:classify" if path.name in ND_FILES else "damit:classify"
        raise ReceptorsError(f"{path} does not exist (run {alg} again)")
    return path


def _wkb_parse(wkb: bytes, off: int):
    """(points, offset after this geometry) of a 2-D WKB geometry: Point, LineString, Polygon (every ring) and their
    Multi* forms. Other types give no points and stop the walk."""
    order = "<" if wkb[off] == 1 else ">"
    gtype = struct.unpack_from(order + "I", wkb, off + 1)[0] % 1000
    p = off + 5
    if gtype == 1:
        return [struct.unpack_from(order + "dd", wkb, p)], p + 16
    if gtype == 2:
        n = struct.unpack_from(order + "I", wkb, p)[0]
        return [struct.unpack_from(order + "dd", wkb, p + 4 + 16 * i) for i in range(n)], p + 4 + 16 * n
    if gtype == 3:
        n_rings = struct.unpack_from(order + "I", wkb, p)[0]
        q, out = p + 4, []
        for ring in range(n_rings):
            n = struct.unpack_from(order + "I", wkb, q)[0]
            if ring == 0:  # the outer ring is enough to place and box a polygon
                out = [struct.unpack_from(order + "dd", wkb, q + 4 + 16 * i) for i in range(n)]
            q += 4 + 16 * n
        return out, q
    if gtype in (4, 5, 6, 7):
        n = struct.unpack_from(order + "I", wkb, p)[0]
        out, q = [], p + 4
        for _ in range(n):
            part, q = _wkb_parse(wkb, q)
            out += part
        return out, q
    return [], len(wkb)


def _wkb_coords(wkb: bytes, off: int = 0):
    """(x, y) points of a 2-D WKB Point / LineString / Polygon (outer ring) / Multi* geometry, else []."""
    return _wkb_parse(wkb, off)[0]


def gpkg_geometry(blob: bytes | None, epsg: int | None = None):
    """A GeoPackage geometry blob -> (point to zoom to, [west, south, east, north]) in lon/lat, or (None, None).
    epsg: the layer's CRS when it is not lon/lat (ndhazard:classify writes EPSG:5070); a CRS real_receptors.to_lonlat
    does not know gives (None, None) rather than a point in the wrong place."""
    if not blob or len(blob) < 8 or blob[:2] != b"GP":
        return None, None
    flags = blob[3]
    env = _ENVELOPE_BYTES.get((flags >> 1) & 7, 0)
    try:
        pts = _wkb_coords(blob, 8 + env)
    except struct.error:
        return None, None
    if pts and epsg and epsg not in _LONLAT_EPSG:
        pts = [to_lonlat(epsg, x, y) for x, y in pts]
        if any(p is None for p in pts):
            return None, None
    if not pts:
        return None, None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mid = pts[len(pts) // 2]
    return [round(mid[0], 6), round(mid[1], 6)], [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]


def _name(layer: str, props: dict, rid: str) -> str:
    """A receptor's name in words from its classify_inputs feature."""
    if layer == "STRUCTURES":
        if props.get("name"):
            return str(props["name"])
        occ = str(props.get("occtype") or "").strip()
        if occ:
            code = occ.split("-")[0]
            words = OCCUPANCY.get(code) or OCCUPANCY.get(code[:4]) or OCCUPANCY.get(code.rstrip("0123456789"), "")
            fd = props.get("fd_id")
            return " · ".join(b for b in (f"NSI {fd}" if fd else "NSI", occ + (f" ({words})" if words else "")) if b)
        return rid
    if layer == "ROADS":
        route = str(props.get("route_name") or "").strip() or str(props.get("route_id") or "").strip() or rid
        aadt = props.get("aadt")
        return f"{route} (AADT {aadt:,})" if isinstance(aadt, int) else route
    owner = str(props.get("RROWNER1") or "").strip()
    sub = str(props.get("SUBDIV") or "").strip()
    branch = str(props.get("BRANCH") or "").strip()
    bits = [b for b in (owner, f"subdivision {sub}" if sub else "", branch) if b]
    return " · ".join(bits) or rid


def _inputs(folder: Path, name: str) -> list[dict]:
    try:
        data = json.loads((folder / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    feats = data.get("features") if isinstance(data, dict) else None
    return [f.get("properties") or {} for f in feats or [] if isinstance(f, dict)]


def read_receptors(gpkg: Path, limit: int = MAX_ROWS) -> dict:
    """{"receptors": [...], "counts": {layer: {"total", "wet", "hit"}}, "total", "truncated", "gpkg", "ruling"}: receptors with
    a hit (class >= 0) or water on them, strongest class first, then deepest. An ndhazard:classify layer name reads
    the ND layers beside it (read_nd)."""
    if gpkg.name in ND_FILES:
        return read_nd(gpkg.parent, limit)
    inputs_dir = gpkg.parent.parent / "classify_inputs"
    try:
        report = json.loads((gpkg.parent / "damit_hazard_report.json").read_text(encoding="utf-8"))
        report = report if isinstance(report, dict) else {}
    except (OSError, ValueError):
        report = {}
    cfg = report.get("config") if isinstance(report.get("config"), dict) else {}
    labels = cfg.get("labels") if isinstance(cfg.get("labels"), dict) else {}
    try:
        out = _read(gpkg, inputs_dir, labels, limit)
    except sqlite3.Error as exc:
        raise ReceptorsError(f"could not read {gpkg.name}: {exc}") from exc
    # The class badge's "needs ruling" summary, so a dam classified before the desk knew it gets the flag too.
    out["ruling"] = unruled_top(report, labels) if report else None
    return out


def _read(gpkg: Path, inputs_dir: Path, labels: dict, limit: int) -> dict:
    con = sqlite3.connect(f"file:{gpkg.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("select table_name from gpkg_contents")}
        rows, counts = [], {}
        for table, (layer, src) in TABLES.items():
            if table not in have:
                continue
            props = _inputs(inputs_dir, src)
            total, wet, hit = con.execute(
                f'select count(*), sum(coalesce(depth_ft,0) > 0), sum(coalesce(class,-1) >= 0 or coalesce(adv_class,-1) >= 0) from "{table}"').fetchone()
            counts[layer] = {"total": total or 0, "wet": wet or 0, "hit": hit or 0}
            for (rid, src_fid, kind, cls, adv, label, depth, vel, flags, methods, geom) in con.execute(
                    f'select rid, src_fid, kind, class, adv_class, label, depth_ft, vel_fps, flags, methods, geom from "{table}" '
                    "where coalesce(class,-1) >= 0 or coalesce(adv_class,-1) >= 0 or coalesce(depth_ft,0) > 0"):
                rule = isinstance(cls, int) and cls >= 0
                ordinal = cls if rule else adv if isinstance(adv, int) and adv >= 0 else None
                word = str(label) if rule and label else str(labels.get(str(ordinal), ordinal)) if ordinal is not None else ""
                p = props[src_fid] if isinstance(src_fid, int) and 0 <= src_fid < len(props) else {}
                at, bbox = gpkg_geometry(geom)
                rows.append({
                    "rid": str(rid), "layer": layer, "kind": str(kind or ""),
                    "name": _name(layer, p, str(rid)),
                    "ordinal": ordinal,
                    "label": word,
                    # A class from an advisory method (e.g. M6 on a structure) rather than a rule.
                    "advisory": ordinal is not None and not rule,
                    "depthFt": round(depth, 2) if isinstance(depth, (int, float)) else None,
                    "velFps": round(vel, 2) if isinstance(vel, (int, float)) else None,
                    "methods": str(methods or ""),
                    "flags": [f for f in str(flags or "").split(",") if f],
                    "at": at, "bbox": bbox,
                })
    finally:
        con.close()
    rows.sort(key=lambda r: (-(r["ordinal"] if r["ordinal"] is not None else -1), -(r["depthFt"] or 0)))
    return {"receptors": rows[:limit], "total": len(rows), "truncated": len(rows) > limit, "counts": counts,
            "gpkg": str(gpkg)}


def _num(v):
    return round(v, 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _nd_table(con: sqlite3.Connection) -> tuple[str, int | None, set[str]]:
    """The feature table of one ndhazard:classify layer, its EPSG code and its column names."""
    row = con.execute("select table_name, srs_id from gpkg_contents where data_type = 'features' limit 1").fetchone()
    if not row:
        raise sqlite3.DatabaseError("no feature table")
    table, srs = row
    epsg = srs
    try:
        org = con.execute("select organization, organization_coordsys_id from gpkg_spatial_ref_sys where srs_id = ?",
                          (srs,)).fetchone()
        if org and str(org[0]).upper() == "EPSG":
            epsg = org[1]
    except sqlite3.Error:
        pass
    cols = {r[1] for r in con.execute(f'pragma table_info("{table}")')}
    return table, epsg, cols


def _nd_row(layer: str, r: dict) -> dict | None:
    """One ndhazard:classify feature as a desk receptor, or None when it is dry and has no class."""
    depth = _num(r.get("Max_Depth_ft"))
    raw = r.get("Max_Depth_ft")
    wet = isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0
    flags: list[str] = []
    if layer == "STRUCTURES":
        outcome = str(r.get("ND_Outcome") or "")
        word = ND_OUTCOME_CLASS.get(outcome.strip().lower(), "")
        if not word and not wet:
            return None
        unverified = str(r.get("Habitable") or "").strip().lower() == "unverified"
        if unverified:
            flags.append("habitability_unverified")
        sid = r.get("Struct_ID") if r.get("Struct_ID") is not None else r.get("fid")
        occ = str(r.get("Occupancy") or "").strip()
        code = occ.split("-")[0].split(",")[0].strip()
        words = OCCUPANCY.get(code) or OCCUPANCY.get(code[:4]) or OCCUPANCY.get(code.rstrip("0123456789"), "")
        addr = " ".join(b for b in (str(r.get("Address") or "").strip(), str(r.get("City") or "").strip()) if b)
        occ_text = (occ + (f" ({words})" if words else "")) if occ and "=" not in occ else ""
        name = " · ".join(b for b in (addr or f"Structure {sid}", occ_text) if b)
        zone = str(r.get("ACER_Zone_Label") or "").strip()
        rid, kind = f"structure:{sid}", str(r.get("ACER_Type") or "structure")
        methods = outcome + (f" (ACER {zone})" if zone and zone != "DRY" else "")
        # An unverified structure is not in the ND class until it is signed off: shown with its class, as advisory.
        advisory = bool(word) and unverified
    else:
        word = str(r.get("ND_Class") or "").strip()
        basis = str(r.get("ND_Basis") or "")
        if not word and not wet:
            return None
        low = basis.lower()
        if layer == "ROADS":
            if "assumed" in low or ("aadt" in low and "no aadt" in low):
                flags.append("aadt_assumed")
            aadt = r.get("AADT")
            route = str(r.get("Road_Name") or "").strip() or f"road {r.get('fid')}"
            name = f"{route} (AADT {int(aadt):,})" if isinstance(aadt, (int, float)) and aadt > 0 else route
            rid, kind = f"road:{r.get('fid')}", str(r.get("Road_Class") or "road")
        else:
            if "not confirmed" in low:
                flags.append("crossing_unconfirmed")
            sub = str(r.get("Subdivision") or "").strip()
            bits = [str(r.get("Railroad") or "").strip(), f"subdivision {sub}" if sub else "",
                    "passenger" if str(r.get("Passenger") or "").lower() == "yes" else ""]
            name = " · ".join(b for b in bits if b) or f"rail {r.get('fid')}"
            rid, kind = f"rail:{r.get('fid')}", "rail"
        methods = basis
        advisory = False
    ordinal = ND_ORDINAL.get(word.lower()) if word else None
    return {"rid": rid, "layer": layer, "kind": kind, "name": name[:160], "ordinal": ordinal, "label": word,
            "advisory": advisory and ordinal is not None, "depthFt": depth, "velFps": _num(r.get("Max_Vel_fps")),
            "methods": methods[:240], "flags": flags, "_wet": wet}


def nd_ruling(rows: list[dict]) -> dict | None:
    """The class badge's "needs ruling" summary for an ND run, the same shape as qgis_run.unruled_top: of the receptors
    at the top class by rule, how many rest on a value the engineer still has to rule on (a road with no AADT
    assumed Medium, a rail line whose crossing is not confirmed). None when none does."""
    ruled = [r for r in rows if r["ordinal"] is not None and not r["advisory"]]
    if not ruled:
        return None
    top = max(r["ordinal"] for r in ruled)
    at_top = [r for r in ruled if r["ordinal"] == top]
    unruled = [r for r in at_top if any(f in ND_UNRULED for f in r["flags"])]
    if not unruled:
        return None
    label = at_top[0]["label"] or str(top)
    why: dict[str, int] = {}
    for r in unruled:
        word = {"ROADS": "road stretch", "RAIL": "rail stretch"}.get(r["layer"], "structure")
        why[f"{word}(es) at {label}: {r['methods'][:120]}"] = why.get(f"{word}(es) at {label}: {r['methods'][:120]}", 0) + 1
    return {"label": label, "hits": len(at_top), "unruled": len(unruled),
            "why": [f"{n} {k}" for k, n in sorted(why.items(), key=lambda kv: -kv[1])][:3]}


def read_nd(folder: Path, limit: int = MAX_ROWS) -> dict:
    """ndhazard:classify's three receptor layers in one folder, in the same shape as read_receptors. "gpkg" is the
    structures layer (the one the desk stores); "files" names every layer read."""
    rows: list[dict] = []
    counts: dict[str, dict] = {}
    files: list[str] = []
    for name, layer in ND_FILES.items():
        path = folder / name
        if not path.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                table, epsg, cols = _nd_table(con)
                pick = [c for c in ("fid", "Struct_ID", "Address", "City", "Occupancy", "Habitable", "ACER_Type",
                                    "ACER_Zone_Label", "ND_Outcome", "Road_Name", "Road_Class", "AADT", "Railroad",
                                    "Subdivision", "Passenger", "ND_Class", "ND_Basis", "Max_Depth_ft", "Max_Vel_fps",
                                    "geom") if c in cols]
                layer_rows = []
                total = 0
                for values in con.execute(f'select {", ".join(chr(34) + c + chr(34) for c in pick)} from "{table}"'):
                    total += 1
                    rec = dict(zip(pick, values))
                    out = _nd_row(layer, rec)
                    if out is None:
                        continue
                    out["at"], out["bbox"] = gpkg_geometry(rec.get("geom"), epsg)
                    layer_rows.append(out)
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise ReceptorsError(f"could not read {name}: {exc}") from exc
        files.append(str(path))
        wet = sum(1 for r in layer_rows if r.pop("_wet"))
        hit = sum(1 for r in layer_rows if r["ordinal"] is not None and r["ordinal"] >= 2 and not r["advisory"])
        counts[layer] = {"total": total, "wet": wet, "hit": hit}
        rows += layer_rows
    if not files:
        raise ReceptorsError(f"no ndhazard:classify receptor layer in {folder} (run ndhazard:classify again)")
    rows.sort(key=lambda r: (-(r["ordinal"] if r["ordinal"] is not None else -1), -(r["depthFt"] or 0)))
    structures = folder / "Habitable_Structures.gpkg"
    return {"receptors": rows[:limit], "total": len(rows), "truncated": len(rows) > limit, "counts": counts,
            "gpkg": str(structures if structures.is_file() else Path(files[0])), "files": files,
            "ruling": nd_ruling(rows), "source": "ndhazard:classify"}


def nd_summary(folder: Path) -> dict:
    """What _run_classify_nd stores with the class, from the ND layers in outputs/Classification: the GeoPackage
    the desk keys the receptor list on, how many features each layer checked and found with a class (Medium or
    above), the wet habitable structures, the "needs ruling" summary and the hits for the Review table. {} when the
    folder has no ND layer."""
    try:
        got = read_nd(folder, limit=MAX_ROWS)
    except ReceptorsError:
        return {}
    rows = got["receptors"]
    hits = [{"method": r["layer"].title() + ": " + (r["methods"].split(" (")[0] or r["label"])[:40],
             "ordinal": r["ordinal"], "label": r["label"], "strength": "advisory" if r["advisory"] else "rule",
             "reason": f"{r['name']}: {r['methods']}"[:200], "scenario": "breach", "receptors": [r["rid"]],
             "receptorCount": 1} for r in rows if r["ordinal"] is not None and r["ordinal"] >= 2][:300]
    counts = got["counts"]
    return {
        "gpkg": got["gpkg"],
        "files": got["files"],
        "layers": {k: v["total"] for k, v in counts.items()},
        "impacted": {k: v["hit"] for k, v in counts.items()},
        "wetStructures": counts.get("STRUCTURES", {}).get("wet"),
        "ruling": got["ruling"],
        "hits": hits,
        "hitsTotal": sum(1 for r in rows if r["ordinal"] is not None and r["ordinal"] >= 2),
    }
