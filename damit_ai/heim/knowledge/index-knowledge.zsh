#!/usr/bin/env zsh
# index-knowledge.zsh — add this knowledge pack (and, if present, the vor engine
# docs) to Heim's RAG database so `heim` / `rag_query` can cite them.
#
#   ./index-knowledge.zsh                 # index this folder into the default knowledge.db
#   ./index-knowledge.zsh --with-engine-docs   # also index the engine docs if downloaded
#
# rag_index.py lives next to this folder's parent (damit_ai/heim/tools) or in ~/local-ai.
set -e
HERE=${0:A:h}                         # .../damit_ai/heim/knowledge
PY=${PYTHON:-python3}

# find rag_index.py.
# These used to be `[[ -f "$c" ]] && RAG="$c" && break`: under `set -e` a miss on the
# FIRST candidate made the loop body return non-zero and killed the script with no
# message, even though a later candidate existed.
for c in "$HERE/../tools/rag_index.py" "$HOME/local-ai/rag_index.py" "$HOME/local-ai/tools/rag_index.py"; do
  if [[ -f "$c" ]]; then
    RAG="$c"
    break
  fi
done
if [[ -z "${RAG:-}" ]]; then
  echo "rag_index.py not found (looked next to heim/tools and ~/local-ai)"
  exit 1
fi

echo "Indexing knowledge pack: $HERE"
$PY "$RAG" -c heim_knowledge "$HERE"

if [[ "${1:-}" == "--with-engine-docs" ]]; then
  # the library may still be under its pre-rename name when Vor's installer has not been re-run
  DOCS="${VOR_HOME:-$HOME/Vor}/library/references/software"
  for d in "${VOR_HOME:-$HOME/Vor}" "${DAMRESEARCH_HOME:-$HOME/DamResearch}"; do
    if [[ -d "$d/library/references/software" ]]; then
      DOCS="$d/library/references/software"
      break
    fi
  done
  if [[ -d "$DOCS" ]]; then
    echo "Indexing engine docs: $DOCS"
    $PY "$RAG" -c engine_docs "$DOCS"
  else
    echo "Engine docs not found at $DOCS — run 'fetch_asdso.py --catalog software' first."
  fi
fi
echo "Done. Ask Heim, e.g.: heim \"what does REFINE_NEAR do and why default it off\""
