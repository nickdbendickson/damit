# Run watcher: the digest, its flags, and what Lumo does with them

Reference for the DamIT run watcher (`tools/run_digest.py`, `tools/lumo_watch.py`). Index it into Lumo so
"what does flag X mean" is answered from here, not guessed.

## Who decides what

- **Code owns the verdict.** `run_digest.py` reads the Runner's own files and sets **OK / WATCH / PROBLEM**
  from its flags alone: the highest severity present (INFO flags never count). It takes well under a
  second and needs no AI. The review is complete without Lumo.
- **Lumo only explains.** It gets the 20-40 line digest text and the flag titles (about 500-1,000 tokens),
  a pinned system prompt of Nick's rules, and writes a few bullets to `lumo_<event>.md`. It never changes,
  gates or delays the verdict. If Lumo does not answer within a few seconds the review still stands, and
  whatever Lumo has streamed so far is on disk (`lumo_<event>.status.json` says done / partial / unavailable).
- **Explainer model:** a small model (default `qwen3:4b`; `phi4-mini` is the alternative), set with
  `LUMO_WATCH_MODEL` or `--model`. Interactive Q&A (`lumo`, `lumo-chat`) is a different, larger model
  (`LUMO_CHAT_MODEL`, 30B on a 32 GB+ Mac). Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an Intel Arc /
  Intel iGPU box runs on the CPU, which is why the small model is the default there.
- **Ollama settings:** `/api/chat` with `think:false` (on `/api/generate`, `/no_think` does not stop Qwen3
  thinking), `num_ctx` 4,096 (kept between 4,096 and 6,144), `stream:true`, every piece saved as it arrives, no
  hard total timeout (only a wait for the first piece, 600 s, and between pieces, 180 s, and neither discards text).

## Hooks (events)

| Event | When | Digest covers |
|---|---|---|
| `pass_end` | a LISFLOOD-FP pass wrote its `Finish` line | passes so far |
| `stall` | the latest pass is unfinished and its `.mass` has not grown for 900 s | passes so far |
| `run_end` | `run_report.json` exists (or `run_setup.json` status finished) | the whole run |
| `before_hazard` | after `run_end`, before `damit:classify` has written its report | the whole run, receptors from the structures layer |
| `after_hazard` | `classify/damit_hazard_report.json` appeared | adds the Hazard drivers to review |

A 45 s run still gets every hook (all five fire on the first look). When several events arrive together each
gets its digest but only the newest is sent to Lumo (one inference at a time).

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
| `EDGE_INFLOW` | PROBLEM | water enters through an edge (negative Qout), over 2 % of injected |
| `EDGE_OUTFLOW_EARLY` | WATCH | an early pass leaked through a wet edge. Normal while the domain grows; confirm the final pass is clean |
| `EDGE_OUTFLOW_FINAL` | PROBLEM (WATCH if only a wet edge) | the FINAL pass leaks: extent and depths are not final |
| `PASS_UNFINISHED` | PROBLEM / WATCH | a pass has no Finish line, or stopped before 99 % of its planned sim time |
| `STALL` | PROBLEM | a running pass whose `.mass` has not grown for the stall time |
| `STOPPED_MOVING` | WATCH | the run ended (clock / MAX_RUNS cap) while the flood still moved |
| `HEIGHT_MISMATCH` | WATCH (PROBLEM over 5 ft or 15 %) | crest minus streambed differs from the inventory height (e.g. 39 vs 37 ft) |
| `BREACH_BOTTOM_RAISED` | WATCH | the Runner raised the breach bottom to the reservoir bottom (usually the height mismatch showing up) |
| `DATUM` | PROBLEM for DWR | not NAVD88, or 0-300 ft (a local datum) |
| `START_WSE` | PROBLEM | starting WSE is not the top of dam (= DWR max pool) |
| `OUTLET_FLOW` | PROBLEM | a boundary source besides the breach (outlet, spillway, inflow); not a sunny day |
| `TOE_INFLOW` | PROBLEM | the breach inflow is outside the toe band |
| `TOE_BAND` | WATCH | the Runner's band end differs from H x (slope+1) |
| `ENGINE_FALLBACK` | WATCH | the built-in numpy engine ran, not LISFLOOD-FP |
| `RUN_WARNINGS` | WATCH | the Runner logged warnings |
| `RECEPTOR_NODATA` | WATCH | structure(s) on a NoData cell next to wet cells (Hazard reads NoData as dry) |
| `RECEPTOR_DRY_NEXT_TO_WET` | WATCH | structure(s) on a dry cell beside water at least 1 ft deep |
| `ROADS_UNSCORED` | WATCH | roads with unknown class/AADT not scored by M8a |
| `HAZARD_REVIEW` | WATCH | sole-access (M8b) not scored, missing receptor layers, judgment-zone hits, guessed M13 |
| `RAIL_TRAINS` | WATCH | a rail line has no trains/day, or the lookup's BNSF KO row is not 15 |
| `NO_RUN_FILES` | PROBLEM / WATCH | nothing to read, or a raster could not be read |

Per-edge outflow: LISFLOOD-FP's `.mass` gives one outflow total, so the digest reports the total boundary
outflow % and the depth at each edge (N/S/W/E), and attributes the outflow to the wet edges.

## Peak depth and peak velocity

Peaks are maxima over **wet cells** (depth of 0.1 ft or more), from `Depth (Max).tif` and `Velocity (Max).tif`
(or the last pass's `run.max` / `run.maxVc`). The digest prints both.

## Where output goes

`~/local-ai/watch/<dam>_<run>/` (or `--out`): `digest_<event>.json` (machine flags), `digest_<event>.txt`,
`latest_verdict.json`, `lumo_<event>.md` and `lumo_<event>.status.json`. Never inside the run folder.

## Commands

```
lumo-digest RUN_DIR                       # the digest, no AI   (python run_digest.py RUN_DIR [--json])
lumo-watch watch RUN_DIR                  # fire the hooks as the run progresses
lumo-watch event run_end RUN_DIR          # one hook now
lumo-watch event pass_end RUN_DIR --pass 2
lumo-watch digest RUN_DIR --json --exit-code     # exit 0 OK, 1 WATCH, 2 PROBLEM (from the code, never from Lumo)
```
