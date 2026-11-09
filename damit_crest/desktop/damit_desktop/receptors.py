"""Downstream receptor layers for damit:classify (DamIT Hazard), so the chosen preset or custom methods judge the
downstream consequences.

The desk sends them with the Classify job (src/lib/crest/classify-receptors.ts, "damit_crest/classify_receptors"):
one EPSG:4326 FeatureCollection per classify receptor layer (STRUCTURES, ROADS, RAIL, FACILITIES, LIFELINES,
ENVIRONMENT) and the drawn downstream area as DOMAIN. Without that payload (an older page, a scripted call) the
record's mapped seeds (their own lon/lat) and 911 seeds with a cached address point are used, as points and
nothing else.

Files: <dam folder>/classify_inputs/<layer>.geojson (only layers with at least one usable feature), domain.geojson,
and receptors_manifest.json (counts, placement, skipped receptors and why). Nothing here starts QGIS."""

from __future__ import annotations

import json
import math
from pathlib import Path

LAYERS = ("STRUCTURES", "ROADS", "RAIL", "FACILITIES", "LIFELINES", "ENVIRONMENT")
#: Geometry types damit:classify accepts per layer (ROADS / RAIL are line sources; the rest any type).
GEOMETRY = {
    "STRUCTURES": ("Point", "MultiPoint", "Polygon", "MultiPolygon"),
    "ROADS": ("LineString", "MultiLineString"),
    "RAIL": ("LineString", "MultiLineString"),
    "FACILITIES": ("Point", "MultiPoint", "Polygon", "MultiPolygon", "LineString", "MultiLineString"),
    "LIFELINES": ("Point", "MultiPoint", "Polygon", "MultiPolygon", "LineString", "MultiLineString"),
    "ENVIRONMENT": ("Point", "MultiPoint", "Polygon", "MultiPolygon", "LineString", "MultiLineString"),
}
FOLDER = "classify_inputs"
#: Property values kept: scalars only, short strings.
_MAX_TEXT = 200
_MAX_FEATURES = 20000

STRUCTURE_KINDS = {"house": "home", "mobile": "mobile_home", "barn": "farm_unoccupied"}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _position(p) -> bool:
    return (
        isinstance(p, (list, tuple))
        and len(p) >= 2
        and _finite(p[0])
        and _finite(p[1])
        and -180 <= p[0] <= 180
        and -90 <= p[1] <= 90
    )


def _coords_ok(gtype: str, c) -> bool:
    if gtype == "Point":
        return _position(c)
    if gtype in ("MultiPoint", "LineString"):
        return isinstance(c, list) and len(c) >= (2 if gtype == "LineString" else 1) and all(_position(p) for p in c)
    if gtype == "MultiLineString":
        return isinstance(c, list) and bool(c) and all(_coords_ok("LineString", part) for part in c)
    if gtype == "Polygon":
        return isinstance(c, list) and bool(c) and all(isinstance(r, list) and len(r) >= 4 and all(_position(p) for p in r) for r in c)
    if gtype == "MultiPolygon":
        return isinstance(c, list) and bool(c) and all(_coords_ok("Polygon", part) for part in c)
    return False


def usable_geometry(geom, allowed) -> bool:
    if not isinstance(geom, dict):
        return False
    gtype = geom.get("type")
    return gtype in allowed and _coords_ok(gtype, geom.get("coordinates"))


