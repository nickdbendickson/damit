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

**Preset** – pick one of the DamIT Catalog presets (15 in the Nov 9, 2026 edition): FEMA 333
baseline, USBR (ACER TM-11), BIA (secondary), NRCS (unverified), North Dakota, Nebraska, New
York (draft), Virginia, Texas, Idaho, Colorado, Rhode Island, Arizona, California, Alaska. Class
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
  descriptor guesses, and per-preset notes and switches (e.g. USBR: M1 marks lives for M5 and
  returns no class itself; New York: R2 floor presumption, R8 lowering-from-High). A test
  checks that it repeats no parameter the other files carry.
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
JSON: a dam record (`storage_acft`, `current_class`, `is_new`, ...), more runs (one per
scenario), extra TM-11 charts.

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
* Draft, secondary or unverified items follow DamIT Catalog's verification fields: the BIA
  (secondary), NRCS (unverified) and New York (draft) presets are marked beside their names.

## Tests

    python3 damit_hazard/tests/run_tests.py            # engine, DamIT Catalog bridge, TM-11 (no QGIS)
    QT_QPA_PLATFORM=offscreen <QGIS python> damit_hazard/tests/run_tests.py
                                                        # + sampling (GDAL) and damit:classify

Set `DWR_PLUGINS_ROOT` to a DWR_Plugins checkout to also check the TM-11 curves and the
sampling code against DamSafety_Core / DamSafety_Hazard. The runner works with or without
pytest.
