# Known behaviours, conventions and cross-plugin contracts

Triage knowledge for the ND / DamSafety dam suite that is **not** derivable from the
source code or the per-plugin `metadata.txt` changelogs. Feed this to Heim so it can
answer "is this expected?" and "has this been decided before?" without re-deriving it.

Scope: the ND set (`nd_hazard` / profile `nd`, archived at its final versions) and the
active DamSafety fork (`DWR_Plugins` / profile `damsafety`), plus the Crest screening app.
Shared code is vendored into both plugin repos under `damsuite/` (DamSafety Core plugin
owns the one real copy; each plugin's `damsuite/` is a shim).

---

## Conventions (standing decisions)

- **Pool convention.** A sunny-day (fair-weather) breach uses the DWR **maximum** pool /
  maximum storage unless stated otherwise. A PMF / flood-inflow breach uses the storage at
  the **starting pool** per ND Dam Safety Standards. `Vw` in every breach equation
  (Froehlich 2008/1995, MLM, Von Thun & Gillette, TR-60) follows this, and the HEC-RAS
  plan's Froehlich piping takes the run's `Vw`. Enforced from Runner 3.16.4 (DWR) /
  3.29.4 (ND); report records `vw_source`.
- **One QGIS profile per set.** ND and DWR plugins collide on Processing provider ids, so
  each set runs in its own QGIS profile (`nd` vs `damsafety`). Never enable both in one
  profile.
- **Solver choice (Runner).** `SOLVER` = ACC (default) / FV2 / MWDG2; FV1 and plain DG2 are
  refused for a main run. Set with `--breach-param SOLVER=` or `NDBREACH_LISFLOOD_SOLVER`.
  FV2 / MWDG2 (with `limitslopes`) are **CUDA-only** in LISFLOOD-FP: a CPU-only binary
  silently runs IterateQ adaptive instead, so on a machine without a CUDA build only ACC
  is a real choice (see modeling findings).
- **DamSafety Core first.** Every DamSafety plugin depends on the DamSafety Core plugin; the
  installer installs and enables it. `metadata.txt plugin_dependencies` names it.
- **No default HEC-RAS compute timeout.** Decided in Runner 3.10.48 and kept by audit M18;
  `NDBREACH_HECRAS_TIMEOUT_S` is opt-in. Cancel is the way to stop a long run.
- **`_ORPHANS` is never freed (Hazard).** Parked worker-thread layers are kept on purpose:
  freeing one touches the ended thread's PROJ state (the QGIS 3.34 bug the H5 adopt fix
  works around), a crash risk worse than the memory. From Hazard 2.24.5 a warning is
  logged every 500 (`ORPHANS_LOG_EVERY`). For long batches use **WORKERS > 1** (each dam
  in its own `qgis_process` child, so its layers die with it).
- **Audit M03 declined on purpose.** Nested `parallel_map` in `_arcgis_features_tiled`
  can exceed the six HTTP slots, but don't remove page parallelism: for a single or warm
  cache tile it is the only parallelism left. With M18/M04/M02/M16 merged (2026-11-10)
  the DWR medium/low audit backlog is cleared.
