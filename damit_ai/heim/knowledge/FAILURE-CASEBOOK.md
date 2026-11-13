# Failure casebook

Real failures of this suite, each as **what was seen**, **what it was**, **how to tell**
and **the fix**. Heim: when a log or a symptom matches a case, name the case, say how to
confirm it, and ask for the file that would settle it. A match is a lead, not a verdict;
the deterministic checks set the verdict.

Every case here happened. None is hypothetical. Cases about the plugins' numerics are in
`MODELING-FINDINGS.md`; the watcher's flags are in `WATCHER-DIGEST.md`.

---

## A. The run "succeeded" and the result is wrong

### A1. Batch reports `ok` for dams that failed
- **Seen:** a batch summary says every dam is ok; the per-dam folders hold no results, or
  `Chain_Summary_ND.csv` says `failed: chain`.
- **Was:** `dam_chain.py run --set nd` exited 0 whatever happened. It printed FAILED, wrote
  `failed` into `<dam>/_chain_nd/state.json`, then returned without an exit code. The
  DamSafety path (`--set dwr`) always exited 1 on failure, so only the ND path lied.
- **Tell:** the version on the first line of the installed `~/local-ai/dam_chain.py` is below
  1.5.2. Read `state.json`, not the exit code.
- **Fix:** dam_chain 1.5.2. A dam counts as failed when its status does not start with
  `done`; `done (earlier run)` is not a failure; `--dry-run` still exits 0.

### A2. The installed tool is not the tool that was fixed
- **Seen:** a fix is merged, the behaviour on the Mac does not change.
- **Was:** `setup-local-heim.sh` carries six tools **inside itself** as quoted heredocs
  (`rag_index.py`, `rag_query.py`, `audit_plugin.py`, `suite_check.py`, `dam_chain.py`,
  `repo_audit.py`) and writes them to `~/local-ai/`. A fix made only in
  `damit_ai/heim/tools/` never reaches an installed copy.
- **Tell:** compare the version line at the top of `~/local-ai/<tool>` with the repo's.
- **Fix:** change both; `tests/test_dam_chain_exit.py` compares all six. Re-run the
  installer (or copy the tool over) to update an installed copy.

### A3. Flood stops at a straight line
- **Seen:** the inundation ends on a straight north-south or east-west edge.
- **Was:** one of two things. A VRT with a missing source tile (read as nodata, treated as
  high ground), or the model domain edge. See "Terrain swaps" in `KNOWN-BEHAVIOURS.md`.
- **Tell:** the line coincides with a tile boundary of the DEM (missing tile) or with the
  run's bounds in `run_progress.json` (domain edge; then look for the `extent_is_minimum`
  flag and the edge-outflow share).
- **Fix:** restore the tile, or let the domain grow; do not cap a run that is still spreading.

### A4. Run modelled the old terrain after the DEM was changed
- **Seen:** results identical to the previous run although a new DEM was supplied.
- **Was:** Get data kept the DEM already recorded in `dam.json` (`damdata.exists` is true
  unless `OVERWRITE`), or `record.ok` survived a DEM change.
- **Tell:** `dam.json` `data.dem.path` and `when` predate the change; the log says
  `get data: ok` within a second or two.
- **Fix:** `--getdata-param OVERWRITE=true`, and `--redo` for the review runs.

### A5. Velocity is zero near the dam
- **Seen:** maximum velocity 0.0 in the fine box around the dam; depth looks right.
- **Was:** Runner 3.8.0 to 3.11.1 with the near-dam refine on. LISFLOOD-FP 8.1's FV1 writes
  no `.maxVc`, the reader set velocity to 0, and the merge zeroed the refine box.
- **Tell:** Runner version; `REFINE_NEAR=true`; no `.maxVc` in the refine pass folder.
- **Fix:** Runner 3.12.0 (refine off by default; with it on, the ACC velocity is kept and the
  report says `velocity_kept_acc`). Re-run older results made with the refine on.

