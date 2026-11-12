"""A dam folder (<dams>/<dam id>/, as DamIT Crest and the DamSafety Runner keep it), read only."""
import json
import math
import os

JOIN_TOL = 1e-7        # coordinate units (degrees for the lon/lat dam lines, metres in a model CRS): "the same vertex"


def _length(line):
    """Planar length of a vertex list; lon/lat degrees are scaled to metres at the line's mean latitude (a rough, ordering-only
    length: the longest part is wanted, not an exact figure)."""
    if len(line) < 2:
        return 0.0
    lat = sum(p[1] for p in line) / len(line)
    deg = abs(lat) <= 90.0 and all(abs(p[0]) <= 180.0 and abs(p[1]) <= 90.0 for p in line)
    kx, ky = (111320.0 * math.cos(math.radians(lat)), 110540.0) if deg else (1.0, 1.0)
    return sum(math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * ky) for a, b in zip(line, line[1:]))


def _same(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def merge_lines(parts, tol=JOIN_TOL):
    """Join line parts end to end where exactly two of them meet (shapely's linemerge rule: a vertex shared by three or more
    parts is a junction and is left alone). Returns the merged parts, each a list of (x, y)."""
    parts = [list(p) for p in parts if len(p) >= 2]
    changed = True
    while changed and len(parts) > 1:
        changed = False
        ends = []                                           # (part index, 0 = start / 1 = end, point)
        for i, p in enumerate(parts):
            ends.append((i, 0, p[0]))
            ends.append((i, 1, p[-1]))
        for k, (i, ei, pi) in enumerate(ends):
            mates = [(j, ej) for (j, ej, pj) in ends if _same(pi, pj, tol) and (j, ej) != (i, ei)]
            if len(mates) != 1 or mates[0][0] == i:
                continue
            j, ej = mates[0]
            a = parts[i] if ei == 1 else parts[i][::-1]       # a ends at the shared vertex
            b = parts[j] if ej == 0 else parts[j][::-1]       # b starts there
            joined = a + b[1:]
            parts = [q for n, q in enumerate(parts) if n not in (i, j)] + [joined]
            changed = True
            break
    return parts


def pick_dam_line(geometry_parts, what="dam line", multi=False):
    """(line, note) from the parts of a MultiLineString (a list of vertex lists; a LineString is one part): the parts are merged
    end to end, and when several remain the longest is used. note says what was done and why, or "" for a plain LineString."""
    parts = [[(float(q[0]), float(q[1])) for q in p] for p in geometry_parts if p and len(p) >= 2]
    if not parts:
        return None, ""
    if len(parts) == 1:
        return parts[0], ("{} is a MultiLineString with one part; that part is the dam line".format(what) if multi else "")
    merged = merge_lines(parts)
    merged.sort(key=_length, reverse=True)
    best = merged[0]
    total = sum(_length(m) for m in merged)
    note = "{} is a MultiLineString of {} parts; {}".format(what, len(parts), (
        "joined end to end into one line" if len(merged) == 1 else
        "joined into {} lines and the longest was used ({:.0f} m of {:.0f} m, {} vertices): the model takes one dam line, "
        "so the other part(s) are not used".format(len(merged), _length(best), total, len(best))))
    return best, note


def read(folder):
    """What Crest (and the DamSafety Runner) keep in a dam folder: dam.json fields, the dam line, the reservoir
    point and the breach / dam point (lon / lat, EPSG:4326). Missing files give None; nothing is written."""
    out = {"fields": {}, "dam_line": None, "dam_line_note": "", "reservoir": None, "breach_point": None, "folder": folder}
    if not folder or not os.path.isdir(folder):
        return out
    try:
        with open(os.path.join(folder, "dam.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        out["fields"] = rec.get("fields") if isinstance(rec.get("fields"), dict) else rec
    except (OSError, ValueError):
        pass

    def geo(name, kind):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                gj = json.load(fh)
        except (OSError, ValueError):
            return None
        feats = gj.get("features") if gj.get("type") == "FeatureCollection" else [gj]
        for f in feats or []:
            g = (f or {}).get("geometry") or {}
            c = g.get("coordinates")
            if kind == "line" and g.get("type") == "LineString" and c and len(c) >= 2:
                return [(float(x), float(y)) for x, y in (pt[:2] for pt in c)]
            if kind == "line" and g.get("type") == "MultiLineString" and c:
                # (0.3.2) a pack's dam line is a MultiLineString (often one part); it used to be skipped without a word, and the
                # run fell back to the dam point (DWR-2645: inflow 192 m on the pool side of the line)
                line, note = pick_dam_line([[pt[:2] for pt in part] for part in c], "dam_line.geojson", multi=True)
                if line:
                    out["dam_line_note"] = note
                    return line
            if kind == "point" and g.get("type") == "Point" and c:
                return (float(c[0]), float(c[1]))
        return None
    out["dam_line"] = geo("dam_line.geojson", "line")
    out["reservoir"] = geo("reservoir_point.geojson", "point")
    out["breach_point"] = geo("breach_point.geojson", "point")
    return out
