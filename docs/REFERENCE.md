# DamIT reference (full plugin, catalog and hand-off details)

The short introduction is the [README](../README.md). This page keeps the full detail.

DamIT: multi-jurisdiction dam hazard screening, breach modeling, and classification plugins for QGIS
(3.28 – 4.99, Qt5 and Qt6).

> **Suggestions, not determinations.** Every DamIT result is a *suggested* classification. The engineer of
> record and the regulating agency make the determination.

## Plugins in this repository

| Folder | Display name | Processing provider | Role |
|---|---|---|---|
| `damit_catalog/` | DamIT Catalog | none | Appendix A data catalog (JSON) + Python loader, evaluator and hand-off schema |
| `damit_screener/` | DamIT Screener | `damit_screen` | Preflight, scenario-driven screening chain with a 2D screening flood (built-in engine), preliminary suggestion, hand-off packages |
| `damit_runner/` | DamIT Runner | `damit_run` | Full breach engine: LISFLOOD-FP (built-in solver), ANUGA 2D, HEC-RAS 2D. 8 Processing algorithms: rundam, batch, sensitivity, cascade, hydrograph, estimate, check, finishanuga |
| [`damit_hazard/`](../damit_hazard/README.md) | DamIT Hazard | `damit` | Suggested hazard class from flood rasters and receptor layers, 19 jurisdiction presets or a custom method set (`damit:classify`) |
| [`damit_core/`](../damit_core/README.md) | DamIT Core | none | Shared library: suite settings, DamIT plugin list and version check, US state table, dam-record field helpers, catalog access, HTTP helper. Menu: About only |
| [`damit_setup/`](../damit_setup/README.md) | DamIT Setup | none | Start here: suite data folder, work folder, state / preset, suite check, settings fill, hand-off to `damit_screen:preflight` |
| [`damit_data/`](../damit_data/README.md) | DamIT Data | `damit_data` | 9 national data sources: NSI, Microsoft footprints, OSM, USA Structures, HPMS roads, FRA rail, Census TIGER counties, NBI bridges, HIFLD facilities (`damit_data:download`, `:status`) |
| [`damit_hazardlite/`](../damit_hazardlite/README.md) | DamIT Hazard Lite | `damit_lite` | One tool, `damit_lite:classify`: suggested class from depth / velocity rasters at structures, roads and rail with DamIT Catalog presets or custom methods |
| [`damit_pmp/`](../damit_pmp/README.md) | DamIT PMP | `damit_pmp` | NOAA Atlas 14 only: point / basin precipitation-frequency tables, Atlas 14 GIS grids fetched from NOAA for any return period and duration, alternating-block hyetograph, grid basin statistics, LISFLOOD-FP / ANUGA rain-on-grid files, an ANUGA rain-on-grid job on the runner's gmsh mesh (no PMP values; launches nothing unless asked) |
| [`damit_finder/`](../damit_finder/README.md) | DamIT Finder | `damit_find` | Structures not on the lists: fills across streams in the LiDAR (dams, dry dams, road fills), ponds and dugouts in a water-body layer, road / rail stream crossings (culverts); each listed / unsure / new against the NID and the other layers you give |
| [`damit_crest/`](../damit_crest/README.md) | DamIT Crest | none (desktop app) | Local desktop app (pywebview), adapted from Crest: draw a dam, size its breach, view results and flood maps, and hand one dam to the DamIT QGIS plugins through `qgis_process` |

**DamIT Hazard** (`damit_hazard/`, provider `damit`, algorithm `damit:classify`) classifies finished runs from
rasters and receptors. DamIT Screener and DamIT Runner do not use the `damit` provider id and do not classify
finished rasters.

