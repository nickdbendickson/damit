# runner_shared: verbatim copies of damit_runner's ANUGA / gmsh / LISFLOOD-FP / 3DEP code

DamIT plugins are installed independently, so damit_pmp cannot import damit_runner. The repo's
pattern for shared code is a verbatim per-plugin copy (`catalog_bridge.py`, `_deps.py`, `compat/`).
These files are byte-for-byte copies of `damit_runner/core/<name>.py` (`terrain3dep.py`: `damit_runner/flood/terrain3dep.py`); the runner is the source of
truth. Do not edit them here: edit the runner, then run `python3 scripts/sync_pmp_runner_shared.py`.
`damit_pmp/tests/test_runner_shared_sync.py` (CI) fails when a copy differs from the runner's file.

| file | what damit_pmp uses it for |
|---|---|
| `gmsh_mesher.py` | the ANUGA gmsh mesher (spec JSON in, npz out); sizing defaults, spec checks, line clipping; run in the ANUGA Python (gmsh is never imported in QGIS) |
| `grid.py`, `terrain.py` | the model-DEM `Grid`, `mask_outline` / `largest_component` / `dilate` (the mesh outer ring) and `trace_downstream` (the flow path refinement line) |
| `anuga_worker.py`, `omp_probe.py`, `anuga_dtdiag.py` | copied next to the generated ANUGA script, which imports the worker's helpers (`bilinear`, `sample_fine`, `fill_nan`, `make_outer_boundary`, `apply_threads`) so the domain is built with the runner's own functions; only run in the ANUGA Python |
| `lisflood.py`, `units.py`, `data_conventions.py` | (0.4.0, `damit_pmp:lisfloodrain`) the runner's LISFLOOD-FP setup: `LisfloodSettings`, solver names and choice (ACC default, FV2 / MWDG2 by name, FV1 / DG2 refused), `local_grid`, the gauge-section clipping, the `.mass` reader and `write_inputs` (the tests pin every shared `.par` line to it); `data_conventions.detect_lisflood` is the executable search; `units.py` is its constants. Their process-starting code (`lisflood.run`) is never called here: `damit_pmp/launch.py` starts the executable |
| `terrain3dep.py` | (0.4.0, `damit_pmp:watershed`) the USGS 3DEP ImageServer tile download; copied from `damit_runner/flood/terrain3dep.py` (the only file here not from `core/`) |
| `wallclock.py` | the runner's launcher (wall-clock timeout, SIGTERM then SIGKILL), used by `damit_pmp/launch.py` |

Only `damit_pmp/launch.py` starts a process, and only for the optional gmsh mesh build, the
optional ANUGA run (both need an explicit ANUGA Python path) and the optional LISFLOOD-FP run
(`RUN_LISFLOOD`, off by default). The tests in
`tests/test_metadata_suite.py` ban process launching everywhere else in damit_pmp, and skip this
folder only because it holds the runner's own files (their sha is pinned by the sync test).
