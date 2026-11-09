# DamIT Setup 0.1.0

Start here for the DamIT plugins: **Plugins > DamIT > Start here… (DamIT Setup)**.
Depends on DamIT Core and DamIT Catalog; no DamSafety plugin and no North Dakota pack is needed.

1. **Suite data folder** – any folder of layers. The scan (read-only, 4 levels, 20,000 files at most)
   recognizes by file / folder name: dams (`dams`, `nid`, `inventory` …, required), terrain (`dem`,
   `dtm`, `terrain`, `lidar`, `3dep` rasters), structures (`nsi`, `building`, `footprint`, `microsoft`,
   `overture`, `usa_structures`), roads and railroads, including the folders DamIT Data writes
   (`<STATE>/nsi`, `microsoft_footprints`, `osm`, `usa_structures`).
2. **Work folder** – where DamIT Screener / Runner runs go; refused inside the data folder.
3. **State** and **Preset** – choosing a state proposes the DamIT Catalog preset with that ID (ND, NE, NY,
   VA, TX, ID, CO, RI, AZ, CA, AK, AL, NC); other states pick an agency preset (FEMA333, USBR / USBR_TM11,
   BIA, NRCS, USACE, TVA) or custom mode.
4. The suite check lists the DamIT plugins found; DamIT Core or DamIT Catalog missing, a missing DamIT
   dependency or a non-DamIT dependency turns **Continue** off with the reason shown.
5. **Save** stores the folders and fills only empty settings (layer paths, state, preset).
6. **Continue in DamIT Screener…** writes `<work>/damit_screen_settings.json` (DamIT Screener SETTINGS
   format: mode, preset, terrain, field_map, catalog_dir) and opens `damit_screen:preflight` with WORK,
   DAMS, TERRAIN, RECEPTORS, MODE, PRESET, FIELD_MAP (proposed from the dam layer's fields, e.g.
   `dam_id=NIDID`) and SETTINGS filled in.

Hand-off targets are `damit_screen:preflight`, `damit_screen:runchain` and `damit_run:rundam` only;
`nddam:*` / `ndbreach:*` ids are refused with no fallback. Setup launches no model.

Tests: `damit_setup/tests/test_setup.py` (scan, problems, settings fill, Screener settings round trip,
target refusal) and `tests/test_qgis_new_plugins.py` (the window offscreen, handing off to a real
`damit_screen:preflight` run).
