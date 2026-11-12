#!/usr/bin/env zsh
# index-knowledge.zsh — add this knowledge pack (and, if present, the dam-research engine
# docs) to Lumo's RAG database so `lumo` / `rag_query` can cite them.
#
#   ./index-knowledge.zsh                 # index this folder into the default knowledge.db
#   ./index-knowledge.zsh --with-engine-docs   # also index the engine docs if downloaded
#
# rag_index.py lives next to this folder's parent (damit_ai/lumo/tools) or in ~/local-ai.
set -e
HERE=${0:A:h}                         # .../damit_ai/lumo/knowledge
PY=${PYTHON:-python3}

# find rag_index.py
for c in "$HERE/../tools/rag_index.py" "$HOME/local-ai/rag_index.py" "$HOME/local-ai/tools/rag_index.py"; do
  [[ -f "$c" ]] && RAG="$c" && break
done
[[ -z "${RAG:-}" ]] && { echo "rag_index.py not found (looked next to lumo/tools and ~/local-ai)"; exit 1; }

echo "Indexing knowledge pack: $HERE"
$PY "$RAG" -c lumo_knowledge "$HERE"

if [[ "${1:-}" == "--with-engine-docs" ]]; then
  DOCS="${DAMRESEARCH_HOME:-$HOME/DamResearch}/library/references/software"
  if [[ -d "$DOCS" ]]; then
    echo "Indexing engine docs: $DOCS"
    $PY "$RAG" -c engine_docs "$DOCS"
  else
    echo "Engine docs not found at $DOCS — run 'fetch_asdso.py --catalog software' first."
  fi
fi
echo "Done. Ask Lumo, e.g.: lumo \"what does REFINE_NEAR do and why default it off\""