### A6. Mass balance error of hundreds of percent
- **Seen:** report `max_volume_error_pct` far above 1 (one dam: about +567 %); flood area
  several times a clean run; water level checkerboards by metres in a deep pond.
- **Was:** the ACC solver with its defaults (theta 1.0, CFL 0.7) creating water on a 10 m
  grid. Not the dam's data and not the crest burn.
- **Tell:** the pass's `.mass` file Verror grows after the hydrograph has ended, or while it
  is still going in on a small fast breach.
- **Fix:** automatic from ND Runner 3.28.1 / DamSafety Runner 3.15.1: an ACC run over 1 %
  is re-run with theta 0.7 and CFL 0.5, and later runs of the dam keep those settings
  (marker `lisflood/stable_settings.json`). theta 0.7 alone does not fix the fast-breach case.

### A7. A real height error reported as WATCH
- **Seen:** a tall dam whose crest-minus-streambed is several feet off the inventory height
  gets `HEIGHT_MISMATCH` at WATCH.
- **Was:** the severity test used `max(5 ft, 15 %)`, so both thresholds had to be crossed.
  The rule is over 5 ft **or** over 15 %. A 50 ft dam off by 6 ft is a PROBLEM.
- **Fix:** run_digest uses `min(...)`. If a digest predates that, re-run it.

---

## B. Nothing is wrong, it only looks stuck or broken

### B1. `PASS_UNFINISHED` at 99 %
- **Was:** LISFLOOD-FP writes `.mass` every `massint` seconds, so a clean pass can end up to
  one interval short of `sim_time` (DWR-2801 pass 1: 24,309 s of 24,561 s, `massint` 300).
- **Tell:** the pass log has a Finish line, or a later pass exists.
- **Fix:** run_digest 1.3.1 does not raise the flag in that case.

### B2. First run shows nothing for most of an hour
- **Was:** two separate things. A model of about 17 to 24 GB being pulled mid-run, whose
  progress bar is drawn with carriage returns that `tee` swallows; and Python block-buffering
  its output because stdout was a pipe.
- **Tell:** `ollama ps` lists a model: it is answering. Nothing listed and
  `du -sh ~/.ollama/models` growing: it is still pulling.
- **Fix:** `PYTHONUNBUFFERED=1` on the eval call and a size announcement before the pull.
  Any long Python step under a `tee`-logging script needs the same.

### B3. Two-model comparison timings that mean nothing
- **Was:** the two models of a tier do not fit in memory together, and Ollama keeps the
  first loaded for five minutes while the second loads. The second is timed while swapping.
- **Fix:** `ollama stop <model>` between them. Compare answers, not minutes, from older runs.

### B4. "QGIS does not import in env ndqgis" on a Mac whose env is complete
- **Was:** the check ran the env's `python` directly. On macOS the QGIS libraries resolve
  only with the env **activated**; on Linux the direct call works.
- **Tell:** `mamba run -n ndqgis python -c "import qgis.core"` succeeds.
- **Fix:** every env check goes through `mamba run -n <env> python`. Because the installer
  stopped there, the plugins were never installed: a missing-plugins report after this error
  is the same failure, not a second one.

### B5. A tool is "missing" from `qgis_process list`
- **Was:** algorithms flagged hidden from the toolbox are omitted from `list`.
- **Tell:** `qgis_process help <id>` works.
- **Rule:** check with `help <id>` before reporting a tool as not installed.

---

## C. Installers and scripts

### C1. A script dies with no message under `set -e`
- **Was:** a `[ -f FILE ] && command` as the **last command of a loop body whose loop is
  the last stage of a pipeline**: `... | while read ...; do [ -f "$f" ] && echo ...; done`.
  The list's status becomes the loop's, the loop's becomes the pipeline's, and a pipeline
  is not exempt from `set -e`.
- **Not it:** a bare `[ -f X ] && cmd` statement, or one at the end of a plain loop. Those
  are exempt. Test the suspect shape in a four-line script before naming it the cause.
