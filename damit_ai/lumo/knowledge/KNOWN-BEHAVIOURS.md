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
- **DamSafety Core first.** Every DamSafety plugin depends on the DamSafety Core plugin; the
  installer installs and enables it. `metadata.txt plugin_dependencies` names it.

## Known behaviours / bugs (durable)

- **FV1 near-dam instability.** The near-dam refine pass with FV1 can blow up (a FREE edge
  sitting in the reservoir basin imports water and grows exponentially; ACC is stable).
  Run with `REFINE_NEAR=false` until fixed. FV1 and plain DG2 also write no max-velocity
  field in the bundled LISFLOOD-FP 8.1 binary.
- **Velocity is solver-sensitive; depth is not.** Max velocity depends on the solver (ACC
  throws a ~27 ft/s wet-dry-front spike; FV2-LL / MWDG2-LL damp below reference). Treat
  velocity as indicative; study it before using FV2/MWDG2 for a hazard call. Depth extents
  agree across solvers.
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
