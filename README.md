# damit

DamIT: multi-jurisdiction dam hazard screening, breach modeling, and classification plugins for QGIS
(3.28 – 4.99, Qt5 and Qt6).

> **Suggestions, not determinations.** Every DamIT result is a *suggested* classification. The engineer of
> record and the regulating agency make the determination.

## Plugins in this repository

| Folder | Display name | Processing provider | Role |
|---|---|---|---|
| `damit_catalog/` | DamIT Catalog | none | Appendix A data catalog (JSON) + Python loader, evaluator and hand-off schema |
| `damit_screener/` | DamIT Screener | `damit_screen` | Preflight, scenario-driven screening chain, preliminary suggestion, hand-off packages |
| `damit_runner/` | DamIT Runner | `damit_run` | Prepares and records breach runs from a hand-off package (0.1.0 launches no model) |
| [`damit_hazard/`](damit_hazard/README.md) | DamIT Hazard | `damit` | Suggested hazard class from flood rasters and receptor layers, 19 jurisdiction presets or a custom method set (`damit:classify`) |
| [`damit_core/`](damit_core/README.md) | DamIT Core | none | Shared library: suite settings, DamIT plugin list and version check, US state table, dam-record field helpers, catalog access, HTTP helper. Menu: About only |
| [`damit_setup/`](damit_setup/README.md) | DamIT Setup | none | Start here: suite data folder, work folder, state / preset, suite check, settings fill, hand-off to `damit_screen:preflight` |
| [`damit_data/`](damit_data/README.md) | DamIT Data | `damit_data` | Offline NSI, Microsoft footprints, OpenStreetMap (Geofabrik) and USA Structures layers for any US state (`damit_data:download`, `:status`) |
| [`damit_hazardlite/`](damit_hazardlite/README.md) | DamIT Hazard Lite | `damit_lite` | One tool, `damit_lite:classify`: suggested class from depth / velocity rasters at structures, roads and rail with DamIT Catalog presets or custom methods |
| [`damit_pmp/`](damit_pmp/README.md) | DamIT PMP | `damit_pmp` | NOAA Atlas 14 only: point / basin precipitation-frequency tables, alternating-block hyetograph, Atlas 14 grid basin statistics (no PMP values in 0.1.0) |
| [`damit_crest/`](damit_crest/README.md) | DamIT Crest | none (desktop app) | Local desktop app (pywebview), adapted from Crest: draw a dam, size its breach, view results and flood maps, and hand one dam to the DamIT QGIS plugins through `qgis_process` |

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

DamIT Setup, DamIT Data, DamIT Hazard Lite and DamIT PMP declare `plugin_dependencies=DamIT Core` (Setup and
Hazard Lite also DamIT Catalog). Install order: DamIT Core, DamIT Catalog, then the rest. Provider IDs are all
distinct: `damit` (Hazard), `damit_lite` (Hazard Lite), `damit_screen`, `damit_run`, `damit_data`, `damit_pmp`;
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
| `damit_screen:runchain` | Preflight (a FAIL refuses the run), then per dam: prepare → terrain → storage at each scenario pool → breach direction → hydrograph → triage (M13) → 2D engine hook (contract only) → preliminary suggestion → hand-off. Writes a Markdown run report. |
| `damit_screen:prepare`, `:terrain`, `:storage`, `:breachdirection`, `:hydrograph`, `:triage`, `:engine2d`, `:suggest` | The individual steps. |
| `damit_screen:handoff` | Writes `<work>/handoff/<dam>/damit_handoff.json` for DamIT Runner. |
| `damit_screen:report` | Rewrites the run report from the chain summary. |

The 2D screening engine hook only records its input/output contract in 0.1.0; DamIT Screener never launches
LISFLOOD-FP, ANUGA, HEC-RAS or Wine.

## DamIT Runner (`damit_run`)

| Algorithm | What it does |
|---|---|
| `damit_run:rundam` | Accepts a hand-off package (or equivalent parameters), validates it against the catalog and creates a **new** run folder with `run_setup.json`, a copy of the package, `README_run.md` and the expected-output contract for DamIT Hazard. |
| `damit_run:checkhandoff` | Validates a package and lists what a run still needs. |

0.1.0 is prepare / record only. Choosing a model engine (LISFLOOD-FP, ANUGA, HEC-RAS) or turning `DRY_RUN` off
is refused with a clear message; it never starts `ndbreach:rundam`, `ndbreach:batch` or Wine. Runner attaches
catalog metadata and citations; classification is DamIT Hazard's job (`damit:classify`).

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
