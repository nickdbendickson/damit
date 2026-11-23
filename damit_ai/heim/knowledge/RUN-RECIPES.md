# Run recipes

How runs of this suite are actually launched, so that a failed run can be traced back to
the command that started it. Each recipe says **what it runs**, **where the results and
logs go**, and **what it skips when run a second time**. The scripts' own headers are the
full reference; `CLI-HELP.md` lists every flag of the local-AI tools.

Everything headless goes through `qgis_process` in the conda env `ndqgis`, with the QGIS
profile of **one** plugin set. The ND, DamSafety and DamIT sets share Processing ids and
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

`--cell`, `--solver` and `--manning` (and `--runner-param KEY=VALUE`) set the Runner's
`CELL`, `SOLVER` and `MANNING` for the listed dams. From dam_chain 1.6.0 every name is
checked against `ndbreach:batch` (`qgis_process --json help`) before the chain starts: a
wrong name stops the run instead of being ignored, and an option may be given by its text
(`--solver fv2`).

## 2a. A list of dams, DamIT set (`damchain run --set damit`, dam_chain 1.6.0)

```
damchain setup
damchain plugins --set damit --selftest
damchain run --set damit --dams LAYER --ids 2801,4031 --out D --dem DEM --cell 5 --solver fv2 --check-only
damchain run --set damit --dams LAYER --ids 2801,4031 --out D --dem DEM --cell 5 --solver fv2
```

- `setup` links `~/local-ai/qgis-batch/damit/profiles/default` to your QGIS profile `damit`
  (the one install-all makes) and turns the DamIT plugins on for `qgis_process`.
- `plugins --set damit --selftest` checks the tools are there and runs `damit_run:check`
  (LISFLOOD-FP on a tiny channel, ANUGA import). DamIT has no self-test tools of its own.
  It says FAIL when any line of the check says PROBLEM (for example, no LISFLOOD-FP found). It
  checks the engine the DamIT Runner is set to use, unless `--lisflood` names another.
- The flood engine: `--lisflood PATH` (before `run`) names a LISFLOOD-FP binary; `--lisflood builtin`,
  `gpu` or `gpu-sgc` picks the DamIT Runner's own engines. Without `--lisflood`, damchain passes no
  engine and the Runner uses its own setting (an engine chosen in QGIS stays chosen). A `--lisflood`
  that is neither a file nor an engine name is refused.
- `run` is the DamIT Runner's batch (`damit_run:batch`): breach runs only, one folder per
  dam under `D`. Classification is not part of it (DamIT Hazard has no batch classifier):
  classify a run with `damit:classify`.
- Checks before anything runs: the dams layer, the DEM and the folder above `D` exist;
  every `--ids` id is in the layer (a `.gpkg` or `.csv` is read; field `--id-field`, else the
  first the Runner itself would pick: NationalID, NIDID, NID_ID, DamID, DAM_ID, ...; that field is
  passed to the Runner as `F_ID`, so both read the same ids); every option name given with
  `--cell`, `--solver`, `--manning`, `--runner-param` or `--param` is a real `damit_run:batch`
  parameter. Option text may be the start of the option (`SCENARIO=sunny`) or its number; text
  that fits two options is refused. `--check-only` runs only these checks.
- Second run: dams that finished are skipped (`SKIP_DONE`); `--redo` runs them again.
  `--workers N` runs dams side by side, but with `--ids` the Runner runs one at a time.
- A GeoPackage with several layers needs `|layername=NAME`; with `|layerid=N` or no name, the
  ids are left for the Runner to match (no F_ID is passed).
