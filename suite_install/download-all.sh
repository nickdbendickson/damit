#!/bin/bash
# =============================================================================
# download-all.sh  -  fill this package's offline/ folder so install-all can run
#                     with NO network (Linux or macOS host; bash 3.2 is fine)
# =============================================================================
#
# Downloads, for each platform you ask for, every file the installer needs:
#   offline/conda/<platform>/<subdir>/ QGIS 3.34, ANUGA 4.1 + gmsh 4.15, the local-AI env
#                                    (and macOS/Linux build tools): exactly the packages
#                                    pinned in locks/<platform>/*.lock
#   offline/miniforge/               the pinned Miniforge installer
#   offline/lisflood-src/            LISFLOOD-FP 8.3 source (macOS builds it at install)
#   damit_ai/offline/ollama/         the pinned Ollama runtime for that platform
#   damit_ai/offline/models/         the AI models (pulled once; same files on every OS)
#   damit_ai/offline/Vor/    the vor reference library
#
#   bash download-all.sh                          # this machine's platform
#   bash download-all.sh --platform win-64        # build a Windows set from a Mac / Linux box
#   bash download-all.sh --platform all           # linux-64 osx-arm64 osx-64 win-64
#   bash download-all.sh --no-models --no-library # just the installers + conda packages
#   bash download-all.sh --models "qwen3:14b nomic-embed-text"
#   bash download-all.sh --pack                   # also zip each platform's set (offline-<platform>.zip)
#
# Every file is checked against the sha256 pinned in locks/ (or, for models, Ollama's own
# digests) before it is put in place. A cut-off download is resumed, not restarted, and up to 4
# passes run by themselves (DAMSUITE_DL_PASSES; DAMSUITE_DL_PARALLEL sets how many files download
# at once, default 3). curl downloads files only; nothing downloaded is
# run, except the pinned Ollama binary used on a side port (127.0.0.1:11499) to pull models.
# No sudo, no pip, nothing installed. Re-run any time: files already OK are skipped.
# =============================================================================
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LOCKS="$HERE/locks"
PLATS=""; DO_MODELS=1; DO_LIBRARY=1; PACK=0
MODELS="${DAMSUITE_MODELS:-qwen3:30b-a3b qwen3:14b nomic-embed-text qwen3-embedding:0.6b}"
while [ $# -gt 0 ]; do
  case "$1" in
    --platform) shift; PLATS="$PLATS ${1:?--platform needs a value}" ;;
    --no-models) DO_MODELS=0 ;;
    --models) shift; MODELS="${1:-}" ;;
    --no-library) DO_LIBRARY=0 ;;
    --pack) PACK=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  ok  %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
sha()  { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }
command -v curl >/dev/null 2>&1 || die "curl is needed"
[ -d "$LOCKS" ] || die "no locks/ folder next to this script"

host_platform() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) echo linux-64 ;; Darwin-arm64) echo osx-arm64 ;; Darwin-x86_64) echo osx-64 ;;
    *) echo unsupported ;;
  esac
}
HOST="$(host_platform)"
[ -n "$PLATS" ] || PLATS="$HOST"
case " $PLATS " in *" all "*) PLATS="linux-64 osx-arm64 osx-64 win-64" ;; esac
for p in $PLATS; do [ -d "$LOCKS/$p" ] || die "no locks for platform '$p' (have: $(ls "$LOCKS" | tr '\n' ' '))"; done

# fetch_list <listfile>: lines "<url> <dest> <sha256>". Each missing file is downloaded to
# <dest>.part and moved into place only once its sha256 matches. Built for flaky links
# (2026-11-16: 8 big osx-64 packages died with "connection reset" / "broken pipe" when 8 ran at
# once, and the truncated files were then deleted as sha256 mismatches):
#   - DAMSUITE_DL_PARALLEL (default 3) transfers at a time, not 8;
#   - curl retries every error, including resets mid-transfer (--retry-all-errors), and drops a
#     connection that stalls below 1 KB/s for 60 s;
#   - a cut-off .part is RESUMED (-C -) on the next pass, not deleted;
#   - up to DAMSUITE_DL_PASSES (default 4) passes run by themselves, with a pause between.
# A .part that did not grow during a pass and still fails its sha256 is deleted (it is corrupt,
# not short) and starts over on the next pass. Anything still missing at the end is counted.
BAD=0
DL_PARALLEL="${DAMSUITE_DL_PARALLEL:-3}"
DL_PASSES="${DAMSUITE_DL_PASSES:-4}"
CURL_VER="$(curl --version 2>/dev/null | awk 'NR==1 {print $2}')"
curl_at_least() {  # curl_at_least 7 71
  local maj min; maj="${CURL_VER%%.*}"; min="${CURL_VER#*.}"; min="${min%%.*}"
  [ "${maj:-0}" -gt "$1" ] 2>/dev/null || { [ "${maj:-0}" -eq "$1" ] && [ "${min:-0}" -ge "$2" ]; } 2>/dev/null
}
CURL_OPTS="-fsSL --connect-timeout 30 --speed-limit 1024 --speed-time 60 --retry 5 --retry-delay 5 -C -"
if curl_at_least 7 71; then CURL_OPTS="$CURL_OPTS --retry-all-errors"; fi
if curl_at_least 7 66 && [ "$DL_PARALLEL" -gt 1 ] 2>/dev/null; then CURL_PAR="--parallel --parallel-max $DL_PARALLEL"; else CURL_PAR=""; fi
fsize() { if [ -f "$1" ]; then wc -c < "$1" | tr -d ' '; else echo 0; fi; }

