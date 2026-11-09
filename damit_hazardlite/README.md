# DamIT Hazard Lite 0.1.0

One Processing tool, **`damit_lite:classify`** (provider `damit_lite`, distinct from DamIT Hazard's
`damit:classify`), for a quick suggested hazard class from a finished run's maximum depth (and
optional velocity) raster and structure, road and rail layers. Depends on DamIT Core and DamIT Catalog.
No dialog of its own and no flood model.

**Multi-jurisdiction from DamIT Catalog.** MODE preset (PRESET any catalog ID or alias: ND, NE, NY, VA,
TX, ID, CO, RI, AZ, CA, AK, AL, NC, FEMA333, USBR / USBR_TM11, BIA, NRCS, USACE, TVA) or custom (METHODS, e.g. `M2,M6,M8a`).
Receptor records go to `damit_catalog.evaluate` – the evaluator and data DamIT Hazard uses – so every
threshold, class, label and modifier is the catalog's. The wet depth, sampling distances (point disc,
outline edge ring, line step) and the lowest class used when nothing is hit come from the catalog's
`hazard.json` `general`; the receptor-type vocabulary from `hazard.json` `receptor_types`. The plugin's
`data/vocab.json` only maps layer values onto that vocabulary (NSI `occtype` prefixes, common
structure words, OSM `highway` values, yes / no spellings).

Sampling: outlines – every cell whose centre is inside the outline grown by the edge ring; points – a
disc; lines – one cell per line step. Peak depth over the cells; peak velocity and depth × velocity over
the wet cells only. A receptor off the raster is `in_domain = false` (the evaluator flags it). Depth /
velocity in feet or metres. The raster must be in a projected CRS; receptor layers are reprojected.

Inputs read from fields: structure type / occupancy, habitable, occupants, M1 chart zone; road class,
AADT; rail trains per day, passenger, active. MODEL_DIMENSION (1D / 2D) and HYDRAULICS_SOURCE /
STORAGE_ACFT go to the dam summary (M1 / M2 2D / 1D rules, R8).

Outputs: `hazard_lite.json` (result, receptors, catalog version + SHA-256), `receptors.csv`,
`hazard_lite_summary.md` (driving method / receptor / scenario, advisories, flags, citations, the enabled
methods Lite does not screen) and a receptor point layer.

0.1.0 limits: structures, roads and rail only (lifelines, facilities, environment, counts that need a
dam-level summary, sole access etc. are flagged as missing input or listed as not screened); M1 chart
zones are not computed (map an `m1_zone` field or use DamIT Hazard); one receptor per line feature (no
split into wet stretches, no crown check); no NSI habitability rules beyond the vocabulary.
