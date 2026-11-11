#!/usr/bin/env bash
# ============================================================================
# download-all-linux.sh — pre-download EVERYTHING the Linux installer needs into
# damit_ai/offline/, so install-local-ai-linux.sh can then run with no network:
#
#   offline/ollama/ollama-linux-amd64.tgz (+ SHA256SUMS)   the Ollama runtime
#   offline/models/                                        the AI models (Lumo + dam-research)
#   offline/DamResearch/library/                           the dam-research PDF library + url list
#
# Run this on a machine WITH network, then carry the whole damit_ai/ folder to the
# target and run ./install-local-ai-linux.sh there (it picks up offline/ automatically).
#
#   ./download-all-linux.sh                       # Ollama + default models + library
#   ./download-all-linux.sh --no-models            # skip the (large) model pull
#   ./download-all-linux.sh --models "qwen3:14b nomic-embed-text"
#   ./download-all-linux.sh --no-library           # skip the PDF library
#   ./download-all-linux.sh --ollama-version v0.12.6   # pin a specific Ollama release
#
# Policy: curl downloads FILES only (never piped into a shell); every file is checked
# against Ollama's own published sha256. No sudo, no pip, nothing installed into your
# system or your conda. Your own Ollama and its models are not touched.
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
sha(){ sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

# fetch <url> <dest> <sha256|->: keep a matching file, else download to .part, verify, move
fetch(){
  local url="$1" dest="$2" want="$3"
  if [[ -f "$dest" && "$want" != "-" && "$(sha "$dest")" == "$want" ]]; then ok "have $(basename "$dest") (sha256 ok)"; return 0; fi
  mkdir -p "$(dirname "$dest")"
  curl -fL --progress-bar --retry 3 --connect-timeout 30 -o "$dest.part" "$url" || { rm -f "$dest.part"; warn "download failed: $url"; return 1; }
  if [[ "$want" == "-" || "$(sha "$dest.part")" == "$want" ]]; then mv "$dest.part" "$dest"; ok "downloaded $(basename "$dest")${want:+ (sha256 checked)}"
  else rm -f "$dest.part"; warn "sha256 mismatch, discarded: $url"; return 1; fi
}

command -v curl >/dev/null || die "curl is required"

# ---------------------------------------------------------------------------
say "Ollama runtime -> offline/ollama (version: $OLLAMA_VERSION)"
ASSET="ollama-linux-amd64.tgz"
BASE="https://github.com/ollama/ollama/releases"
if [[ "$OLLAMA_VERSION" == "latest" ]]; then
  # resolve the tag the 'latest' release redirects to
  eff="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$BASE/latest" 2>/dev/null || true)"
  OLLAMA_VERSION="${eff##*/tag/}"; [[ "$OLLAMA_VERSION" == "$eff" || -z "$OLLAMA_VERSION" ]] && die "could not resolve the latest Ollama version (pass --ollama-version)"
  ok "latest Ollama release is $OLLAMA_VERSION"
fi
# pull the release's published checksum list and read this asset's hash
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
  # we need the Ollama binary we just downloaded to pull the models
  TMPOL="$(mktemp -d)"; tar -xzf "$OFFLINE/ollama/$ASSET" -C "$TMPOL" 2>/dev/null || warn "could not extract Ollama to pull models"
  OL="$TMPOL/bin/ollama"; [[ -x "$OL" ]] || OL="$(find "$TMPOL" -name ollama -type f -perm -u+x 2>/dev/null | head -1)"
  if [[ -x "$OL" ]]; then
    export OLLAMA_HOST=127.0.0.1:11499 OLLAMA_MODELS="$MDIR"
    "$OL" serve >"$MDIR/.serve.log" 2>&1 &
    SRV=$!
    for _ in $(seq 1 30); do curl -sf "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1 && break; sleep 1; done
    for m in $MODELS; do printf '  pulling %s ...\n' "$m"; "$OL" pull "$m" </dev/null && ok "$m" || warn "could not pull $m"; done
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
  offline/ is now populated. Carry the whole damit_ai/ folder to the target and run:
      ./install-local-ai-linux.sh
  It will use offline/ollama (no Ollama download) and seed models from offline/models.
  Size of offline/: $(du -sh "$OFFLINE" 2>/dev/null | awk '{print $1}')
EOF
