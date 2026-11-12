# Run watcher: the digest, its flags, and what Pierre does with them

Reference for the DamIT run watcher (`tools/run_digest.py`, `tools/pierre_watch.py`). Index it into Pierre so
"what does flag X mean" is answered from here, not guessed.

## Who decides what

- **Code owns the verdict.** `run_digest.py` reads the Runner's own files and sets **OK / WATCH / PROBLEM**
  from its flags alone: the highest severity present (INFO flags never count). It takes well under a
  second and needs no AI. The review is complete without Pierre.
- **Pierre only explains.** It gets the 20-40 line digest text and the flag titles (about 500-1,000 tokens),
  a pinned system prompt of Nick's rules, and writes one bullet per flag, **INFO notes included** (1.2.0), to `pierre_<event>.md`, under a
  **complete flag list that code wrote first** (every flag of every severity, with its receptor ids, nothing capped; a footer names any flag
  Pierre skipped, INFO ones too, or any flag-like id it invented). It never changes,
  gates or delays the verdict. If Pierre does not answer within a few seconds the review still stands, and
  whatever Pierre has streamed so far is on disk (`pierre_<event>.status.json` says done / partial / unavailable).
- **Explainer model:** a small model (default `qwen3:4b`; `phi4-mini` is the alternative), set with
  `PIERRE_WATCH_MODEL` or `--model`. Interactive Q&A (`pierre`, `pierre-chat`) is a different, larger model
  (`PIERRE_CHAT_MODEL`, 30B on a 32 GB+ Mac). Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an Intel Arc /
  Intel iGPU box runs on the CPU, which is why the small model is the default there.
- **Ollama settings:** `/api/chat` with `think:false` (on `/api/generate`, `/no_think` does not stop Qwen3
  thinking), `num_ctx` 4,096 (kept between 4,096 and 6,144), `stream:true`, every piece saved as it arrives, no
  hard total timeout (only a wait for the first piece, 600 s, and between pieces, 180 s, and neither discards text).
  `think:false` should stop `message.thinking`; if thinking tokens arrive anyway they are kept in
  `pierre_<event>.md.thinking.txt` and the status says `thinking_despite_think_false`. The status JSON also carries
  Ollama's own timings: `prompt_eval_duration`, `load_duration`, `eval_duration`, `total_duration`, the two token counts,
  and derived `prompt_eval_s`, `eval_tok_per_s`, `first_piece_s`. `first_byte_wait_s` is the **measured** wait from the request to
  the first streamed line (the seconds actually waited if nothing streamed); the configured limit is its own field,
  `first_token_cap_s`.

## Hooks (events)

| Event | When | Digest covers |
|---|---|---|
| `pass_end` | a LISFLOOD-FP pass wrote its `Finish` line | passes so far |
| `stall` | the latest pass is unfinished and its `.mass` has not grown for 900 s | passes so far |
| `run_end` | `run_report.json` exists (or `run_setup.json` status finished) | the whole run |
| `before_hazard` | after `run_end`, before `damit:classify` has written its report | the whole run, receptors from the structures layer |
| `after_hazard` | `classify/damit_hazard_report.json` appeared | adds the Hazard drivers to review |

A 45 s run still gets every hook (all five fire on the first look). When several events arrive together each
gets its digest but only the newest is sent to Pierre (one inference at a time).

### When Pierre may use the CPU (it must not slow LISFLOOD)

