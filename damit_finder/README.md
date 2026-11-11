# DamIT Finder

Finds structures that are **not on the lists**: dams (with or without a pool), road fills that
hold water, ponds, dugouts and the road / rail crossings of streams where a culvert or a bridge
must be. Every candidate is checked against the known-structure layers you give and marked
**listed**, **unsure** or **new**.

Screening aid. The LiDAR is not a survey: check every candidate against an aerial image. A "new"
candidate is new to the lists you gave, not necessarily to the state dam-safety office. A new dam has no NID ID, so DamIT Screener
refuses it as a dam record (the NID-only rule) until the state or the NID lists it.

Install: needs DamIT Core. Processing Toolbox → DamIT Finder → Find structures.

## The three tools

| Tool | Input | Finds |
|---|---|---|
| `damit_find:embankments` Find fills across streams | bare-earth DEM, stream lines (3DHP / NHD flowlines), roads and railroads (optional) | Every fill that blocks a valley a stream line crosses: **dam** (holds water), **dry embankment** (a dry / detention dam, a levee, an unmapped crossing), **road fill (ponding)** (a road that holds water: the culvert is missing in the DEM, small or blocked), **road fill** |
| `damit_find:ponds` Find ponds and dugouts | water-body polygons (3DHP / NHD waterbodies, NWI, your own), DEM | **embankment pond**, **dugout** (natural depressions on request) - the pond engine of DamSafety Screening's pond tool |
| `damit_find:crossings` Find road and rail crossings of streams | roads, railroads, stream lines; the first tool's fills (optional) | Every crossing - the places a culvert or a bridge must be - with the fill there |

All three take **Known structures** (any number of point, line or polygon layers: the NID, state dam,
pond and dugout lists, NBI bridges (DamIT Data), state DOT bridge / culvert inventories, USGS stream
crossings, SARP / ABI crossings), a match distance (YOUR value; unsure up to twice it) and an
optional extent. A known point anywhere inside a pond's outline makes that pond listed.

## How a fill is found (`core/embankments.py`)

1. Each stream line is walked downstream over the DEM. A hump is where the ground rises more than
   0.15 m above the lowest ground already passed and falls back below it within `max_len`.
2. **Spill level**: the highest water level at which the ground just above the hump and the toe
   below it are still separate pools. Above it the water gets over or round the fill (a
   spillway, a saddle, the low end). This 2-D test is what drops a bank the line wanders onto:
   above and below join along the real channel at about the toe level.
3. **Height** = spill level - toe (the foot of the downstream face). **Head** = the upstream level
   - toe, less the fall the valley itself makes over that distance. A head of at least
   `min_head`, or a flat pool surface behind the fill (flat ground whose rim is all higher, as a
   hydro-flattened lake is), = the fill holds water.
4. **Storage** and pool area at the spill level (the LiDAR cannot see under water: a pool surface
   counts as ground, so storage is above the water surface only). A pool reaching the analysis
   window is marked `open_pool` (storage is a minimum).
5. A road / rail mask (the centrelines, 6 m either side) tells a road fill from a dam.

Fills closer than 60 m are one. The DEM is read in 5 km tiles with a pad, so a county runs in
bounded memory. The elevation unit comes from the raster (feet are scaled); the warp reads the
full-resolution cells and keeps the values as stored (`core/warp_opts.py`, the DamSafety rule).

What it cannot find: a fill on a draw with no stream line (a whole-DEM search for raised ridges is
the next step), a fill the DEM has been hydro-enforced through, a pond with no polygon.

## Outputs

One GeoPackage per tool run (EPSG:5070 points, lat / lon fields) and a CSV beside it. The
work grid is CONUS Albers (EPSG:5070): Alaska, Hawaii and the territories are not supported yet.

* `embankments` / `ponds` / `crossings`: every candidate, new first, with `status`, `known_id`,
  `known_layer`, `known_ft`, heights in feet, storage in acre-feet, areas in acres, `confidence`
  and `notes`.
* `screening_dams` / `screening_ponds`: the not-listed candidates that could release water, as
  dam records (`structure_id` = FIND-… / POND-…, `dam_name`, `max_dam_height` ft,
  `max_pool_vol` ac-ft, `max_pool_area` ac, `status` = Candidate) to send to the state or to screen
  once they are listed.
* `<output>_hillshade.tif`: a hillshade lit from all round (`gdaldem hillshade -multidirectional`)
  for the review. A fill parallel to a single sun direction does not show; this shows every
  embankment and pond rim.

## Files

`core/embankments.py`, `core/listed.py`, `core/crossings.py` (new), `core/ponds.py`,
`core/storage.py`, `core/warp_opts.py` (the DamSafety Screening engine files, the same bytes
as in dAmIt_Plugins but for warp_opts' docstring), `finder.py` (the three runs on files: GDAL / OGR, no QGIS), `plugin.py`
(the Processing tools), `brand.py` (what differs from DamSafety Finder in dAmIt_Plugins).

Tests: `python -m unittest damit_finder.tests.test_core damit_finder.tests.test_finder
damit_finder.tests.test_qgis` (synthetic terrain; the QGIS tests skip without QGIS).
