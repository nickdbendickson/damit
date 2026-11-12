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

**Dam record shape and where it comes from (0.2.1, 0.2.2).** `DAM_JSON` may be a flat record (as above) or the dam
folder's own `dam.json`, which nests its values under `fields`; the nested `fields` are read as they are (over
any top-level values), no hand-flattening. With `DAM_JSON` empty, damit:classify looks for a record (`engine/dam_record.py`):
the `dam.json` in the depth raster's folder or up to four folders above it (the run folder's parent is the dam
folder), else the run watcher's flat copy `~/local-ai/watch/<dam id>_<run folder>/dam_record_hazard.json` (folder
overridable with `DAMIT_WATCH_DIR`), for the run folder the raster sits in. 0.2.2: the normal raster path is
`<Dams>/<dam id>/Depth (Max).tif`, with no run folder in it, so the search also matches the watcher's real folder name
`<dam id>_run_<timestamp>/` for a folder above the raster that is the dam id (the copy's own `dam_id` must agree,
case-insensitive; the newest copy wins). A record found this way must have a dam
id; one with no usable NID ID is left out with a warning (an explicitly given file still fails, as before). The
report's *Inputs* lists the file used, marked "found automatically". Nothing is written beside it. Give `DAM_JSON`
to override.

**Inputs line and empty layers (0.2.2).** The report's *Inputs* section says what the dam record was: the file used and its
values, or "none given or found (...); only the name was given: <DAM_NAME>" (it used to print the name as a bare `{"name": ...}`).
A method that needs a layer kind (M9a rail, M11a lifelines, M8a/M8b roads) reports `no_layer` (warning) only when no receptor of that kind
was supplied. When some were supplied and sampled but none is in the scored set (every one outside the routed domain, or
dropped by the scenario, development and cutoff filters), it reports `layer_none_scored` (info) with the counts instead.

Attribute names are matched case-insensitively; the first of these per field is used
(`engine/receptors.py` has the full list):

| Field | Also read as |
|---|---|
| `type` | struct_type, bldg_type, occ_type, facility_type, lifeline_type, site_type |
| `occtype` (0.4.0) | the NSI occupancy type (RES1-1SWB, COM4, AGR1 ...); kept in the output, only suggests a type |
| `habitable`, `is_911` (0.4.0) | Crest's habitable flag; `is_911` / `nd911` / `address_point_911`, `source` = nd911, `placed` = 911 address point or an `nguid` mark an ND 911 address point |
| `bid`, `fd_id`, `usastrucid`, `nguid`, `crest_id`, `source_ref`, `structure_id` (0.4.0) | the first one found is the structure's key (`struct_key`) for the review |
| `occupants` | people, persons, par, pop, population |
| `floor_elev` / `floor_height_ft` | ffe, first_floor_elev / ffh, found_ht |
| `ground_elev`, `foundation_elev` | lag, grade_elev / found_elev |
| `future`, `nights_per_year`, `descriptor` | proposed / nights / m13 |
| `road_class`, `aadt`, `lanes`, `func_class` | rd_class / adt, traffic / num_lanes / fclass |
| `sole_access`, `isolates_homes`, `crossings_failed`, `washout` | |
| `active`, `trains_per_day`, `passenger`, `freight_class`, `line_category`, `main_line`, `hazmat_yard`, `strategic` | |
| `impact`, `units_served`, `outage_days`, `major_population`, `ww_class`, `own_supply` | |
| `mitigation`, `substantial`, `anadromous`, `agency_identified`, `unique`, `permanent` | |

### Trains per day when the rail layer has none (0.1.2)

NARN and similar rail layers have no trains-per-day field, so M9a's High test (10+ freight trains a day, or a
passenger line) cannot be confirmed and an impacted active line stays Medium with a `trains_unknown` warning.
DamIT assumes **no default**. Give the number explicitly with `RAIL_TRAINS_LOOKUP`, a CSV:

