# DamIT PMP 0.4.3 – NOAA Atlas 14 only

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
| `damit_pmp:hyetograph` | Design hyetograph from a pointpf / basinpf JSON: storm total = the Atlas 14 depth for the storm duration (1 h – 10 days) at the chosen frequency. **Temporal pattern (0.4.0):** alternating block (default; sub-durations log-log interpolated between published durations; not an Atlas 14 temporal distribution), the **NOAA Atlas 14 temporal distributions** (Volume 8, HDSC quartile curves) or the **NRCS 24-hour Type I / IA / II / III** curves. **Losses (0.4.0):** optional initial + constant loss, in inches or mm (default 0), giving an excess-rain column. |
| `damit_pmp:gridbasin` | Basin mean / min / max of an Atlas 14 GIS grid: a file you have (NOAA's, thousandths of an inch, SCALE 0.001; frequency and duration read from the standard file name, e.g. `mw100yr24ha.asc`, also the 2-day `48h` and `al` / `au` bound names) or a `fetchgrid` GeoTIFF (already inches, read with scale 1), **or** leave GRID empty and give the same frequency / duration / series / bound / region choices as `fetchgrid`: it fetches the NOAA grid itself. |
| `damit_pmp:fetchgrid` | **New in 0.3.0.** Downloads the Atlas 14 "PF in GIS format" grid for one frequency and duration, clips it to a point buffer, an extent or a basin (optionally blanking cells outside the polygons) and writes a Float32 GeoTIFF in **inches** (NOAA's thousandths x 0.001; NAD83 geographic, nodata -9999) plus `<tif>.json` (source URL, fetch time, SHA-256, Atlas 14 volume / version, citation, stats, value at the point). |
| `damit_pmp:raingrid` | **New in 0.3.0.** Rain-on-grid files from a hyetograph CSV (or a pointpf / basinpf JSON + FREQUENCY + STORM + STEP_MIN): a LISFLOOD-FP `.rain` file (mm/hr), an ANUGA rate series CSV (m/s) with a README, and a JSON record (units, totals, mass check). Optionally rescaled to an Atlas 14 grid at a point or as a basin mean, with a spatial factor raster. Launches nothing. 0.4.0: the same temporal patterns and losses as `hyetograph` (the files then hold the excess rain; the gross storm is in the record). |
| `damit_pmp:anugarain` | **New in 0.3.0.** An ANUGA rain-on-grid job on the damit_runner gmsh mesh: DEM + basin polygon / extent + the `raingrid` rate CSV (+ factor raster) -> the runner's gmsh mesh, a self-contained `run_anuga_rain.py`, a run manifest. Builds the mesh only when an ANUGA Python is given; runs ANUGA only with `RUN_ANUGA` (off by default). 0.4.0: optional discharge section (`GAUGE_A` / `GAUGE_B`: flow through a line, recorded every yield step) and `SIMPLIFY_M` for a jagged basin outline. |
| `damit_pmp:watershed` | **New in 0.4.0.** The watershed of a dam point from a DEM (a file you give, or USGS 3DEP fetched for you): D8 flow on the runner's depression-filled DEM, the pour point snapped to the nearest stream cell, the upstream area as a polygon, a JSON record and the ratio to the NID drainage area you give. |
| `damit_pmp:lisfloodrain` | **New in 0.4.0.** A LISFLOOD-FP rain-on-grid job built the way `damit_runner` sets up its LISFLOOD-FP run, on the same domain as `anugarain`: `Model Terrain (LISFLOOD).tif`, `.dem.asc`, `.bci` (FREE edges), the `.rain` file, `.par` (ACC by default), an optional discharge gauge and a manifest. Runs LISFLOOD-FP only with `RUN_LISFLOOD` (off by default). |

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
  60 days, **one shared list** (`atlas14.DURATION_LABELS`) used by `DURATION` in `fetchgrid` / `gridbasin` and `STORM` in
  `hyetograph` / `raingrid`, so the same index is the same duration in every tool: 0 = 5-min, 1 = 10-min, 2 = 15-min,
  3 = 30-min, 4 = 60-min, 5 = 2-hr, 6 = 3-hr, 7 = 6-hr, 8 = 12-hr, **9 = 24-hr (the default everywhere)**, 10 = 2-day,
  11 = 3-day, 12 = 4-day, 13 = 7-day, 14 = 10-day, 15 = 20-day, 16 = 30-day, 17 = 45-day, 18 = 60-day. A storm that
  cannot be built (shorter than `STEP_MIN`, not a whole number of steps, or more than 20 000 blocks) is not hidden:
  the tool stops and says which `STEP_MIN` to use (e.g. a 5-min storm needs `STEP_MIN` 5).
  **Breaking change since the 0.2.0 / early 0.3.0 `STORM` list** (60-min ... 10-day, 11 entries, 24-hr = 5): a caller
  that passes a number now gets the duration of the shared list (old 5 is now 2-hr; old 0-10 are new 4-14; add 4). The
  default is still 24-hr, so callers that leave `STORM` alone are unaffected.
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

`--steps` writes `anuga_rain_steps.json` (+ `anuga_rain_steps_timeseries.csv`) and `--run` writes `anuga_rain_run.json` (+ `anuga_rain_timeseries.csv`), each with a water balance (exact rain volume put on the mesh, water stored,
outflow through the outer boundary from ANUGA's boundary flux integral, residual, maximum depth, wet area over 5 cm /
30 cm); `--dry` keeps its own `anuga_rain_dry_check.json`, so no mode overwrites another; `--run` also writes `anuga_rain_result.npz` (maximum depth per triangle).
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


## Watershed of a dam (`watershed`) – new in 0.4.0

`damit_pmp:watershed` takes a dam point (the NID location or a crest point), a DEM and a snap radius and returns the
upstream basin: `OUTPUT_BASIN` (polygon), optional `OUTPUT_POUR` (the snapped point) and `OUTPUT_MASK` (raster) and
`OUTPUT_JSON` (`damit.pmp.watershed`: method, snap distance, area in sq mi and km2, DEM source and citation, the
comparison with `NID_AREA_SQMI`, a flag when the basin reaches the DEM edge). Method, in numpy / scipy (QGIS 3.34's
Processing has no GRASS provider on every install, and pysheds / whitebox are not assumed): the runner's
`terrain.priority_flood` fills depressions (a lidar DEM's flat reservoir surface is crossed), D8 steepest descent,
flow accumulation by headwater peeling, the pour point moves to the *nearest* cell whose accumulation is at least 95 % of
the largest in the snap window (the plain maximum would always be the far edge of the window and pick up side area
below the dam), and the upstream cells are traced. Cross-checked against GRASS `r.watershed` + `r.water.outlet` on
DWR-2801 (same area to three digits, overlap 0.999).

Leave `DEM` empty and the tool fetches USGS 3DEP (the National Map ImageServer, `elevation.nationalmap.gov`, the
runner's `terrain3dep.py`, tiled, EPSG:5070) for a square of `FETCH_RADIUS_KM` around the point at `FETCH_CELL_M`
into `WORK_DIR`; if the basin reaches the edge it widens the square (x 1.5, twice) and says so. The two hosts of
this fetch (and nothing else outside `hdsc.nws.noaa.gov`) are allowed by `test_only_pfds_host`: USGS 3DEP is a terrain
source, not a precipitation source. D8 follows the DEM surface: culverts, ditches and storm sewers are not in it, and
NID areas can include non-contributing area, so the two numbers differ.

## Temporal patterns and losses (`hyetograph`, `raingrid`) – new in 0.4.0

**NOAA Atlas 14 stays the only depth source.** `PATTERN` chooses only the *shape* of the storm; the total is always the
Atlas 14 depth for the storm duration and frequency.

| PATTERN | Curve | Storm durations |
|---|---|---|
| Alternating block (default) | built from the Atlas 14 depth-duration curve (unchanged) | any |
| NOAA Atlas 14 temporal distribution | HDSC "Temporal distributions of precipitation" for Volume 8 (Midwestern States), files `https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw_<area>_<hours>h_temporal.csv`; cumulative % of the storm total every 0.5 h for the quartile case (`QUARTILE`, default second) at the percent of occurrence (`PERCENT`, default 50 = median curve); the area 1 – 4 is found from the HDSC shapefile (`Vol8_Temporals_Shapefiles.zip`) by point-in-polygon, or set with `TDA`; the file URL, fetch time, SHA-256, title and a citation go into the JSON | 6, 12, 24, 96 h |
| NRCS Type I / IA / II / III | the 24-hour rainfall distributions of USDA SCS TR-55 (hourly ordinates, half-hour points for Type II), linear interpolation | 24 h |

A pattern that does not exist for the storm duration (for example Atlas 14 temporal for a 3-hour storm, NRCS for 12 h)
stops with a message naming the durations; nothing falls back silently. The Atlas 14 curves describe storms that exceed
the 2-year ARI and are published for Volume 8 only; other regions stop with a message. The median (50 %) curve is a
smooth, mild storm (for the 2nd-quartile 24 h case the steepest hour is 8.7 % of the total); the NRCS Type II curve
puts 42.8 % of the depth into hour 11 – 12, so the two patterns give very different peaks for the same Atlas 14 depth.
The NRCS ordinates are typed from TR-55 tables; check them against WinTR-55's 0.1-hour tables for regulatory work.
The HDSC files are downloaded once and cached (`CACHE_DIR`, `OFFLINE`).

**Losses.** `INITIAL_LOSS` (a depth) and `CONSTANT_LOSS` (a depth per hour) in `LOSS_UNITS` (in or mm; default 0 = no
loss). The initial loss is taken from the first rain, then a constant rate per step, never more than the rain in the
step. `hyetograph` adds `loss_<u>` and `excess_<u>` columns (only when a loss is set; with losses at 0 the CSV is
byte-for-byte the 0.3.0 format) and `# temporal:` / `# losses:` comment lines; `raingrid` writes the excess rain to the
`.rain` and ANUGA files (`TOTAL_MM`; the gross storm is `GROSS_MM`) and records both. Losses are not applied twice: a
CSV that already has an excess column is refused together with losses.

## LISFLOOD-FP rain-on-grid (`lisfloodrain`) – new in 0.4.0

Chain: `fetchgrid` -> `hyetograph` -> `raingrid` (`*_anuga_rate.csv`) -> `lisfloodrain` (and `anugarain`, same domain).
Reuse of damit_runner's LISFLOOD-FP setup, as sha-pinned verbatim copies in `runner_shared/` (`lisflood.py`, `units.py`,
`data_conventions.py`, `grid.py`, `wallclock.py`):

| Part | Runner code used |
|---|---|
| Settings and solver choice | `LisfloodSettings`, `solver_from_text`: **ACC** (the local-inertial CPU solver) by default; FV2 / MWDG2 only by name; FV1 / DG2 refused with the runner's message |
| Model DEM | the runner's `Grid` at `CELL_M`, masked to the same outer ring as `anugarain` (written as `Model Terrain (LISFLOOD).tif` and as `rain.dem.asc` in local coordinates, `local_grid`: the LISFLOOD-FP build is single precision) |
| `.par` | the runner's keywords and order (`DEMfile`, `resroot`, `dirroot`, `sim_time`, `initial_tstep`, `massint`, `saveint`, `bcifile`, solver, `elevoff`, `depthoff`, optional `theta` / `cfl`, `fpfric`, `gaugefile`); the test `runner_inputs_match` pins every shared line to `lisflood.write_inputs`. Rain run differences: `rainfall rain.rain` instead of the breach `bdyfile`, no `hazard` / `inittm_depth` (the arrival-time patch is not needed) |
| `.bci` | `FREE` (outflow, bed slope) on all four grid edges (`CLOSED_EDGES` closes some); cells outside the domain polygon are NODATA, which LISFLOOD-FP treats as walls. The grid is cropped to the domain's valid cells, so FREE acts where the domain reaches an edge (the manifest's `edge_valid_cells`; all zero = a closed model, warned) |
| `.rain` | mm/hr from the ANUGA rate series' own breakpoints (both solvers interpolate linearly, so the volume is the same) |
| Gauge | `GAUGE_A` / `GAUGE_B`: the runner's `gauge_section` / `_gauge_line` clip; LISFLOOD-FP sections run along a grid axis, so an oblique line becomes the nearest E / W / N / S section of the same width, centred on the line |
| Executable | `LISFLOOD_EXE`, else `data_conventions.detect_lisflood` (`DAMIT_LISFLOOD`, `PATH`, the usual build folders); the runner's numpy "built-in" engine is never offered |
| Launcher | `damit_pmp/launch.py::run_lisflood`: `lisflood -v rain.par` in the job folder, `OMP_NUM_THREADS`, the runner's wall-clock timeout and process-group stop. The runner's keep-awake wrapper is not used |

**Solvers.** `ACC` runs on any CPU build. **FV2 and MWDG2 are CUDA solvers of LISFLOOD-FP 8: a CPU build does not stop,
it silently runs another solver**, so check the log and do not read such a result as FV2 / MWDG2. The tool writes the
keyword and warns; it cannot tell which solver ran.

**Launching.** Nothing is launched by default. `RUN_LISFLOOD` (**off by default**) runs the executable and reads
`results/rain.max` (maximum depth, also written as `lisflood_max_depth.tif`), `rain.mass` (the water balance: the last,
cumulative, rain column; stored volume; outflow by difference and from Qout) and the gauge `rain.discharge` into
`lisflood_rain_results.json`. CI launch ban: `tests/test_metadata_suite.py` still bans process launching everywhere in
damit_pmp except `damit_pmp/launch.py`, which now holds the gmsh, ANUGA and LISFLOOD-FP launchers; the minimal
allowlist change is `lisfloodrain.py` and `algorithms/lisflood_algs.py` in `SOLVER_NAMES_OK` (they may name the solvers,
not import them), `lisflood_algs.py` as a second importer of `launch`, and a check that `RUN_LISFLOOD` defaults to off.

Limits: uniform rain only (one `.rain` series); no infiltration unless the series is already excess rain; the domain
rim is a wall in LISFLOOD-FP (only domain cells on the grid edge drain) but an outflow boundary all round in ANUGA; the gauge follows a grid axis; 10 m ACC on a 40 km2
domain is a long single-core run (hours for 36 h of simulated time).

Tests added in 0.4.0: `test_watershed.py` (synthetic valleys, the 3DEP fetch with a fake service),
`test_temporal_storm.py` (NRCS ordinates, the real HDSC file in `fixtures/`, a fake downloader and shapefile, losses),
`test_lisflood_rain.py` (files, runner parity, launcher with a stand-in executable; set `DAMIT_PMP_LISFLOOD` to run a
real LISFLOOD-FP for five simulated minutes) and `PMPPatternsLossesWatershedLisflood` in `tests/test_qgis_new_plugins.py`.

**Discharge section sign (0.4.1).** ANUGA's `Cross_section` counts flow as positive to the right of the polyline a -> b
(a north -> south line reads -Q for an eastward flow). With `FLOW_PATH_START` given, `anugarain` orders `GAUGE_A` /
`GAUGE_B` so positive is away from that point (downstream), the same sign as the LISFLOOD-FP gauge of `lisfloodrain`;
without it the ends are used as given. The magnitude was never affected.