On a CPU-only box the model and LISFLOOD-FP share the cores: one explanation during a pass made the Runner about 7x
slower (202 s instead of 28 s). So the digest and the complete flag list are written at once, but **Pierre explains only
after the Runner's whole pipeline has finished** (`PIERRE_WATCH_EXPLAIN=idle`, the default, 1.3.0), and no `lisflood` process runs.
The finish markers, strongest first: `run_progress.json` `complete` (DamIT Runner 0.3.1 writes it after `run_report.json`),
`run_report.json`, `run_setup.json` status `finished` or `failed`. A quiet gap between passes is **not** idle: the Runner works in
Python between passes with no `lisflood` process and no log growing (1.2.0's 20 s gap started Pierre 2 s after pass 6 of DWR-2824;
pass 7 took 71 s instead of 26 s and the Runner 164 s instead of 106 s). A pass hook therefore only queues. A Runner that died
(nothing written to the run folder for `PIERRE_WATCH_STALE_S`, 900 s, and no `lisflood` process) counts as over, so the queue
cannot wait forever. Until then the newest event waits in a queue (`pierre.status` = `queued`); a one-shot `event` prints how to ask
later. Other modes: `end` (the same gate), `always` (the old behaviour), `never`. `PIERRE_WATCH_IDLE_GAP_S` is still accepted but no
longer used. Ollama is also capped to `PIERRE_WATCH_NUM_THREAD`
threads (default 2; 0 = Ollama's own) and the explain process is niced (`PIERRE_WATCH_NICE`, 10, POSIX).

### Waiting for a busy Ollama

`PIERRE_WATCH_FIRST_TOKEN_S` (default 600; **0 = wait without limit**) is how long to wait for the first byte. It counts
time queued behind another Ollama job (a live run waited 211 s) and the model load. When it runs out the status is
`timeout` (not `partial`, not `error`): no answer yet, the digest stands, `pierre_watch.py explain DIGEST_JSON` asks again.
`partial` is only ever text that did stream. `PIERRE_WATCH_IDLE_S` (180; 0 = no limit) is the wait between pieces.

## What the digest checks (and the flag ids)

The Runner's own numbers are reused: the per-pass record in `run_report.json` (`boundary_outflow_pct`,
`edge_depths_ft`, `sim_time_hr`, `still_moving`, `max_volume_error_pct` when present) and the per-pass results
under `model/runNN_*/results/`. Only when a number is not there does the digest compute it from the `.mass`
file, with the Runner's formula (signed sum of the interval errors over the injected volume).