```
field,value,trains_per_day,source
SUBDIV,KO,15,"DamSafety DWR-2801 pass (BNSF KO subdivision) - needs Nick's ruling"
```

(the row above is an example of the format, not a shipped value). A rail line whose own `trains_per_day` is empty
and whose attribute `field` equals `value` (case-insensitive, first matching row wins) takes that number. Every
value used this way is flagged `trains_lookup` ("needs Nick's ruling"). DamIT Crest passes the file from the dam's
`railTrainsLookup` or the `DAMIT_RAIL_TRAINS_LOOKUP` environment variable.

## Outputs

In the output folder: `damit_hazard_report.md`, `.html`, `.json` (suggested class, driving
receptors and methods, advisory results, per-scenario results, flags, inputs with dates and
sizes, citations) and `damit_hazard_receptors.gpkg` (one layer per input layer; fields `rid`,
`src_fid`, `kind`, `type`, `class`, `label`, `adv_class`, `methods`, `depth_ft`, `vel_fps`,
`dv_ft2s`, `rise_ft`, `flags`, `sampling`; 0.4.0 adds `occtype`, `suggested_type`, `struct_key`, `is_911`, `reviewed_habitable`, `habitable_status`, `habitable_basis` and the `usa_*` check fields), styled by class.

### Depth-velocity chart of the habitable structures (0.3.0, rule changed in 0.4.0)

Every classify run also writes `damit_hazard_dv_habitable.png` and `damit_hazard_dv_habitable.csv` (the
plotted points) and `damit_hazard_dv_habitable_unverified.csv` (the worklist, below) in the output folder; the
Markdown report links the chart and the HTML report embeds it.
(`EXTRA_RUNS`: one set per run, `damit_hazard_dv_habitable_run<N>_<scenario>`.)

* **What is plotted:** one point per wet *habitable* structure (structures only, not facilities): its peak depth
  against its peak velocity over its wet cells (the two peaks are read independently), on the ND REG_05.2026
  Fig. 5.1 house chart, with a 0-4 ft/s, 0-3.5 ft zoom panel, and on the Fig. 5.2 mobile-home chart only when
  there is a mobile home. The ID is written beside each point in the high and judgment zones. The title gives the
  dam ID and name, the source, the run date, the counts in high, MEDIUM (the judgment zone) and low, and how many
  points are 911 address points and how many were reviewed. With no wet habitable structure the chart is still
  written, with an empty-state note.
* **Which structures (0.4.0):** only an **ND 911 address point** (blue circle), or a structure an **engineer
  reviewed habitable** in Hazard (orange diamond). A 911 point is left out only if the layer marks it
  `habitable` = false (Crest's flag can only remove a point) or gives a type that is not habitable (`farm_unoccupied`,
  `storage` ...), or the engineer reviewed it not habitable. **Every other wet structure is "unverified" (counted, not
  plotted):** a type, an occupancy, an NSI `occtype`, a USA Structures footprint and Crest's `habitable` flag never make
  a non-911 structure habitable on their own. A note on the chart gives the count of wet unverified structures, and the CSV
  `damit_hazard_dv_habitable_unverified.csv` lists each one (key, occtype, the type NSI suggests, the USA Structures
  check, zone, depth, velocity) for review. (0.3.0 charted every structure with a habitable type or no type at all;
  that rule is gone from the chart. It is still the rule M6 and the class use by default, see *Habitability*.)
* **Source in the title:** *Runner* for a model run's `Depth (Max).tif`, *Screener* for a `Screening Depth (Max).tif`,
  otherwise *Imported raster: <the depth raster's file name>* (a DSS-WISE or other raster given as `DEPTH` and
  `VELOCITY`, with `METRES` for SI rasters). `SOURCE_LABEL` sets the name (e.g. `DSS-WISE`). The chart needs the
  velocity raster; without one it is skipped with a warning.
