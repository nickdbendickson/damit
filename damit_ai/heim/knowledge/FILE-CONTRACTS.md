# File contracts

The small state files the suite passes from one stage to the next: **who writes each one,
who reads it, and what does or does not make it stale.** Most "the run used old inputs"
problems are one of these files surviving a change it should not have survived.

Heim: when a run looks as if it ignored a change, name the file below that would carry the
old value and ask to see it.

---

## `<dam folder>/dam.json` (the dam record)

One record per dam, shared by Screening, the Runner and Hazard (`damsuite/dam_record.py`).

```
{"format": "nd_dam_suite/dam_record", "format_version": 1,
 "fields":    {name: value},
 "sources":   {name: {"tool", "version", "when", "note"}},
 "status":    [{"step", "tool", "version", "when", "result": {}}],
 "conflicts": [{"field", "old", "new", "old_source", "new_source", "when", "applied"}],
 "data":      {role: {"path", "source", "when", "count", "note"}}   <- written by Get data
 ... any other top-level key is kept as it was }
```

- **Written by:** `dam_chain.py seed` (from a CSV row; never overwrites an existing file),
  each plugin's own step, and Get data (`ndhazard:getdamdata`, the `data` section).
- **Rules of a write (`set`):** an empty value never overwrites anything. An empty field
  takes the value and records its source. The same value keeps the **first** source. A
  different value from the **same** tool replaces it. A different value from **another** tool,
  or over a value with no recorded source (typed by the engineer), is **not applied**: it goes
  to `conflicts` with `"applied": false`. So a field that "will not update" is usually a
  refused conflict; read `conflicts`.
- **Save** is atomic and last-writer-wins. Do not hold a record open across a long run.
- **A file that is not valid JSON, another format, or a newer `format_version`** raises an
  error on load and is never touched.
- **What does NOT invalidate it:** changing the DEM, the data pack or the data folder. Get
  data treats a role already listed in `data` as done unless `OVERWRITE` is set
  (`damdata.exists`). To refresh inputs: `--getdata-param OVERWRITE=true`.
- **`data` paths** are relative to the dam folder (`data/structures.gpkg|layername=structures`).
  `dem` is a VRT window over the user's own DEM or over cached tiles: no copy, no resampling.
  Moving the dam folder without its `data/` breaks them.
- **Legacy:** with no `dam.json`, a `dam_location.json` is imported for the location only.
  `dam_id` is never guessed from the folder name.

## `<dam folder>/_chain_nd/state.json` (ND chain, per dam)

```
{"status": "done" | "failed", "nd_class": "...", "log": "...", "error": "...", "when": "..."}
```

- **Written by:** `dam_chain.py run --set nd`, after each dam.
- **Read by:** the next `run` (a dam whose status is `done` is skipped: "done earlier";
  `--redo` runs it again), and by the batch scripts, which read it **instead of the exit
  code** because the exit code was wrong before dam_chain 1.5.2.
- **Beside it:** `<dams folder>/Chain_Summary_ND.csv` (one row per dam, status in full:
  `done`, `done (earlier run)`, `failed: get data`, `failed: chain`, `no dam.json`) and
  `<dams folder>/_chain_logs/<time>/<dam>_1_getdamdata.log`, `<dam>_2_suitechain.log`.
- **Stale when:** the dam's inputs changed and `--redo` was not given. `done` records that
  the chain finished, not which inputs it used.

## Review runs: `work/<dam>/status/<stage>.ok` and `work/<dam>/rundam.json`

(`tools/mac/nickreview_mac.py`, `run_nickreview.sh`, DamSafety repo.)

Stages, in order: `prepare`, `structures`, `precheck`, `record`, `rundam`, `hazclass`,
`hazbatch`. A finished stage leaves `status/<stage>.ok` and is skipped next time.

The table that decides what `--redo` re-runs (each stage, and the earlier stages it reads):

| Stage | Reads |
|---|---|
| `prepare` | nothing |
| `structures` | `prepare` |
| `precheck` | `structures` |
| `record` | nothing (only `--data`) |
| `rundam` | `prepare`, `structures`, `record` |
| `hazclass` | `prepare`, `rundam` |
| `hazbatch` | `rundam`, `hazclass` |

- `--redo` re-runs the stages named in `--stages` and every later stage that reads them, and
  first sets their `.ok` files aside as `<stage>.ok.redo_<time>` (kept, not deleted).
- A `--redo` that stopped is finished by the **same command without `--redo`**; repeating the
  `--redo` command redoes everything again.
- **The gap:** `record` is listed as reading nothing, but it passes the DEM into the
  Screening 7b record. A DEM change does not make `record` due. After a terrain change use
  `--redo` (which covers it) or a fresh `--out`.
- `rundam.json` is written by each run just after `precheck`. It records the inputs the
  later stages were given (for a kit dam, which structures file), and is how a later run
  tells whether an old `.ok` was made in prepare mode or from the box preparation.
- For the three dams with a finished box preparation, `prepare` and `structures` do not
  apply unless `--no-kits`.

## `<run folder>/run_progress.json` and `run_report.json` (the Runner)

- **Written by:** the Runner. `run_report.json` (the bounds and CRS of the result) exists
  only once the run has ended. `run_progress.json` is written by the DamIT Runner from 0.3.1
  after every pass: the model CRS, each pass's folder and bounds, `growth_loops_done`, and
  `complete` at the very end, after `run_report.json`. A run from an older Runner has no
  `run_progress.json`.
- **Read by:** the run watcher (see `WATCHER-DIGEST.md`). `complete` is the strongest
  "finished" signal; a quiet log is not.
- **Timing trap:** LISFLOOD-FP writes its Finish line before the Runner has written that
  pass into `run_progress.json` (it is still reading the pass's results). A pass-end hook
  that fires in the gap finds no bounds for the pass; the watcher waits for the record.

## `<run folder>/lisflood/stable_settings.json`

- **Written by:** the Runner, the first time an ACC run exceeds 1 % volume error and is
  re-run damped (theta 0.7, CFL 0.5).
- **Read by:** every later run of that dam, including a resume, which then starts damped.
- **Consequence:** two runs of the same dam can differ in `acc_theta` / `acc_cfl` depending
  on whether this file was there. Deleting it returns the dam to default settings.
  `NDBREACH_STABILITY_RETRY=0` turns the retry off.

## Local AI stores

| Store | What | Stale or empty when |
|---|---|---|
| `~/local-ai/knowledge.db` | Heim's index, one **collection** per source (`heim_knowledge`, `engine_docs`, the repos, `added`) | a collection is rebuilt whole, through a hidden stage, so a failed run leaves the old one. An empty collection is **not listed and not an error**: a query against it just returns nothing. |
| `~/local-ai/added/` | files given to `heim-add` (copies) | the collection `added` is rebuilt from this folder each time |
| `~/Vor/vor.db` | Vor's index (documents, passages, vectors) | bound to one embedding model; a different `VOR_EMBED` is refused, not mixed |
| `~/Vor/library/` | Vor's documents; `references/<group>/` from the catalog, `asdso/`, `added/` | `vor ingest` reads only new or changed files; `--prune` drops entries whose file is gone |
| `~/Vor/library/references/<group>/sources.csv` | what each catalog entry did on the last fetch, including "get by hand" | rewritten on every fetch |

Vor's home is the folder that **holds the index**: `VOR_HOME` if set, else `~/Vor` or the
pre-rename `~/DamResearch`, whichever has `vor.db` / `research.db`.

---

_Curated. Update when a file's writer, reader or invalidation rule changes. Keep machine
names, credentials and file-server links out._