| Flag id | Severity | Meaning |
|---|---|---|
| `MASS_NAN` | PROBLEM | NaN or Inf rows in a `.mass` file |
| `MASS_BALANCE` | WATCH over 0.5 %, PROBLEM over 1 % | per-pass volume error as % of injected volume (the Runner's own limit is 1 %) |
| `DOMAIN_VOLUME` | PROBLEM | the model holds more than 1.10x the water that went in (an edge is importing water) |
| `EDGE_INFLOW` | PROBLEM | water enters through a model domain edge (negative Qout), over 2 % of injected |
| `EDGE_OUTFLOW_EARLY` | WATCH | an early pass let water leave through a wet **model domain edge** (the border of the computation grid, not the breach and not the dam). Expected while the domain grows; it is not dam leakage; confirm the final pass is clean |
| `EDGE_OUTFLOW_FINAL` | PROBLEM (WATCH if only a wet edge) | the FINAL pass leaks: extent and depths are not final |
| `PASS_UNFINISHED` | PROBLEM / WATCH | a pass has no Finish line, or stopped before 99 % of its planned sim time. Not raised (1.3.1) when the last `.mass` sample is within one output interval (`massint` in `run.par`, else the gap between the last two samples) of `sim_time` and the pass log has a Finish line, or the Runner recorded the pass (`run_progress.json` / `run_report.json`), or a later pass exists: LISFLOOD-FP writes `.mass` every `massint` s, so a clean pass can end up to one interval short of `sim_time` (DWR-2801 pass 1: 24,309 s of 24,561 s, `massint` 300) |
| `STALL` | PROBLEM | a running pass whose `.mass` has not grown for the stall time |
| `STOPPED_MOVING` | WATCH | the run ended (clock / MAX_RUNS cap) while the flood still moved |
| `HEIGHT_MISMATCH` | WATCH (PROBLEM over 5 ft or 15 %) | crest minus streambed differs from the inventory height (e.g. 39 vs 37 ft). With no streambed in the dam record the title says `breach bottom used as streambed (no streambed in dam record)`: BOTTOM_FT stands in for it |
| `BREACH_BOTTOM_RAISED` | WATCH | the Runner raised the breach bottom to the reservoir bottom (usually the height mismatch showing up) |
| `DATUM` | PROBLEM for DWR (INFO when unknown) | not NAVD88, or 0-300 ft (a local datum). A top of dam above 300 ft with no datum stated is taken as NAVD88-range and raises nothing; with no elevation at all it is INFO `unknown datum (no dam record)` |
| `START_WSE` | PROBLEM | starting WSE is not the top of dam (= DWR max pool) |
| `OUTLET_FLOW` | PROBLEM | a boundary source besides the breach (outlet, spillway, inflow); not a sunny day |
| `TOE_INFLOW` | PROBLEM | the breach inflow is outside the toe band |
| `TOE_BAND` | WATCH | the Runner's band end differs from H x (slope+1) |
| `TOE_BAND_WIDENED` | INFO | the Runner widened the toe band (the nearer ground was the dam face) and the inflow is inside the widened band (1.3.3) |
| `TOE_UNCHECKED` | WATCH (INFO) | the run report gives no distance from the dam line (the Runner fell back to the lowest ground near the dam point, or there is no `dam_line.geojson`): the inflow position is not checked; the band still is |
| `TOE_SOURCE_RUN_REPORT` | INFO | the run report DOES give the toe inflow distance (the Runner measured it) but there is no `dam_line.geojson` to measure it again: the digest uses the Runner's number and says so ("toe from run_report, no dam_line") instead of raising `TOE_UNCHECKED`. The position check (`TOE_INFLOW`) and the band check still run on it |
| `ENGINE_FALLBACK` | WATCH | the built-in numpy engine ran, not LISFLOOD-FP |
| `RUN_WARNINGS` | WATCH | the Runner logged warnings |
| `RECEPTOR_NODATA` | WATCH | structure(s) on a NoData cell next to wet cells (Hazard reads NoData as dry) |
| `RECEPTOR_DRY_NEXT_TO_WET` | WATCH | structure(s) on a dry cell beside water at least 1 ft deep |
| `ROADS_UNSCORED` | WATCH | roads with unknown class/AADT not scored by M8a |
| `HAZARD_REVIEW` | WATCH | sole-access (M8b) not scored, missing receptor layers, judgment-zone hits, guessed M13 |
| `RAIL_TRAINS` | WATCH | a rail line has no trains/day, or the lookup's BNSF KO row is not 15 |
| `NO_RUN_FILES` | PROBLEM / WATCH | nothing to read, or a raster could not be read (the message names the exception type and a traceback tail, and hints at PROJ_DATA when the PROJ database cannot be opened) |
| `DAM_RECORD_MISSING` | INFO | no `dam.json` in the dam folder: streambed and datum unknown; the dam id comes from the run, the report, the hand-off or the folder name |
| `RECEPTORS_UNCHECKED` | INFO | the structure layer could not be sampled (GDAL/OGR or numpy missing) |

Receptor flags (`RECEPTOR_NODATA`, `RECEPTOR_DRY_NEXT_TO_WET`) name the first 10 structure ids and a count in the digest, the
complete flag list and the Pierre prompt; the JSON `data` has every id.

**One flag per id (1.2.0).** An id raised more than once (`EDGE_OUTFLOW_EARLY` in passes 1 and 2) is listed once in the
digest, the flag list, `latest_verdict.json` and the Pierre prompt: the most severe one is kept, the latest among equals. The others are in
the flag's `data` (`occurrences`, `also`) and its detail ("Also raised at pass 1 ..."). The verdict is unchanged.
`latest_verdict.json` lists the WATCH / PROBLEM ids in `flags` and the INFO ids in `info_flags`.

**Pass hooks flag receptors too (1.3.0).** A pass's own `run.max` is in local coordinates and `run_report.json` (the bounds and
CRS) does not exist until the run ends, so the 1.2.0 pass hooks could not place a receptor. DamIT Runner 0.3.1 writes
`run_progress.json` in the run folder after every pass: the model CRS and each pass's folder and bounds (and `complete`, `growth_loops_done`).
The digest reads it, so `RECEPTOR_NODATA` / `RECEPTOR_DRY_NEXT_TO_WET` appear at `pass_end` from the structure layer (`--structures`
or `--points`) on the pass's own grid, with the same ids as `run_end` when the grid is the same. A run from an older Runner has no
`run_progress.json`: its pass hooks still cannot flag receptors (the run_end hook does).