**NID dams only.** The dam inventory for every DamIT plugin is the USACE National Inventory of Dams (NID).
A dam record needs an NID ID (two letters and digits, e.g. `ND00199`): `dam_id` should be the NID ID, or a
`nid_id` field carries it (a different `dam_id` with a valid `nid_id` passes with a warning). Refused, even
when `nid_id` is set or the record is new / a sample: a `nid_id` that is not an NID ID, a `dam_id` that is a
different NID ID than `nid_id`, and a state dam-safety / dugout / unknown-structure id (`DWR-2801`, `DUG-130`,
`UNK-…`). The only records allowed without an NID ID are a new / proposed dam (`is_new` true or
`new_or_existing` = new / proposed) and a desk sample (`is_sample` true); they pass with a warning / gap.
One rule, `handoff.nid_rule` in DamIT Catalog, used by DamIT Screener (a dam problem, FAIL), DamIT Runner (the
package is rejected) and DamIT Hazard (`damit:classify` fails on such a `DAM_JSON`). DamIT Crest hands off
`dam_id` = NID ID, `nid_id`, `is_new` and `is_sample` (and `NID_ID` / `IS_NEW` / `IS_SAMPLE` to
`damit_run:rundam`) and stops before `qgis_process` on a record the plugins would refuse. Presets (including
North Dakota REG_05.2026) are unchanged.


DamIT Hazard, DamIT Screener and DamIT Runner all declare `plugin_dependencies=DamIT Catalog` and read their
presets, methods and thresholds from it, so install DamIT Catalog first (the QGIS Plugin Manager offers it). None of the DamIT plugins depend on the DamSafety / DWR plugins.

DamIT Setup, DamIT Data, DamIT Hazard Lite, DamIT PMP and DamIT Finder declare `plugin_dependencies=DamIT Core` (Setup and
Hazard Lite also DamIT Catalog). Install order: DamIT Core, DamIT Catalog, then the rest. Provider IDs are all
distinct: `damit` (Hazard), `damit_lite` (Hazard Lite), `damit_screen`, `damit_run`, `damit_data`, `damit_pmp`, `damit_find`;
no DamIT tool hands off to `nddam:*` or `ndbreach:*`. DamIT Hazard, Screener, Runner and Crest do not import
DamIT Core yet; they can switch to its settings / plugin registry later.

## The catalog: Appendix A as data

`damit_catalog/data/` holds Appendix A of *US Dam Hazard Classification — Corrected Edition* (Nov 9, 2026),
pages 18–30:

| File | Content |
|---|---|
| `catalog.json` | Manifest: catalog version, source, the two operating modes, combination logic, validation flags |
| `methods.json` | Methods M1–M13 (M4a–c, M8a–g, M9a–c, M10a–b, M11a–c, M12a–d): name, inputs, parameters, class returned, strength (rule / advisory), citation, verification status, and the rules in a small JSON condition language |
| `scenarios.json` | Scenarios S1–S7 (pool rule, dam fields each needs) and domain cutoffs D1, D2 |
| `modifiers.json` | Modifiers R1–R10 |
| `labels.json` | Class-label normalization (ordinal 0 Minimal … 4 Extremely High, local equivalents) |
| `hazard.json` | DamIT Hazard's engine profile: receptor-type vocabulary, TM-11 chart assignment, sampling defaults, per-preset notes. Repeats no threshold of the other files and holds no rule DamIT Screener would miss |
| `presets.json` | FEMA 333, USBR (ACER TM-11), BIA, NRCS, North Dakota (REG_05.2026), Nebraska, New York, Virginia, Texas, Idaho, Colorado, Rhode Island, Arizona, California, Alaska (Appendix A.6); Alabama, North Carolina, USACE, TVA (Nov 2026 Summaries); `no_preset` lists FERC, USFWS, MSHA and the other ~40 states with the reason |

Preset IDs may have aliases (`presets.json` `aliases`): `USBR_TM11` is accepted everywhere `USBR` is (Screener
`PRESET`, hand-off validation, `damit:classify` `PRESET_ID`) and a run records the stored ID `USBR`.

