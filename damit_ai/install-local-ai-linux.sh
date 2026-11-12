#!/usr/bin/env bash
# ============================================================================
# install-local-ai-linux.sh — install BOTH local AIs (Pierre code-triage +
# dam-research literature) on Linux, tested for openSUSE (Tumbleweed/Leap) and
# usable on any x86_64 Linux. The Linux counterpart of damit_ai/pierre/setup-local-pierre.sh
# and research/setup-dam-research.zsh.
#
#   ./install-local-ai-linux.sh                 # both AIs
#   ./install-local-ai-linux.sh --no-pierre        # dam-research only
#   ./install-local-ai-linux.sh --no-research     # Pierre only
#   ./install-local-ai-linux.sh --ocr             # dam-research with OCR (ocrmypdf + tesseract)
#   ./install-local-ai-linux.sh --small           # force the small chat model
#   ./install-local-ai-linux.sh --no-index        # skip indexing the knowledge pack / engine docs
#   ./install-local-ai-linux.sh --watch-model=TAG # the SMALL run-watcher explainer (default qwen3:4b; phi4-mini is the
#                                                 # alternative); --no-watch-model skips pulling it. pierre (Q&A) keeps the big model.
#
# If `ollama pull` fails (a proxy that breaks the registry redirect), the model's official GGUF is fetched from
# Hugging Face (https_proxy / HF_ENDPOINT honoured), sha256-checked and loaded with `ollama create` under the
# same tag (qwen3 4b/8b/14b/30b-a3b, phi4-mini, nomic-embed-text). PIERRE_NO_HF_FALLBACK=1 turns that off.
#
# By default, when Pierre is installed the Pierre knowledge pack (pierre/knowledge) and, if present,
# the dam-research engine docs are indexed into the RAG so Pierre comes up already knowing the
# suite's behaviours, findings and tool contracts. Pass --no-index to skip that.
#
# Policy (same as the Mac installer): NO download-then-run. Ollama and Miniforge
# are reused if already installed; otherwise you place the file yourself (a
# bundled copy under damit_ai/offline/, or a file in ~/Downloads) and the script
# verifies and uses it. Nothing is piped from curl into a shell. No sudo is used;
# a note at the end lists the optional system libraries for a GUI QGIS.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_AI="$HOME/local-ai"
MODELS_DIR="$LOCAL_AI/models"
PIERRE_TOOLS="$LOCAL_AI"                      # pierre tools live directly in ~/local-ai (match the Mac layout)
RESEARCH_DIR="$LOCAL_AI/research"
RHOME="${DAMRESEARCH_HOME:-$HOME/DamResearch}"
DOWNLOADS="${XDG_DOWNLOAD_DIR:-$HOME/Downloads}"
OFFLINE="$HERE/offline"
RC="$HOME/.bashrc"; [[ -n "${ZSH_VERSION:-}" || -f "$HOME/.zshrc" ]] && RC="$HOME/.zshrc"
PIERRE_ENV="ndpierre"; RESEARCH_ENV="ndresearch"
OLLAMA_HOST_URL="http://127.0.0.1:11434"
DO_PIERRE=1; DO_RESEARCH=1; OCR=0; SMALL=0; INDEX_KN=1
WATCH_MODEL="${PIERRE_WATCH_MODEL:-qwen3:4b}"