- **Version discipline.** A shipped change bumps the plugin's `metadata.txt` `version=` and
  changelog (`%%` for a literal percent), `DamSafety_Core/damsuite/versions.py`
  `RELEASE[...]`, regenerates the manifest (`tools/damsuite_files.py`), and must pass
  `tools/ci_checks.py`. `RELEASE` is one line, so two PRs bumping different plugins need
  a trivial rebase. Two open PRs claiming the same version: whichever merges second bumps
  (2026-11-10: #321 kept Runner 3.17.7; M18 landed as 3.17.8, M16 as 3.17.9).

## Run-watcher rules (pinned; Heim has got these backwards before)

These are Nick's standing rules, pinned in the watcher's system prompt (`heim_watch.py`) and checked by the
digest (`run_digest.py`). A local model once reversed the first one. The sunny-day, Vw and real-tool-name rules are
also pinned in the Q&A persona's SYSTEM prompt (`prompts/persona_rules.txt`, copied into every installer), because
`heim-chat` asks the model directly and never reads this pack; `eval_heim.py --no-context` scores that path.

- **Sunny day = no inflow, outlets empty, no outlet or spillway flow.** The reservoir starts at the **top of dam,
  which is the DWR max pool**. The only water is the breach. (Never "inflow equal to the reservoir's capacity" or
  "outlets operational".) The Runner records `PMF_FT` but does not start there.
- **DWR elevations are NAVD88 only** (NGVD29 + VERTCON 0.9088 ft in ND). A dam elevation of 0-300 ft is a local
  datum, not NAVD88 (ND is roughly 800-3,500 ft).
- **Toe rule.** The breach inflow goes in at the lowest ground in the downstream toe band: 5 m out to
  H x (downstream slope + 1), 3:1 when the slope is not known, never more than 150 m from the dam line. H is the
  inventory height (37 ft x 0.3048 x 3.5 = 39.5 m for a 2.5:1 slope).
- **Height.** Crest minus streambed should equal the inventory height. When they differ (DWR-2658: 39.0 vs 37 ft)
  the Runner can raise the breach bottom to the reservoir bottom; flag it, do not average it away.
- **Early passes may let water out of the model domain edge.** The Runner grows the domain while water leaves the
  border of the computation grid (the *model domain edge*; it is not the breach and not dam leakage), so edge outflow in
  pass 1-2 followed by a clean final pass is normal (WATCH); a leaking final pass is not.
- **BNSF KO subdivision = 15 trains per day** (the DamSafety value) for the M9a / M9b rail checks, passed as
  `RAIL_TRAINS_LOOKUP` (`field,value,trains_per_day,source` = `SUBDIV,KO,15,...`). Other lines without a value
  stay flagged.
- **Judgment zone = Medium in ND** (the TM-11 judgment zone counts as Medium in the ND preset).
- **Receptors on NoData (Hazard 0.2.6).** When the cell under a structure (or every cell of its footprint) is NoData
  and a neighbour is wet, the rule depends on the depth-grid cell (larger side, in metres): coarser than 20 m
  (`NODATA_NEIGHBOURHOOD_MIN_CELL_M`), Hazard takes the peak depth and velocity over the wet cells of the 3x3
  neighbourhood (`sampling=neighbourhood`, flag `nodata_neighbourhood`); at 20 m or finer it still scores the cell dry
  (0 ft, `sampling=centre_nodata_dry`) and flags `nodata_dry_review`. Either way it goes to a person (`HAZARD_REVIEW`).
  A dry (finite 0) cell stays dry; a NoData cell with no wet neighbour stays dry and is not flagged. A structure on a
  dry cell beside deep water can still be missed by a coarse grid: flag it for a person. DamIT Hazard does not score
  roads with unknown class or AADT (M8a); the older DamSafety plugin scored them Medium by assumption.
- **Peak depth and peak velocity are maxima over wet cells** (depth of 0.1 ft or more).
- **Real tool names only:** `damit_screen:handoff`, `damit_run:rundam`, `damit:classify` (and `damit_lite:classify`).
  The automatic 10 m refine is switched off with `--GRID_REFINE=0`. There is no `damit_runner`, no `--no-refine` and
  no `damit_screener_handoff`. See `ALGORITHM-HELP-DAMIT.md` (generated from the code) for every id and parameter.

## Known behaviours / bugs (durable)

- **FV1 near-dam instability.** The near-dam refine pass with FV1 can blow up (a FREE edge
  sitting in the reservoir basin imports water and grows exponentially; ACC is stable).
  Run with `REFINE_NEAR=false` until fixed. FV1 and plain DG2 also write no max-velocity
  field in the bundled LISFLOOD-FP 8.1 binary.
- **Velocity is solver-sensitive; depth is not.** Max velocity depends on the solver (ACC
  throws a ~27 ft/s wet-dry-front spike). The earlier "FV2-LL / MWDG2-LL damp below
  reference" finding is **suspect**: those runs' labels were invalidated (see modeling
  findings). Treat velocity as indicative. Depth extents agree across ACC and FV1; DG2-LL
  ran ~30% wider at 20 m.
- **Grid artifact at Absaraka (DWR-2801).** Flood area shrinks as the grid refines (a grid
  artifact, not physics); use >= 10 m on flat plains. Over-spread vs DSS-WISE is terrain /
  crest-resolution, not the solver. CSI ~0.34-0.37 is model-grade (three 2-D models agree
  only ~0.3-0.5 at 0.1 ft).
- **ACC mass-balance auto-rerun.** Volume error > 1% triggers an automatic damped rerun
  (theta 0.7, CFL 0.5). Shipped and verified (in release 1.28).
