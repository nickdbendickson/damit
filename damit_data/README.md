# DamIT Data 0.1.0

Offline copies of public structure and footprint layers for **any US state** (Processing provider
`damit_data`). Depends on DamIT Core. Generalized from the North Dakota-only DamSafety Data.

| Source | Scope | How it is fetched | Change check |
|---|---|---|---|
| USACE National Structure Inventory (`nsi`) | a state (one NSI API request per county, county FIPS from the Census 2023 file) or an extent of at most 1 square degree (one `bbox` request) | `https://nsi.sec.usace.army.mil/nsiapi/structures?fips=…` / `?bbox=…`, merged into `nsi.geojson` | content SHA-256; re-checked after 30 days or with FORCE |
| Microsoft US Building Footprints (`microsoft`) | a state (none published for Puerto Rico) | `usbuildings-v2/<State>.geojson.zip` | ETag / Last-Modified / size |
| OpenStreetMap, Geofabrik (`osm`) | a state, DC or Puerto Rico | `<state>-latest-free.gpkg.zip` | ETag / Last-Modified / size |
| FEMA / ORNL USA Structures (`usa_structures`) | the zip whose https link you paste (FEMA publishes no stable per-state URL pattern) | that link | ETag / Last-Modified / size |

Tools:

* `damit_data:download` – STATE, optional EXTENT (NSI only), SOURCES, optional USA_STRUCTURES_URL,
  FOLDER, FORCE, MAX_MB (default 1500: a larger download is refused before it starts when the server
  reports its size). Each download is staged in a hidden folder, verified (zip integrity and safe paths,
  GeoJSON FeatureCollection) and only then swapped in, so a failed update keeps the old copy.
* `damit_data:status` – what the manifest holds.
* Menu: **Download / update offline layers…** and **Add DamIT Data layers to the project** (group
  "DamIT data").

Without QGIS, the same engine from a terminal (any Python 3, run from the plugin's folder, DamIT Core
beside it):

    python3 get_data.py --list                          # the sources, and which are fetched by default
    python3 get_data.py --state ND                      # the default sources for one state
    python3 get_data.py --state ND --sources nsi,osm    # only these; `all` = every source that needs no link
    python3 get_data.py --bbox=-101.2,46.8,-100.8,47.2  # NSI for a box of at most 1 square degree
    python3 get_data.py --status                        # what the data folder holds

It exits 0 when every source asked for is in place and 1 when one or more failed; the others are kept, and
running the same command again fetches only what is missing or changed. `--folder`, `--force`, `--max-mb`
and `--usa-structures-url` are the tool's parameters of the same names.

Layout: `<data folder>/<STATE or extent_xxxxxxxx>/<source>/…` plus `damit_data_manifest.json`
(versions, URLs, citations). The data folder is the tool's FOLDER, else the DamIT `data_folder` setting
(DamIT Setup), else `~/Documents/DamIT Data`. Any folder inside an `ND_Dam_Suite_Pack` is refused.

Not in 0.1.0 (North Dakota-specific in DamSafety Data, no national equivalent wired yet): ND 911
address points, NDDOT AADT, DWR layers, the ND offline pack builder, NAIP imagery, Overture buildings,
the OSM pack layers built from `.osm.pbf`, automatic background checks. Connecticut's 2023 county
equivalents are the nine planning regions; if NSI still serves the old county FIPS there, use an extent.

Tests use a fake HTTP client and a 3-structure NSI fixture (`tests/fixtures/`); nothing is downloaded.
