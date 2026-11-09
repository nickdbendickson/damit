# DamIT Crest hand-off: algorithm ids and how to point the app at them

DamIT Crest does not classify dams, run a screening chain or run a breach model itself. From the **Report** step it
writes the dam folder and hands it to the DamIT QGIS plugins through `qgis_process` (or, for one dam with a DEM point,
the DamIT runner's command-line script). This page lists the ids it calls, which ones are confirmed, and how to change
them without a code change.

## Algorithm ids

| Role | Default id | Provided by | Status | ND suite analog (never called) |
|---|---|---|---|---|
| `classify` | `damit:classify` | `damit_hazard` (QGIS Dev, PR #1) | **published**: hazard classification from a model's rasters and receptors; runs no breach model | (new in DamIT) |
| `preflight` | `damit_screen:preflight` | `damit_screener` 0.1.0 (SWE, PR #2) | **published** | `nddam:preflight` |
| `runchain` | `damit_screen:runchain` | `damit_screener` 0.1.0 (SWE, PR #2) | **published** | `nddam:runchain` |
| `rundam` | `damit_run:rundam` | `damit_runner` 0.1.0 (SWE, PR #2) | **published**; 0.1.0 prepares and records a run, it launches no engine | `ndbreach:rundam` |
| `batch` | `damit_run:batch` | — | **not published**; a name only, **never started by the app** | `ndbreach:batch` |

Both PRs were open (not merged) when this was written; the ids are the ones their providers register. They stay
overridable (below) in case review renames them.

One-dam runner CLI: `damit_cli.py` (or `damit_runner_cli.py`), searched in DamIT plugin folders (`damit_runner`,
`damit_*`, `damit`, each in `scripts/` or at the plugin root) under the QGIS profiles on macOS
(`~/Library/Application Support/QGIS/QGIS3/profiles/*/python/plugins`), Linux (`~/.local/share/QGIS/QGIS3/...`) and
Windows (`%APPDATA%\QGIS\QGIS3\...`). ND analog: `ndbreach_cli.py`, which is never searched for or called.

The compiled-in defaults live in `desktop/damit_desktop/algorithms.py` (`DEFAULT_ALGORITHMS`) and, for what the page
shows before the desktop server answers, `src/lib/crest/handoff.ts`. Tests pin both.

## Overriding

For every role the first of these wins:

1. **Environment variable**: `DAMIT_ALG_CLASSIFY`, `DAMIT_ALG_PREFLIGHT`, `DAMIT_ALG_RUNCHAIN`, `DAMIT_ALG_RUNDAM`,
   `DAMIT_ALG_BATCH`; `DAMIT_CLI` for the full path of the runner CLI.
2. **Config file**: the path in `DAMIT_HANDOFF_CONFIG`, else `damit-handoff.json` in the app's settings folder
   (Windows `%APPDATA%\DamIT Crest`, macOS `~/Library/Application Support/DamIT Crest`, Linux
   `~/.local/share/damit-crest`). See [`damit-handoff.example.json`](damit-handoff.example.json):

   ```json
   { "algorithms": { "preflight": "damit_screen:preflight", "rundam": "damit_run:rundam" }, "cli": "" }
   ```

3. The DamIT default above.

The file is re-read for every job, so an edit applies without restarting. The Report step shows the ids in use
(`GET /api/handoff`) and any override that was refused.

**Guard rails.** An override must be a `provider:name` id. An id from the North Dakota suite's providers (`nddam`,
`ndbreach`, `nd_*`, …) is refused with a message and the DamIT default is kept; there is no fallback to the ND ids. A
`*:batch` id is refused for every role except `batch`, and the app never starts `batch`. Before each run the app asks
`qgis_process help <id>`; if the algorithm is not installed the job stops with a message naming the variable to set,
and nothing is started.

## What each button sends

Every `qgis_process` call sends **only the parameters the installed algorithm's `qgis_process help <id>` lists**, so
a renamed or missing parameter is skipped, never guessed. The candidates cover the published DamIT interfaces
(below) and an ND-style port (`DAM_ID`, `DAMS_FOLDER`, `DEM`, `METHOD`, `TIER`, `LOG`, …), so an override pointing at
such a port also works. Enums are sent as the option index read from `help` (QGIS 3.34 rejects option text).

| Button | Calls | Arguments sent to the published algorithms |
|---|---|---|
| Get layers | nothing in QGIS | Downloads USGS 3DEP + NHD for the area, or points `damit_settings.json` at the DamIT data folder |
| Write the dam folder | nothing in QGIS | `<work>/dams/<id>/dam.json` (`damit/dam_record`), geometries, hydrographs, LISFLOOD package, flood strip |
| Write folder and run screening | `preflight`, then `runchain` **only if READY** | `--WORK --DAMS=<dam folder>/dam_point.geojson --MODE --PRESET` (preset) or `--SCENARIOS --METHODS` (custom) `[--TERRAIN] [--APPLY_ADVISORIES] --SETTINGS`; preflight adds `--REPORT`, runchain `--PREFLIGHT=true --FAIL_ON_ERROR=true` |
| Run the flood model | `rundam` (one dam) or the runner CLI | `--HANDOFF=<work>/handoff/<id>/damit_handoff.json` when the screening wrote it, else `--DAM_ID --X --Y --CRS=EPSG:4326 --HEIGHT_FT --STORAGE_ACFT --MODE --PRESET/--SCENARIOS/--METHODS [--TERRAIN] [--HYDROGRAPH]`; always `--OUTPUT_FOLDER=<work>/runs --DRY_RUN=true`, never `ENGINE`; CLI: `run runner_config.json` |
| Classify | `classify` | `--PRESET=<index>` (0 = custom, else the option whose text is the preset's catalog label) `[--METHODS --SCENARIOS --MODIFIERS] [--APPLY_ADVISORY] --DEPTH [--VELOCITY] [--DV] [--WSE] [--NONBREACH] [--ARRIVAL]` + the receptor layers `[--STRUCTURES] [--ROADS] [--RAIL] [--FACILITIES] [--LIFELINES] [--ENVIRONMENT]=<dam folder>/classify_inputs/<layer>.geojson` (at least one) `[--DOMAIN=<dam folder>/classify_inputs/domain.geojson] --DAM_JSON=<dam folder>/damit_dam.json --DAM_NAME --OUTPUT=<dam folder>/classify` |

Details:

- **NID IDs.** The dam inventory is the NID only. `dam_id` **is the NID ID** (e.g. `ND00199`) and `nid_id` the same,
  in `dam.json`, the DAMS layer, `damit_dam.json`, `only_ids` and `DAM_ID`. A record without a real NID ID is never
  given one: `nid_id` is left out and `dam_id` is the desk record's own id. Such a record is handed off only when it
  is a **new (proposed) dam** (`is_new: true`, the *New dam* box) or one of the built-in fictional **samples**
  (`is_sample: true`; `SAMPLE-4031` and `DESK-014` are not NID IDs); otherwise the job stops before `qgis_process`
  with "… is not an NID ID". DWR-, DUG- or other inventory ids are never sent or substituted: when a screener's
  outputs name the dam by another id, the log says so and the results are read by the NID ID only. The DamIT
  plugins apply the same rule (a non-NID id is a FAIL; new / sample records pass with a warning). A Runner whose
  `damit_run:rundam` lists `NID_ID`, `IS_NEW` and `IS_SAMPLE` gets them too (the NID ID, or `IS_NEW=true` /
  `IS_SAMPLE=true` for a record without one); older Runners simply do not get them.
- **DAMS layer.** `dam_point.geojson` is this dam alone as a point (EPSG:4326: breach point, else reservoir point,
  else the record's lon/lat) with DamIT Screener's field names (`dam_id`, `name`, `nid_id`, `is_new`, `is_sample`, `height_ft`, `storage_acft`,
  `top_of_dam_elev_ft`, `normal_pool_elev_ft`, `surface_area_ac`, `hydrograph_csv` = `inputs/breach_hydrograph.csv`,
  `failure_mode`), so no `FIELD_MAP` is needed. Without a position no layer is written and the preflight reports it.
- **One dam.** `damit_settings.json` carries `dam_ids` (DamIT Screener's filter) and `only_ids`, so `runchain`
  screens this dam only. It also carries `data_folder` (and `suite_folder`), `terrain` / `local_dem` when a DEM is
  known, and `classification`.
- **READY.** Read from the preflight's `READY:` output, else `FAILS:`, else the report's first line. Anything else
  stops before `runchain`.
- **Read-back.** After the chain the app reads `screening` from this dam's `damit_handoff.json` (preliminary label,
  ordinal, flags; logged as a screening suggestion, not an official class), and the dam's row of
  `10_reports/summary.csv`, both by the NID ID.
- **Flood model.** `damit_run:rundam` takes no DEM parameter, so a missing DEM is logged as a gap instead of
  stopping; for an algorithm that declares `DEM` (or for the CLI) a missing DEM still stops. DamIT Runner 0.1.0
  prepares `run_setup.json` in a new folder under `<work>/runs`; the app reports `RUN_FOLDER`. It never sends an
  engine choice or `DRY_RUN=false`.
- **Classify** needs the model run's maximum depth raster: type its path under *Depth raster* (velocity, depth ×
  velocity, water-surface elevation, non-breach depth and arrival-time rasters are optional and sent as `VELOCITY`,
  `DV`, `WSE`, `NONBREACH`, `ARRIVAL` when typed). It also needs at least one downstream receptor layer (see
  *Downstream receptors for classify* below). Without a depth raster, without a receptor it can place, when the
  installed algorithm lists none of the receptor layers, or when it does not list the chosen preset, the job stops
  before running and the log says why.
  `damit_dam.json` is a flat record: `dam_id`, `nid_id`, `name`, `storage_acft`, `height_ft`, `current_class`, `is_new`, `is_sample` (samples only),
  `failure_mode`, and `class_of_record_text` (the original class-of-record text, for people; classify ignores it).
  See *Class of record and new dams* below.

## Downstream receptors for classify (the chosen jurisdiction judges them)

`damit:classify` applies the chosen preset's methods (or the ticked custom methods) to **receptor layers**; it refuses
a run without one. The Classify button therefore sends the dam's downstream receptors, so the selected state, agency
or custom method set, not the desk's ND / ACER TM 11 screen, judges the downstream consequences.

**Built in the page** (`src/lib/crest/classify-receptors.ts`, `classifyReceptors`) and sent with the job as
`receptors` (`"format": "damit_crest/classify_receptors"`); the server checks every feature
(`desktop/damit_desktop/receptors.py`) and writes, in `<dam folder>/classify_inputs/`:

| File | Classify parameter | From | Geometry |
|---|---|---|---|
| `structures.geojson` | `STRUCTURES` | house, mobile home, barn seeds (911 points added for review included) | Point |
| `roads.geojson` | `ROADS` | road seeds | LineString: the crossing drawn across the valley (perpendicular to the downstream direction, the desk half-width each side, at least 50 m) |
| `rail.geojson` | `RAIL` | a `rail` seed, if a record carries one | LineString, as roads |
| `domain.geojson` | `DOMAIN` | the drawn downstream area (Flood step AOI), when one is drawn | Polygon / MultiPolygon |
| `receptors_manifest.json` | — | counts, placement, the downstream-direction note, every receptor **not** sent and why | — |

All files are EPSG:4326 (GeoJSON CRS84); classify reprojects them to the depth raster's CRS. A layer file is written
only when it has at least one feature with a usable geometry, and only layers the installed algorithm lists in
`help` are sent. The desk has no critical-facility, lifeline or environmental receptors, so `FACILITIES`,
`LIFELINES` and `ENVIRONMENT` are not written from the desk (classify accepts them; add them in QGIS for now).

**Attributes** (named for Hazard's receptor reader, `damit_hazard/engine/receptors.py`): `crest_id`, `name`, `kind`
(the Crest kind), `type` (house → `home`, mobile → `mobile_home`, barn → `farm_unoccupied`; a structure marked not
habitable → `outbuilding`, a barn marked habitable → `farm_occupied`), `habitable`, `placed`, `distance_km`, `pad_ft`
(pad above the channel bed; informational, not a floor elevation), `source` / `source_ref` (`nd911` and the NG911
Site_NGUID); roads add `road_class` (`interstate`, `us_state`, `other`) and `aadt`, and `geom_basis`.

**Where each receptor goes** (`placed`), first that applies:

1. `mapped`: the seed's own longitude/latitude;
2. `911 address point`: a 911 seed's address point from the record's NG911 cache (by Site_NGUID);
3. `desk valley`: where the desk's straight valley puts it: from the breach (breach point, else the record's lat/lon,
   dam line or reservoir point) along the downstream direction (across the dam line away from the reservoir point, or
   reservoir point → breach) at its distance, `lateral` across the desk half-width. This is schematic: the real
   stream bends, so the log says how many receptors were placed this way.

A receptor none of these can place (no lon/lat, and no breach location or no downstream direction) is **skipped**,
listed in the job log and the manifest with the reason. A road also needs the downstream direction to be drawn as a
line. If nothing can be placed, classify is not started. Without the page's payload (an older page or a scripted
call) the server uses mapped and 911 seeds only, as structures.

**Result.** The job returns `CLASS`, `ORDINAL`, `REPORT` and `GPKG` (receptors by class) and the app reads the run's
`damit_hazard_report.json` for the preset/mode it ran, the hits that set the class and its warning count (a ran
preset other than the chosen one is logged). The Report step stores this on the record (`hazardResult`) with the
choice and receptors it was made for and **leads with it** as *DamIT classification (<preset or custom methods>)*; the
paper sheet's stamp becomes `DAMIT CLASSIFY: <class>`. A result for another preset, other methods or changed
receptors is shown as out of date, never as the new choice's class. The desk screen stays on the Screen step, the
dashboard and the paper sheet only as a *schematic preview* on the ND / ACER TM 11 desk rules, labeled as not the DamIT
classification.

## Class of record and new dams (`damit_dam.json`)

`damit:classify` reads `current_class` and `is_new` from `DAM_JSON`: S6 looks up `by_current_class` with `"new"`
when `is_new` is true, else `str(current_class)`; R8's lowering-from-High rule does `int(current_class)`; R6
(new-dam proximity) runs only when `is_new` is true.

**`current_class`** is the dam's class of record as the catalog ordinal (0 Minimal, 1 Low, 2 Significant, 3 High,
4 Extremely High), mapped in one place, `desktop/damit_desktop/hazard_class.py` (`class_ordinal`):

- an int, or a string `"0"`–`"4"`, is used as is; anything outside 0–4 (or a bool, NaN) is not mapped;
- otherwise the text is matched against known labels and the **earliest** match wins, so the primary class leads:
  `"ND MEDIUM (NID hazard Significant)"` → 2. Longer phrases are listed before the words they contain
  (`extremely high` before `high`, `very low` before `low`). Labels: Minimal / Very Low / No Public Hazard → 0,
  Low → 1, Significant / Medium / Intermediate / Moderate → 2, High → 3, Extremely High → 4, and Class A → 1,
  Class B → 2, Class C → 3 (New York style; classify already reads "class c" as 3);
- text that says there is no class (Undetermined, Unknown, Not rated / classified, cleared, Review, N/A) or that
  matches no label gives no ordinal, and **`current_class` is omitted** — the raw text is never sent as the class.

**`is_new`** is always written as a boolean. It is `true` only when the **New dam** box on the Record step (under the
dam fields) is ticked (`DamRecord.isNew`, persisted with the dam). It defaults to unticked / `false`, is never inferred
from a missing class of record, is cleared when the record is filled from another NID dam, and is `false` on every
sample dam. The desk's `dam.json` export carries it too (`is_new`).

## Failure mode default

A failure mode the user did not choose (missing, blank or unknown) is **piping**, never overtopping (Nick,
2026-11-05, carried over from Crest): in the desk (`blankDam`, the engine), in what the page sends (`handoff.ts`), in
`dam.json` (`failure_mode`), in the `rundam` `METHOD` option and in the CLI's `runner_config.json`
(`breach.failure_mode`).

## Jurisdiction context (preset vs custom)

The Report step's *Jurisdiction and classification methods* panel sets `dam.classification`, written into `dam.json`
and `damit_settings.json`, and sent to the screener as `MODE` + `PRESET` or `SCENARIOS` / `METHODS`, and to
`classify` as the `PRESET` option or `METHODS` / `SCENARIOS` / `MODIFIERS`:

```json
{ "mode": "preset", "preset": "FEMA333", "catalog_version": "2026-11-09", "tool": "damit_crest", "when": "…" }
{ "mode": "custom", "methods": ["S1", "M2", "M8a", "R7"], "apply_advisory": true, "tool": "damit_crest", "when": "…" }
```

Default: preset mode, **FEMA 333 baseline** (national, not a state). No threshold is written or shown by the app; the
thresholds live in the hazard catalog data file `damit:classify` reads (Appendix A.7). The desk's preset list is a
display index, `src/lib/crest/data/jurisdictions.json`, generated from DamIT Catalog (`damit_catalog/data/`, through
`python3 -m damit_hazard.engine.catalog --export`) by `node scripts/sync-jurisdictions.mjs` (`--check` fails when it
is out of date).

## Open points for review

1. **Preset ids (resolved).** DamIT Hazard reads DamIT Catalog, whose stored Reclamation id is `USBR` with
   `USBR_TM11` as an alias, so the desk's `USBR` passes Screener preflight and `damit:classify`.
2. **One catalog (resolved).** The desk index is generated from DamIT Catalog; `damit_hazard/data/catalog.json` is gone.
3. No batch algorithm and no runner CLI are published; the CLI search and the `batch` name stay for a later runner.
4. If review renames any id or parameter: change `DEFAULT_ALGORITHMS` in `desktop/damit_desktop/algorithms.py` and
   `src/lib/crest/handoff.ts` (and their tests), rebuild the bundle (`npm run build:desktop`) and commit; until then
   users can set `DAMIT_ALG_*` or `damit-handoff.json`. Parameter renames are absorbed by the `help` filter but the
   value then is not sent; check the job log.