- **Fix:** `if ...; then ...; fi`.

### C2. `--model TAG` typed literally
- **Was:** a printed hint ended in the placeholder `--model TAG`; it was run as written and
  Ollama tried to pull a model called TAG ("pull model manifest: file does not exist").
- **Fix:** the hint names a real tag, and the setup script refuses the placeholder words.

### C3. Reports from an old run mixed into a new summary
- **Was:** a `cp reports/eval_*` copied every report ever written, so a stale "0 / 16"
  (all ERROR, from an older Ollama) sat beside the same model's real score from that day.
- **Fix:** copy only files newer than a marker made when the step started.

### C4. Engine documents sent to an OCR queue they did not need
- **Was:** the indexer ran under a Python with no PDF library. Every PDF yielded nothing and
  each was reported as "no text layer, needs OCR".
- **Tell:** the first line of the run: `PDF extraction backends: NONE`.
- **Fix:** run the indexer through its alias (`heim-index`), which uses the environment that
  has PyMuPDF. The message now says "skipped, no PDF library" when that is the cause.

---

## D. The local AIs themselves

### D1. Every eval question skipped: "0/0 passed (16 skipped, source not indexed)"
- **Was:** the Mac installer wrote the indexer and its alias but never ran it, so the
  knowledge collection was empty. The Linux and Windows installers did index it.
- **Tell:** `heim-index --list-collections` does not list `heim_knowledge`. An empty
  collection is simply not listed; it is not an error.
- **Fix:** the installer indexes the pack and verifies the collection is not empty. By hand:
  `heim-index -c heim_knowledge <package>/damit_ai/heim/knowledge`.

### D2. Heim answers from the persona alone after a rename
- **Was:** the collection kept its old name (`pierre_knowledge`, `lumo_knowledge`) while the
  tools asked for `heim_knowledge`. Querying an empty collection is not an error, so nothing
  said the documents were not being read.
- **Fix:** `rag_index.py` renames the old collection in place on first use.

### D3. Vor finds no passages although the library is full
- **Was, case 1:** a second, empty library. Something created `~/Vor` before the installer
  had moved the pre-rename `~/DamResearch` across, and the installer then treated the rename
  as done. The indexed library was left under the old name.
- **Tell:** `vor list` shows no documents while `~/DamResearch/research.db` exists.
- **Fix:** Vor uses the folder that holds the index; the installers move it or keep it.
- **Was, case 2:** the question named the publication ("... in FEMA P-946"). The name only
  adds search words that match every FEMA document, and `ask` read at most three passages
  per document.
- **Fix:** `--doc P-946` (filters before ranking and lifts the per-document cap).

### D4. An eval question that no model can pass
- **Seen:** `findings` 1 or more, `rejected` 0, `grounded` empty.
- **Was:** the question's expected page window was wrong (the text is on p.8, the test
  expected pp.10 to 13). Both models quoted the right sentence and the checker verified it.
- **Rule:** verified findings with nothing rejected and nothing grounded means the test's
  page window is wrong, not the model.

### D5. A model that says the library has nothing while holding the answer
- **Was:** a fast mixture-of-experts model returned the same "the library returned no
  passage" sentence on 7 of 16 questions whose page was in its own top 8.
- **Rule:** retrieval was identical between the two models compared, so the difference was
  entirely after retrieval. Do not change retrieval or embeddings to fix an answer-stage gap.

### D6. A local model used as a live run watcher
- **Was:** on a CPU-only machine it took over 13 minutes to read a 10k-token prompt and timed
  out before any verdict; a 45 s run was long over. In direct questions it got the sunny-day
  rule backwards and invented tool names.
- **Rule:** code does the checking and sets OK / WATCH / PROBLEM. Heim explains a short
  digest, after the fact, and never gates anything.

---

_Add a case when a failure cost more than an hour to diagnose and would be recognised
again from its log. Keep machine names, credentials and file-server links out._
