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
| Classify | `classify` | `--PRESET=<index>` (0 = custom, else the option whose text is the preset's catalog label) `[--METHODS --SCENARIOS --MODIFIERS] [--APPLY_ADVISORY] --DEPTH [--VELOCITY] --DAM_JSON=<dam folder>/damit_dam.json --DAM_NAME --OUTPUT=<dam folder>/classify` |

Details:

- **DAMS layer.** `dam_point.geojson` is this dam alone as a point (EPSG:4326: breach point, else reservoir point,
  else the record's lon/lat) with DamIT Screener's field names (`dam_id`, `name`, `height_ft`, `storage_acft`,
  `top_of_dam_elev_ft`, `normal_pool_elev_ft`, `surface_area_ac`, `hydrograph_csv` = `inputs/breach_hydrograph.csv`,
  `failure_mode`), so no `FIELD_MAP` is needed. Without a position no layer is written and the preflight reports it.
- **One dam.** `damit_settings.json` carries `dam_ids` (DamIT Screener's filter) and `only_ids`, so `runchain`
  screens this dam only. It also carries `data_folder` (and `suite_folder`), `terrain` / `local_dem` when a DEM is
  known, and `classification`.
- **READY.** Read from the preflight's `READY:` output, else `FAILS:`, else the report's first line. Anything else
  stops before `runchain`.
- **Read-back.** After the chain the app reads `screening` from this dam's `damit_handoff.json` (preliminary label,
  ordinal, flags; logged as a screening suggestion, not an official class), and, for an ND-style port,
  `10_reports/summary.csv`.
- **Flood model.** `damit_run:rundam` takes no DEM parameter, so a missing DEM is logged as a gap instead of
  stopping; for an algorithm that declares `DEM` (or for the CLI) a missing DEM still stops. DamIT Runner 0.1.0
  prepares `run_setup.json` in a new folder under `<work>/runs`; the app reports `RUN_FOLDER`. It never sends an
  engine choice or `DRY_RUN=false`.
- **Classify** needs the model run's maximum depth raster: type its path under *Depth raster* (velocity optional).
  Without it, or when the installed algorithm does not list the chosen preset, the job stops before running.
  `damit_dam.json` is a flat record: `dam_id`, `name`, `storage_acft`, `height_ft`, `current_class`, `is_new`,
  `failure_mode`, and `class_of_record_text` (the original class-of-record text, for people; classify ignores it).
  See *Class of record and new dams* below.

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
display index, `src/lib/crest/data/jurisdictions.json`, generated from `damit_hazard/data/catalog.json` by
`node scripts/sync-jurisdictions.mjs` (`--check` fails when it is out of date).

## Open points for review

1. **Preset ids differ between the two catalogs.** QGIS Dev's `damit_hazard/data/catalog.json` (the source of the
   desk's index) calls the Reclamation preset `USBR`; SWE's `damit_catalog/data/presets.json` calls it `USBR_TM11`.
   The other 14 ids match. The screener gets the desk's id, so `USBR` fails its preflight until one catalog changes.
2. The desk index is generated from `damit_hazard`'s catalog; once one shared catalog is merged, point
   `scripts/sync-jurisdictions.mjs` at it.
3. No batch algorithm and no runner CLI are published; the CLI search and the `batch` name stay for a later runner.
4. If review renames any id or parameter: change `DEFAULT_ALGORITHMS` in `desktop/damit_desktop/algorithms.py` and
   `src/lib/crest/handoff.ts` (and their tests), rebuild the bundle (`npm run build:desktop`) and commit; until then
   users can set `DAMIT_ALG_*` or `damit-handoff.json`. Parameter renames are absorbed by the `help` filter but the
   value then is not sent; check the job log.
