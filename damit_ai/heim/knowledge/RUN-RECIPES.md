# Run recipes

How runs of this suite are actually launched, so that a failed run can be traced back to
the command that started it. Each recipe says **what it runs**, **where the results and
logs go**, and **what it skips when run a second time**. The scripts' own headers are the
full reference; `CLI-HELP.md` lists every flag of the local-AI tools.

Everything headless goes through `qgis_process` in the conda env `ndqgis`, with the QGIS
profile of **one** plugin set. The ND set and the DamSafety set share Processing ids and
are never loaded together.

---

## 1. One or a few dams, ND set (`damchain`)

```
damchain seed --dams-folder D --csv dams.csv
damchain run --set nd --dams-folder D --ids DWR-2801,DWR-4031
```

- `seed` writes `D/<dam_id>/dam.json` from each CSV row and never overwrites one.
- `run` does, per dam: Get data (`ndhazard:getdamdata`), then Screening, Runner and Hazard
  (`ndhazard:suitechain`).
- Results: the dam folder. State: `D/<dam_id>/_chain_nd/state.json`. Summary:
  `D/Chain_Summary_ND.csv`. Logs: `D/_chain_logs/<time>/`.
- Second run: a dam whose state is `done` is skipped. `--redo` runs it again. Neither
  re-fetches data already recorded in `dam.json`; that needs `--getdata-param OVERWRITE=true`.
- `--hi-res` asks Get data for a 1 m DEM. `--dry-run` prints the commands and runs nothing.
  `--triage` asks Heim to explain a failed step into `TRIAGE.txt` beside the log; it does
  not change the result.
- Defaults can sit in the environment, each a space-separated `KEY=VALUE` list:
  `DAMCHAIN_GETDATA_PARAM`, `DAMCHAIN_BREACH_PARAM`, `DAMCHAIN_SCREEN_PARAM`,
  `DAMCHAIN_CLASSIFY_PARAM`. A flag on the command line wins.
- Exit code: 1 when any dam failed (from dam_chain 1.5.2).

## 2. A list of dams, DamSafety set (`damchain run --set dwr`)

```
damchain run --set dwr --dams LAYER --ids 2801,4031 --out D --dem DEM --screen-work W
```

The DamSafety Runner's own list chain (`ndbreach:chainbatch`: Screening, Runner, Hazard).
Logs in `D/_chain_logs/`. Here the DEM is given on the command line, not fetched.

## 3. The review dams (`run_nickreview.sh`, DamSafety repo `tools/mac/`)

```
bash run_nickreview.sh --dam DWR-2801 --dry-run
bash run_nickreview.sh --dam DWR-2801
bash run_nickreview.sh
```

- Runs the stages `prepare`, `structures`, `precheck`, `record`, `rundam`, `hazclass`,
  `hazbatch` with the fixed review settings (`absaraka/grok_settings_DWR-2801.json` is the
  machine-readable copy for DWR-2801).
- Inputs: `--data` (read only; default `~/dwr-dam-suite/NickReview_data`). Results: `--out`
  (default `~/dwr-dam-suite/Dams/NickReview_mac`), with `dams/<dam>/` and
  `work/<dam>/run_<dam>.log`.
- Second run: finished stages are skipped (`work/<dam>/status/<stage>.ok`). `--redo` re-runs
  the named stages and everything that reads them. See `FILE-CONTRACTS.md` for the table
  and for the one stage it misses after a terrain change.
- Three dams (DWR-2801, 2865, 3034) use a finished box preparation in place of `prepare`
  and `structures`, unless `--no-kits`.

## 4. The same runs on a local terrain file (`use_local_terrain.sh`)

```
bash use_local_terrain.sh check
bash use_local_terrain.sh absaraka-kit
bash use_local_terrain.sh absaraka
bash use_local_terrain.sh nickreview
bash use_local_terrain.sh batch44-lisflood
bash use_local_terrain.sh batch44-anuga
```

- Points recipe 3 and the 44-dam batches at one local terrain VRT in place of downloaded
  or copied 3DEP tiles. `--vrt PATH` or `$ND_LOCAL_TERRAIN` names it.
- `check` runs nothing and prints what each run would do. Run it first.
- `absaraka-kit` keeps the DWR-2801 composite DEM (1 m over the dam, 5 m underneath) and only
  redirects its 1 m tile paths; the model is the same terrain as the reference run.
  `absaraka` uses the plain 1 m VRT and so loses the 5 m underlay.
- It adds `--redo` for the review runs and `OVERWRITE=true` for Get data, because without
  them the old terrain is silently reused. `--no-redo` removes the first and is rarely right.
- What a terrain swap changes besides the path is listed under "Terrain swaps" in
  `KNOWN-BEHAVIOURS.md`. Read that before comparing a swapped run with an earlier one.

## 5. Many dams (`run_lisflood_44.py`, `run_anuga_culverts_44.py`, `run_county.py --list`)

- Each drives recipe 1 or 2 over a list. All take `--dry-run`, `--only <dam>`,
  `--parallel N`, `--redo`, `--dem`, `--cell`, `--watch` (the run watcher) and `--triage`.
  `run_county.py` adds `--county`, `--list`, `--limit N`, `--kind`, `--mode` (LISFLOOD-FP
  or ANUGA) and `--status`.
- These three scripts are not in a repository yet; they travel with the batch packages.
- They decide pass or fail from `state.json`, not from the exit code.
- LISFLOOD-FP scales poorly with threads: several dams side by side at one thread each
  finish sooner than one dam on many threads.

## 6. Repo audit and golden runs (`damchain audit`)

```
damchain audit --repo R --golden --results D
```

Packaging, security patterns, network hosts, optional Heim diff review, and golden runs
compared with stored results. Report in `~/local-ai/reports`. Heim's review is commentary;
the checks decide.

## 7. The run watcher (`heim-watch`, `heim-digest`)

`heim-digest <run folder>` computes the flags and the verdict with no model. `heim-watch`
does the same at each pass end and at run end and may add Heim's explanation. The verdict
is the code's. See `WATCHER-DIGEST.md`.

## 8. Vor (`first-run.zsh`, `vor`)

```
zsh first-run.zsh
vor ask "..." --doc P-946
vor add <file>
```

`first-run.zsh` installs Vor if needed, downloads the library, indexes it, runs the eval on
the models the machine can hold, and zips the log and reports. One to three hours cold.
Its log is `~/Vor/first-run-<time>/first-run.log`.

## Environment that changes a run without appearing on its command line

| Variable | Effect |
|---|---|
| `NDSUITE_DATA` | overrides the plugin's saved data folder |
| `NDSUITE_PACK` | overrides the saved offline-pack path |
| `ANUGA_PYTHON` | which Python runs ANUGA; a saved Processing setting still beats the bare variable |
| `NDBREACH_LISFLOOD_SOLVER` | the Runner's solver (ACC default) |
| `NDBREACH_STABILITY_RETRY=0` | turns the damped re-run off |
| `NDBREACH_HECRAS_TIMEOUT_S` | opt-in HEC-RAS compute timeout (none by default) |
| `QGIS_CUSTOM_CONFIG_PATH` | the QGIS profile root; write `$HOME`, not `~`. A path that does not exist is **created empty**, and the run then finds no plugins |
| `DAMCHAIN_*_PARAM` | default parameters for `damchain run` |
| `HEIM_DB`, `HEIM_MODEL`, `VOR_HOME`, `VOR_MODEL`, `VOR_EMBED` | which index and model the local AIs use |

---

_Curated. Update when a launch script's stages, defaults or skip rules change. Keep machine
names, credentials and file-server links out._
