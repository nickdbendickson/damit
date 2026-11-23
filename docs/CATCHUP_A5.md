# A5. Core, Data, Setup, Screener — what was not ported

Reviewed against DWR_Plugins `6816c7f` (2026-11-23). Nothing was copied. DamIT's copies of these four plugins are not line-synced with the DamSafety plugins; the shared file names are different programs that happen to share a job.

| Plugin | DamIT | DWR at the pin | Why nothing moved |
| --- | --- | --- | --- |
| Core | 0.3.3 | 1.5.3 | `unit_widgets.py`, `display_units.py` and `shared_defaults.py` share some names. The DWR-only pieces are SI CSV copies (`si_copies_of`, `write_si_csv`) and `bindings_for`. DamIT already sets the display system in its own `display_units.set_system`. Those writers are a new output, not a fix of a DamIT function. `dam_record.py` and `settings.py` are a different record and a different settings file. |
| Data | 0.2.2 | 1.11.2 | DWR Data is the ND offline pack, imagery and pack builder (`build_nd_pack.py`, `offline_pack.py`, `pack_build.py`). DamIT Data is the national download set (NSI, footprints, OSM, USA Structures, HPMS, FRA, TIGER, NBI, HIFLD). Same basename `sources.py`, different sources. |
| Setup | 0.2.0 | 1.2.0 | Only `__init__.py` and `plugin.py` share a name. DWR Setup is the ND suite installer dialog. DamIT Setup is the US-wide first-run dialog. |
| Screener | 0.3.9 | 0.31.0 | DWR Screening is the statewide pipeline (about 200 Python files DamIT does not have). `pack_terrain.py` is the closest shared feature and it is not the same feature: DWR switches the screening DEM onto the pack through a VRT in the work folder; DamIT only points larger clips at a pack DEM and leaves the main terrain choice alone. Copying the DWR function would change screening depths. Not ported. |

Not ported, on purpose: state hazard-rule text, AWA, a state 911 extract, state form numbers, and the Screening pipeline.
