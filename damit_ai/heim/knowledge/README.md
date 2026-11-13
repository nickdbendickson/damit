# Heim knowledge pack

Extra data for **Heim** (the local code-triage AI) beyond the suite source code. Heim's
RAG already indexes the repos' code and markdown; this folder adds the knowledge Heim
*can't* get from the source:

| File | What it is |
|------|-----------|
| `KNOWN-BEHAVIOURS.md` | Standing conventions, durable known behaviours/bugs, cross-plugin hand-off contracts, and Processing-provider gotchas. |
| `MODELING-FINDINGS.md` | Empirical run findings (grid convergence, solver comparison, velocity sensitivity, mass balance) — the "why" behind results-changing fixes. |
| `OPEN-ISSUES.md` | Snapshot of open GitHub issues (regenerate with `refresh-open-issues.zsh`). |
| `ALGORITHM-HELP-DAMIT.md` | The REAL DamIT Processing algorithm ids, parameters and defaults, generated from the plugin code by `tools/dump_damit_algorithm_help.py` (offscreen QGIS; CI checks it is current). Heim cites ids from here. |
| `WATCHER-DIGEST.md` | The run watcher: what the deterministic digest checks, every flag id, the hooks, and who decides the verdict (code, never Heim). |
| `ALGORITHM-HELP.md` | Every Processing tool's parameters/help (generate on a QGIS box with `dump-algorithm-help.zsh`). |

There is also a **code-triage eval** in [`../eval/questions.json`](../eval/questions.json), run with
[`../tools/eval_heim.py`](../tools/eval_heim.py): 10 questions whose answers live in this pack, scored
against a model so you can measure Heim's triage quality and catch regressions when you change models
(`python3 eval_heim.py --model <tag>`). It mirrors the Vor eval.

The per-plugin fix log stays where it already is — each plugin's `metadata.txt` `changelog=`
(and `docs/CHANGELOG.md`) — which Heim already indexes. This pack does not duplicate it.

## Index it into Heim

```
cd damit_ai/heim/knowledge
./index-knowledge.zsh                    # -> collection "heim_knowledge"
./index-knowledge.zsh --with-engine-docs # also the Vor engine docs, if downloaded
```

`rag_query` searches `all` collections by default, so once indexed Heim cites these
automatically. Ask e.g. `heim "what does REFINE_NEAR do and why is it off by default"` or
`heim "has the 2801 over-spread been attributed to the solver or the terrain"`.

## Keep it current

- `python3 ../tools/dump_damit_algorithm_help.py` (QGIS Python, `QT_QPA_PLATFORM=offscreen`) regenerates
  `ALGORITHM-HELP-DAMIT.md`; add `--check` to see whether it is stale. Run it whenever an algorithm or parameter changes.

- `refresh-open-issues.zsh [owner/repo ...]` — re-snapshot open issues (needs `gh`).
- `dump-algorithm-help.zsh [profile]` — re-dump tool help (run on a machine with the
  plugins installed in a QGIS profile).
- Edit the two curated `.md` files by hand when a decision or durable behaviour changes.
  Keep machine names, credentials and file-server links out of them.
