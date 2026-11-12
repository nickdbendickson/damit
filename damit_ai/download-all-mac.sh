#!/usr/bin/env zsh
# ============================================================================
# download-all-mac.sh — pre-download EVERYTHING the macOS installers need into
# damit_ai/offline/, so setup-local-pierre.sh / setup-dam-research.zsh can then run
# with no network:
#
#   offline/ollama/Ollama-darwin.zip (+ SHA256SUMS)   the Ollama app
#   offline/models/                                   the AI models (Pierre + dam-research)
#   offline/DamResearch/library/                      the dam-research PDF library + url list
#
# Run this on a Mac WITH network, then carry the whole damit_ai/ folder to the target
# Mac and run the installers there (they pick up offline/ automatically and seed the
# models from offline/models). This is the local-AI-only counterpart of the full suite
# package's download_everything.sh — it does only the two AIs, not the QGIS/Crest suite.
#
#   ./download-all-mac.sh                       # Ollama + default models + library
#   ./download-all-mac.sh --no-models            # skip the (large) model pull
#   ./download-all-mac.sh --models "qwen3:14b nomic-embed-text"
#   ./download-all-mac.sh --no-library           # skip the PDF library
#   ./download-all-mac.sh --ollama-version v0.12.6
#
# Policy: curl downloads FILES only (never piped into a shell); every file is checked
# against Ollama's own published sha256. No sudo, no pip, nothing installed into your
# system or your conda. Your own Ollama and its models are not touched.
# ============================================================================
set -e
HERE="${0:A:h}"
OFFLINE="$HERE/offline"
PY=${PYTHON:-python3}
DO_MODELS=1; DO_LIBRARY=1; OLLAMA_VERSION="${OLLAMA_VERSION:-latest}"
MODELS="qwen3:30b-a3b qwen3:14b nomic-embed-text qwen3-embedding:0.6b"

while [[ $# -gt 0 ]]; do case "$1" in
  --no-models) DO_MODELS=0 ;;
  --models) shift; MODELS="${1:-}" ;;
  --no-library) DO_LIBRARY=0 ;;
  --ollama-version) shift; OLLAMA_VERSION="${1:-latest}" ;;
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 1 ;;
esac; shift; done

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok(){ printf '  \033[32mok\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mwarn\033[0m %s\n' "$*" >&2; }
die(){ printf '  \033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }
sha(){ shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

# fetch <url> <dest> <sha256|->: keep a matching file, else download to .part, verify, move
fetch(){
  local url="$1" dest="$2" want="$3"
  if [[ -f "$dest" && "$want" != "-" && "$(sha "$dest")" == "$want" ]]; then ok "have ${dest:t} (sha256 ok)"; return 0; fi
  mkdir -p "${dest:h}"
  curl -fL --progress-bar --retry 3 --connect-timeout 30 -o "$dest.part" "$url" || { rm -f "$dest.part"; warn "download failed: $url"; return 1; }
  if [[ "$want" == "-" || "$(sha "$dest.part")" == "$want" ]]; then mv "$dest.part" "$dest"; ok "downloaded ${dest:t}${want:+ (sha256 checked)}"
  else rm -f "$dest.part"; warn "sha256 mismatch, discarded: $url"; return 1; fi
}

command -v curl >/dev/null || die "curl is required"

# ---------------------------------------------------------------------------
say "Ollama app -> offline/ollama (version: $OLLAMA_VERSION)"
ASSET="Ollama-darwin.zip"
BASE="https://github.com/ollama/ollama/releases"
if [[ "$OLLAMA_VERSION" == "latest" ]]; then
  eff="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$BASE/latest" 2>/dev/null || true)"
  OLLAMA_VERSION="${eff##*/tag/}"; [[ "$OLLAMA_VERSION" == "$eff" || -z "$OLLAMA_VERSION" ]] && die "could not resolve the latest Ollama version (pass --ollama-version)"
  ok "latest Ollama release is $OLLAMA_VERSION"
fi
SUMS_TMP="$(mktemp)"; trap 'rm -f "$SUMS_TMP"' EXIT
curl -fsSL -o "$SUMS_TMP" "$BASE/download/$OLLAMA_VERSION/sha256sum.txt" || warn "could not fetch sha256sum.txt (will download unverified)"
WANT="$(awk -v a="$ASSET" '$2 ~ a"$" || $2 == a {print $1}' "$SUMS_TMP" 2>/dev/null | head -1)"
[[ -n "$WANT" ]] && ok "published sha256 for $ASSET: $WANT" || { WANT="-"; warn "no published hash for $ASSET"; }
fetch "$BASE/download/$OLLAMA_VERSION/$ASSET" "$OFFLINE/ollama/$ASSET" "$WANT" \
  && printf '%s  %s\n' "$(sha "$OFFLINE/ollama/$ASSET")" "$ASSET" > "$OFFLINE/ollama/SHA256SUMS" \
  && ok "wrote offline/ollama/SHA256SUMS"

# ---------------------------------------------------------------------------
if (( DO_MODELS )); then
  say "AI models -> offline/models: $MODELS"
  MDIR="$OFFLINE/models"; mkdir -p "$MDIR"
  TMPOL="$(mktemp -d)"; ( cd "$TMPOL" && unzip -q "$OFFLINE/ollama/$ASSET" ) 2>/dev/null || warn "could not unzip Ollama to pull models"
  OL="$TMPOL/Ollama.app/Contents/Resources/ollama"
  [[ -x "$OL" ]] || OL="$(find "$TMPOL" -name ollama -type f -perm -u+x 2>/dev/null | head -1)"
  if [[ -x "$OL" ]]; then
    export OLLAMA_HOST=127.0.0.1:11499 OLLAMA_MODELS="$MDIR"
    "$OL" serve >"$MDIR/.serve.log" 2>&1 &
    SRV=$!
    for _ in {1..30}; do curl -sf "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1 && break; sleep 1; done
    for m in ${=MODELS}; do printf '  pulling %s ...\n' "$m"; "$OL" pull "$m" </dev/null && ok "$m" || warn "could not pull $m"; done
    kill "$SRV" 2>/dev/null || true; wait "$SRV" 2>/dev/null || true
    unset OLLAMA_HOST OLLAMA_MODELS
    ok "models in $MDIR ($(du -sh "$MDIR" 2>/dev/null | awk '{print $1}'))"
  else
    warn "no Ollama binary to pull models with; skipped"
  fi
  rm -rf "$TMPOL"
fi

# ---------------------------------------------------------------------------
if (( DO_LIBRARY )); then
  say "dam-research library -> offline/DamResearch/library"
  LIB="$OFFLINE/DamResearch"; mkdir -p "$LIB/library"
  if [[ -f "$HERE/research/fetch_asdso.py" ]]; then
    DAMRESEARCH_HOME="$LIB" "$PY" "$HERE/research/fetch_asdso.py" --urls "$LIB/library/library-urls.txt" || true
    DAMRESEARCH_HOME="$LIB" "$PY" "$HERE/research/fetch_asdso.py" --catalog --asdso || warn "some library files failed (see its sources.csv / log)"
    ok "library in $LIB/library"
  else
    warn "research/fetch_asdso.py not found; skipped"
  fi
fi

# ---------------------------------------------------------------------------
say "Done"
cat <<EOF
  offline/ is now populated. Carry the whole damit_ai/ folder to the target Mac and run:
      zsh pierre/setup-local-pierre.sh
      zsh research/setup-dam-research.zsh
  They use offline/ollama (no Ollama download) and seed models from offline/models.
  Size of offline/: $(du -sh "$OFFLINE" 2>/dev/null | awk '{print $1}')
EOF
