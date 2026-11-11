# Lumo knowledge pack

Extra data for **Lumo** (the local code-triage AI) beyond the suite source code. Lumo's
RAG already indexes the repos' code and markdown; this folder adds the knowledge Lumo
*can't* get from the source:

| File | What it is |
|------|-----------|
| `KNOWN-BEHAVIOURS.md` | Standing conventions, durable known behaviours/bugs, cross-plugin hand-off contracts, and Processing-provider gotchas. |
| `MODELING-FINDINGS.md` | Empirical run findings (grid convergence, solver comparison, velocity sensitivity, mass balance) — the "why" behind results-changing fixes. |
| `OPEN-ISSUES.md` | Snapshot of open GitHub issues (regenerate with `refresh-open-issues.zsh`). |
| `ALGORITHM-HELP.md` | Every Processing tool's parameters/help (generate on a QGIS box with `dump-algorithm-help.zsh`). |

The per-plugin fix log stays where it already is — each plugin's `metadata.txt` `changelog=`
(and `docs/CHANGELOG.md`) — which Lumo already indexes. This pack does not duplicate it.

## Index it into Lumo

```
cd damit_ai/lumo/knowledge
./index-knowledge.zsh                    # -> collection "lumo_knowledge"
./index-knowledge.zsh --with-engine-docs # also the dam-research engine docs, if downloaded
```

`rag_query` searches `all` collections by default, so once indexed Lumo cites these
automatically. Ask e.g. `lumo "what does REFINE_NEAR do and why is it off by default"` or
`lumo "has the 2801 over-spread been attributed to the solver or the terrain"`.

## Keep it current

- `refresh-open-issues.zsh [owner/repo ...]` — re-snapshot open issues (needs `gh`).
- `dump-algorithm-help.zsh [profile]` — re-dump tool help (run on a machine with the
  plugins installed in a QGIS profile).
- Edit the two curated `.md` files by hand when a decision or durable behaviour changes.
  Keep machine names, credentials and file-server links out of them.
