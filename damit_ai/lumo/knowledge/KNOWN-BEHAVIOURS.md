# Known behaviours, conventions and cross-plugin contracts

Triage knowledge for the ND / DamSafety dam suite that is **not** derivable from the
source code or the per-plugin `metadata.txt` changelogs. Feed this to Lumo so it can
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
