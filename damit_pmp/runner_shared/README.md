# runner_shared: verbatim copies of damit_runner's ANUGA / gmsh code

DamIT plugins are installed independently, so damit_pmp cannot import damit_runner. The repo's
pattern for shared code is a verbatim per-plugin copy (`catalog_bridge.py`, `_deps.py`, `compat/`).
These files are byte-for-byte copies of `damit_runner/core/<name>.py`; the runner is the source of
truth. Do not edit them here: edit the runner, then run `python3 scripts/sync_pmp_runner_shared.py`.
`damit_pmp/tests/test_runner_shared_sync.py` (CI) fails when a copy differs from the runner's file.

| file | what damit_pmp uses it for |
|---|---|
| `gmsh_mesher.py` | the ANUGA gmsh mesher (spec JSON in, npz out); sizing defaults, spec checks, line clipping; run in the ANUGA Python (gmsh is never imported in QGIS) |
| `grid.py`, `terrain.py` | the model-DEM `Grid`, `mask_outline` / `largest_component` / `dilate` (the mesh outer ring) and `trace_downstream` (the flow path refinement line) |
| `anuga_worker.py`, `omp_probe.py`, `anuga_dtdiag.py` | copied next to the generated ANUGA script, which imports the worker's helpers (`bilinear`, `sample_fine`, `fill_nan`, `make_outer_boundary`, `apply_threads`) so the domain is built with the runner's own functions; only run in the ANUGA Python |
| `wallclock.py` | the runner's launcher (wall-clock timeout, SIGTERM then SIGKILL), used by `damit_pmp/launch.py` |

Only `damit_pmp/launch.py` starts a process, and only for the optional gmsh mesh build and the
optional ANUGA run (both need an explicit ANUGA Python path). The tests in
`tests/test_metadata_suite.py` ban process launching everywhere else in damit_pmp, and skip this
folder only because it holds the runner's own files (their sha is pinned by the sync test).
