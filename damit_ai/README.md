# damit_ai: local AI (Ollama) for the dam suite

Two local assistants that run on your Mac through [Ollama](https://ollama.com). Nothing is sent
off the machine. They are kept apart: separate Ollama models, separate databases, separate commands.

| Folder | Assistant | What it does | Ollama model | Data |
|---|---|---|---|---|
| [`lumo/`](lumo/) | **Lumo**, code triage | Audits plugin code (static pass + model pass), runs the plugin test suites, drives the plugin chain headless (`damchain`), explains failed runs | `lumo` | `~/local-ai/knowledge.db` |
| [`research/`](research/) | **dam-research**, literature | Answers questions from your library of dam-safety / dam-design / flood-hazard publications, citing document and page; deep-research briefs with every quote checked against its page | `dam-research` | `~/DamResearch/research.db` |

> **Both are assistants, not engineers.** A local model misreads code and papers often enough that
> every Lumo finding must be confirmed against the live code with a failing test, and every
> dam-research statement checked against the cited page of the source, before anything is
> changed or relied on in a dam-safety decision.

These are Mac tools (zsh, Ollama.app, conda). They are not QGIS plugins and are not part of any
plugin zip or CI job.

> **Linux and Windows:** one installer per platform sets up **both** assistants —
> [`install-local-ai-linux.sh`](install-local-ai-linux.sh) (openSUSE/Linux) and
> [`install-local-ai-windows.ps1`](install-local-ai-windows.ps1) (Windows 10/11). Same models,
> paths, personas and no-download-then-run policy as the Mac steps below. See
> [`INSTALL-cross-platform.md`](INSTALL-cross-platform.md).

## Install

1. **Lumo (installs Ollama too):**
   ```zsh
   cd damit_ai/lumo
   zsh setup-local-lumo.sh                     # --small for a 16 GB Mac, --model TAG for any model
   source ~/.zshrc
   ```
   Commands: `lumo-start` (Ollama server, in its own tab), `lumo-chat`, `lumo-index`, `lumo-query`,
   `lumo-audit`, `lumo-digest`, `lumo-watch`, `damchain ...` (the watcher's small model: `--watch-model TAG`, default `qwen3:4b`).

   **Repo audit:** `damchain audit --repo ~/path/to/DWR_Plugins` writes one report to
   `~/local-ai/reports/audit_<repo>_<time>.md` (and `.json`). It checks:
   1. release and packaging: runs the repo's own `tools/ci_checks.py`, every plugin's metadata
      and its DamSafety Core dependency, release/install lists that leave a plugin out, and with
      `--zips FOLDER` the built zips (one top folder, versions match the checkout);
   2. security: built-in patterns (TLS checks off, curl into a shell, sudo, unpickling, eval,
      tar extract, plain FTP, hard-coded secrets) plus bandit and ruff when they are installed
      (never installed by the audit);
   3. network: every host the code names, written to `hosts_<repo>.txt` for IT; with
      `--allow-hosts FILE` any host not in the file is flagged;
   4. `--lumo`: the local model reviews the diff against `origin/main`. Its findings are marked
      UNVERIFIED (triage only; confirm each with a failing test);
   5. golden runs: `damchain audit --golden-record --results ~/DamSafety/Dams --ids DWR-2801,DWR-4031`
      saves those dams' run_report.json numbers as a baseline, and after a plugin update rerun the
      dams and use `--golden` instead. Peak flow, flooded acres, depth, velocity, storage and arrival
      time must stay within tolerance, and LISFLOOD-FP volume error must stay at 1 % or under.
   Any HIGH finding gives exit code 1, so the audit can gate a merge. `--only release,security`
   runs a subset.

2. **dam-research (needs Ollama from step 1, or the Ollama app):**
   ```zsh
   cd damit_ai/research
   zsh setup-dam-research.zsh                  # --ocr for scanned PDFs, --big / --small / --model TAG
   source ~/.zshrc
   ```
   Then drop PDFs in `~/DamResearch/library`, or fetch the public ASDSO / FEMA reference set
   (about 49 PDFs) with `python3 fetch_asdso.py` and 58 hazard-classification and dam-design sources
   with `python3 fetch_asdso.py --catalog`, and run `damresearch ingest`. After that:
   `damresearch search | ask | research | chat ...`, also available as `damchain research ...`.
   **Just the library, no pipeline:** `zsh research/download-library.zsh` downloads the catalog
   and ASDSO files only (no install, ingest, OCR or eval) and writes `library-urls.txt` — a
   plain-text list of every source and its web address; `python3 fetch_asdso.py --urls FILE`
   writes that list alone, offline, downloading nothing.
   **First run, in one command:** `zsh first-run.zsh` installs dam-research if needed, downloads
   both reference sets, indexes them, scores two models on 16 questions with known answers
   (`eval_damresearch.py`), and packs the results into `~/Desktop/damresearch-first-run.zip`.
   Full guide, model and memory trade-offs: [`research/INSTALL.md`](research/INSTALL.md).
   Starter reading list: [`research/READING-LIST.md`](research/READING-LIST.md).

## Run watcher: Lumo reviews a DamIT run

Lumo can watch a DamIT Runner run, but the review does not depend on the model. Two parts:

1. **`run_digest.py`, deterministic, no AI.** After each Runner pass it reads what the Runner already wrote (the
   per-pass record in `run_report.json`, the per-pass results, the dam folder, the Hazard report) and checks: `.mass`
   volume balance and NaNs; per-pass edge outflow % and edge depths; sim-time progress and stalls; crest minus
   streambed against the inventory height; datum (NAVD88; 0-300 ft is a local datum); the toe inflow against
   H x (slope + 1) (3:1 default, 5 m minimum, 150 m cap); starting WSE = top of dam (= DWR max pool); no outlet or
   spillway flow; receptors on NoData or dry cells next to wet cells; unscored roads; Hazard drivers that need a person
   (e.g. BNSF KO = 15 trains/day). It prints a 20-40 line summary and machine flags (JSON), and **the code sets the
   verdict, OK / WATCH / PROBLEM, from the flags alone.**
2. **`lumo_watch.py`, Lumo explains.** A 500-1,000 token prompt (the digest and flag titles, plus a pinned system
   prompt of Nick's rules and the real tool names) goes to a **small model** (default `qwen3:4b`; `phi4-mini` is the
   alternative; `LUMO_WATCH_MODEL` or `--model`), through Ollama `/api/chat` with `think:false`, `num_ctx` about 4k and
   `stream:true`. Every streamed piece is saved at once, so a slow box leaves partial text; there is no hard timeout that
   throws it away. Lumo never changes or gates the verdict, and if it does not answer in a few seconds the review stands.
   The **complete flag list** (every flag, receptor ids capped at 10 plus a count) is written by code at the top of
   `lumo_<event>.md`; Lumo's one-line comments go below it, and a footer names any flag it skipped or any flag-like id it
   invented. Timing (`prompt_eval_duration`, `eval_duration`, tokens/s ...) and any `message.thinking` that arrived despite
   `think:false` are kept in the status JSON.
   **Lumo does not compete with LISFLOOD for the CPU.** `LUMO_WATCH_EXPLAIN=idle` (default) queues the explanation until no
   `lisflood` process runs and the pass log has been quiet for `LUMO_WATCH_IDLE_GAP_S` (20 s); at run end it runs at once.
   `end` explains only at the run end, `always` is the old behaviour, `never` writes the digest only. Ollama gets
   `num_thread` 2 (`LUMO_WATCH_NUM_THREAD`, 0 = Ollama's default) and the explain process is niced. A busy shared Ollama is
   waited for (`LUMO_WATCH_FIRST_TOKEN_S`, default 600; 0 = no limit): it ends as status `timeout`, not a partial reply.
   Interactive Q&A (`lumo`, `lumo-chat`) stays on the larger model (30B on a 32 GB+ Mac); both are configurable.

Hooks fire at the end of each pass, on a stall, before Hazard and at the run end, so even a 45 s run is reviewed:

```
lumo-digest RUN_DIR                       # the digest, no AI (add --json for the machine flags)
lumo-watch watch RUN_DIR                  # follow a run; one digest per hook, Lumo explains the newest
lumo-watch event run_end RUN_DIR          # one hook now (pass_end | stall | before_hazard | after_hazard | run_end)
```

Output goes to `~/local-ai/watch/<dam>_<run>/`, never into the run folder. Details, every flag id and the thresholds:
[`lumo/knowledge/WATCHER-DIGEST.md`](lumo/knowledge/WATCHER-DIGEST.md). The real algorithm ids and parameters Lumo cites come
from [`lumo/knowledge/ALGORITHM-HELP-DAMIT.md`](lumo/knowledge/ALGORITHM-HELP-DAMIT.md), generated from the plugin code by
`lumo/tools/dump_damit_algorithm_help.py` in an offscreen QGIS (CI checks it is current).

No `dam.json` in the dam folder? The digest says so (`DAM_RECORD_MISSING`, info), does not raise a datum alarm for elevations in
the NAVD88 range, takes the dam id from the run setup, the handoff or the folder name, and writes a flat
`dam_record_hazard.json` next to the digest for Hazard (never into the dam or run folder; DamIT Hazard 0.2.1 also reads the nested
`dam.json` itself and finds either file when `DAM_JSON` is empty). If PROJ cannot open its database
(`NO_RUN_FILES` with a PROJ error), set `PROJ_DATA` (or `PROJ_LIB`) to the folder holding `proj.db`.

> **GPUs:** stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs. An Intel Arc or Intel iGPU box runs the model on the CPU
> (about 2.5-4 tokens/s for an 8B model in testing), which is why the watcher's explainer defaults to a 4B model and gets a
> short prompt. The digest is the review; the model is commentary.

## Offline folder (nothing downloaded by the installers)

The `damit_ai-offline` download adds `damit_ai/offline/` next to `lumo/` and `research/`:

- `offline/ollama/Ollama-darwin.zip` + `SHA256SUMS`: Ollama for Mac, checked against Ollama's
  published hash. Both installers use it, after checking the hash, instead of downloading Ollama.
- `offline/conda/osx-arm64/` and `offline/conda/osx-64/`: every conda-forge package for the
  `ndresearch` env (Python 3.12, numpy, PyMuPDF, pypdf, ocrmypdf, tesseract, ghostscript), with
  `ndresearch.txt` and `SHA256SUMS`. `setup-dam-research.zsh` builds the env from these files with
  `conda create --offline`, OCR included. It needs conda (the dam-suites package ships Miniforge).

Models still come from Ollama's registry (`ollama pull`, 17 to 24 GB each). They are too big to bundle. If `ollama pull` fails
(for example behind a proxy), the Linux, Mac and Windows installers fall back to the model's Hugging Face GGUF (sha256 checked,
resumable) and `ollama create` it under the same tag. `HF_ENDPOINT` points at a mirror, `LUMO_GGUF_SPEC` overrides the table,
`LUMO_NO_HF_FALLBACK=1` turns the fallback off.

## Models by Mac

| Mac | Lumo | dam-research |
|---|---|---|
| Apple Silicon 48 GB+ | `qwen3:30b-a3b` | `qwen3.6:35b-a3b` (falls back to `qwen3:30b-a3b`) |
| Apple Silicon 32 GB | `qwen3:30b-a3b` | `qwen3:30b-a3b`, sharing Lumo's download. `--model qwen3.6:27b` trades speed for quality |
| Apple Silicon 16-24 GB | `qwen3:14b` | `qwen3:14b` / `qwen3:8b` |
| Intel Mac (CPU only) | `qwen3:30b-a3b` at 32 GB+, else `qwen3:8b` | `qwen3.6:35b-a3b` at 48 GB+, `qwen3:30b-a3b` at 32 GB |

Embeddings: Lumo uses `nomic-embed-text`; dam-research uses `qwen3-embedding:0.6b`.

## Status

- `lumo/knowledge/` is a knowledge pack to index into Lumo's RAG beyond the source code (known behaviours /
  conventions, modeling findings, open-issues snapshot, and helpers to dump Processing-tool help and index
  it); see `lumo/knowledge/README.md` and `index-knowledge.zsh`.
- `lumo/` is setup-local-lumo.sh v3.8 (bundled Ollama and packages, no web downloads) with rag_index 2.4, rag_query 2.2, audit_plugin 1.3,
  suite_check 1.0, dam_chain 1.5 and repo_audit 1.0 (written by the installer itself; v3.8 also copies the run watcher: run_digest 1.2.0 and lumo_watch 1.2.0; `lumo-chat` shows the
  DaMiT banner). dam_chain 1.5 adds DamSafety Core to the DWR set and no longer reports the hidden
  self-test / run-chain tools as MISSING (`qgis_process list` leaves them out). `suite_check.py` and `dam_chain.py` drive the ND and DamSafety plugin sets (QGIS
  profiles `nd` and `damsafety`). The DamIT plugins are not wired into them yet.
- `research/` is damresearch 1.0.4, setup-dam-research 1.1 (bundled Ollama and packages), fetch_asdso 1.3 (download-library.zsh + --urls), eval_damresearch 1.1 and first-run.zsh 1.0.
  fetch_asdso was tested against damsafety.org on 2026-11-09 (48 of 49 files downloaded; the 49th
  is on damtoolbox.org, which the cloud workspace can't reach). The `--catalog` sources were only
  partly tested: the cloud workspace reaches 2 of their 31 sites, so most catalog URLs were checked
  against search listings, not downloaded. The cloud workspace could not download Ollama models, so
  everything was tested with a stand-in Ollama server and real PDFs. Answer quality with the real
  models has not been measured yet; `first-run.zsh` measures it.