Every threshold, label map, method parameter, scenario and modifier lives in those files; the Python code only
validates ID formats and interprets the rule language. **Presets can be updated without a plugin release**:
edit a copy of `data/` and point `DAMIT_CATALOG_DIR` (or the Screener's `catalog_dir` setting) at it. Each run
records the catalog version and a SHA-256 of the data files.

Items the document marks *(unverified)* or *(secondary)* carry that status and raise a flag. Where the
document has a dash (no confirmed method) the preset falls back to M13 and engineering judgment; where it
confirms no scenario, the user must pick one and the run is flagged. M1's depth–velocity chart curves are not
digitized in the catalog: M1 reads a per-structure `m1_zone` (from DamIT Hazard or the engineer) and is
blocked, with a flag, on a 1D run when the preset requires 2D.

#### Catalog 2026.11.09.4: the two Nov 2026 source documents

The catalog follows two documents (both recorded in `catalog.json` `source`):

* *US Dam Hazard Classification — Corrected Edition* (Nov 9, 2026; re-issued 22:17 UTC). Its text, including
  Appendix A, is identical to the edition the catalog was built from; the presets were re-checked against
  Appendix A after the later PRs.
* *In-Depth Summaries: Dam & Pond Hazard Classification — Federal Agencies and the States* (compiled Nov 2026,
  printed Nov 9, 2026). Where it is more current or more precise, it corrects or enriches the presets:
  * New presets **AL**, **NC**, **USACE** (M5 secondary) and **TVA**: FEMA 333-style M5 (High at 1+ life) + M13,
    no confirmed scenario, flagged `method_fallback_m13` (the sources give no jurisdiction-specific criteria).
    Alabama notes: AEMA, effective Oct 1, 2026, voluntary for private owners, act number secondary.
    North Carolina's small-dam exemption is a jurisdiction rule and is not encoded.
  * **TX** adds M13 with 30 TAC § 299.14's economic-loss wording (isolated homes, secondary highways, minor
    railroads, utility interruption → Significant; excessive urban economic loss → High) beside M4c.
  * **AK** M13 uses the 11 AAC 93.157 Class II / III wording; the anadromous-fish criterion is the current
    one and the old "salmon spawning habitat" wording is named only as superseded.
  * **NY** adds M5 (High at 1+ life): TOGS 3.1.5 "where loss of a single human life is likely … Class C".
  * **USBR** S5 for borderline dams is no longer marked unverified (Summaries F-3).
  * Citations and notes updated (ND REG_05.2026 § 5.5 → "§ 5.1.3" error flagged, NE DWEE, CO Rule 4.13, RI,
    AZ, VA superseded size-based SDF note, NRCS NEM § 520.21).
  * FERC, USFWS, MSHA and the remaining ~40 states get no preset (`presets.json` `no_preset` says why).
* Kept as decided: USBR M1 marks lives and M5 sets the class; M3 institution datums; status marks. NRCS stays
  `unverified` although the Summaries report NEM § 520.21 verified verbatim (`status_review`): the owner decides.

#### Decisions recorded in catalog 2026.11.09.3

These were open questions in PR #5. They are catalog data, so DamIT Hazard and DamIT Screener (and Hazard
Lite, which uses the same evaluator) apply them the same way.

* **USBR M1.** M1 marks the lives in jeopardy (habitable structures in the high-danger zone) and M5 sets the
  class: 1–6 Significant, 7 or more High. In `presets.json`, the USBR preset gives M1 `class_zones: []`, so M1
  cannot return High by itself. Other presets keep the general M1 rule (high-danger zone → High).
* **M3 institutions.** The Significant / Low split uses depth above the foundation ground line, and the High
  test (2 ft, DV 15) uses depth above the lowest occupied floor. These are the catalog's existing M3 rules and
  values. DamIT Hazard now reads each M3 row's datums from those rules instead of using the floor for both.
  M10b uses the same datums.
