#!/usr/bin/env bash
# ============================================================================
# install-local-ai-linux.sh — install BOTH local AIs (Heim code-triage +
# vor literature) on Linux, tested for openSUSE (Tumbleweed/Leap) and
# usable on any x86_64 Linux. The Linux counterpart of damit_ai/heim/setup-local-heim.sh
# and vor/setup-vor.zsh.
#
#   ./install-local-ai-linux.sh                 # both AIs
#   ./install-local-ai-linux.sh --no-heim        # vor only
#   ./install-local-ai-linux.sh --no-vor     # Heim only
#   ./install-local-ai-linux.sh --ocr             # vor with OCR (ocrmypdf + tesseract)
#   ./install-local-ai-linux.sh --small           # force the small chat model
#   ./install-local-ai-linux.sh --no-index        # skip indexing the knowledge pack / engine docs
#   ./install-local-ai-linux.sh --watch-model=TAG # the SMALL run-watcher explainer (default qwen3:4b; phi4-mini is the
#                                                 # alternative); --no-watch-model skips pulling it. heim (Q&A) keeps the big model.
#   ./install-local-ai-linux.sh --prefix=DIR      # a SANDBOX: everything in DIR and nothing outside it. Ollama, its models,
#                                                 # the Heim tools, their envs (conda -p, or venvs) and Heim's databases in
#                                                 # DIR/local-ai; Vor's library in DIR/Vor; its own Ollama server (port
#                                                 # 11435, home DIR/local-ai). NO lines go into ~/.bashrc / ~/.zshrc: the
#                                                 # commands are in DIR/local-ai/env.sh  ( . DIR/local-ai/env.sh ).
#                                                 # VOR_HOME from your shell is ignored there. Remove it: kill the server
#                                                 # (DIR/local-ai/ollama-serve.pid) and delete DIR.
#   ./install-local-ai-linux.sh --ollama-port=N   # the Ollama port (default 11434; 11435 with --prefix)
#   ./install-local-ai-linux.sh --no-models       # no model pulls and no personas or index (they need the models): the
#                                                 # server, envs, tools and commands only. Re-run without it for the models.
#
# Everything it prints also goes to ~/local-ai/install.log. If it stops, run the same command again:
# it carries on (models already downloaded are not downloaded again). Before the models are pulled it
# checks the free disk space against their size and stops with the numbers when there is not enough.
# At the end it runs ai-doctor and prints the first commands to try.
#
# Run it from the package's damit_ai/ folder (it copies heim/ and vor/ from beside itself; a copy of
# this script on its own installs no tools and indexes nothing, and says so).
# If `ollama pull` fails (a proxy that breaks the registry redirect), the model's official GGUF is fetched from
# Hugging Face (https_proxy / HF_ENDPOINT honoured), sha256-checked and loaded with `ollama create` under the
# same tag (qwen3 4b/8b/14b/30b-a3b, phi4-mini, nomic-embed-text). HEIM_NO_HF_FALLBACK=1 turns that off.
#
# By default, when Heim is installed the Heim knowledge pack (heim/knowledge) and, if present,
# the vor engine docs are indexed into the RAG so Heim comes up already knowing the
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
HEIM_TOOLS="$LOCAL_AI"                      # heim tools live directly in ~/local-ai (match the Mac layout)
VOR_DIR="$LOCAL_AI/vor"
RHOME="${VOR_HOME:-$HOME/Vor}"
DOWNLOADS="${XDG_DOWNLOAD_DIR:-$HOME/Downloads}"
OFFLINE="$HERE/offline"
RC="$HOME/.bashrc"; [[ -n "${ZSH_VERSION:-}" || -f "$HOME/.zshrc" ]] && RC="$HOME/.zshrc"
HEIM_ENV="ndheim"; RESEARCH_ENV="ndvor"
OLLAMA_HOST_URL="http://127.0.0.1:11434"
DO_HEIM=1; DO_VOR=1; OCR=0; SMALL=0; INDEX_KN=1; NO_MODELS=0; SANDBOX=""; OLLAMA_PORT=""
WATCH_MODEL="${HEIM_WATCH_MODEL:-qwen3:4b}"

# --prefix DIR / --ollama-port N are also accepted as two words
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix|--ollama-port) [[ $# -gt 1 && -n "$2" ]] || { echo "$1 needs a value" >&2; exit 1; }
                            ARGS+=("$1=$2"); shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
for a in ${ARGS[@]+"${ARGS[@]}"}; do case "$a" in
  --no-heim) DO_HEIM=0 ;;
  --no-vor) DO_VOR=0 ;;
  --ocr) OCR=1 ;;
  --small) SMALL=1 ;;
  --index-knowledge) INDEX_KN=1 ;;      # on by default; kept for compatibility
  --no-index) INDEX_KN=0 ;;
  --watch-model=*) WATCH_MODEL="${a#*=}" ;;
  --no-watch-model) WATCH_MODEL="" ;;
  --prefix=*) SANDBOX="${a#*=}" ;;
  --ollama-port=*) OLLAMA_PORT="${a#*=}" ;;
  --no-models) NO_MODELS=1 ;;
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $a" >&2; exit 1 ;;
esac; done

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok(){ printf '  \033[32mok\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mwarn\033[0m %s\n' "$*" >&2; }
die(){ printf '  \033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }
sha(){ sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

case "$OLLAMA_PORT" in ""|[0-9]|[0-9][0-9]|[0-9][0-9][0-9]|[0-9][0-9][0-9][0-9]|[0-9][0-9][0-9][0-9][0-9]) ;;
  *) die "--ollama-port needs a port number (got '$OLLAMA_PORT')" ;; esac
