# DamIT Hazard 0.1.0

A QGIS plugin (3.28 – 4.x, Qt5 and Qt6) that suggests a dam hazard class from existing flood
rasters and receptor layers. It uses the methods, modifiers and jurisdiction presets in
*US Dam Hazard Classification — Corrected Edition* (9 Nov 2026), Appendix A.

> Informational screening aid, not legal or engineering advice and not a regulatory
> determination. The output is a suggested classification; the engineer of record and the
> regulating agency make the determination. Items marked (unverified), (secondary) or (draft)
> should be confirmed before a preset is relied on.

**Requires the DamIT Catalog plugin** (`damit_catalog/`, declared as
`plugin_dependencies=DamIT Catalog`). Every preset, method, threshold, scenario, modifier and
class label comes from DamIT Catalog's Appendix A data files; DamIT Hazard ships no catalog of
its own (see *Where the thresholds come from*).

It does **not** run a breach or flood model. The rasters come from a run made elsewhere; the
scenario ID (S1–S7) records which run they are.

* Processing provider `damit`, algorithm **`damit:classify`** (shared with the other DamIT
  plugins: whichever loads first registers the provider, the others add their algorithms).
* Menu **DamIT ▸ DamIT Hazard…** opens the window.
* Based on DamSafety_Hazard (DWR_Plugins at `e12f35d`): the structure sampling
  (`sampling/fastsample.py`) and the TM-11 houses / mobile homes curves (`data/tm11_charts.json`,
  from DamSafety_Core `tm11_curves`) are copied, not re-digitized. The window widgets
  (`ui/`) are DamSafety_Core's GUI-grammar widgets.

## Modes

**Preset** – pick one of the DamIT Catalog presets (19 in catalog 2026.11.09.4: the 15 of Appendix A
plus 4 from the Nov 2026 In-Depth Summaries): FEMA 333 baseline, USBR (ACER TM-11), BIA (secondary),
NRCS (unverified), North Dakota, Nebraska, New York (draft), Virginia, Texas, Idaho, Colorado, Rhode
Island, Arizona, California, Alaska, Alabama, North Carolina, USACE (secondary), TVA. Alabama, North
Carolina, USACE and TVA have no jurisdiction-specific criteria in the sources: they run FEMA 333-style
M5 (High at 1+ life) and M13, and every run gets a `method_fallback_m13` warning. Class
labels are the jurisdiction's own. In `damit:classify` the `PRESET` list shows `ID: label`
(e.g. `ND: North Dakota (REG_05.2026)`), and `PRESET_ID` takes a preset ID or alias as text
(it wins over the list): `USBR` and `USBR_TM11` are the same preset.

**Custom** – tick methods, modifiers and scenarios by name. No jurisdiction appears in the
method list; labels are generic (Minimal, Low, Significant, High, Extremely High); each method's
source is still listed under *Citations* in the report.

In both modes the parameters (thresholds) of the chosen methods are editable JSON
(`OVERRIDES`); a key may use the classifier's name (`{"M2": {"threshold_ft": 2.5}}`) or the
catalog's (`{"M2": {"depth_ft": 2.5}}`).

## Where the thresholds come from

DamIT Catalog is the single source of truth. At run time DamIT Hazard imports `damit_catalog`
(the installed plugin, or the `damit_catalog/` folder beside `damit_hazard/` in a checkout),
which reads `DAMIT_CATALOG_DIR` if set, else its bundled `data/`. `engine/catalog.py`
translates the catalog to the classifier's configuration:

* `methods.json`, `modifiers.json`, `scenarios.json`, `labels.json`, `presets.json`: every
  threshold, count band, class label, scenario, modifier and preset bundle (parameter renames
  such as `depth_ft` → `threshold_ft` are listed in `engine/catalog.py` `RENAMES`; the M4b /
  M4c bands and the M3 / M8a / M8g class lists are read from the catalog rules).
* `hazard.json` (in DamIT Catalog): only what the Appendix A files do not express — the
  receptor-type vocabulary of Hazard's layers, which TM-11 chart applies to which receptor,
  sampling defaults (5 ft edge ring, 20 ft point disc, 10 ft line step), the M13 type →
  descriptor guesses, per-preset notes, and which catalog M3 rule sets each M3 row's datums. A
  test checks that it repeats no parameter the other files carry. The USBR M1 reading (M1 marks
  lives for M5 and returns no class itself: `class_zones: []`), New York's R2 floor presumption
  and R8 lowering-from-High, and the preset status marks are in `presets.json` /
  `modifiers.json`, so DamIT Screener applies them too (catalog 2026.11.09.3).
* `damit_hazard/data/tm11_charts.json` stays here: the digitized TM-11 curves.

Edit a copy of DamIT Catalog's `data/` and set `DAMIT_CATALOG_DIR` to change presets or
thresholds for Hazard, Screener and Runner at once; each report records the catalog version,
SHA-256 and folder. Neither the engine nor the translation contains a threshold number
(`tests/test_catalog.py` checks both).

`python3 -m damit_hazard.engine.catalog --export out.json` writes the catalog as Hazard reads
it (one JSON file), e.g. for DamIT Crest's jurisdiction index.

## How the class is formed

1. Rule results set the suggested class (the highest one wins). Advisory results are listed
   and count only when *Apply advisory results* is ticked.
2. Modifiers (R1–R10) filter receptors first (transient use, future development, domain and
   D1/D2 cutoffs, incremental masking) and adjust the result after (no evacuation credit, dams
   in series, proximity rule for new dams, re-review trigger).
3. The report names the driving receptors and the method IDs, per scenario.
4. A missing input is flagged as *not evaluated*; it never passes silently.

## Inputs