**Pass-hook receptor cost (1.3.1).** DWR-2801 (88,734 structures) ran 493 s with the watcher against 348 s without, pass 7 191 s against 75 s:
the 1.3.0 hooks re-read and reprojected the whole structure layer through GDAL at every pass, while LISFLOOD-FP uses all cores.
Now: the layer is loaded once per process (cached by path, mtime, size and CRS); receptors are numpy arrays; sampling is one vectorised
index lookup per pass (only the points inside the wet extent's bounding box, grown by a cell, are looked up; the result and its
order are the per-point version's); a `pass_end` hook samples only every `PIERRE_WATCH_PASS_RECEPTOR_EVERY`-th pass (default 2) unless the
run is already over, and always at `run_end`; the digest says `receptors_skipped` when it did not; `watch` lowers its own priority to
nice `PIERRE_WATCH_PASS_NICE` (19). The one-off read of the layer (about 1.1 s per 88k points) lands on the first sampled pass.

**Every pass hook says what it sampled (1.3.2).** DWR-2801 (Absaraka, 9 passes, `PIERRE_WATCH_PASS_RECEPTOR_EVERY` 2): passes 4, 6 and 8 had neither
`receptors` nor `receptors_skipped`, and no peaks. Cause: LISFLOOD-FP writes the `Finish` line, the watcher fires `pass_end`, and the Runner
is still reading the pass's results (`G.edge_depths`, `flood_stats`); it writes the pass into `run_progress.json` (the georeference) only after
that. A hook that fires in the gap finds no bounds for the pass, so there is no grid and nothing to sample; the 1.3.1 code recorded a skip
reason only when it had chosen not to sample. Now: (1) `pass_end` waits until `run_progress.json` has the pass (`PIERRE_WATCH_RECORD_GRACE_S`,
default 120 s after the pass log finished, then it fires anyway); (2) whatever happens, `checks.receptors` or `checks.receptors_skipped`
is set (not sampled at this hook, no georeference yet, no run.max, no receptor points, not enough free RAM, unreadable grid, a missing
package), and the `watch` log line for the pass says it. Not changed: a pass folder name reused by a later grid-check / refine loop still
resolves to the LAST progress entry of that name.

**Memory (1.3.2).** A late pass's grid is the biggest thing the watcher holds. The digest read every earlier pass's `run.max` again at
every hook just for the four edge depths (`read_asc_edges` now streams them: first / last row, first / last value of each row, cached by
file mtime and size); a grid above 4 million cells is read as float32; the pass grid, the wet mask and the receptor grid are made in place
(no `np.where` full-size copies) and dropped as soon as the hook is done; a mid-run hook does not read a grid that would leave less than
`PIERRE_WATCH_MIN_FREE_MB` (default 1024) of RAM free (it says so in `receptors_skipped`; `run_end` reads the final outputs unguarded).
Ollama keeps the model `PIERRE_WATCH_KEEP_ALIVE` (default 2m, was a fixed 30m) after an explain, so a model loaded for one run does not sit in
RAM beside the next run's LISFLOOD-FP.

**A widened toe band is not a TOE_INFLOW problem (1.3.3).** The Runner widens the toe band 10 m at a time (up to 60 m more) while the lowest ground in
it is the dam's face (less than 75 % of the dam height below the top). DWR-2645: 5-27.1 m widened to 5-37 m, inflow 36 m from the line,
24.5 ft below the crest; 1.3.2 judged that against 5-27.1 m and set the run to PROBLEM. Runner 0.3.3 records `inflow.toe_band.effective_inner_m`,
`effective_outer_m`, `original_outer_m`, `widened` and `widening_reason` in `run_report.json`; a report without them is read from the inflow
text ("5-37 m downstream of the dam line ... (band widened from 27 m: reason)"). The digest judges the inflow against the effective band: inside
it and beyond the nominal band is `TOE_BAND_WIDENED` (INFO, names the reason); outside the effective band (or under the inner edge) stays
`TOE_INFLOW` PROBLEM; a report with neither fields nor text is judged against its own band as before.

**The Runner's end-of-run edge warning (1.3.3, Runner 0.3.3).** DWR-2645 ended at the 96 h clock with the S edge at 0.94 ft and 3.37 % of the
volume gone, and the Runner said nothing: the growth loop grows the domain only for an edge deeper than `EDGE_TOL_FT` (1 ft) or an edge
carrying 10 % of the outflow once `OUTFLOW_EXTEND_PCT` (5 %) has left, and warned only at 5 % outflow. Those are deliberate limits, not a
bug; the Runner now warns (log, `run_report.json warnings`, `run_setup.json run_notes`) when the last pass has a wet edge (>= the arrival
depth) with at least 1 % outflow, or a wet edge deeper than the tolerance, or 5 % outflow: it names the edges, depths and outflow %, the limit
it stopped at, or why it did not grow. The watcher shows it as `RUN_WARNINGS`; `EDGE_OUTFLOW_FINAL` is unchanged.

**The dam line file is read (1.3.2).** `dam_line_found` used to mean the file existed. The digest now opens a GeoJSON dam line: a
LineString or a MultiLineString with at least one line of two vertices counts (`dam_line_geometry`, `dam_line_parts` say which and how many
parts); an empty or line-less file is not a dam line (`dam_line_unusable`). The Runner (0.3.2) joins a MultiLineString's parts end to end
and uses the longest, and says so in the run notes. When the dam line exists but the report's inflow is a fallback, `TOE_UNCHECKED` says the
Runner placed it without the line (a Runner before 0.3.2 read a MultiLineString as nothing: DWR-2645, the inflow landed 192 m on the pool
side).

**Where the dam line is looked for (1.3.0).** `dam_line.geojson` (or `dam_line_linestring.geojson`, `dam_line.gpkg`, `.shp`) in the dam folder
and its `inputs/`; `<work>/inputs/` and `<work>/handoff/<dam id>/` beside the `dams/` and `runs/` folders; the run folder and its
`inputs/`; the folder of every input in `run_setup.json inputs` (the terrain's folder: the Screener's `inputs/`); the hand-off's
folder; and a `dam_line` path the setup names. Without one the digest says `TOE_SOURCE_RUN_REPORT` as before.

**Receptors read the same at every hook (1.2.0).** The Runner's final `Depth (Max).tif` writes depth <= 0 as NoData, so a
dry cell there is NoData. A pass's own `run.max` has 0.0 on dry cells. The digest now treats depth <= 0 as NoData for every
source before sampling, so a receptor is `RECEPTOR_NODATA` at a `pass_end` hook and at `run_end` alike (it used to be
`RECEPTOR_DRY_NEXT_TO_WET` mid-run and `RECEPTOR_NODATA` at the end). `RECEPTOR_DRY_NEXT_TO_WET` is now only a receptor on a cell
with a trace of water (above 0, under 0.1 ft) beside water 1 ft deep or more. A pass hook samples the coarse pass grid
(the flag says so); the final raster can be finer, so the ids can still differ between a pass hook and `run_end`.

Per-edge outflow: LISFLOOD-FP's `.mass` gives one outflow total, so the digest reports the total boundary
outflow % and the depth at each edge (N/S/W/E), and attributes the outflow to the wet edges.

## Peak depth and peak velocity

Peaks are maxima over **wet cells** (depth of 0.1 ft or more), from `Depth (Max).tif` and `Velocity (Max).tif`
(or the last pass's `run.max` / `run.maxVc`). The digest prints both.

## Where output goes

`~/local-ai/watch/<dam>_<run>/` (or `--out`): `digest_<event>.json` (machine flags), `digest_<event>.txt`,
`latest_verdict.json`, `pierre_<event>.md` (complete flag list by code, then Pierre's bullets) and
`pierre_<event>.status.json`, plus `dam_record_hazard.json`. Never inside the run or dam folder.

## No dam.json in the dam folder (the Screener / Runner path may not write one)

The digest does not stop: the dam id comes from the run, the report, `damit_handoff.json` or the dam folder's name
(`DAM_RECORD_MISSING`, INFO); the height check uses BOTTOM_FT and says so; the datum is judged from the elevation; the
toe inflow position is skipped with `TOE_UNCHECKED` when the report has no distance; when it has one (the Runner measured it),
it is used and the digest says "toe from run_report, no dam_line" (`TOE_SOURCE_RUN_REPORT`, INFO). The watcher writes a flat
`dam_record_hazard.json` beside the digest (a copy, never a change to the dam folder). Since DamIT Hazard 0.2.1 `damit:classify`
no longer needs it pointed out: `DAM_JSON` may be the nested dam folder `dam.json` as it is, and with `DAM_JSON` empty Hazard finds the
`dam.json` above the depth raster, else this watcher copy: for the run folder the raster sits in, or (0.2.2) by dam id when the raster is in
the dam folder (`<Dams>/<dam id>/Depth (Max).tif`, where `rundam` puts it): the newest `<dam id>_run_<timestamp>/dam_record_hazard.json`
whose own `dam_id` is that folder's name (`DAMIT_WATCH_DIR` if the watch folder is not `~/local-ai/watch`).

## If the receptor or raster check fails with a PROJ error

GDAL needs PROJ's database (`proj.db`). If PROJ cannot find it, `NO_RUN_FILES` says so (with the exception type and a
traceback tail, never an empty message). Set `PROJ_DATA` (older stacks: `PROJ_LIB`) to the folder holding `proj.db`
(`<conda env>/share/proj`, or the QGIS install's `share/proj`) and run again. Everything else in the digest is unaffected.

## Commands

```
pierre-digest RUN_DIR                       # the digest, no AI   (python run_digest.py RUN_DIR [--json])
pierre-watch watch RUN_DIR                  # fire the hooks as the run progresses
pierre-watch event run_end RUN_DIR          # one hook now
pierre-watch event pass_end RUN_DIR --pass 2
pierre-watch digest RUN_DIR --json --exit-code     # exit 0 OK, 1 WATCH, 2 PROBLEM (from the code, never from Pierre)
```