fetch_list() {
  local list="$1" cfg sizes n pass=1 url dest want before after left
  cfg="$(mktemp)"; sizes="$(mktemp)"
  while :; do
    : > "$cfg"; : > "$sizes"; n=0
    while read -r url dest want; do
      [ -n "$url" ] || continue
      if [ -f "$dest" ] && [ "$(sha "$dest")" = "$want" ]; then continue; fi
      mkdir -p "$(dirname "$dest")"; rm -f "$dest"
      # a .part left complete by an interrupted run: just move it into place
      if [ -f "$dest.part" ] && [ "$(sha "$dest.part")" = "$want" ]; then mv -f "$dest.part" "$dest"; continue; fi
      printf 'url = "%s"\noutput = "%s"\n' "$url" "$dest.part" >> "$cfg"
      echo "$dest $(fsize "$dest.part")" >> "$sizes"; n=$((n+1))
    done < "$list"
    [ "$n" -gt 0 ] || break
    if [ "$pass" -gt "$DL_PASSES" ]; then
      while read -r dest before; do
        warn "still missing after $DL_PASSES passes: $(basename "$dest")"; BAD=$((BAD+1))
      done < "$sizes"
      warn "re-run to carry on: finished files are kept and partial ones (.part) resume"
      break
    fi
    echo "  downloading $n file(s), $DL_PARALLEL at a time (pass $pass of $DL_PASSES) ..."
    # shellcheck disable=SC2086
    curl $CURL_OPTS $CURL_PAR -K "$cfg" || echo "  some downloads were cut off; checking ..."
    while read -r dest before; do
      after="$(fsize "$dest.part")"
      want="$(awk -v d="$dest" '$2==d {print $3; exit}' "$list")"
      if [ -f "$dest.part" ] && [ "$(sha "$dest.part")" = "$want" ]; then mv -f "$dest.part" "$dest"
      elif [ "$after" -le "$before" ]; then rm -f "$dest.part"; fi
    done < "$sizes"
    pass=$((pass+1))
    if [ "$pass" -le "$DL_PASSES" ] && grep -q . "$sizes"; then
      left=0; while read -r dest before; do [ -f "$dest" ] || left=$((left+1)); done < "$sizes"
      if [ "$left" -gt 0 ]; then echo "  $left file(s) not finished; pass $pass in $((pass*10)) s ..."; sleep $((pass*10)); fi
    fi
  done
  rm -f "$cfg" "$sizes"
}