* **Status marks.** A preset's document status is `presets.json` `status` (allowed values: `status_values`).
  NRCS is `unverified` because its hazard-definition wording is unverified, and New York is `draft` because
  TOGS 3.1.5 is marked DRAFT. `resolve_preset` returns the status and raises a `preset_status` flag, and
  DamIT Hazard shows it beside the preset name. Methods stay `as_documented`, so DamIT Hazard's older
  method-level draft marks (M4b, M8d, M8f, M9c, M10a, M11c, M12b, D1; M13 unverified) are not restored: they
  came from the NY and NRCS presets.
* **New York R2 / R8.** `modifiers.json` adds R2 `floor_presumption` (default false) and R8 `variant` (default
  `storage_limit`). New York's `modifier_overrides` set `floor_presumption: true` and `lowering_from_high`.
  Before, these were only in `hazard.json`, which DamIT Screener does not read.

### Preset mode and custom mode

* **Preset mode** — pick a state or agency; its scenarios, method IDs with parameter overrides, modifiers and
  class labels are loaded (e.g. North Dakota: S3 + S7; M1 two charts, 2D; M2 > 2 ft, 1D only; M6 advisory;
  M8a, M8b, M9a, M11a; R2, R3, R4 advisory, R5, R7, R8, R9; Low / Medium / High).
* **Custom mode** — tick method IDs; no state or agency names are shown, parameters stay editable, results use
  the generic labels. Source citations still go in the run report.

Combination logic (Appendix A): every enabled scenario runs and the most severe governs; the suggested class
is the highest *rule*-strength result across receptors; advisory results are reported beside it and applied
only if the user opts in; modifiers (R-codes) are applied; the driving receptors and method IDs are reported.

## DamIT Screener (`damit_screen`)

| Algorithm | What it does |
|---|---|
| `damit_screen:preflight` | Work folder, disk, catalog, preset/custom selection and its flags, dams layer and the fields each chosen scenario needs, terrain, receptor fields the enabled methods read. Missing inputs are WARN/FAIL, never passed. |
| `damit_screen:runchain` | Preflight (a FAIL refuses the run), then per dam: prepare → terrain → storage at each scenario pool → breach direction → hydrograph → triage (M13) → 2D screening flood (engine2d) → preliminary suggestion → hand-off. Writes a Markdown run report. |
| `damit_screen:prepare`, `:terrain`, `:storage`, `:breachdirection`, `:hydrograph`, `:triage`, `:engine2d`, `:suggest` | The individual steps. |
| `damit_screen:handoff` | Writes `<work>/handoff/<dam>/damit_handoff.json` for DamIT Runner. |
| `damit_screen:report` | Rewrites the run report from the chain summary. |