Rasters (feet, ft/s and ft²/s, or tick *metres*): maximum depth (required), velocity, DV,
water-surface elevation, non-breach depth, arrival time. Layers: structures, roads, railroads,
critical facilities, lifelines, environmental / cultural features, routed domain. Optional
JSON: a dam record (`dam_id`, `nid_id`, `storage_acft`, `current_class`, `is_new`, `is_sample`, ...),
more runs (one per scenario), extra TM-11 charts.

**NID dams only.** The dam inventory is the USACE National Inventory of Dams (NID). A dam record
needs the dam's NID ID (two letters and digits, e.g. `ND00199`): `dam_id` should be the NID ID, or
`nid_id` carries it. damit:classify **fails** on a dam record whose `nid_id` is not an NID ID, whose
`dam_id` is a state dam-safety / dugout style id (`DWR-2801`, `DUG-130`, `UNK-…`) or a different NID
ID than its `nid_id`, or that has no NID ID at all (`SAMPLE-4031`, `DESK-014`, `NEW` are not NID IDs).
The exceptions are a new / proposed dam (`is_new` true, or `new_or_existing` = new / proposed) and a desk
sample (`is_sample` true): they run, with a warning (report flag `nid_exception`). The report lists the NID
ID under *Inputs*. Without a dam record the result is flagged `nid_none` (not tied to an NID dam). The rule
is DamIT Catalog's `handoff.nid_rule` (the same one DamIT Screener and Runner apply); `engine/core.py`
`nid_rule` only passes through to it.

Attribute names are matched case-insensitively; the first of these per field is used
(`engine/receptors.py` has the full list):

| Field | Also read as |
|---|---|
| `type` | struct_type, bldg_type, occ_type, facility_type, lifeline_type, site_type |
| `occupants` | people, persons, par, pop, population |
| `floor_elev` / `floor_height_ft` | ffe, first_floor_elev / ffh, found_ht |
| `ground_elev`, `foundation_elev` | lag, grade_elev / found_elev |
| `future`, `nights_per_year`, `descriptor` | proposed / nights / m13 |
| `road_class`, `aadt`, `lanes`, `func_class` | rd_class / adt, traffic / num_lanes / fclass |
| `sole_access`, `isolates_homes`, `crossings_failed`, `washout` | |
| `active`, `trains_per_day`, `passenger`, `freight_class`, `line_category`, `main_line`, `hazmat_yard`, `strategic` | |
| `impact`, `units_served`, `outage_days`, `major_population`, `ww_class`, `own_supply` | |
| `mitigation`, `substantial`, `anadromous`, `agency_identified`, `unique`, `permanent` | |

## Outputs

In the output folder: `damit_hazard_report.md`, `.html`, `.json` (suggested class, driving
receptors and methods, advisory results, per-scenario results, flags, inputs with dates and
sizes, citations) and `damit_hazard_receptors.gpkg` (one layer per input layer; fields `rid`,
`src_fid`, `kind`, `type`, `class`, `label`, `adv_class`, `methods`, `depth_ft`, `vel_fps`,
`dv_ft2s`, `rise_ft`, `flags`, `sampling`), styled by class.

File-path inputs through `processing.run` or the Processing Toolbox leave nothing beside the
input rasters. Classify checks its parameters and runs with GDAL PAM off
(`GDAL_PAM_ENABLED=NO`, the previous value restored afterwards), so that path does not write
`<raster>.aux.xml` next to the files. Limits remain:

* The DamIT Hazard window always passes layers already loaded in the project, and the Toolbox
  does the same when inputs are picked from the project-layer dropdown. QGIS writes the same
  `.tif.aux.xml` files just from loading and removing those layers, with no classify at all;
  this plugin cannot stop that.
* A bare `qgis_process run damit:classify` still writes the sidecars, because `qgis_process` opens
  the rasters outside the algorithm's own steps. Set `GDAL_PAM_ENABLED=NO` in its environment.
  DamIT Crest already does this on its classify call (`qgis_run.classify_env`).

## Only partly evaluable

* **M1 TM-11 charts:** houses and mobile homes are digitized; passenger vehicles, adults and
  children (Figs 4–6) are not. Receptors of those types are flagged; supply curves with
  *Extra TM-11 charts*. Judgment-zone hits are flagged; R7 promotes them only if configured.
* **M12d** (intangible losses identified by a resource agency): flag only, no class.
* **M11c** "several weeks" outage has no number in the source (`high_outage_days` is null):
  flagged.
* **M13** descriptors: an explicit `descriptor` attribute is a rule result; a descriptor
  guessed from the receptor type is advisory and flagged.
* **M6** Colorado / Idaho variants need floor or foundation attributes; without them the
  receptor is flagged.
* **M8f** isolation needs `isolates_homes` / `crossings_failed` attributes; no network
  analysis is done.
* Draft, secondary or unverified items follow DamIT Catalog's fields: preset `status` in
  `presets.json` (NRCS unverified, New York draft) and per-method marks (BIA M5 secondary). Those
  presets are marked beside their names. Methods are as documented, with no method-level draft marks.
* **M3 institutions:** Significant / Low is split at the foundation ground line, and High
  (2 ft or DV 15) is tested at the lowest occupied floor. The datums come from DamIT Catalog's M3
  rules. M10b uses the same datums.

## Tests

    python3 damit_hazard/tests/run_tests.py            # engine, DamIT Catalog bridge, TM-11 (no QGIS)
    QT_QPA_PLATFORM=offscreen <QGIS python> damit_hazard/tests/run_tests.py
                                                        # + sampling (GDAL) and damit:classify

Set `DWR_PLUGINS_ROOT` to a DWR_Plugins checkout to also check the TM-11 curves and the
sampling code against DamSafety_Core / DamSafety_Hazard. The runner works with or without
pytest.