- **Don't cap max-extent runs short.** On flat terrain the flood is often still spreading at
  12-24 h; a run stopped at a cap with >= 5% of the breach volume still leaving the domain
  is flagged `extent_is_minimum`.
- **Screening peak = normal-pool area (ND bug).** ND Screening peak reads the normal-pool
  area; a depth-only edge rule applies in both Runners; the ND UTM warp can hide wet edges.
- **LISFLOOD OpenMP scales poorly.** Thread scaling is weak; run dams side by side at 1
  thread each rather than many threads on one dam. ND bundles a LISFLOOD-FP binary; DWR
  ships none by default (set the path or use the built-in Python engine).
- **Storage leak (Screening fill past spillway)** fixed in Screening 0.19.0. DWR crests sit
  on the local datum, not NAVD88.
- **`run.dem.asc` doesn't line up in QGIS** (local 0,0 origin, no projection). From Runner
  3.17.7 each run copies a georeferenced `Model Terrain (LISFLOOD).tif` (and
  `ANUGA Mesh.gpkg` when gmsh ran) next to the results; review files only, nothing reads
  them back. `NDBREACH_EXPORT_TERRAIN=0` turns it off.
- **HEC-RAS Cancel (Runner 3.17.8+, audit M18).** Cancel is threaded through
  `run_hecras_stage(..., cancel=)` into preprocess (every Wine step and `Ras.exe -c`) and
  compute; `wallclock.wait` polls every 0.25 s, then `stop_group` (SIGTERM to the process
  group, grace `NDBREACH_HECRAS_KILL_GRACE_S`, SIGKILL) and raises `lisflood.Cancelled`.
  Single-dam tool: `QgsProcessingException("Cancelled")`; batch row: `cancelled`; CLI:
  first Ctrl-C. Measured on native Linux RasUnsteady 7.0.1: stops in well under 1 s, no
  orphan. **Not yet verified:** cancel during the Wine preprocess TCU-dialog wait, and an
  interactive QGIS dialog Cancel on a full HEC-RAS run. The Windows launcher
  (`hecras_windows.py`) was not changed.
- **Hazard provider bulk read (2.24.4+, audit M04).** For rasters GDAL can't open (WCS,
  ArcGIS MapServer, the Population tab's virtual raster), the block is read in one go only
  for whitelisted numeric types (Byte, Int8, UInt16, Int16, UInt32, Int32, Float32,
  Float64); image/ARGB, complex, no-data-bitmap, short-buffer or error cases fall back to
  the per-cell loop, bit-identical. A **NaN or infinite no-data value also takes the
  loop**, because QGIS 4.x and 3.34 disagree on whether a value equal to an infinite
  no-data is no-data. Not yet checked on a live WCS / MapServer Population layer.
- **Runner window scan (3.17.9+, audit M16).** `Model.window` scans only the previous
  window, falling back to the full grid on the first call, when the wet box touches a
  non-edge side, and every 50th call (`WINDOW_SELF_CHECK`); a mismatch returns the
  full-grid answer and logs `window_mismatch`. Golden baseline unchanged.

## Terrain swaps: a wrong result with no error

Pointing a run at a different DEM (a local statewide VRT in place of downloaded 3DEP
tiles, a 1 m file in place of a 5 m one) changes more than the file path. None of these
raises an error; each gives a plausible-looking result. `tools/mac/use_local_terrain.sh`
(DamSafety repo) handles the last two and warns about the first three.

- **The model grid takes the DEM's CRS.** Both Runners do
  `if dem_crs.isValid() and not dem_crs.isGeographic() and dem_unit == 1.0: work = dem_crs`.
  `WORK_CRS` is read **only** when the DEM is not projected in metres, so any metre DEM
  overrides it, including the EPSG:5070 the review runs set. Deliberate: reprojecting results
  back from a UTM model grid left nodata triangles on every raster edge, and the Hazard
  extent check then saw no wet edge cells. The run log prints `Model CRS <authid>` every
  run; it never says that `WORK_CRS` was overridden. A DEM swap can therefore move a run's
  output CRS without anyone asking. To see what a DEM will impose: `gdalsrsinfo -o epsg <dem>`.
- **A VRT reads a missing source as nodata.** A VRT whose source file is absent still opens,
  and the missing tile comes back as nodata, which the Runner treats as high ground. The
  flood stops at a straight tile edge and nothing is logged. Check every `SourceFilename`
  of a VRT resolves before a long run (`gdalinfo` lists them; a relative path is relative to
  the VRT when `relativeToVRT="1"`).