for a in "$@"; do case "$a" in
  --no-pierre) DO_PIERRE=0 ;;
  --no-research) DO_RESEARCH=0 ;;
  --ocr) OCR=1 ;;
  --small) SMALL=1 ;;
  --index-knowledge) INDEX_KN=1 ;;      # on by default; kept for compatibility
  --no-index) INDEX_KN=0 ;;
  --watch-model=*) WATCH_MODEL="${a#*=}" ;;
  --no-watch-model) WATCH_MODEL="" ;;
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $a" >&2; exit 1 ;;
esac; done

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok(){ printf '  \033[32mok\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mwarn\033[0m %s\n' "$*" >&2; }
die(){ printf '  \033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }
sha(){ sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

# ---------------------------------------------------------------------------
say "Step 1 — Directory skeleton"
mkdir -p "$LOCAL_AI" "$MODELS_DIR" "$RESEARCH_DIR" "$RHOME/library" "$RHOME/reports"
ok "$LOCAL_AI, $RHOME"

# ---------------------------------------------------------------------------
say "Step 2 — Ollama (no sudo, no download-then-run)"
OLLAMA=""
for c in "$(command -v ollama 2>/dev/null)" "$LOCAL_AI/ollama/bin/ollama" "$HOME/.local/bin/ollama"; do
  [[ -n "$c" && -x "$c" ]] && { OLLAMA="$c"; break; }
done
if [[ -z "$OLLAMA" ]]; then
  # Ollama ships ollama-linux-amd64.tar.zst in current releases (older ones: .tgz); either is accepted
  TGZ=""
  for cand in "$OFFLINE/ollama/ollama-linux-amd64.tar.zst" "$OFFLINE/ollama/ollama-linux-amd64.tgz" \
              "$DOWNLOADS/ollama-linux-amd64.tar.zst" "$DOWNLOADS/ollama-linux-amd64.tgz"; do
    [[ -f "$cand" ]] && { TGZ="$cand"; break; }
  done
  if [[ -n "$TGZ" && "$TGZ" == "$OFFLINE"/* && -f "$OFFLINE/ollama/SHA256SUMS" ]]; then
    want=$(awk -v n="$(basename "$TGZ")" '{f=$2; sub(/^.*\//,"",f)} f==n {print $1}' "$OFFLINE/ollama/SHA256SUMS")
    [[ -n "$want" && "$want" == "$(sha "$TGZ")" ]] || { warn "bundled Ollama archive failed its SHA256SUMS; ignoring"; TGZ=""; }
  fi
  if [[ -z "$TGZ" ]]; then
    cat >&2 <<EOF
  No Ollama found, and no local tarball to install from.
  Download it yourself (no root needed) and re-run this script:
    1) Open https://ollama.com/download/linux  (or the GitHub releases page)
    2) Save 'ollama-linux-amd64.tar.zst' (or an older '.tgz') into $DOWNLOADS
  (Or install Ollama however you prefer so 'ollama' is on your PATH.)
EOF
    die "Ollama not available"
  fi
  mkdir -p "$LOCAL_AI/ollama"
  case "$TGZ" in
    *.zst) tar --zstd -xf "$TGZ" -C "$LOCAL_AI/ollama" 2>/dev/null \
             || { command -v zstd >/dev/null && zstd -dc "$TGZ" | tar -xf - -C "$LOCAL_AI/ollama"; } \
             || die "could not extract $TGZ (needs zstd: it is in every openSUSE install; Debian/Ubuntu: zstd package)" ;;
    *) tar -xzf "$TGZ" -C "$LOCAL_AI/ollama" || die "could not extract $TGZ" ;;
  esac
  OLLAMA="$LOCAL_AI/ollama/bin/ollama"
  [[ -x "$OLLAMA" ]] || OLLAMA="$(find "$LOCAL_AI/ollama" -name ollama -type f -perm -u+x | head -1)"
  [[ -x "$OLLAMA" ]] || die "ollama binary not found after extracting"
  ok "Ollama extracted to $LOCAL_AI/ollama"
else
  ok "Ollama already installed ($OLLAMA)"
fi
export OLLAMA_MODELS="$MODELS_DIR" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0

# start the server if it isn't answering
if ! curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1; then
  ok "starting ollama serve (log: $LOCAL_AI/ollama-serve.log)"
  nohup env OLLAMA_MODELS="$MODELS_DIR" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 \
    "$OLLAMA" serve >"$LOCAL_AI/ollama-serve.log" 2>&1 &
  for i in $(seq 1 30); do curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 && break; sleep 1; done
fi
curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 || die "ollama server did not come up (see $LOCAL_AI/ollama-serve.log)"
ok "server up on $OLLAMA_HOST_URL"

# seed models from a pre-downloaded offline bundle (download-all-linux.sh), so pulls are skipped
if [[ -d "$OFFLINE/models/manifests" && ! -d "$MODELS_DIR/manifests" ]]; then
  cp -a "$OFFLINE/models/." "$MODELS_DIR/" 2>/dev/null && ok "seeded models from offline/models (no download needed)" || warn "could not seed offline models"
fi

# ---------------------------------------------------------------------------
say "Step 3 — conda (reuse an existing install; venv fallback)"
CONDA=""
for c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null)" "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/miniconda/bin/conda"; do
  [[ -n "$c" && -x "$c" ]] && { CONDA="$c"; break; }
done
[[ -n "$CONDA" ]] && ok "conda: $CONDA" || warn "no conda found — will use python3 venvs (need python3 + python3-venv)"

make_env(){  # name  "pkgspec"   -> echoes the python path
  local name="$1" spec="$2" envpath=""
  if [[ -n "$CONDA" ]]; then
    envpath="$("$CONDA" env list | awk -v n="$name" '$1==n{print $NF}')"
    if [[ -z "$envpath" ]]; then
      "$CONDA" create -y -n "$name" -c conda-forge --override-channels $spec >/dev/null 2>&1 \
        || { warn "conda create $name failed — falling back to a venv"; CONDA=""; }
    fi
    [[ -n "$CONDA" ]] && envpath="$("$CONDA" env list | awk -v n="$name" '$1==n{print $NF}')"
    [[ -n "$envpath" ]] && { echo "$envpath/bin/python"; return; }
  fi
  command -v python3 >/dev/null || die "no conda and no python3"
  python3 -m venv "$LOCAL_AI/$name-venv" >/dev/null 2>&1 || die "venv $name failed"
  # pip the pure-python deps (PyMuPDF/pypdf/numpy) — no system packages
  "$LOCAL_AI/$name-venv/bin/pip" -q install --upgrade pip >/dev/null 2>&1 || true
  "$LOCAL_AI/$name-venv/bin/pip" -q install pymupdf pypdf numpy >/dev/null 2>&1 || warn "pip deps failed (PDFs may be skipped)"
  echo "$LOCAL_AI/$name-venv/bin/python"
}

# ---------------------------------------------------------------------------
say "Step 4 — RAM + chat model"
RAM_GB=$(awk '/MemTotal/{printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 16)
if [[ "$SMALL" == 1 ]]; then CHAT_MODEL="qwen3:14b"; (( RAM_GB < 16 )) && CHAT_MODEL="qwen3:8b"
elif (( RAM_GB >= 32 )); then CHAT_MODEL="qwen3:30b-a3b"
elif (( RAM_GB >= 16 )); then CHAT_MODEL="qwen3:14b"
else CHAT_MODEL="qwen3:8b"; fi
NUM_CTX=16384; (( RAM_GB < 32 )) && NUM_CTX=12288
ok "RAM ${RAM_GB} GB -> chat model $CHAT_MODEL (num_ctx $NUM_CTX)"
# >>> hf_gguf_fallback (the same block is in install-local-ai-linux.sh and pierre/setup-local-pierre.sh; a test keeps them equal)
# `ollama pull` can fail behind a proxy (the registry's manifest / redirect never completes). Fallback: fetch the model's
# official GGUF from Hugging Face (curl honours https_proxy; HF_ENDPOINT can point at a mirror), check its sha256, write a
# Modelfile and `ollama create` the SAME tag, then delete the GGUF (Ollama keeps its own copy).
# PIERRE_GGUF_SPEC="repo file sha256 bytes" overrides the table (another quant, or a mirror's file); PIERRE_GGUF_DIR = scratch dir.
hf_gguf_spec(){
  if [[ -n "${PIERRE_GGUF_SPEC:-}" ]]; then echo "$PIERRE_GGUF_SPEC"; return 0; fi
  case "$1" in
    qwen3:4b)       echo "Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf 7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5 2497280256" ;;
    qwen3:8b)       echo "Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785 5027783488" ;;
    qwen3:14b)      echo "Qwen/Qwen3-14B-GGUF Qwen3-14B-Q4_K_M.gguf 500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0 9001752960" ;;
    qwen3:30b-a3b)  echo "Qwen/Qwen3-30B-A3B-GGUF Qwen3-30B-A3B-Q4_K_M.gguf 0d003f6662faee786ed5da3e31b29c978de5ae5d275c8794c606a7f3c01aa8f5 18556685824" ;;
    phi4-mini|phi4-mini:*) echo "unsloth/Phi-4-mini-instruct-GGUF Phi-4-mini-instruct-Q4_K_M.gguf 88c00229914083cd112853aab84ed51b87bdf6b9ce42f532d8c85c7c63b1730a 2491874272" ;;
    nomic-embed-text|nomic-embed-text:*) echo "nomic-ai/nomic-embed-text-v1.5-GGUF nomic-embed-text-v1.5.f16.gguf f7af6f66802f4df86eda10fe9bbcfc75c39562bed48ef6ace719a251cf1c2fdb 274290560" ;;
    *) return 1 ;;
  esac
}
hf_gguf_create(){
  local tag="$1" spec repo file sha size dir url got avail have
  spec="$(hf_gguf_spec "$tag")" || { warn "no Hugging Face GGUF is known for $tag (set PIERRE_GGUF_SPEC=\"repo file sha256 bytes\")"; return 1; }
  read -r repo file sha size <<< "$spec"
  if [[ "${PIERRE_NO_HF_FALLBACK:-0}" == 1 ]]; then warn "PIERRE_NO_HF_FALLBACK=1: not downloading $tag from Hugging Face"; return 1; fi
  command -v curl >/dev/null 2>&1 || { warn "curl not found: cannot fetch the GGUF for $tag"; return 1; }
  dir="${PIERRE_GGUF_DIR:-${TMPDIR:-/tmp}/pierre-gguf}"; mkdir -p "$dir" || return 1
  avail=$(df -Pk "$dir" 2>/dev/null | awk 'NR==2{print $4*1024}')
  if [[ -n "$avail" ]] && (( avail < size + size / 10 )); then
    warn "not enough free space in $dir for the $((size / 1048576)) MB GGUF (set PIERRE_GGUF_DIR to a bigger disk)"; return 1
  fi
  url="${HF_ENDPOINT:-https://huggingface.co}/$repo/resolve/main/$file"
  have=$(wc -c < "$dir/$file" 2>/dev/null || echo 0); have="${have//[[:space:]]/}"
  if [[ "$have" != "$size" ]]; then
    ok "ollama pull failed: downloading $file from Hugging Face ($((size / 1048576)) MB)"
    curl -fL -C - --retry 3 --retry-delay 5 -o "$dir/$file" "$url" || { warn "download failed: $url"; return 1; }
  fi
  got="$( (sha256sum "$dir/$file" 2>/dev/null || shasum -a 256 "$dir/$file") | awk '{print $1}')"
  if [[ "$got" != "$sha" ]]; then warn "sha256 of $file is $got, expected $sha: not used"; rm -f "$dir/$file"; return 1; fi
  { printf 'FROM %s\n' "$dir/$file"
    [[ "$tag" == nomic* ]] || printf 'PARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER top_p 0.9\n'; } > "$dir/Modelfile.$$"
  if ! "$OLLAMA" create "$tag" -f "$dir/Modelfile.$$" >/dev/null; then
    warn "ollama create $tag failed"; rm -f "$dir/Modelfile.$$"; return 1
  fi
  rm -f "$dir/$file" "$dir/Modelfile.$$"
  ok "created $tag from the Hugging Face GGUF"
}
# <<< hf_gguf_fallback
pull(){ "$OLLAMA" list 2>/dev/null | grep -q "^$1" || { ok "pulling $1 (first time, large)"; "$OLLAMA" pull "$1" || hf_gguf_create "$1" || die "pull failed: $1"; }; }

# ===========================================================================
if [[ "$DO_PIERRE" == 1 ]]; then
  say "Pierre — code triage"
  pull "$CHAT_MODEL"; pull "nomic-embed-text"
  # the run-watcher's explainer: a SMALL model. Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an
  # Intel Arc / Intel iGPU box runs it on the CPU, which is why a 4B model is the default there.
  case "$WATCH_MODEL" in phi) WATCH_MODEL="phi4-mini" ;; small) WATCH_MODEL="qwen3:4b" ;; esac
  if [[ -n "$WATCH_MODEL" ]]; then
    "$OLLAMA" list 2>/dev/null | grep -q "^$WATCH_MODEL" || "$OLLAMA" pull "$WATCH_MODEL" || hf_gguf_create "$WATCH_MODEL" \
      || warn "could not pull the watcher model $WATCH_MODEL (pierre-watch still gives the digest and verdict)"
  fi
  cat > "$LOCAL_AI/Modelfile.pierre" <<EOF
FROM $CHAT_MODEL
PARAMETER num_ctx $NUM_CTX
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 20
SYSTEM """You are Pierre-Lite, a fully local assistant for dam-safety engineering work on this machine.
- QGIS plugins of the ND dam suite and the DamSafety fork; QGIS 3.34 / Python 3.12 from conda-forge; CI also runs QGIS 4 / Qt6.
- Crest: a TypeScript desk-screening app (screening, not hazard classification).
- Dam hazard classification per USBR ACER TM-11 and ND state standards; depth/velocity/arrival rasters (EPSG:26914), LISFLOOD-FP and ANUGA outputs.
Be precise about code, filenames, paths and units (ft vs m, cfs vs m3/s, NAVD88 vs local datum). Show the complete corrected function, never fragments. Never call sys.exit()/os._exit() in code that runs inside QGIS. Guard None before string ops. Only report a defect you can point to by line number in code you were shown. When uncertain, say UNSURE. Never recommend destructive operations without a backup and a dry-run.
STANDING RULES (Nick's; never contradict them, even if a question assumes otherwise):
- Sunny-day breach: there is NO inflow, the outlets are empty, and there is NO outlet or spillway flow. The reservoir starts at the top of dam, which is the DWR max pool. The only water is the breach. Never say the inflow equals the reservoir capacity or that the outlets are operational.
- Breach volume Vw: a sunny-day breach uses the DWR maximum pool and maximum storage unless stated otherwise; a PMF or flood-inflow breach uses the storage at the pool when the breach starts (ND Dam Safety Standards).
- The real DamIT qgis_process algorithm ids: damit_screen:handoff (hand-off to the Runner), damit_run:rundam (breach flood for one dam), damit:classify (hazard classification), damit_lite:classify (Hazard Lite). The automatic 10 m refine is turned off with --GRID_REFINE=0. There is no damit_runner algorithm, no damit_screener_handoff, no damit_hazard_classification and no --no-refine switch.
- Never invent a tool, algorithm id, parameter, switch, flag id or number. If a name is not in these rules or in the context you were given, say UNSURE and point to ALGORITHM-HELP-DAMIT.md.
- The run watcher's OK / WATCH / PROBLEM verdict is set by code from the flags alone. Pierre only explains the flags and never sets or changes the verdict."""
EOF
  "$OLLAMA" create pierre -f "$LOCAL_AI/Modelfile.pierre" >/dev/null || die "pierre persona creation failed"
  ok "'pierre' persona created"
  PYL="$(make_env "$PIERRE_ENV" "python=3.12 pymupdf pypdf numpy")"
  ok "pierre python: $PYL"
  for t in rag_index.py rag_query.py audit_plugin.py dam_chain.py repo_audit.py suite_check.py eval_pierre.py run_digest.py pierre_watch.py; do
    [[ -f "$HERE/pierre/tools/$t" ]] && cp "$HERE/pierre/tools/$t" "$PIERRE_TOOLS/$t"
  done
  [[ -d "$HERE/pierre/eval" ]] && cp -r "$HERE/pierre/eval" "$PIERRE_TOOLS/eval"   # code-triage eval set (eval_pierre.py)
  printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$PYL" > "$LOCAL_AI/python"; chmod +x "$LOCAL_AI/python"
  ok "pierre tools -> $LOCAL_AI"
fi

# ===========================================================================
if [[ "$DO_RESEARCH" == 1 ]]; then
  say "dam-research — literature"
  EMBED="qwen3-embedding:0.6b"; "$OLLAMA" pull "$EMBED" >/dev/null 2>&1 || { warn "qwen3-embedding pull failed; using nomic-embed-text"; EMBED="nomic-embed-text"; }
  pull "$CHAT_MODEL"; pull "$EMBED"
  cat > "$RESEARCH_DIR/Modelfile" <<EOF
FROM $CHAT_MODEL
PARAMETER num_ctx $NUM_CTX
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.05
SYSTEM """You are a research assistant for dam-safety engineers in North Dakota: dam safety, dam and spillway design, breach parameters, inundation mapping, hydrology and flood hazards. When source passages are supplied, use only them: every fact gets a citation to its source and page, quotes are copied exactly, numbers/units/equations and their applicability limits kept exactly, and disagreements between sources are reported, not resolved silently. When no passages are supplied, say the answer is from general knowledge, is UNVERIFIED, and must be checked against the primary publication; give the publication to check (agency, document number, year) and never invent a citation, page number, coefficient or value. You are not a licensed engineer and your output is not engineering judgement."""
EOF
  "$OLLAMA" create dam-research -f "$RESEARCH_DIR/Modelfile" >/dev/null || die "could not create the dam-research model"
  ok "'dam-research' persona created"
  RSPEC="python=3.12 numpy pymupdf"; [[ "$OCR" == 1 ]] && RSPEC="$RSPEC ocrmypdf tesseract"
  PYR="$(make_env "$RESEARCH_ENV" "$RSPEC")"
  ok "research python: $PYR"
  for t in damresearch.py fetch_asdso.py eval_damresearch.py reference_sources.json; do
    [[ -f "$HERE/research/$t" ]] && cp "$HERE/research/$t" "$RESEARCH_DIR/$t"
  done
  [[ -d "$HERE/research/eval" ]] && cp -r "$HERE/research/eval" "$RESEARCH_DIR/eval"
  printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$PYR" > "$RESEARCH_DIR/python"; chmod +x "$RESEARCH_DIR/python"
  ok "dam-research tools -> $RESEARCH_DIR; drop PDFs in $RHOME/library"
fi

# ===========================================================================
if [[ "$INDEX_KN" == 1 && "$DO_PIERRE" == 1 && -d "$HERE/pierre/knowledge" ]]; then
  say "Indexing the Pierre knowledge pack"
  "$PYL" "$PIERRE_TOOLS/rag_index.py" -c pierre_knowledge "$HERE/pierre/knowledge" || warn "knowledge index failed"
  # engine docs, if the dam-research library has them downloaded
  EDOCS="$RHOME/library/references/software"
  if [[ -d "$EDOCS" ]]; then
    "$PYL" "$PIERRE_TOOLS/rag_index.py" -c engine_docs "$EDOCS" || warn "engine-docs index failed"
    ok "indexed engine docs from $EDOCS"
  fi
fi

# ---------------------------------------------------------------------------
say "Step 5 — shell config ($RC)"
MARK="# >>> dam local AI (pierre + dam-research) >>>"
if ! grep -qF "$MARK" "$RC" 2>/dev/null; then
  cp "$RC" "$RC.bak-localai" 2>/dev/null || true
  {
    echo ""
    echo "$MARK"
    echo "export OLLAMA_MODELS=\"$MODELS_DIR\""
    echo "export OLLAMA_FLASH_ATTENTION=1"
    echo "export OLLAMA_KV_CACHE_TYPE=q8_0"
    [[ "$DO_PIERRE" == 1 ]] && echo "export PIERRE_NUM_CTX=$NUM_CTX"
    [[ "$DO_PIERRE" == 1 ]] && echo "alias pierre='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_query.py\"'"
    [[ "$DO_PIERRE" == 1 ]] && echo "alias damchain='\"$LOCAL_AI/python\" \"$LOCAL_AI/dam_chain.py\"'"
    [[ "$DO_PIERRE" == 1 ]] && echo "export PIERRE_WATCH_MODEL=\"${WATCH_MODEL:-qwen3:4b}\""
    [[ "$DO_PIERRE" == 1 ]] && echo "alias pierre-digest='\"$LOCAL_AI/python\" \"$LOCAL_AI/run_digest.py\"'"
    [[ "$DO_PIERRE" == 1 ]] && echo "alias pierre-watch='\"$LOCAL_AI/python\" \"$LOCAL_AI/pierre_watch.py\"'"
    [[ "$DO_RESEARCH" == 1 ]] && echo "export DAMRESEARCH_HOME=\"$RHOME\""
    [[ "$DO_RESEARCH" == 1 ]] && echo "alias damresearch='\"$RESEARCH_DIR/python\" \"$RESEARCH_DIR/damresearch.py\"'"
    echo "# <<< dam local AI <<<"
  } >> "$RC"
  ok "aliases written to $RC (backup: $RC.bak-localai)"
else
  ok "shell block already present in $RC"
fi

# ---------------------------------------------------------------------------
say "Done"
cat <<EOF
  Open a new shell (or: source $RC), then:
EOF
[[ "$DO_PIERRE" == 1 ]] && echo "    pierre \"where is the breach width computed\"   # set ND_REPO/DWR_REPO/CREST_REPO first for repo audits"
[[ "$DO_RESEARCH" == 1 ]] && echo "    damresearch ingest    # after dropping PDFs in $RHOME/library (or run research/fetch_asdso.py --catalog)"
cat <<EOF
  openSUSE GUI-QGIS note (only if you also run the plugins here): a conda QGIS may need system
  GL/X libraries. If the xcb platform plugin fails, install them with:
    sudo zypper install -y Mesa-libGL1 libxcb-cursor0 libxkbcommon-x11-0
  The local AIs themselves need none of that.
EOF
