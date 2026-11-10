# US-Wide Data Sources for DamIT

Replacements for ND-specific data sources, organized by what the engine needs.

## Dam Inventory

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Dam records | ND DWR dam inventory | **NID (National Inventory of Dams)** | Already integrated via `nid-dams.ts`. ~92,000 dams. USACE maintains. Fields: NID_ID, dam name, height, storage, hazard class, owner, etc. |
| Dam locations | DWR GPS coordinates | **NID coordinates** | NID has lat/lon for every dam. |
| Dam elevations | DWR inventory fields | **NID + USGS 3DEP** | NID has limited elevation data. Top-of-dam elevation read from 3DEP DEM at dam location. |
| Downstream slope | DWR `downstream_slope` field | **Manual entry or NID** | NID doesn't carry downstream slope. User enters it, or default 3:1 with warning. Consider NBI abutment data as proxy. |
| County | ND counties GeoJSON | **US Census TIGER county boundaries** | `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2023/MapServer` — all 3,143 US counties. Or use NID's county field. |

## Terrain / DEM

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Elevation DEM | ND DWR LiDAR (1m/3m) | **USGS 3DEP** | Already integrated. 1m coverage expanding; 1/3 arc-sec (~10m) nationwide. `https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer` |
| Vertical datum | ND VERTCON grid | **National VERTCON via pyproj** | Already integrated in `vertcon.ts` + `/api/vertcon` endpoint. NGVD29→NAVD88 nationwide. |

## Land Cover / Roughness

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Manning's n | NLCD + ND lookup table | **NLCD 2021 (national)** | Already in `data_conventions.py`. NLCD is nationwide. Same Manning's n lookup table applies everywhere. `https://www.mrlc.gov/geoserver/mrlc_download/wcs` |

## Receptors (Structures at Risk)

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Structures | ND address points | **NSI (National Structure Inventory)** | Already integrated as default receptor source. FEMA/USACE. Occupancy class, first-floor height, replacement value. ~120M structures. `https://nsi.sec.usace.army.mil/nsiapi/structures` |
| Structures (outlines) | HIFLD / MS Buildings | **USA Structures (FEMA)** | `https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/USA_Structures_View/FeatureServer/0` — building outlines with occupancy class. |
| Roads + AADT | ND DOT roads | **HPMS (Highway Performance Monitoring System)** | Already integrated in `damit_data/core/sources.py`. AADT, functional class, speed limit, lanes. Per-state FeatureServers via `https://geo.dot.gov/server/rest/services/Hosted/` |
| Railroads | ND rail layer | **FRA Rail Network** | Already integrated. `https://fragis.fra.dot.gov/arcgis/rest/services/FRA/FRA_Rail_Network/FeatureServer/0` — includes class, owner. |
| Critical facilities | Manual / HIFLD | **HIFLD (Homeland Infrastructure Foundation-Level Data)** | Hospitals, schools, fire stations, law enforcement. `https://hifld-geoplatform.opendata.arcgis.com/`. Requires HIFLD account for some layers. |

## Bridges / Culverts

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Bridge/culvert inventory | NDDOT bridge inventory | **NBI (National Bridge Inventory)** | FHWA. ~620,000 structures. Item 43B identifies culverts. Span, rise, condition rating. `https://www.fhwa.dot.gov/bridge/nbi/ascii.cfm` (annual CSV downloads). |
| Culvert descriptions | NDDOT text format | **NBI coded fields** | NBI uses coded fields (item 43A structure type, 43B design type) rather than free text. `culvert_text.py` already handles NBI codes alongside text. |

## Hydrology

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| PMF / flood frequency | Site-specific | **USGS StreamStats** | `https://streamstats.usgs.gov/` — basin delineation, flood-frequency estimates for ungauged sites. API available. |
| Precipitation | Site-specific | **NOAA Atlas 14 / Atlas 15** | Precipitation frequency estimates. `https://hdsc.nws.noaa.gov/` |
| Inflow hydrographs | TR-60 / user CSV | **TR-60 (national)** | Already in `breach.py`. The Froehlich and other empirical methods are nationwide. |

## Hazard Classification

| Need | ND Source | US-Wide Replacement | Notes |
|------|-----------|-------------------|-------|
| Classification rules | ND Dam Safety Standards (REG_05) | **DamIT Catalog presets** | Already implemented. 19 presets covering FEMA 333, USBR, USACE, TVA, BIA, NRCS, and 13 state-specific rulesets. Auto-selected from NID state code. |
| TM-11 charts | ND Figures 5.1/5.2 | **ACER TM-11 (national)** | Already in `damit_hazard/engine/tm11.py`. The Reclamation depth-velocity charts are national. |

## Recommended Priority for New Integrations

1. **US Census TIGER counties** — replace `nd_counties.py` for county attribution on reports
2. **NBI (National Bridge Inventory)** — replace NDDOT bridge data for culvert identification
3. **HIFLD critical facilities** — hospitals, schools, emergency services as receptor layers
4. **USGS StreamStats API** — automated basin delineation and flood frequency for ungauged dams
5. **NOAA Atlas 14/15** — precipitation frequency for PMF estimation
