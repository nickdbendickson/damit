# DamIT Core 0.3.0

Shared library of the DamIT plugins (`damit_core.lib`). As a QGIS plugin it adds one menu entry,
**Plugins > DamIT > About DamIT Core…**, which lists the DamIT plugins found and their versions.
It has no Processing provider and depends on no DamSafety plugin.

| Module | What it holds |
|---|---|
| `settings` | Suite settings (`data_folder`, `work_folder`, `catalog_dir`, `state`, `preset`, layer paths, `pfds_cache`): QgsSettings group `damit/` inside QGIS, or the JSON file named by `DAMIT_SETTINGS` (tests, portable installs), else `~/.config/damit/settings.json`. `fill_empty()` never overwrites a value. |
| `plugins` | The DamIT plugins with their Processing provider ids (`damit_data`, `damit_screen`, `damit_run`, `damit`, `damit_lite`, `damit_pmp`), metadata reading, a suite / dependency check (missing DamIT dependencies, non-DamIT dependencies), the hand-off target ids, and `is_foreign_algorithm()` that refuses `nddam:*` / `ndbreach:*`. |
| `states` | 50 states, DC and Puerto Rico: postal code, name, FIPS, county FIPS, WGS84 bounding box, Geofabrik path and Microsoft footprint name (`data/states.json`, from the Census 2023 cartographic boundary files). |
| `dam_record` | DamIT Screener dam field names, a field-name alias table (NID export and generic spellings) and `suggest_field_map()` / `field_map_string()` for `damit_screen:*` `FIELD_MAP`. |
| `catalog_access` | Loads DamIT Catalog (installed plugin, or the sibling folder in a checkout), lists presets, proposes the preset whose ID is a state's postal code (none otherwise: DamIT never assumes a jurisdiction), resolves preset / custom configs. |
| `http` | `get_bytes` (QGIS network settings inside QGIS, urllib outside), `head`, streamed `download_file` with a size limit and cancel. |
| `shared_defaults` | The shared defaults file (`data/defaults.json`, format `dam-defaults`, the same as DamSafety Core 1.2.0 and Crest): sunny-day starting pool, PMF Vw rule, failure mode, breach equation, Manning's n. Your values in `~/DamIT/defaults.json` (setting `defaults_file`, env `DAMIT_DEFAULTS`) hold only the keys you changed. `load()`, `value()`, `save_user()`, `assumptions()` for dam.json. DamIT Runner 0.4.0 reads it. |
| `qtcompat` | `QAction`, `exec_dialog`, field types for QGIS 3.28 – 4.x. |

No jurisdiction threshold lives here; those are DamIT Catalog data.

DamIT Hazard, Screener, Runner and Crest do not import DamIT Core in 0.1.0 (their PRs are open);
they can switch to `damit_core.lib.settings` / `plugins` later.

Tests: `damit_core/tests/test_core.py` (pure Python) and `tests/test_qgis_new_plugins.py` (About).
