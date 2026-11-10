"""A dam folder (<dams>/<dam id>/, as DamIT Crest and the DamSafety Runner keep it), read only."""
import json
import os


def read(folder):
    """What Crest (and the DamSafety Runner) keep in a dam folder: dam.json fields, the dam line, the reservoir
    point and the breach / dam point (lon / lat, EPSG:4326). Missing files give None; nothing is written."""
    out = {"fields": {}, "dam_line": None, "reservoir": None, "breach_point": None, "folder": folder}
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
            if kind == "point" and g.get("type") == "Point" and c:
                return (float(c[0]), float(c[1]))
        return None
    out["dam_line"] = geo("dam_line.geojson", "line")
    out["reservoir"] = geo("reservoir_point.geojson", "point")
    out["breach_point"] = geo("breach_point.geojson", "point")
    return out