if [[ -n "$SANDBOX" ]]; then
  # --prefix: a sandbox. Every path below moves into it, and the caches and registries that would
  # otherwise land in your home folder (conda's package cache and env list, pip's cache, Ollama's
  # key in ~/.ollama, the GGUF download folder) are pointed into it too.
  case "$SANDBOX" in "~") SANDBOX="$HOME" ;; "~"/*) SANDBOX="$HOME/${SANDBOX#"~/"}" ;; /*) ;; *) SANDBOX="$PWD/$SANDBOX" ;; esac
  SANDBOX="${SANDBOX%/}"
  [[ -n "$SANDBOX" && "$SANDBOX" != "$HOME" ]] || die "--prefix needs its own folder (not / or your home folder)"
  LOCAL_AI="$SANDBOX/local-ai"; MODELS_DIR="$LOCAL_AI/models"; HEIM_TOOLS="$LOCAL_AI"; VOR_DIR="$LOCAL_AI/vor"
  RHOME="$SANDBOX/Vor"; RC="$LOCAL_AI/env.sh"
  OLLAMA_PORT="${OLLAMA_PORT:-11435}"
  export CONDA_PKGS_DIRS="$LOCAL_AI/conda-pkgs" CONDA_REGISTER_ENVS=false PIP_NO_CACHE_DIR=1
  export HEIM_GGUF_DIR="${HEIM_GGUF_DIR:-$LOCAL_AI/gguf-tmp}"
  # the Heim tools' own defaults are ~/local-ai/...: the index step below runs them, so point them here
  export HEIM_DB="$LOCAL_AI/knowledge.db" HEIM_RUNS_DB="$LOCAL_AI/runs.db" HEIM_REPORTS="$LOCAL_AI/reports"
fi
# conda_sb: conda with a home inside the sandbox (even with CONDA_REGISTER_ENVS=false it rewrites
# ~/.conda/environments.txt and makes ~/.cache/conda); your ~/.condarc is still read (CONDARC)
conda_sb(){
  local e=(HOME="$LOCAL_AI/.home" XDG_CACHE_HOME="$LOCAL_AI/.home/.cache")
  [[ -n "${CONDARC:-}" || ! -f "$HOME/.condarc" ]] || e+=(CONDARC="$HOME/.condarc")
  env "${e[@]}" "$CONDA" "$@"
}
if [[ -n "$OLLAMA_PORT" ]]; then
  OLLAMA_HOST_URL="http://127.0.0.1:$OLLAMA_PORT"
  export OLLAMA_HOST="127.0.0.1:$OLLAMA_PORT" OLLAMA_URL="$OLLAMA_HOST_URL"   # the ollama CLI and the Heim/Vor tools
fi
# Everything printed from here on also goes to the install log, and a stop says how to carry on.
mkdir -p "$LOCAL_AI"
INSTALL_LOG="$LOCAL_AI/install.log"
printf '\n=== %s  install-local-ai-linux.sh %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${ARGS[*]+"${ARGS[*]}"}" >> "$INSTALL_LOG"
exec > >(tee -a "$INSTALL_LOG") 2>&1
on_exit() {
  local rc=$?
  if (( rc != 0 )); then
    printf '\n  The install stopped (exit %s). What it did so far is kept: fix what it says above, then run the\n' "$rc"
    printf '  same command again and it carries on from there (models already downloaded are not downloaded again).\n'
    printf '  Everything it printed is in %s\n' "$INSTALL_LOG"
  fi
}
trap on_exit EXIT
if [[ "$DO_HEIM" == 1 && ! -d "$HERE/heim/tools" ]]; then
  warn "no heim/tools beside this script ($HERE): run it from the package's damit_ai/ folder, or Heim gets no tools and no index"
fi

# ---------------------------------------------------------------------------
say "Step 1 — Directory skeleton"
# Vor was called damresearch until 2026-11-13 and kept its library and index in ~/DamResearch
# (or wherever DAMRESEARCH_HOME pointed). The mkdir below would create an empty ~/Vor beside it
# and the rc block would then pin VOR_HOME to that empty folder: the indexed library is left
# behind and nothing errors, `vor ask` just finds no passages. So carry it over first. The
# index decides, the move happens only onto a name that does not exist, nothing is deleted.
OLD_RHOME="${DAMRESEARCH_HOME:-$HOME/DamResearch}"
vor_has_index() { [[ -f "$1/vor.db" || -f "$1/research.db" ]]; }
if [[ -z "${SANDBOX:-}" && -z "${VOR_HOME:-}" && "$OLD_RHOME" != "$RHOME" ]] && vor_has_index "$OLD_RHOME" && ! vor_has_index "$RHOME"; then
  # Only the default folder is renamed. A library someone put elsewhere (another disk) stays
  # there: moving it home would be a copy of the whole library, not a rename.
  if [[ "$OLD_RHOME" == "$HOME/DamResearch" && ! -e "$RHOME" ]] && mv "$OLD_RHOME" "$RHOME" 2>/dev/null; then
    ok "moved your Vor library from $OLD_RHOME to $RHOME (nothing was copied)"
  else
    warn "keeping your indexed Vor library where it is: $OLD_RHOME"
    RHOME="$OLD_RHOME"
  fi
fi
if [[ -f "$RHOME/research.db" && ! -f "$RHOME/vor.db" ]]; then
  mv "$RHOME/research.db" "$RHOME/vor.db" && ok "index renamed research.db -> vor.db (nothing re-indexed)"
fi
mkdir -p "$LOCAL_AI" "$MODELS_DIR" "$VOR_DIR" "$RHOME/library" "$RHOME/reports"
ok "$LOCAL_AI, $RHOME"

# ---------------------------------------------------------------------------
say "Step 2 — Ollama (no sudo, no download-then-run)"
OLLAMA=""
OCANDS=("$(command -v ollama 2>/dev/null || true)" "$LOCAL_AI/ollama/bin/ollama" "$HOME/.local/bin/ollama")
if [[ -n "$SANDBOX" ]]; then
  # the sandbox's own copy first, then the bundled archive (extracted into the sandbox below), and
  # only then an Ollama already on this machine (its program is only run, never changed)
  OCANDS=("$LOCAL_AI/ollama/bin/ollama")
  [[ -f "$OFFLINE/ollama/ollama-linux-amd64.tar.zst" || -f "$OFFLINE/ollama/ollama-linux-amd64.tgz" ]] \
    || OCANDS+=("$(command -v ollama 2>/dev/null || true)" "$HOME/.local/bin/ollama")
fi
for c in "${OCANDS[@]}"; do
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
  # the assignment is the FINAL element of the `||` list, so it is not exempt from errexit:
  # a `find` that hits an unreadable subdir exits 1 while still printing, and under pipefail
  # that would kill the script instead of reaching the clean `die` below
  [[ -x "$OLLAMA" ]] || OLLAMA="$(find "$LOCAL_AI/ollama" -name ollama -type f -perm -u+x 2>/dev/null | head -1 || true)"
  [[ -x "$OLLAMA" ]] || die "ollama binary not found after extracting"
  ok "Ollama extracted to $LOCAL_AI/ollama"
else
  ok "Ollama already installed ($OLLAMA)"
fi
export OLLAMA_MODELS="$MODELS_DIR" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0

# --prefix: the port must be this sandbox's own server, or models would be pulled into another
# Ollama's store (e.g. your usual one in ~/.ollama on 11434)
if [[ -n "$SANDBOX" ]] && curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1; then
  SPID="$(cat "$LOCAL_AI/ollama-serve.pid" 2>/dev/null || true)"
  [[ -n "$SPID" ]] && kill -0 "$SPID" 2>/dev/null \
    || die "something else already answers on $OLLAMA_HOST_URL (another Ollama?). Stop it, or pick a free port with --ollama-port=N"
fi
# start the server if it isn't answering
if ! curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1; then
  ok "starting ollama serve on $OLLAMA_HOST_URL (log: $LOCAL_AI/ollama-serve.log)"
  SERVE_ENV=(OLLAMA_MODELS="$MODELS_DIR" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0)
  [[ -z "$OLLAMA_PORT" ]] || SERVE_ENV+=(OLLAMA_HOST="127.0.0.1:$OLLAMA_PORT")
  [[ -z "$SANDBOX" ]] || SERVE_ENV+=(HOME="$LOCAL_AI")      # its key (~/.ollama) stays in the sandbox
  nohup env "${SERVE_ENV[@]}" "$OLLAMA" serve >"$LOCAL_AI/ollama-serve.log" 2>&1 &
  [[ -z "$SANDBOX" ]] || echo $! > "$LOCAL_AI/ollama-serve.pid"
  for i in $(seq 1 30); do curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 && break; sleep 1; done
fi
curl -sf "$OLLAMA_HOST_URL/api/version" >/dev/null 2>&1 || die "ollama server did not come up (see $LOCAL_AI/ollama-serve.log)"
ok "server up on $OLLAMA_HOST_URL"

# seed models from a pre-downloaded offline bundle (download-all-linux.sh), so pulls are skipped
if [[ "$NO_MODELS" == 0 && -d "$OFFLINE/models/manifests" && ! -d "$MODELS_DIR/manifests" ]]; then
  cp -a "$OFFLINE/models/." "$MODELS_DIR/" 2>/dev/null && ok "seeded models from offline/models (no download needed)" || warn "could not seed offline models"
fi

# ---------------------------------------------------------------------------
say "Step 3 — conda (reuse an existing install; venv fallback)"
CONDA=""
for c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null)" "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/miniconda/bin/conda"; do
  [[ -n "$c" && -x "$c" ]] && { CONDA="$c"; break; }
done
[[ -n "$CONDA" ]] && ok "conda: $CONDA" || warn "no conda found — will use python3 venvs (need python3 + python3-venv)"
[[ -z "$SANDBOX" || -z "$CONDA" ]] || ok "sandbox: envs go in $LOCAL_AI/envs (by path), none in $(conda_sb info --base 2>/dev/null || echo 'the conda base')"

make_env(){  # name  "pkgspec"   -> echoes the python path
  local name="$1" spec="$2" envpath=""
  if [[ -n "$CONDA" && -n "$SANDBOX" ]]; then
    # --prefix: the env is made BY PATH inside the sandbox (install-all --sandbox builds it there
    # from the offline packages first, so this finds it); never by name in the conda base
    envpath="$LOCAL_AI/envs/$name"
    if [[ ! -d "$envpath/conda-meta" ]]; then
      conda_sb create -y -p "$envpath" -c conda-forge --override-channels $spec >/dev/null 2>&1 \
        || { warn "conda create $envpath failed — falling back to a venv"; CONDA=""; }
    fi
    [[ -n "$CONDA" ]] && { echo "$envpath/bin/python"; return; }
  fi
  if [[ -n "$CONDA" ]]; then
    # `|| true` inside both substitutions. A `conda env list` that exits non-zero (an
    # uninitialised or half-broken conda, or one that warns and exits 1) would otherwise
    # fail the assignment under pipefail and kill make_env — and since make_env is called
    # as PYL="$(make_env ...)", that death propagates out and ends the installer, instead
    # of taking the venv fallback the next few lines were written for.
    envpath="$("$CONDA" env list | awk -v n="$name" '$1==n{print $NF}' || true)"
    if [[ -z "$envpath" ]]; then
      "$CONDA" create -y -n "$name" -c conda-forge --override-channels $spec >/dev/null 2>&1 \
        || { warn "conda create $name failed — falling back to a venv"; CONDA=""; }
    fi
    if [[ -n "$CONDA" ]]; then
      envpath="$("$CONDA" env list | awk -v n="$name" '$1==n{print $NF}' || true)"
    fi
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
# >>> hf_gguf_fallback (the same block is in install-local-ai-linux.sh and heim/setup-local-heim.sh; a test keeps them equal)
# `ollama pull` can fail behind a proxy (the registry's manifest / redirect never completes). Fallback: fetch the model's
# official GGUF from Hugging Face (curl honours https_proxy; HF_ENDPOINT can point at a mirror), check its sha256, write a
# Modelfile and `ollama create` the SAME tag, then delete the GGUF (Ollama keeps its own copy).
# HEIM_GGUF_SPEC="repo file sha256 bytes" overrides the table (another quant, or a mirror's file); HEIM_GGUF_DIR = scratch dir.
hf_gguf_spec(){
  if [[ -n "${HEIM_GGUF_SPEC:-}" ]]; then echo "$HEIM_GGUF_SPEC"; return 0; fi
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
  spec="$(hf_gguf_spec "$tag")" || { warn "no Hugging Face GGUF is known for $tag (set HEIM_GGUF_SPEC=\"repo file sha256 bytes\")"; return 1; }
  read -r repo file sha size <<< "$spec"
  if [[ "${HEIM_NO_HF_FALLBACK:-0}" == 1 ]]; then warn "HEIM_NO_HF_FALLBACK=1: not downloading $tag from Hugging Face"; return 1; fi
  command -v curl >/dev/null 2>&1 || { warn "curl not found: cannot fetch the GGUF for $tag"; return 1; }
  dir="${HEIM_GGUF_DIR:-${TMPDIR:-/tmp}/heim-gguf}"; mkdir -p "$dir" || return 1
  avail=$(df -Pk "$dir" 2>/dev/null | awk 'NR==2{print $4*1024}')
  if [[ -n "$avail" ]] && (( avail < size + size / 10 )); then
    warn "not enough free space in $dir for the $((size / 1048576)) MB GGUF (set HEIM_GGUF_DIR to a bigger disk)"; return 1
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
# --no-models: nothing is pulled, and the personas (heim, vor) and the index, which need the models, wait
[[ "$NO_MODELS" == 0 ]] || warn "--no-models: no model is pulled; the heim/vor personas and the knowledge index are made when you run this again without it"

# Free disk space before the downloads (12-22 GB): a full disk half way through a pull is the worst
# place to find out. The sizes are the 4-bit files in the table above; qwen3-embedding is ~0.64 GB.
model_bytes(){ local spec; spec="$(HEIM_GGUF_SPEC='' hf_gguf_spec "$1" 2>/dev/null)" && { echo "${spec##* }"; return; }
  case "$1" in qwen3-embedding:*) echo 639000000 ;; *) echo 0 ;; esac; }
gb(){ awk -v b="$1" 'BEGIN{printf "%.1f", b/1073741824}'; }
if [[ "$NO_MODELS" == 0 ]]; then
  WANT_MODELS=()
  [[ "$DO_HEIM" == 1 ]] && WANT_MODELS+=("$CHAT_MODEL" "nomic-embed-text")
  if [[ "$DO_HEIM" == 1 && -n "$WATCH_MODEL" ]]; then
    case "$WATCH_MODEL" in phi) WANT_MODELS+=("phi4-mini") ;; small) WANT_MODELS+=("qwen3:4b") ;; *) WANT_MODELS+=("$WATCH_MODEL") ;; esac
  fi
  [[ "$DO_VOR" == 1 ]] && WANT_MODELS+=("$CHAT_MODEL" "qwen3-embedding:0.6b")
  HAVE_LIST="$("$OLLAMA" list 2>/dev/null || true)"
  NEED=0; NEED_NAMES=""
  for m in $(printf '%s\n' ${WANT_MODELS[@]+"${WANT_MODELS[@]}"} | awk 'NF && !seen[$0]++'); do
    grep -q "^$m" <<< "$HAVE_LIST" && continue
    NEED=$(( NEED + $(model_bytes "$m") )); NEED_NAMES="$NEED_NAMES $m"
  done
  if (( NEED > 0 )); then
    FREE=$(df -Pk "$MODELS_DIR" 2>/dev/null | awk 'NR==2{print $4*1024}' || true)
    if [[ -n "$FREE" ]] && (( FREE < NEED + NEED / 10 + 1073741824 )); then
      die "not enough free disk space for the models:$NEED_NAMES need about $(gb "$NEED") GB in $MODELS_DIR and $(gb "$FREE") GB is free. Free some space$([[ "$CHAT_MODEL" == qwen3:8b ]] || echo " (or add --small for a smaller chat model)"), then run this again."
    fi
    ok "models to download:$NEED_NAMES (about $(gb "$NEED") GB; $(gb "${FREE:-0}") GB free). Their progress shows below; Ctrl+C is safe, a re-run carries on."
  fi
fi

# ===========================================================================
if [[ "$DO_HEIM" == 1 ]]; then
  say "Heim — code triage"
  [[ "$NO_MODELS" == 1 ]] || { pull "$CHAT_MODEL"; pull "nomic-embed-text"; }
  # the run-watcher's explainer: a SMALL model. Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an
  # Intel Arc / Intel iGPU box runs it on the CPU, which is why a 4B model is the default there.
  case "$WATCH_MODEL" in phi) WATCH_MODEL="phi4-mini" ;; small) WATCH_MODEL="qwen3:4b" ;; esac
  if [[ -n "$WATCH_MODEL" && "$NO_MODELS" == 0 ]]; then
    "$OLLAMA" list 2>/dev/null | grep -q "^$WATCH_MODEL" || "$OLLAMA" pull "$WATCH_MODEL" || hf_gguf_create "$WATCH_MODEL" \
      || warn "could not pull the watcher model $WATCH_MODEL (heim-watch still gives the digest and verdict)"
  fi
  cat > "$LOCAL_AI/Modelfile.heim" <<EOF
FROM $CHAT_MODEL
PARAMETER num_ctx $NUM_CTX
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 20
SYSTEM """You are Heim-Lite, a fully local assistant for dam-safety engineering work on this machine.
DOMAIN CONTEXT (what this machine builds; it tells you what the names mean, never whether a claim is true):
- The DamIT QGIS plugins (damit_core, damit_screener, damit_runner, damit_hazard, damit_hazardlite, damit_finder, damit_data, damit_catalog, damit_pmp, damit_setup) and the DamSafety fork of the same engine. Their Processing ids clash, so each set gets its own QGIS profile.
- QGIS 3.34 LTR, Python 3.12 from conda-forge (env ndqgis) on macOS; CI also runs QGIS 4 / Qt6.
- Crest: a TypeScript desk-screening app off USGS 3DEP 10 m. A screening tool, not a hazard classification.
- Hazard classification follows USBR ACER TM-11 and the ND Dam Safety Standards (REG_05.2026).
- The hydraulic engines are subprocesses, not libraries: LISFLOOD-FP 8.x (ACC is the default solver; FV2 and MWDG2 are CUDA-only), ANUGA 4.1, gmsh, and HEC-RAS under Wine. Each Runner pass writes Depth, Velocity, Arrival Time and WSE rasters.
- Terrain is 3DEP 1 m and statewide VRTs on NAVD88, EPSG:26914 (ND) or EPSG:5070 (DamSafety WORK_CRS). A DEM projected in metres overrides WORK_CRS, and a VRT reads a missing source back as nodata, which the models read as high ground.
- Data sources: NSI, ND GIS Hub, FEMA, OSM, NDDOT ArcGIS REST, USGS 3DHP, the NID and the ND DWR dam list.
- The GUI can display SI, but a Run still receives FEET.
- You have NO web access and cannot check anything online. Your training is older than this code: say when a fact may be out of date instead of asserting it.
- Every file, log and run you are shown stays on this machine. Treat all of it as private.
Be precise about code, filenames, paths and units (ft vs m, cfs vs m3/s, NAVD88 vs local datum). Show the complete corrected function, never fragments. Never call sys.exit()/os._exit() in code that runs inside QGIS. Guard None before string ops. Only report a defect you can point to by line number in code you were shown. When uncertain, say UNSURE. Never recommend destructive operations without a backup and a dry-run.
HOW YOU ANSWER (this is your manner; it is about what you do, not how you sound):
- Lead with the verdict or the line number. The reasoning comes after it, never before it.
- Quote the code you are judging before you judge it. A defect described in general terms, with no line to point at, is a guess wearing a finding's clothes.
- One finding at a time, worst first. A list of maybes is not a finding, and length is not thoroughness.
- Never soften a defect into a suggestion. If it is wrong, say it is wrong.
- Asking is a complete answer: name the file, function or log you would need to see, and stop there.
- You watch and explain; you do not decide. Where the code sets a verdict or a status, explain the flags that produced it and leave the verdict alone.
STANDING RULES (Nick's; never contradict them, even if a question assumes otherwise):
- Sunny-day breach: there is NO inflow, the outlets are empty, and there is NO outlet or spillway flow. The reservoir starts at the top of dam, which is the DWR max pool. The only water is the breach. Never say the inflow equals the reservoir capacity or that the outlets are operational.
- Breach volume Vw: a sunny-day breach uses the DWR maximum pool and maximum storage unless stated otherwise; a PMF or flood-inflow breach uses the storage at the pool when the breach starts (ND Dam Safety Standards).
- The real DamIT qgis_process algorithm ids: damit_screen:handoff (hand-off to the Runner), damit_run:rundam (breach flood for one dam), damit:classify (hazard classification), damit_lite:classify (Hazard Lite). The automatic 10 m refine is turned off with --GRID_REFINE=0. There is no damit_runner algorithm, no damit_screener_handoff, no damit_hazard_classification and no --no-refine switch.
- Never invent a tool, algorithm id, parameter, switch, flag id or number. If a name is not in these rules or in the context you were given, say UNSURE and point to ALGORITHM-HELP-DAMIT.md.
- The run watcher's OK / WATCH / PROBLEM verdict is set by code from the flags alone. Heim only explains the flags and never sets or changes the verdict."""
EOF
  if [[ "$NO_MODELS" == 0 ]]; then
  "$OLLAMA" create heim -f "$LOCAL_AI/Modelfile.heim" >/dev/null || die "heim persona creation failed"
  ok "'heim' persona created"
  fi
  PYL="$(make_env "$HEIM_ENV" "python=3.12 pymupdf pypdf numpy")"
  ok "heim python: $PYL"
  for t in rag_index.py rag_query.py audit_plugin.py dam_chain.py repo_audit.py suite_check.py eval_heim.py run_digest.py heim_watch.py run_results.py true_hole.py ai_doctor.py ai_ui.py ai_score.py heim_run.py; do
    [[ -f "$HERE/heim/tools/$t" ]] && cp "$HERE/heim/tools/$t" "$HEIM_TOOLS/$t"
  done
  [[ -d "$HERE/heim/eval" ]] && mkdir -p "$HEIM_TOOLS/eval" && cp -R "$HERE/heim/eval/." "$HEIM_TOOLS/eval/"   # code-triage eval set (eval_heim.py); contents, so a re-run does not nest eval/eval
  printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$PYL" > "$LOCAL_AI/python"; chmod +x "$LOCAL_AI/python"
  ok "heim tools -> $LOCAL_AI"
fi

# ===========================================================================
if [[ "$DO_VOR" == 1 ]]; then
  say "vor — literature"
  EMBED="qwen3-embedding:0.6b"
  if [[ "$NO_MODELS" == 0 ]]; then
  "$OLLAMA" list 2>/dev/null | grep -q "^$EMBED" || { ok "pulling $EMBED (Vor's search model, about 0.6 GB)"; "$OLLAMA" pull "$EMBED"; } \
    || { warn "qwen3-embedding pull failed; using nomic-embed-text"; EMBED="nomic-embed-text"; }
  pull "$CHAT_MODEL"; pull "$EMBED"
  fi
  cat > "$VOR_DIR/Modelfile" <<EOF
FROM $CHAT_MODEL
PARAMETER num_ctx $NUM_CTX
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.05
SYSTEM """You are Vor, a research assistant for dam-safety engineers in North Dakota: dam safety, dam and spillway design, breach parameters, inundation mapping, hydrology and flood hazards.
DOMAIN CONTEXT (the vocabulary of this library; it tells you what the terms mean, never what the answer is - the answer comes from the passages):
- Hazard classification: USBR ACER TM-11 depth-velocity danger charts, FEMA 333, ND REG_05.2026 and NDAC 89-08, NRCS TR-60 and TR-210-60, and state rules such as NY 6 NYCRR 673, VA 4VAC50-20 and TX 30 TAC 299.
- Inundation mapping and breach analysis: FEMA P-946, FEMA P-919, FERC Engineering Guidelines Chapter R21, USBR DSO reports, HEC Research Note 5, NRCS TR-66.
- Breach parameters: Froehlich (1995, 2008), Von Thun and Gillette, MacDonald and Langridge-Monopolis, Xu and Zhang - breach width, side slope and formation time, each with its own applicability limits, which are part of the result and must be carried with it.
- Design and hydrology: USACE EM 1110-2-2300, -1902, -1603, -1420 and ER 1110-2-1156; USBR Design of Small Dams; NOAA HMR 51, 52 and 55A and Atlas 14; PMP and PMF.
- Modelling: LISFLOOD-FP (Bates et al. 2010, local inertia), ANUGA (Zoppou and Roberts 1999), HEC-RAS.
- Terms that must never be conflated: hazard potential class and risk; a sunny-day (fair-weather) breach and a PMF breach; NAVD88 and a local datum; feet and metres; cfs and m3/s; depth and the depth-velocity product; peak discharge and the breach outflow hydrograph.
- You have NO web access. Nothing outside the supplied passages and this prompt can be checked, so never present general knowledge as if it were sourced, and say when your training may be out of date.
- The library is the user's own files and stays on this machine. Treat every document as private.
- If the passages do not answer the question, say UNSURE and say what is missing. "Not in the library" is worth more than a plausible paragraph.
HOW YOU ANSWER (this is your manner; it is about what you do, not how you sound):
- The quote carries the claim. Give the source's own words first and your explanation after; your sentences join quotes together, they never stand in for one.
- Never let a sentence of your own sit beside a quote in a way that makes it look sourced.
- Every number keeps its unit and the limits it applies within. A breach coefficient without the range it was fitted over is not an answer.
- When two sources disagree, name both and pick neither. Resolving a disagreement quietly is the worst thing you can do here.
- Say what the library does not hold as readily as what it does, and name the publication a reader should go and get.
- Stop when the quotes have been given. A research answer that needs a paragraph of preamble has not been found yet.
When source passages are supplied, use only them: every fact gets a citation to its source and page, quotes are copied exactly, numbers/units/equations and their applicability limits kept exactly, and disagreements between sources are reported, not resolved silently. When no passages are supplied, say the answer is from general knowledge, is UNVERIFIED, and must be checked against the primary publication; give the publication to check (agency, document number, year) and never invent a citation, page number, coefficient or value. You are not a licensed engineer and your output is not engineering judgement."""
EOF
  if [[ "$NO_MODELS" == 0 ]]; then
  "$OLLAMA" create vor -f "$VOR_DIR/Modelfile" >/dev/null || die "could not create the vor model"
  ok "'vor' persona created"
  fi
  RSPEC="python=3.12 numpy pymupdf"; [[ "$OCR" == 1 ]] && RSPEC="$RSPEC ocrmypdf tesseract"
  PYR="$(make_env "$RESEARCH_ENV" "$RSPEC")"
  ok "research python: $PYR"
  for t in vor.py fetch_asdso.py eval_vor.py reference_sources.json; do
    [[ -f "$HERE/vor/$t" ]] && cp "$HERE/vor/$t" "$VOR_DIR/$t"
  done
  [[ -d "$HERE/vor/eval" ]] && mkdir -p "$VOR_DIR/eval" && cp -R "$HERE/vor/eval/." "$VOR_DIR/eval/"
  printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$PYR" > "$VOR_DIR/python"; chmod +x "$VOR_DIR/python"
  ok "vor tools -> $VOR_DIR; drop PDFs in $RHOME/library"
fi

# ===========================================================================
if [[ "$INDEX_KN" == 1 && "$NO_MODELS" == 0 && "$DO_HEIM" == 1 && -d "$HERE/heim/knowledge" ]]; then
  say "Indexing the Heim knowledge pack"
  "$PYL" "$HEIM_TOOLS/rag_index.py" -c heim_knowledge "$HERE/heim/knowledge" || warn "knowledge index failed"
  # engine docs, if the vor library has them downloaded
  EDOCS="$RHOME/library/references/software"
  if [[ -d "$EDOCS" ]]; then
    "$PYL" "$HEIM_TOOLS/rag_index.py" -c engine_docs "$EDOCS" || warn "engine-docs index failed"
    ok "indexed engine docs from $EDOCS"
  fi
fi

# ---------------------------------------------------------------------------
# Vor's library: a new install has nothing to answer from. The offline pack's library (download-all)
# is copied in and indexed; without one, the line to fetch the starter library is printed below.
LIB_EMPTY=0
# (no `find | grep -q` here: under pipefail a find cut off by grep's early exit reads as "nothing found")
if [[ "$DO_VOR" == 1 && -z "$(find "$RHOME/library" -type f \( -iname '*.pdf' -o -iname '*.md' -o -iname '*.txt' \) -print -quit 2>/dev/null || true)" ]]; then
  LIB_EMPTY=1
  if [[ -n "$(find "$OFFLINE/Vor/library" -type f -iname '*.pdf' -print -quit 2>/dev/null || true)" ]]; then
    say "Vor's library: the offline pack's publications"
    if cp -Rn "$OFFLINE/Vor/library/." "$RHOME/library/"; then ok "copied into $RHOME/library"
    else warn "some library files were not copied (see above)"; fi
    LIB_EMPTY=0
    if [[ "$NO_MODELS" == 0 && "$INDEX_KN" == 1 ]]; then
      ok "indexing them (a while for a full library; Ctrl+C is safe, then run: vor ingest)"
      VOR_HOME="$RHOME" "$VOR_DIR/python" "$VOR_DIR/vor.py" ingest || warn "the library index stopped; run: vor ingest"
    fi
  fi
fi

# ---------------------------------------------------------------------------
if [[ "$NO_MODELS" == 0 ]]; then
  say "Check (ai-doctor)"
  if [[ "$DO_HEIM" == 1 ]]; then
    VOR_HOME="$RHOME" VOR_TOOL="$VOR_DIR/vor.py" "$LOCAL_AI/python" "$LOCAL_AI/ai_doctor.py" \
      || warn "ai-doctor found a PROBLEM above: its line says what to run"
  else
    VOR_HOME="$RHOME" "$VOR_DIR/python" "$VOR_DIR/vor.py" doctor || warn "vor doctor found a PROBLEM above: its line says what to run"
  fi
fi

# ---------------------------------------------------------------------------
say "Step 5 — shell config ($RC)"
MARK="# >>> dam local AI (heim + vor) >>>"
# The block is REPLACED on every full install, not written once. It used to be skipped when
# its first line was already there, so a machine that had been installed once never received
# a command added later (heim-add, heim-chat): the installer said "already present" and the
# new command did not exist. Blocks written under the earlier names (pierre + dam-research)
# go too. A block with no closing line is left exactly as it is: someone edited it.
# A run that installs only one of the two AIs leaves an existing block alone, because
# rewriting it would drop the other AI's commands.
strip_ai_blocks() {
  awk '
    inb { buf = buf $0 "\n"; if ($0 ~ /^# <<< dam local AI <<<$/) { inb = 0; buf = "" }; next }
    /^# >>> dam local AI \(.*\) >>>$/ { inb = 1; buf = $0 "\n"; next }
    { print }
    END { if (inb) printf "%s", buf }' "$1"
}
# ai_block: the block itself (the same lines in ~/.bashrc / ~/.zshrc and in a sandbox's env.sh)
ai_block() {
    echo "$MARK"
    echo "export OLLAMA_MODELS=\"$MODELS_DIR\""
    echo "export OLLAMA_FLASH_ATTENTION=1"
    echo "export OLLAMA_KV_CACHE_TYPE=q8_0"
    if [[ -n "${OLLAMA_PORT:-}" ]]; then
      echo "export OLLAMA_HOST=\"127.0.0.1:$OLLAMA_PORT\""
      echo "export OLLAMA_URL=\"http://127.0.0.1:$OLLAMA_PORT\""
      echo "export HEIM_WATCH_URL=\"http://127.0.0.1:$OLLAMA_PORT\""
    fi
    if [[ -n "${SANDBOX:-}" ]]; then
      # the tools' defaults are ~/local-ai/...: everything they write stays in the sandbox
      echo "export HEIM_DB=\"$LOCAL_AI/knowledge.db\" HEIM_RUNS_DB=\"$LOCAL_AI/runs.db\" HEIM_REPORTS=\"$LOCAL_AI/reports\""
      echo "export DAMAUDIT_REPORTS=\"$LOCAL_AI/reports\" DAMAUDIT_GOLDEN=\"$LOCAL_AI/golden\""
      echo "export DAMCHAIN_BATCH_ROOT=\"$LOCAL_AI/qgis-batch\" DAMCHAIN_CREST_DIR=\"$LOCAL_AI/crest-desktop\" VOR_TOOL=\"$VOR_DIR/vor.py\""
      echo "export PIP_NO_CACHE_DIR=1 CONDA_PKGS_DIRS=\"$LOCAL_AI/conda-pkgs\" CONDA_REGISTER_ENVS=false"
      # the sandbox's own server (its key in $LOCAL_AI/.ollama, not ~/.ollama); stop: kill \$(cat .../ollama-serve.pid)
      echo "dam-ollama-serve() { ( HOME=\"$LOCAL_AI\" nohup \"$OLLAMA\" serve >>\"$LOCAL_AI/ollama-serve.log\" 2>&1 & echo \$! > \"$LOCAL_AI/ollama-serve.pid\" ); }"
    fi
    [[ "$DO_HEIM" == 1 ]] && echo "export HEIM_NUM_CTX=$NUM_CTX"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_query.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias damchain='\"$LOCAL_AI/python\" \"$LOCAL_AI/dam_chain.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-chat='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_query.py\" --chat'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-add='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_index.py\" --add'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-doctor='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_index.py\" --doctor'"
    [[ "$DO_HEIM" == 1 ]] && echo "export HEIM_WATCH_MODEL=\"${WATCH_MODEL:-qwen3:4b}\""
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-digest='\"$LOCAL_AI/python\" \"$LOCAL_AI/run_digest.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-watch='\"$LOCAL_AI/python\" \"$LOCAL_AI/heim_watch.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-runs='\"$LOCAL_AI/python\" \"$LOCAL_AI/run_results.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias ai-doctor='\"$LOCAL_AI/python\" \"$LOCAL_AI/ai_doctor.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias ai='\"$LOCAL_AI/python\" \"$LOCAL_AI/ai_ui.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias ai-score='\"$LOCAL_AI/python\" \"$LOCAL_AI/ai_score.py\"'"
    [[ "$DO_HEIM" == 1 ]] && echo "alias heim-index='\"$LOCAL_AI/python\" \"$LOCAL_AI/rag_index.py\"'"
    [[ "$DO_VOR" == 1 ]] && echo "export VOR_HOME=\"$RHOME\""
    [[ "$DO_VOR" == 1 ]] && echo "alias vor='\"$VOR_DIR/python\" \"$VOR_DIR/vor.py\"'"
    echo "# <<< dam local AI <<<"
}
WRITE_BLOCK=1
if [[ -n "${SANDBOX:-}" ]]; then
  # --prefix: the sandbox's own file, written whole; ~/.bashrc and ~/.zshrc are not opened
  { echo "# dam local AIs in the sandbox $SANDBOX: source this file ( . $RC ). Nothing was added to ~/.bashrc or ~/.zshrc."
    ai_block; } > "$RC"
  ok "commands written to $RC (source it; ~/.bashrc and ~/.zshrc left alone)"
  WRITE_BLOCK=0
elif grep -q '^# >>> dam local AI (.*) >>>$' "$RC" 2>/dev/null; then
  if [[ "$DO_HEIM" == 1 && "$DO_VOR" == 1 ]]; then
    cp "$RC" "$RC.bak-localai"
    strip_ai_blocks "$RC.bak-localai" > "$RC.tmp-localai" && cat "$RC.tmp-localai" > "$RC"
    rm -f "$RC.tmp-localai"
  elif grep -qF "$MARK" "$RC"; then
    WRITE_BLOCK=0
  fi
fi
if [[ "$WRITE_BLOCK" == 1 ]]; then
  [[ -f "$RC.bak-localai" ]] || cp "$RC" "$RC.bak-localai" 2>/dev/null || true
  {
    [[ -s "$RC" && -n "$(tail -n 1 "$RC")" ]] && echo ""
    ai_block
  } >> "$RC"
  ok "aliases written to $RC (backup: $RC.bak-localai)"
elif [[ -z "${SANDBOX:-}" ]]; then
  warn "shell block in $RC left as it is: this run installs only one of the two AIs. Run without --no-heim / --no-vor to refresh it."
fi

# ---------------------------------------------------------------------------
say "Done"
if [[ -n "$SANDBOX" ]]; then cat <<EOF
  Sandbox $SANDBOX: in each shell run  . $RC  (its Ollama: $OLLAMA_HOST_URL; start it again with dam-ollama-serve).
  To remove it: kill \$(cat $LOCAL_AI/ollama-serve.pid), then delete $SANDBOX.
  Try it now (after  . $RC ):
EOF
else cat <<EOF
  Try it now. Open a new terminal window first (or run: source $RC), then:
EOF
fi
[[ "$DO_VOR" == 1 ]] && echo "    vor \"what breach width does Froehlich 2008 give?\"     answered from your library, quotes checked"
[[ "$DO_HEIM" == 1 ]] && echo "    heim \"what does REFINE_NEAR do?\"                      the suite's tools and known behaviours"
[[ "$DO_HEIM" == 1 ]] && echo "    ai                                                     both on one page in your browser"
[[ "$DO_HEIM" == 1 ]] && echo "    heim help                                              the short list of commands"
if [[ "$DO_VOR" == 1 && "$LIB_EMPTY" == 1 ]]; then cat <<EOF
  Vor's library is empty, so vor has nothing to quote yet. Add your own PDFs:  vor add FILE ...
  or fetch the starter library of public dam-safety publications (a few hundred MB), then index it:
    "$VOR_DIR/python" "$VOR_DIR/fetch_asdso.py" --catalog
    vor ingest
EOF
fi
echo "  Check it again any time:  ai-doctor     Everything this printed:  $INSTALL_LOG"
[[ "$DO_HEIM" == 1 ]] && echo "  For developers: set ND_REPO / DWR_REPO / CREST_REPO to your clones, then  heim \"where is the breach width computed\""
cat <<EOF
  openSUSE GUI-QGIS note (only if you also run the plugins here): a conda QGIS may need system
  GL/X libraries. If the xcb platform plugin fails, install them with:
    sudo zypper install -y Mesa-libGL1 libxcb-cursor0 libxkbcommon-x11-0
  The local AIs themselves need none of that.
EOF
exit 0
