# DamIT Discovery

Optional plugin. Finds non-NID ponds, reservoirs, and candidate dams from public hydrography.

## Algorithms

| Algorithm | What it does |
|---|---|
| `damit_discover:waterbodies` | Download NHD waterbodies (FType 390 Lake/Pond, 436 Reservoir) for an extent |
| `damit_discover:osm_ponds` | Optional OSM ponds/reservoirs/dams (not yet implemented) |
| `damit_discover:candidates` | Merge layers, drop features near existing NID points, write candidates with `is_new=true` and a `DISC-XXXX` id |

## Workflow

1. Run `waterbodies` for your extent.
2. Optionally run `osm_ponds` (when implemented).
3. Run `candidates` with the waterbodies file and an optional NID layer.
4. Review the candidate GeoPackage in QGIS.
5. Hand selected features to Crest or the Runner as new dams (`is_new=true`).

## Dependencies

DamIT Core only. No Catalog, Screener, or Runner required.