- **A composite DEM is not the same terrain as its finest layer.** The DWR-2801 review DEM is
  a composite: native 1 m over the dam with a 5 m DEM underneath outside the 1 m tiles. A
  pure 1 m statewide VRT has no underlay, so the area the composite filled at 5 m is nodata.
  `use_local_terrain.sh absaraka-kit` keeps the composite and only redirects its 1 m tile
  paths; it refuses a tile whose size or cell does not match what the composite says.
- **Most review dams are 5 m, not 1 m.** The default review DEM is 3DEP 1 m **averaged to
  5 m** (874 `*_avg5m.tif` rows against 36 native 1 m, all 36 for DWR-2801). Moving those
  dams to true 1 m changes source resolution, run time and results for every one of them.
- **`record` uses the DEM but is not re-run when the DEM changes** (`nickreview_mac.py`).
  The stage table says `READS["record"] = ()`, yet the stage passes the DEM into the
  Screening 7b record. Re-running `rundam` on new terrain with an old `record.ok` models the
  new DEM against a `dam.json` derived from the old one. Use `--redo` (it covers `record`)
  or a fresh `--out`.
- **Get data keeps a DEM it already recorded.** `damdata.exists(role)` is true for a role
  already in `dam.json` unless `OVERWRITE` is set, so a dam folder from an earlier run keeps
  its old `data/dem.vrt` and models the old terrain for hours while the log prints
  `get data: ok`. `--redo` does **not** fix this (it re-runs the chain, not Get data). Pass
  `--getdata-param OVERWRITE=true`.

## Cross-plugin hand-off contracts (`damsuite/versions.py`)

`REQUIRES[(A, B)] = (hard_min, soft_min, reason)` — what plugin A needs of plugin B when
both are installed. A plugin that is not installed is never an error (each works alone; the
hand-offs are optional). Keys are the package short names (`ndhazard`, `ndbreach`,
`ndscreen`), not the Processing provider ids. Highlights:

- Runner needs Hazard >= 2.9.1 (hard) / 2.18.63 (soft: the chain's Hazard import adopts the
  Runner's terrain-basis rasters).
- Hazard needs Runner >= 3.1.1 (hard) / 3.7.0 (soft: a proposed embankment in `dam.json` is
  inserted on the grid).
- Screening needs Runner >= 3.1.0 (hard) / 3.7.0 (soft).

## Crest hand-off

- Crest desktop hands a dam to the installed plugins through `qgis_process`:
  `nddam:preflight`, then `nddam:runchain` only if preflight is READY, or `ndbreach:rundam`
  for one flood; or `scripts/ndbreach_cli.py run` when Point X/Y are given in the DEM's
  CRS. It never starts `ndbreach:batch`.
- Crest addresses plugins by provider id (Screening `nddam`, Runner `ndbreach`, Hazard
  `ndhazard`), which both sets share, so the set it hits is whichever profile is active.
  The intended target is the DamSafety set.
- New Crest records default to **piping**, not overtopping (decided 2026-11-05); an empty
  or unknown `failureMode` is also treated as piping.
- QGIS 3.34 `qgis_process` rejects METHOD/TIER **option text**; Crest reads the option list
  from `qgis_process help ndbreach:rundam` and sends the index.

## Processing-provider gotchas

- `qgis_process list` omits `FlagHideFromToolbox` algorithms (the DWR selftests,
  `nddam:runchain`), so a tool missing from `list` is not missing — check it with
  `qgis_process help <id>`.
- The Runner resolves ANUGA by: `ANUGA_PYTHON` parameter > saved Processing setting
  (`NDBREACH_ANUGA_PYTHON`) > autodetect. Autodetect matches `*anuga*` envs alphabetically,
  so an old `anuga` env without gmsh beats `ndanuga`; pass the parameter or set the
  Processing option to pin it. Exporting the env var alone does not override the saved
  setting.
- `NDSUITE_DATA` (env) overrides the plugin's data-folder QSetting; `suitedata._get` checks
  env, then QSettings, then `~/.ndsuite/config.json`.
- After `VAR=` in zsh, use `$HOME`, not `~` (zsh does not expand `~` there).

---

_This file is curated operational knowledge, kept free of machine names, credentials and
file-server links. Update it when a decision or a durable behaviour changes._
