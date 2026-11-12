# DamIT PMP 0.3.0 – NOAA Atlas 14 only

Processing provider `damit_pmp`. Depends on DamIT Core. **The only data source is NOAA Atlas 14**,
read from the NOAA/NWS Precipitation Frequency Data Server (PFDS, https://hdsc.nws.noaa.gov/pfds/), or
from an Atlas 14 GIS grid you downloaded from PFDS.

This is not a port of DamSafety PMP (the internal prototype of the North Dakota statewide PMP
Evaluation Tool). It ships none of that tool's code or data, uses no PMP study geodatabase, no HMR / HMS
or state PMP product and no other precipitation source. Atlas 14 publishes precipitation-frequency
estimates up to the 1000-year ARI; **this plugin computes no probable maximum precipitation**.

| Tool | What it does |
|---|---|
| `damit_pmp:pointpf` | PFDS point query: 19 durations (5 min – 60 days) × PDS 1 – 1000-year ARI (or AMS 1/2 – 1/1000 AEP), depth or intensity, English or metric, with 90% bounds. Writes a CSV table and a JSON file with the Atlas 14 volume, version, region, query URL, fetch time and citation. |
| `damit_pmp:basinpf` | The same at a point on the basin plus evenly spread points inside it (MAX_POINTS, default 9), combined cell by cell (mean or max); a sample-point layer. No areal reduction (Atlas 14 values are point values). |
| `damit_pmp:hyetograph` | Alternating-block design hyetograph from a pointpf / basinpf JSON: storm total = the Atlas 14 depth for the storm duration (1 h – 10 days) at the chosen frequency; sub-durations log-log interpolated between published durations. Not an Atlas 14 temporal distribution. |
| `damit_pmp:gridbasin` | Basin mean / min / max of an Atlas 14 GIS grid: a file you have (NOAA's, thousandths of an inch, SCALE 0.001; frequency and duration read from the standard file name, e.g. `mw100yr24ha.asc`, also the 2-day `48h` and `al` / `au` bound names) or a `fetchgrid` GeoTIFF (already inches, read with scale 1), **or** leave GRID empty and give the same frequency / duration / series / bound / region choices as `fetchgrid`: it fetches the NOAA grid itself. |
| `damit_pmp:fetchgrid` | **New in 0.3.0.** Downloads the Atlas 14 "PF in GIS format" grid for one frequency and duration, clips it to a point buffer, an extent or a basin (optionally blanking cells outside the polygons) and writes a Float32 GeoTIFF in **inches** (NOAA's thousandths x 0.001; NAD83 geographic, nodata -9999) plus `<tif>.json` (source URL, fetch time, SHA-256, Atlas 14 volume / version, citation, stats, value at the point). |
| `damit_pmp:raingrid` | **New in 0.3.0.** Rain-on-grid files from a hyetograph CSV (or a pointpf / basinpf JSON + FREQUENCY + STORM + STEP_MIN): a LISFLOOD-FP `.rain` file (mm/hr), an ANUGA rate series CSV (m/s) with a README, and a JSON record (units, totals, mass check). Optionally rescaled to an Atlas 14 grid at a point or as a basin mean, with a spatial factor raster. Launches nothing. |
| `damit_pmp:anugarain` | **New in 0.3.0.** An ANUGA rain-on-grid job on the damit_runner gmsh mesh: DEM + basin polygon / extent + the `raingrid` rate CSV (+ factor raster) -> the runner's gmsh mesh, a self-contained `run_anuga_rain.py`, a run manifest. Builds the mesh only when an ANUGA Python is given; runs ANUGA only with `RUN_ANUGA` (off by default). |

A location outside Atlas 14 coverage (for example Portland, Oregon, checked 2026-11-09) fails with
"NOAA Atlas 14 does not cover this location (PFDS: …)". PFDS answers are cached (CACHE_DIR, else the
DamIT `pfds_cache` setting, else next to the outputs); OFFLINE uses the cache only; basin queries wait
one second between live requests.

Citation form written to every output: *<authors>, NOAA Atlas 14 Volume <v> Version <x>,
Precipitation-Frequency Atlas of the United States, <region>. NOAA, National Weather Service, Silver
Spring, MD.*


## Choosing the frequency and duration (0.3.0)

Every tool takes the same choices:

* **Frequency** (`FREQUENCY`, whole years): PDS average recurrence interval 1, 2, 5, 10, 25, 50, 100, 200, 500 or
  1000; AMS annual exceedance probability 1/2 ... 1/1000 (enter 2 ... 1000; there is no 1-year AMS file).
  Any other value stops with a message listing the allowed ones.
* **Duration**: all 19 Atlas 14 durations, 5 min, 10, 15, 30, 60 min, 2, 3, 6, 12, 24 h, 2, 3, 4, 7, 10, 20, 30, 45,
  60 days (`DURATION` in `fetchgrid` / `gridbasin`); the hyetograph and `raingrid` storms (`STORM`) offer the 11
  from 60 min to 10 days.
* **Series** (`pds` / `ams`) and, for the grids, the **estimate or its 90% lower / upper bound** (`BOUND`).

## Atlas 14 GIS grids from NOAA (`fetchgrid`)

Source: the PFDS "PF in GIS format" page, <https://hdsc.nws.noaa.gov/pfds/pfds_gis.html>. Its form builds this URL
(checked against the live server on 2026-11-12):

    https://hdsc.nws.noaa.gov/pub/hdsc/data/{reg}/{reg}{ARI}yr{dur}{type}{series}.zip

| Part | Values |
|---|---|
| `reg` | volume folder: `mw` (Midwestern States, includes North Dakota), `orb`, `se`, `ne`, `tx`, `inw`, `ak`, `hi`, `pr`, `sw` (Southwest), legacy `sa`, and the Pacific island folders |
| `ARI` | `1 2 5 10 25 50 100 200 500 1000` (PDS); `2 5 10 25 50 100 200 500 1000` (AMS, = 1/AEP) |
| `dur` | `05m 10m 15m 30m 60m 02h 03h 06h 12h 24h 48h 03d 04d 07d 10d 20d 30d 45d 60d` (2-day is `48h`) |
| `type` | `a` estimate, `al` lower 90% bound, `au` upper 90% bound |
| `series` | empty = PDS, `_ams` = annual-maximum series |

For example <https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw100yr24ha.zip> (3.7 MB) is the 100-year, 24-hour estimate
for Volume 8. The zip holds an ESRI ASCII grid, a `.prj` and an `.xml`; the grid is NAD83 geographic, 30 arc-second
cells, integer thousandths of an inch, nodata -9. Only the zip is cached (`CACHE_DIR/atlas14_gis/<reg>/`); the grid
is read in place (`/vsizip/`) and clipped straight to the GeoTIFF, so a clip to a basin never unpacks the 25 MB grid.

* **Region**: Auto asks PFDS for the point (or the extent centre / a point on the basin) and uses its volume folder,
  or choose it. PFDS answers `sw` for both Volume 1 (Semiarid Southwest, version 5) and Volume 6 (California); the
  `sw` grids cover both (Phoenix AZ: grid 3.406 in, PFDS Volume 1 point 3.41 in). The `sa` folder is the older
  version 4 grid and is never picked automatically.
* **Clip**: basin polygons, else an extent, else the point with `BUFFER_KM` (default 5 km); with none of them the
  whole regional grid is written (about 3 000 x 2 000 cells). A clip that misses the grid, or lies on empty cells,
  fails with a message.
* **Errors**: no PFDS coverage (e.g. Portland, OR) -> "does not cover this location"; a file NOAA does not publish
  (HTTP 404, e.g. an AMS grid for `sa`) -> "NOAA has not published ..."; network failure -> "download failed";
  `OFFLINE` with nothing cached -> "offline: ...".
* Grids are point estimates; the values at a point agree with the PFDS point query to the cell size (DWR-2801,
  mw100yr24ha: grid 6.342 in, PFDS 6.34 in; 90% bounds 4.679 / 8.565 vs 4.68 / 8.56).

## Rain-on-grid export (`raingrid`)

Units are explicit in every file.

* **LISFLOOD-FP `.rain`** (spatially uniform; keyword `rainfall` in the `.par` file; layout per the LISFLOOD-FP
  manual, section "Rainfall data file (.rain)"): line 1 a comment (ignored), line 2 `<n points> seconds` (or `hours` /
  `days`, `TIME_UNIT`), then `rate time` rows with the **rate in mm/hr**. LISFLOOD-FP interpolates linearly between
  the points, so each hyetograph block is two points (its start and `RAMP_S` seconds before its end, default 1 s) and
  the file ends with 0 mm/hr at the end of the storm (or at `SIM_TIME_H`, so the file covers the whole run). The
  JSON record gives the depth of the written series against the storm total (about 1e-3 %).
* **ANUGA**: `<name>.csv` with `time_s, rate_m_per_s` (m of water depth per second = mm/hr / 3.6e6) and the same
  points, plus `<name>_README.txt` with a snippet; `anuga.Rate_operator(domain, rate=f)` takes the rate in m/s and
  `f` may be a function of `t`:

      t, r = np.loadtxt("rain_anuga.csv", delimiter=",", skiprows=1, unpack=True)
      rain_op = anuga.Rate_operator(domain, rate=lambda t_now: float(np.interp(t_now, t, r, left=0.0, right=0.0)))

* **Rescale to an Atlas 14 grid** (`SCALE_GRID` with `SCALE_POINT` or `SCALE_BASIN`): the storm total becomes the
  grid value at the point or the grid's mean over the basin (the grid must be for the same duration, and for the same
  frequency when the CSV records it); the factor is written to the JSON. `FACTOR_RASTER` writes grid / reference depth
  for spatially varying use.
* **Not done**: the LISFLOOD-FP dynamic-rain NetCDF (`dynamicrainfile`, "TUFLOW NetCDF rainfall format": rainfall in mm
  per tile per interval, same origin as the DEM) is not written, because the variable layout could not be verified
  without the solver, which this plugin never runs. Use `FACTOR_RASTER` and the uniform series as the inputs for it.
  The block order is the alternating-block pattern, not an Atlas 14 temporal distribution.

## ANUGA rain-on-grid on the runner's gmsh mesh (`anugarain`)

Chain: `fetchgrid` -> `hyetograph` -> `raingrid` (the `*_anuga_rate.csv` and `FACTOR_RASTER`) -> `anugarain`.
`damit_pmp:anugarain` makes the ANUGA 2D model the way `damit_runner` does for its ANUGA gmsh tier, by reuse and not by
re-implementation:

| Part | Runner code used |
|---|---|
| Mesher | `damit_runner/core/gmsh_mesher.py`, run as the runner runs it: a stand-alone script in the ANUGA Python (spec JSON in, npz out), clean environment, 600 s wall-clock timeout (`wallclock.run`: SIGTERM then SIGKILL), the same `MESHOK` / `MESHERROR` handling |
| Sizing | the mesher's own `default_sizes()` (lines 100 m2, flow path 250 m2, far field 20 000 m2, min angle 20 deg, gate 0.45 x the smallest size); optional `MAX_AREA_M2`, `LINE_MIN_AREA_M2`, `GRADE_DIST_M` are the runner's `NDBREACH_ANUGA_GMSH_*` keys and set nothing when empty |
| Domain ring | `terrain.mask_outline` of the basin cells, kept a tolerance from the DEM edge / no-data (`anuga_model.mesh_polygons`' rule for `outer`, pinned to it by a test), tolerance `max(min(buffer / 10, 3 dx), dx)` |
| Refinement | optional `FLOW_PATH_START` (the runner's inflow point): `terrain.trace_downstream`, clipped to the ring, `douglas_peucker` (as `anuga_model.gmsh_spec`); empty = a uniform far-field mesh |
| DEM | the runner's `Grid` model DEM (default cell 10 m; bilinear at the centroids); a DEM finer than `CELL_M` is also sampled at the triangle vertices (`sample_fine`, the runner's `fine` elevation) |
| Domain | the worker's build: local coordinates (DEM lower left = 0, 0), `Geo_reference(0, 0)`, every outer edge `outflow`, `DE0`, `set_minimum_storable_height(0.001)`, Manning n 0.06, dry start, `make_outer_boundary` for `edge_bc` (`outflow` default | `transmissive`) |
| Not in the runner | rain: its worker has only a breach inlet. The generated script adds `anuga.Rate_operator(domain, rate=f(x, y, t))`, the series in m/s times the optional per-triangle factor (the factor raster resampled to the model grid, sampled at the centroids) |

**Shared-code pattern.** The plugins install independently, so `damit_pmp/runner_shared/` holds byte copies of
`gmsh_mesher.py`, `grid.py`, `terrain.py`, `anuga_worker.py`, `omp_probe.py`, `anuga_dtdiag.py` and `wallclock.py` from
`damit_runner/core` (the repo's per-plugin copy pattern, as `catalog_bridge.py` / `_deps.py` / `compat/`). Edit the
runner, run `python3 scripts/sync_pmp_runner_shared.py`; `damit_pmp/tests/test_runner_shared_sync.py` (CI) fails on any
difference, and `tests/test_anuga_rain.py` pins the outer ring and line clipping to the runner's functions.

**Output folder**: `gmsh_mesh_in.json` (mesher input), `gmsh_mesh.npz` (the runner's mesh format), `gmsh_mesh.msh` (gmsh
MSH 2.2 with the ground height), `mesh_triangles.geojson` (up to 400 000 triangles), `anuga_rain_job.npz` (DEM, rain
series, settings; the runner's job keys), `run_anuga_rain.py` with the four runner files it imports,
`rain_rate_m_per_s.csv` and `run_manifest.json` (settings, QGIS / ANUGA / gmsh / numpy versions, sha256 of every
input, output and runner file, mesh statistics, what was launched). In the ANUGA Python:

    python run_anuga_rain.py --dry        # mesh if missing, domain, rate operator, storm-volume check; evolves nothing
    python run_anuga_rain.py --steps 2    # then evolve this many yield steps (after t = 0) and stop
    python run_anuga_rain.py --run        # the full simulation (long on a fine mesh)

`--steps` and `--run` write `anuga_rain_run.json` with a water balance (exact rain volume put on the mesh, water stored,
outflow through the outer boundary from ANUGA's boundary flux integral, residual, maximum depth, wet area over 5 cm /
30 cm) and `anuga_rain_timeseries.csv`; `--run` also writes `anuga_rain_result.npz` (maximum depth per triangle).
DWR-2801, coarse mesh (7 109 triangles), 100-yr 24-hr storm to 14 h: 37 s on one thread, balance residual 0.003 %.

**Launching.** Default: nothing is launched. `ANUGA_PYTHON` (a path, as DamSafety Setup shows it; never auto-detected)
plus `BUILD_MESH` (on) runs the runner's mesher (gmsh only) so the mesh and its statistics are in the folder;
`RUN_ANUGA` (**off by default**, needs the mesh) also runs `run_anuga_rain.py --run` with `RUN_TIMEOUT_H`. Only
`damit_pmp/launch.py` starts a process; `tests/test_metadata_suite.py` still bans process launching everywhere else in
the plugin and checks that the run switch defaults to off. gmsh needs the ANUGA Python (`pip install gmsh`; on Linux
`libGLU`).

Limits: the rain is a rate on the whole mesh (no infiltration, no losses, no channel network); ANUGA's `Rate_operator`
with a spatial `f(x, y, t)` runs on the CPU only; the basin is the polygon you give (not a delineated watershed); the
mesh is only as good as the DEM and the sizes (the quality gate rejects a bad one); the runner's worker features that
need a breach (inlet, culverts, crest hold, checkpoints) are not part of a rain job.

Tests: `damit_pmp/tests/test_atlas14.py` (recorded PFDS answers), `test_gis_rain.py` (URL building for every
frequency / duration / series / bound, cache, offline, 404, clip and 0.001 scaling on synthetic NOAA-style zips, `.rain`
format, mm/hr and m/s conversions, mass checks) and `PMPGrids` in `tests/test_qgis_new_plugins.py` (the algorithms in real
QGIS with a fake PFDS and a fake download); `test_anuga_rain.py` and `test_runner_shared_sync.py` for `anugarain`
(set `DAMIT_PMP_ANUGA_PYTHON` to run the real gmsh mesher and the script's `--dry` check). No test calls NOAA unless `DAMIT_NETWORK_TESTS=1` (one real download).