def _props(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in list(raw.items())[:60]:
        key = str(k)[:40]
        if v is None or isinstance(v, bool) or (isinstance(v, (int, float)) and math.isfinite(v)):
            out[key] = v
        elif isinstance(v, str):
            out[key] = v[:_MAX_TEXT]
    return out


def _from_payload(payload: dict) -> tuple[dict, dict | None, list[dict], dict, str | None]:
    layers: dict[str, list] = {}
    skipped: list[dict] = []
    raw_layers = payload.get("layers") if isinstance(payload.get("layers"), dict) else {}
    for key, fc in raw_layers.items():
        if key not in LAYERS:
            skipped.append({"id": "", "name": str(key)[:40], "kind": "layer", "reason": f"{key} is not a damit:classify receptor layer"})
            continue
        feats = fc.get("features") if isinstance(fc, dict) else None
        for feat in (feats if isinstance(feats, list) else [])[:_MAX_FEATURES]:
            props = _props((feat or {}).get("properties") if isinstance(feat, dict) else None)
            geom = feat.get("geometry") if isinstance(feat, dict) else None
            if not usable_geometry(geom, GEOMETRY[key]):
                skipped.append({"id": str(props.get("crest_id") or ""), "name": str(props.get("name") or ""),
                                "kind": str(props.get("kind") or key.lower()),
                                "reason": f"no usable {'/'.join(GEOMETRY[key][:2])} geometry for {key}"})
                continue
            layers.setdefault(key, []).append({"type": "Feature", "geometry": geom, "properties": props})
    for s in payload.get("skipped") or []:
        if isinstance(s, dict):
            skipped.append({k: str(s.get(k) or "")[:_MAX_TEXT] for k in ("id", "name", "kind", "reason")})
    domain = payload.get("domain")
    domain = domain if isinstance(domain, dict) and usable_geometry(domain.get("geometry"), ("Polygon", "MultiPolygon")) else None
    placement = {str(k)[:40]: int(v) for k, v in (payload.get("placement") or {}).items() if _finite(v)} if isinstance(payload.get("placement"), dict) else {}
    direction = payload.get("direction") if isinstance(payload.get("direction"), str) else None
    return layers, domain, skipped, placement, direction


def _from_dam(dam: dict) -> tuple[dict, dict | None, list[dict], dict, str | None]:
    """Fallback without the desk's payload: mapped seeds and cached 911 address points, as STRUCTURES points only.
    Desk-valley placement and road lines need the desk's downstream direction, so those seeds are skipped."""
    cache = (dam.get("nd911") or {}) if isinstance(dam.get("nd911"), dict) else {}
    points = {str(p.get("nguid")): p for p in cache.get("points") or [] if isinstance(p, dict)}
    structures, skipped = [], []
    placement = {"mapped": 0, "911 address point": 0, "desk valley": 0}
    for seed in dam.get("receptors") or []:
        if not isinstance(seed, dict):
            continue
        kind = str(seed.get("kind") or "")
        ident = {"id": str(seed.get("id") or ""), "name": str(seed.get("name") or "")[:_MAX_TEXT], "kind": kind}
        if kind not in STRUCTURE_KINDS:
            skipped.append({**ident, "reason": "roads need the desk's downstream direction to be drawn as a line; send the job from the Report step"})
            continue
        at, placed = None, "mapped"
        if _position([seed.get("lon"), seed.get("lat")]):
            at = [seed["lon"], seed["lat"]]
        elif seed.get("source") == "nd911" and str(seed.get("sourceRef")) in points:
            p = points[str(seed.get("sourceRef"))]
            if _position([p.get("lon"), p.get("lat")]):
                at, placed = [p["lon"], p["lat"]], "911 address point"
        if at is None:
            skipped.append({**ident, "reason": "no longitude/latitude (a desk-valley position needs the desk's downstream direction)"})
            continue
        habitable = seed.get("habitable") if isinstance(seed.get("habitable"), bool) else None
        typ = STRUCTURE_KINDS[kind]
        if habitable is False and kind in ("house", "mobile"):
            typ = "outbuilding"
        if habitable is True and kind == "barn":
            typ = "farm_occupied"
        placement[placed] += 1
        structures.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": at}, "properties": {
            **{k: v for k, v in ident.items() if k != "id"}, "crest_id": ident["id"], "type": typ, "placed": placed,
            "habitable": habitable, "pad_ft": seed.get("padFt") if _finite(seed.get("padFt")) else None,
            "source": str(seed.get("source") or "crest"), "source_ref": str(seed.get("sourceRef") or "") or None}})
    aoi = ((dam.get("geometry") or {}) if isinstance(dam.get("geometry"), dict) else {}).get("aoi")
    domain = aoi if isinstance(aoi, dict) and usable_geometry(aoi.get("geometry"), ("Polygon", "MultiPolygon")) else None
    return ({"STRUCTURES": structures} if structures else {}), domain, skipped, placement, None


def _collection(features: list) -> dict:
    return {"type": "FeatureCollection", "name": "receptors",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": features}


def write_receptor_layers(folder: Path, dam: dict, payload=None) -> dict:
    """Write the classify receptor layers and DOMAIN into <folder>/classify_inputs/. Returns
    {"layers": {KEY: path}, "counts": {KEY: n}, "domain": path | None, "skipped": [...], "placement": {...},
    "direction": str | None, "source": "desk" | "record", "manifest": path}."""
    if isinstance(payload, dict) and payload.get("format") == "damit_crest/classify_receptors":
        layers, domain, skipped, placement, direction = _from_payload(payload)
        source = "desk"
    else:
        layers, domain, skipped, placement, direction = _from_dam(dam or {})
        source = "record"
    out_dir = Path(folder) / FOLDER
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.geojson"):
        stale.unlink()
    paths, counts = {}, {}
    for key in LAYERS:
        feats = layers.get(key) or []
        if not feats:
            continue
        path = out_dir / f"{key.lower()}.geojson"
        path.write_text(json.dumps(_collection(feats)) + "\n", encoding="utf-8")
        paths[key], counts[key] = str(path), len(feats)
    domain_path = None
    if domain:
        domain_path = out_dir / "domain.geojson"
        feat = {"type": "Feature", "geometry": domain["geometry"], "properties": {"name": "drawn downstream area"}}
        domain_path.write_text(json.dumps(_collection([feat])) + "\n", encoding="utf-8")
    manifest = out_dir / "receptors_manifest.json"
    info = {"format": "damit_crest/classify_receptors_manifest", "crs": "EPSG:4326", "source": source,
            "counts": counts, "domain": bool(domain_path), "placement": placement, "direction": direction,
            "skipped": skipped}
    manifest.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return {"layers": paths, "counts": counts, "domain": str(domain_path) if domain_path else None,
            "skipped": skipped, "placement": placement, "direction": direction, "source": source,
            "manifest": str(manifest)}