0.2.0 `engine2d` is the DamSafety Screening tool-7 flood (`damit_runner/flood/screen.py`, the built-in
finite-volume engine, run in the QGIS process): the dam's hydrograph CSV, else a Froehlich (2008) piping breach,
sunny day from the top of dam with no outlet or spillway flow; inflow at the downstream toe (lowest ground 5 m to
H × (DS slope + 1) from the dam line, 3:1 when the slope is missing, never more than 150 m, side check); 20 m cell,
12 h clock grown × 1.5 to 96 h, 1,500 m clip and 600 m corridor grown to 12,000 m (`larger_clips` 0 / 1 / 2), and a
wall-clock limit of 0.8 × `DAMIT_SCREENING_TIMEOUT_S` (else 3600 s) after which the maxima so far are kept and
flagged partial. It writes `Screening Depth (Max).tif`, `Screening Velocity (Max).tif`, `Screening DV (Max).tif`
and `Screening Arrival Time.tif` into `<work>/dams/<id>/`, samples peak depth / velocity / DV over wet cells at the
receptors (and the TM-11 M1 chart zone, from DamIT Hazard's digitized charts when installed), and the suggestion
step gives the preliminary class. Settings JSON: `engine2d` (`builtin` | `off`), `grid_m`, `simh`, `simmax`,
`larger_clips`, `local_dem`, `timeout_s`, `z_units`. DamIT Screener never launches LISFLOOD-FP, ANUGA, HEC-RAS or
Wine; it needs DamIT Runner (plugin dependency) for the flood package.

0.3.0 (review-only follow-up to #16): `engine2d` = `lisflood` runs the screening flood on LISFLOOD-FP (ACC, the
same injection cells, under the same time limit; `lisflood_exe`, else an installed LISFLOOD-FP, else the built-in
engine with a warning); `builtin` stays the default. `larger_clips` 1 (the default) downloads each larger clip
fresh from the USGS 3DEP service into `<work>/dams/<id>/screen_inputs/terrain_3dep/r<radius>m/` (a new folder each
time; a failed download is noted and that clip uses the run's DEM). The step reports OK after a successful flood
(the terrain-edge case is in the detail) and names the engine used. `breach_direction` estimates the azimuth as
DamSafety Screening does (dam line + reservoir point + DEM; else reservoir → dam point; else the steepest DEM drop;
low-confidence cases say so) instead of a gap, and `terrain` checks coverage in the DEM's own CRS.

## DamIT Runner (`damit_run`)

| Algorithm | What it does |
|---|---|
| `damit_run:rundam` | Accepts a hand-off package (or equivalent parameters), validates it against the catalog, creates a **new** run folder and runs the breach model there (DRY_RUN off, the default), then copies the final rasters and vectors into `<DAMS_FOLDER>/<dam id>/`. DRY_RUN on: `run_setup.json`, the package, `README_run.md` and the expected-output contract only. |
| `damit_run:checkhandoff` | Validates a package and lists what a run still needs. |
| `damit_run:hecrasexport` | Writes a HEC-RAS project from a finished run. It does not run HEC-RAS. |
| `damit_run:batch` | The ported DamSafety batch: a layer of dams, one breach run each, with a summary CSV. |
| `damit_run:sensitivity`, `damit_run:cascade` | The ported sensitivity runs for one dam, and the failure of dams in a chain. |
| `damit_run:hydrograph`, `damit_run:estimate`, `damit_run:check` | Breach hydrograph only; run-time estimate for one dam; check of the LISFLOOD-FP / ANUGA installation. |
| `damit_run:finishanuga`, `damit_run:delineate` | Finish an ANUGA run after QGIS closed; delineate the watershed of a dam (USGS StreamStats). |

The eight tools from `batch` down are the DamSafety Runner's own (`algorithms/engine.py`, `core/`), registered since
0.4.1. Until then they failed to import and were silently absent. They take DamSafety's parameters and write
DamSafety's dam-folder layout; `damit_run:rundam` stays the tool the Screener hand-off and DamIT Crest call.

**Engine parity with DamSafety.** `core/`, `algorithms/engine.py`, `flood/breach.py` and DamIT Finder are ports of
the DamSafety plugins ([DWR_Plugins](https://github.com/nickdbendickson/DWR_Plugins)). `scripts/check_engine_parity.py`
compares every ported file with its original: identical, differing exactly as recorded in `damit_runner/PARITY.json`
(DamIT's names, imports and wording), or drifted, which fails. CI runs it on pull requests against the recorded
DamSafety commit and daily against DamSafety's `main`. After porting a DamSafety change run
`python3 scripts/check_engine_parity.py --dwr <DWR_Plugins checkout> --update` and commit `PARITY.json` with it.

0.2.0 runs the model like the DamSafety Runner's `rundam` (`ndbreach:rundam`, DWR_Plugins main), with its parameter
names and defaults: `METHOD` (Froehlich 2008 piping by default; TR-60, MacDonald, Von Thun & Gillette, Froehlich
1995, your CSV), `TIER` (LISFLOOD-FP only / then ANUGA; HEC-RAS 2D refused), `FORCE_ANUGA`, `CELL` 10 m,
`GRID_REFINE` on, `GRID_CHECK_CELL` 0, `MANNING` 0.06, `ARRIVAL_FT` 0.1, `EDGE_TOL_FT` 1, `LENGTH_MI` 4,
`HALF_WIDTH_MI` 1, `STEP_MI` 3, `MAX_EXTENT_MI` 20, `MAX_RUNS` 6, `LISFLOOD_MAX_WALL_S` 0 (24 h),
`LISFLOOD_MAX_TOTAL_WALL_S` 0, `DURATION_HR` 0 (automatic), `DURATION_MAX_HR` 96, `ANUGA_FINE` 100 m²,
`ANUGA_COARSE` 1000 m², `ANUGA_NEAR_MI` 1, `ANUGA_BUFFER` 500 m, `THREADS` 0, `LISFLOOD_EXE` (empty = `lisflood` on
PATH; `builtin` = the built-in numpy engine, never chosen by itself), `ANUGA_PYTHON`, `KEEP_FILES`, `PRODUCTS`,
`CONTOURS_HR` "0.25, 0.5, 1, 2, 4, 8", `PIPE_FRACTION` 0.5, `PIPE_DIA_FT` 0.5, `DEM_Z`. Sunny day: no outlet or
spillway flow, the reservoir starts at the top of dam (`PMF_FT` is recorded only). The inflow is the toe band rule
above. Outputs (US units) in `<run>/outputs/` and the dam folder: `Depth (Max).tif`, `Velocity (Max).tif`,
`WSE (Max).tif`, `Arrival Time.tif`, `hmax_ft.tif` (+ `vmax_fps`, `arr_hr`, `wsemax_ft`), `Flood Polygons (Max
Depth).geojson`, `Flood Extent.geojson`, `Arrival Zones.geojson`, `breach_hydrograph.csv`. It never starts HEC-RAS,
Wine, `ndbreach:rundam` or `ndbreach:batch`; only `damit_runner/flood/lisflood.py` starts a process (LISFLOOD-FP or
the ANUGA worker). Runner attaches catalog metadata and citations; classification is DamIT Hazard's job
(`damit:classify`).

0.3.0 (review-only follow-up to #16): an empty `LISFLOOD_EXE` searches the provider settings
(`DAMIT_RUN_LISFLOOD_EXE`, `DAMIT_RUN_USE_BUILTIN`, then the ND Breach Runner's `NDBREACH_LISFLOOD_EXE`),
`NDBREACH_LISFLOOD`, PATH and the usual install places, and runs the built-in engine **with a warning** when none is
found, as the old ND Breach Runner did; a named path that does not exist is still an error. The engine used is in
`run_report.json` / `run_setup.json` (`engine_selection`) and the outputs `ENGINE_USED`, `ENGINE_FALLBACK`,
`ENGINE_NOTE`. `OUTFLOW_EXTEND_PCT` (5) works as in the DamSafety Runner: once that share of the breach volume has
left through the model edges (LISFLOOD-FP `.mass`), every edge carrying at least 10% of the outflow and wet past the
arrival depth also moves out, even under `EDGE_TOL_FT`; a clock extension is not counted as a run. The ANUGA tier
uses the DamSafety Runner's default mesh (flood mask + buffer, refined near field, inlet at least 3 cells, a wider
second pass when the flood reaches the mesh edge; needs scipy).

North Dakota M1 (catalog plugin 0.1.1): a structure in the TM-11 judgment zone gives **Medium** (still flagged for
engineer review; R7 can take it higher). Other presets keep `judgment_class` null (flag only).

## Hand-off schema (`damit.handoff` v1)

Written by `damit_screen:handoff` / `:runchain`, read by `damit_run:rundam`, and readable by DamIT Hazard next
to a finished run. Defined in `damit_catalog/handoff.py`. Key fields:

* `mode`, `preset_id` / `preset_label` or the custom method list, `scenarios` (S-codes with pool / analyses),
  `conditional_scenarios`, `domain_cutoffs`, `methods` (resolved params + strength), `modifiers`, `label_map`,
  `apply_advisories`;
* `dam`: `dam_id` (the NID ID), `nid_id`, `is_new`, `is_sample`, name, x / y / crs, height, top of dam, normal pool, spillway, PMF peak, existing class,
  storage at top of dam, `scenario_pools` (pool elevation and storage per S-code), breach azimuth, peak outflow;
* `inputs`: `terrain`, `hydrograph_csv`, `storage_curve_csv`, `receptors_json` (paths, never copied);
* `screening`: preliminary suggestion (when receptor hydraulics exist) with driving receptors, advisories,
  flags and citations, or `not_computed`; plus the M13 triage;
* `gaps`: every step that could not complete; `catalog`: version + SHA-256;
* `target`: `damit_run:rundam` and `damit:classify`.

## Tests

```
DAMIT_QGIS_PYTHON="conda run --no-capture-output -n qgis334 python" tests/run_tests.sh
```

Pure-Python suites (catalog content against Appendix A, combination logic, preflight, chain, hand-off round
trip, engine refusal, packaging; DamIT Core settings / suite check / states / dam fields, Setup scan and hand-off,
Data sources and staged updates with a fake HTTP client, Hazard Lite records and catalog classes, PMP Atlas 14
parsing / cache / hyetograph from recorded PFDS answers) plus real-QGIS integration tests run offscreen with a
throw-away profile, `nice -n 19`, single-threaded. No test starts a model (subprocess launches are patched to
fail) and no test touches the network.

## Installation

### From packaged zips

```bash
python3 scripts/package_plugins.py dist/
```

This builds installable `.zip` files for all 9 plugins in `dist/`. Install in QGIS:
Plugins → Manage and Install Plugins → Install from ZIP. Install order: DamIT Core,
DamIT Catalog, then the rest.

### From the repository (development)

Add the repository root to your `QGIS_PLUGINPATH`:

```bash
export QGIS_PLUGINPATH=/path/to/damit
```

## Quick start: dam-to-classification walkthrough

1. **Pick a dam** — use the NID dam picker in DamIT Crest, or pass an NID ID directly.
   The state code (first two letters of the NID ID) auto-selects the jurisdiction preset.

2. **Screen** — `damit_screen:runchain` runs preflight checks (storage, height, location)
   and generates a hand-off package with the breach hydrograph and preset configuration.

3. **Run the breach model** — `damit_run:rundam` takes the hand-off package, prepares the
   run folder, and (with ENGINE=1) runs the LISFLOOD-FP solver to produce depth, velocity,
   and arrival-time rasters.

4. **Classify** — `damit:classify` reads the rasters and receptor layers (NSI structures,
   HPMS roads, FRA rail, HIFLD facilities), applies the preset's methods (M1–M13), and
   produces a suggested hazard class with a run report (Markdown, HTML, JSON) and a
   GeoPackage of receptors styled by class.

5. **Review** — the report names the driving method and receptors. The engineer of record
   and the regulating agency make the determination.

## National data sources

DamIT Data (`damit_data:download`) provides 9 per-state sources:

| Source | Data | Default |
|--------|------|---------|
| NSI | USACE National Structure Inventory (~120M structures) | Yes |
| Microsoft | US Building Footprints (outlines) | Yes |
| OSM | OpenStreetMap (Geofabrik GeoPackage) | Yes |
| USA Structures | FEMA/ORNL building outlines with occupancy | No |
| HPMS | FHWA roads (AADT, functional class, speed limit) | Yes |
| FRA Rail | FRA National Rail Network (active lines, class) | Yes |
| TIGER Counties | US Census county boundaries | No |
| NBI | FHWA National Bridge Inventory (bridges + culverts) | No |
| HIFLD | Critical facilities (hospitals, schools, fire, EMS) | No |

Additional: USGS 3DEP terrain (1m/10m DEM), NLCD land cover (Manning's n),
VERTCON vertical datum conversion (NGVD29→NAVD88), and USGS StreamStats
for ungauged basin delineation and flood frequency.