# ---------------------------------------------------------------------------
for P in $PLATS; do
  say "Platform $P"
  LIST="$(mktemp)"
  # conda packages (one copy of each, even when several envs use it)
  cat "$LOCKS/$P"/*.lock | grep -v '^#' | awk -v d="$HERE/offline/conda/$P" 'NF>=3 {k=split($1,a,"/"); print $1, d"/"a[k-1]"/"a[k], $2}' | sort -u -k2,2 > "$LIST"
  echo "  conda packages: $(wc -l < "$LIST" | tr -d ' ')"
  # Miniforge, Ollama, LISFLOOD-FP source
  awk -v p="$P" -v h="$HERE" '!/^#/ && $1==p && $2!="ollama-pull" {print $4, h"/"$3, $5}' "$LOCKS/extra.lock" >> "$LIST"
  fetch_list "$LIST"; rm -f "$LIST"
  # damit_ai's installers check the Ollama file against this list
  OD="$HERE/damit_ai/offline/ollama"
  if [ -d "$OD" ]; then
    awk '!/^#/ && $2=="ollama" {n=$3; sub(/.*\//,"",n); print $5"  "n}' "$LOCKS/extra.lock" | sort -u | while read -r h n; do
      if [ -f "$OD/$n" ]; then echo "$h  $n"; fi; done > "$OD/SHA256SUMS"
  fi
  ok "$P: $(du -sh "$HERE/offline/conda/$P" 2>/dev/null | awk '{print $1}') of conda packages"
done

# ---------------------------------------------------------------------------
# models: pulled once with this machine's own (pinned) Ollama on a side port
if [ "$DO_MODELS" = 1 ] && [ -n "$MODELS" ]; then
  say "AI models -> damit_ai/offline/models: $MODELS"
  MDIR="$HERE/damit_ai/offline/models"; mkdir -p "$MDIR"
  T="$(mktemp -d)"; OL=""
  case "$HOST" in
    linux-64)
      L="$(awk '!/^#/ && $1=="linux-64" && $2=="ollama" {print $4, $5}' "$LOCKS/extra.lock")"
      F="$T/ollama.tar.zst"; echo "${L%% *} $F ${L##* }" > "$T/l"; fetch_list "$T/l"
      if [ -f "$F" ] && tar --zstd -xf "$F" -C "$T" 2>/dev/null; then OL="$T/bin/ollama"; fi ;;
    osx-*)
      L="$(awk '!/^#/ && $1=="osx-arm64" && $2=="ollama" {print $4, $5}' "$LOCKS/extra.lock")"
      F="$T/Ollama-darwin.zip"; echo "${L%% *} $F ${L##* }" > "$T/l"; fetch_list "$T/l"
      if [ -f "$F" ] && (cd "$T" && unzip -q Ollama-darwin.zip); then OL="$(find "$T" -path '*Contents/Resources/ollama' -type f | head -1)"; fi ;;
  esac
  if [ -n "$OL" ] && [ -x "$OL" ]; then
    OLLAMA_HOST=127.0.0.1:11499 OLLAMA_MODELS="$MDIR" "$OL" serve > "$T/serve.log" 2>&1 &
    SRV=$!
    i=0; while [ $i -lt 30 ]; do curl -sf http://127.0.0.1:11499/api/version >/dev/null 2>&1 && break; sleep 1; i=$((i+1)); done
    for m in $MODELS; do
      echo "  pulling $m ..."
      if OLLAMA_HOST=127.0.0.1:11499 "$OL" pull "$m" </dev/null; then ok "$m"; else warn "could not pull $m"; BAD=$((BAD+1)); fi
    done
    kill "$SRV" 2>/dev/null || true; wait "$SRV" 2>/dev/null || true
    rm -f "$MDIR/.serve.log"
    ok "models: $(du -sh "$MDIR" | awk '{print $1}')"
  else
    warn "no Ollama binary to pull models with on this machine ($HOST); models skipped (the AI installer pulls them online instead)"
  fi
  rm -rf "$T"
fi

# ---------------------------------------------------------------------------
if [ "$DO_LIBRARY" = 1 ]; then
  say "vor library -> damit_ai/offline/Vor/library"
  FA="$HERE/damit_ai/vor/fetch_asdso.py"; PY="$(command -v python3 || true)"
  if [ -f "$FA" ] && [ -n "$PY" ]; then
    LIB="$HERE/damit_ai/offline/Vor"; mkdir -p "$LIB/library"
    VOR_HOME="$LIB" "$PY" "$FA" --catalog --asdso || warn "some library files failed (see $LIB)"
    ok "library: $(du -sh "$LIB/library" | awk '{print $1}')"
  else
    warn "library skipped (needs python3 and damit_ai/vor/fetch_asdso.py)"
  fi
fi

# ---------------------------------------------------------------------------
if [ "$PACK" = 1 ]; then
  say "Packing offline sets"
  cd "$HERE"
  for P in $PLATS; do
    Z="offline-$P.zip"; rm -f "$Z"
    ITEMS="offline/conda/$P"
    for f in $(awk -v p="$P" '!/^#/ && $1==p && $2!="ollama-pull" {print $3}' "$LOCKS/extra.lock" | sort -u); do if [ -f "$f" ]; then ITEMS="$ITEMS $f"; fi; done
    if [ -f damit_ai/offline/ollama/SHA256SUMS ]; then ITEMS="$ITEMS damit_ai/offline/ollama/SHA256SUMS"; fi
    # shellcheck disable=SC2086
    # `zip && ok` reported success only when zip succeeded, but said NOTHING when it failed
    # (the first element of an && list is exempt from errexit), so a failed pack looked the
    # same as no pack at all.
    if zip -q -r -0 "$Z" $ITEMS -x "*.part"; then
      ok "$Z ($(du -h "$Z" | awk '{print $1}')); unzip it in this folder on the target"
    else
      warn "could not pack $Z"; BAD=$((BAD+1))
    fi
  done
fi

say "Done$( [ "$BAD" -gt 0 ] && echo " with $BAD problem(s): re-run the same command to carry on" )"
echo "  Now run the installer from this folder (it uses offline/ and downloads nothing):"
echo "    Linux / macOS:  bash install-all.sh        Windows:  install-all-windows.cmd"
[ "$BAD" -eq 0 ]