* matplotlib (Agg backend) draws the PNG. If it is missing, the PNG is skipped with a warning and the CSV is still
  written; a chart problem never fails the classification.
* DamIT Screener writes the same chart for its screening flood into the dam folder (`damit_screener_dv_habitable.*`),
  from its point sample at each structure, with the same rule (Crest hands over `source` = nd911 for its 911 points).

### Habitability: 911 address points, NSI, USA Structures and the engineer's review (0.4.0)

* **The engineer's review.** `damit:reviewhabitable` (Processing Toolbox, *DamIT Hazard*) saves `reviewed_habitable`
  = true / false for structure keys (type them, or give the worklist CSV edited to the rows you reviewed; the key is the
  `struct_key` column), with the reviewer's name and a note. It writes `habitable_review.json` (schema
  `damit-habitable-review-v1`, with a history of changes) in the dam folder. classify finds that file beside the depth
  raster or up to two folders above it (or `HABITABLE_REVIEW` names it) and only reads it; the chart, the Screener and
  classify never create or change it. A review wins over everything, also over a 911 point. There is no review
  window yet: the worklist CSV plus this tool is the whole mechanism. Names follow DamSafety Hazard's: `reviewed_habitable`,
  and the status words yes / unverified / no (`habitable_status`, with `habitable_basis` = `911_address`,
  `reviewed_habitable`, `reviewed_not_habitable`, `911_not_habitable`, `unreviewed_not_911`). I could not find the
  parallel DWR_Plugins change to compare against, so these names come from the request, not from that code.
* **NSI `occtype`** is read and recorded (`occtype`) and only **suggests** a type (`suggested_type`, never `type`):
  RES1, RES3x = home; RES2 = mobile_home; RES4 = commercial; RES5 = institution; RES6 = nursing_home; COM1-5, 7-9 =
  commercial; COM6 = hospital; COM10 = storage (not habitable); IND* = industrial; AGR* = farm_unoccupied (not
  habitable); REL*, GOV* = institution; EDU1 = school, EDU2 = institution. Suffixes (`RES1-1SWB`) and case are
  ignored; EDU3, RES7 and anything else are unmapped (counted in the report). The suggestion tells the engineer what NSI
  thinks and which chart panel a reviewed structure will use (an NSI RES2 goes to the mobile-home panel once reviewed).
* **USA Structures check** (optional input `USA_STRUCTURES`, a polygon layer of the FEMA / ORNL building footprints, e.g.
  the `usa_structures` folder DamIT Data downloads from a pasted link; `USA_TOLERANCE_M`, default 12 m): each structure is
  `inside` a footprint, `near` one (the point is within the tolerance), or `none`. The footprint's `OCC_CLS` and `PRIM_OCC`
  are recorded and `OCC_CLS` is compared with the NSI class (RES expects residential or commercial, COM commercial or
  assembly, IND industrial, AGR agriculture, REL assembly or religion, GOV government or assembly, EDU education or assembly;
  "Unclassified" is not compared): `usa_occ_check` = agree / differs / no_class. An NSI structure with no footprint is a
  possible phantom. All of it is advisory, in the receptor layer, the worklist and the report; nothing makes a structure
  habitable but a 911 point or the review. No layer given = no check, said in the report. (Those expected classes are
  a lenient reading of the USA Structures schema, not an official crosswalk.)
* **Classification is not changed by default.** M6 and the suggested class keep the 0.3.0 rule (a type in
  `habitable_types` or a habitable occupancy; no type = presumed a home, flagged `type_unknown`). The input
  `HABITABLE_RULE` ("Only ND 911 address points and structures an engineer reviewed habitable") applies the 911 / review
  rule to M6 and the class instead. Whichever is chosen, the report has a *Habitability* section: the wet structures
  counted under both rules, how many they disagree on, and when they disagree, what M6 and the class would be under the
  other rule (flag `habitable_rule_differs`, a warning). It is the engineer's / Nick's call which rule the class of record
  follows; this version only reports the difference.

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