- Exit code: 1 when any dam failed (the Runner's "N failed" count), or when `--ids` was given
  and the Runner found fewer of them than asked, even though `qgis_process` itself exits 0. Logs: `D/_chain_logs/damit_batch_<time>.log`.

## 2b. Drafting a run in plain English (`heim run`, heim_run 1.0.0)

```
heim run --set damit --dams LAYER --out D --dem DEM "run 2801 and 4031 at 5 m with FV2"
heim run "rerun 2801 with n 0.04"
heim run --show "run 2801 at 10 m"
```

- Heim only fills fixed fields: dam ids, cell size (metres), solver, Manning's n, redo.
  The code builds the `damchain run` command itself, never the model.
- The sentence must read as one run word, the dams, then settings for all of them:
  "rerun 2801 and 4031 at 5 m with FV2, n 0.04". Every word must be a dam id, a setting, a run
  word (run, rerun, redo, again, overwrite, from scratch, one more time) or a small word (the,
  a, and, with, using, at, on, for, dam, cell, solver, Manning, please ...).
- Refused, not guessed:
  - any other word ("the 30 m high dam", "thanks", "2 at a time", "FV2 crashed last time");
  - with several dams, a run or redo word anywhere but once before them ("run 2801 and
    overwrite 4031", "run 4031 and 2801 again"; write "rerun 2801 and 4031"), a dam named twice,
    or a dam after a setting ("run 2801 at 5 m and 4031"):
    every dam gets the same settings, so run them one at a time;
  - an id that is not a word of its own in your sentence, or not in the dams layer (any case:
    `nd00123` runs as the layer's `ND00123`; when the layer has both `a1` and `A1`, the
    spelling you wrote is the one run);
  - a cell size not written as one ("at 5 m", "5 m cells", "cell 5"), out of 0.5-200 m, or in
    feet, cm or another unit ("5 cells" and "breach at 5 m" are not cell sizes); a Manning's n
    not written next to "n" or "Manning", written with a unit, or out of 0.01-0.25;
  - a dam id read out of a longer one (2801 out of 2801.A or 2801-B), or a shorter dam when
    your words may name a longer one of the layer;
  - a number nothing accounts for ("with the 2 m DEM", a second cell size for another dam);
  - a solver you did not name, or two solvers named (FV-2 counts as FV2);
  - any "not", "except", "instead of", "skip", "don't" ...: it does not work out what is ruled
    out ("run 2801 but not 4031" or "run 2801, no 4031" is refused; write "run 2801"; "dam no.
    2801" with the dot is fine); a range (2801-2805, 2801 to 2805, 5-10 m); a comma in a number
    (5,5 m, 2,801); a number in letters (five metres);
  - a dam whose id is also a word heim run reads ("N", "A", "run"): type damchain for it;
  - anything it cannot set (ANUGA, an engine, a pool, a scenario, PMF, a DEM, all dams, ...),
    whether or not the model noticed it. It says what, and to type the damchain command for it.
  Redo is left out, with a note, unless your words ask for it (rerun, re-run, redo, again,
  overwrite, from scratch, one more time).
- It shows the command and what differs from the defaults, runs nothing until you type
  `y`, then runs `--check-only` first. Your sentence, the model's reply and the command go
  to `D/_chain_logs/heim_run_<time>.txt`. Every reading, refused, stopped, shown or run, is
  also kept in `~/local-ai/reports/heim_run_drafts.log`.
- `--set`, `--dams`, `--out`, `--dem`, `--id-field`, `--dem-units` are remembered per set
  (paths in full) in `~/local-ai/heim_run.json` after a run you confirmed with `y` (not after
  `--show` or a stop). A dam id such as
  `DWR-2801` does not switch the set; the word `dwr` or `damit` on its own does. `heim run "...?"` (ending in
  `?`) is still a question for Heim.

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
- The three scripts are in the DamSafety repository under `tools/batch/` (since 2026-11-13,
  with tests that run each against a stand-in `dam_chain.py`); copies in the older batch zips
  are stale. `--watch` starts `batch_watch.py`, which checks each finished dam by rule and
  writes `BATCH_FINDINGS.md`; it asks the local model nothing unless started with
  `--with-model`. The zip copies started `lumo_watch.py`, whose model no longer exists.
- Their data files (`dams_44.gpkg`, `nd_dams_dugouts.csv`, `nd_dams_dugouts.gpkg`) are not
  in the repository: next to the script, or `BATCH_DATA_DIR`.
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
