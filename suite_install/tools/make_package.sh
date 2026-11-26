#!/bin/bash
# Build the dam-suite install-all package (maintainers; Linux or macOS with git + python3).
#
#   bash suite_install/tools/make_package.sh --dwr ../DWR_Plugins --out /tmp/dam-suite-all
#        [--lisflood-bin DIR]   DIR/linux-x64/lisflood and DIR/windows-x64/lisflood.exe
#                               (default: build them here from the official 8.3 source with
#                               DWR_Plugins' Runner scripts; Windows needs MinGW-w64)
#        [--desk DIR]           DamIT Desk: a checkout of nickdbendickson/damit-desk, shipped as damit_desk/
#                               (the one desk, with United States and North Dakota profiles; Nick, 2026-11-22).
#                               Default: ../damit-desk next to this damit checkout when it is there;
#                               --desk none leaves the desk out. DamIT Crest (damit_crest/) and the North
#                               Dakota Crest desk (DWR_Plugins dwr_crest/) are retired and no longer shipped;
#                               --crest is accepted and ignored so older build commands still run
#        [--zip]                also write <out>.zip
#        [--no-boann-windows]   leave out Boann's Windows CPU engine (see below)
#
# Boann on Windows: a Windows PC has no C++ compiler, so it runs Boann only from CPU libraries
# shipped in the plugin zips. When MinGW-w64 is here (x86_64-w64-mingw32-g++[-posix]; on a Mac
# `brew install mingw-w64`), they are built for windows-x64 from each checkout's own Boann (DWR's
# into the DamSafety Core zip, damit's into the DamIT Runner zip) the way the releases build them;
# without it the package says so and Windows PCs fall back to LISFLOOD-FP.
#
# The package = suite_install's scripts + locks, the DamSafety plugin zips (DWR_Plugins
# tools/build_release.py: committed files only), the DamIT plugin zips (scripts/package_plugins.py),
# LISFLOOD-FP binaries + the macOS build script, damit_ai/ and the Absaraka run folder.
# The big files (conda packages, Miniforge, Ollama, models) are NOT in it: download-all fetches
# them into offline/, or `download-all.sh --platform X --pack` makes offline-X.zip.
set -eo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"        # suite_install/
DAMIT="$(cd "$HERE/.." && pwd)"
DWR=""; OUT=""; LFBIN=""; ZIP=0; DESK=""; BOANN_WIN=1
while [ $# -gt 0 ]; do case "$1" in
  --dwr) DWR="$(cd "$2" && pwd)"; shift ;; --out) OUT="$2"; shift ;;
  --lisflood-bin) LFBIN="$(cd "$2" && pwd)"; shift ;; --zip) ZIP=1 ;; --no-boann-windows) BOANN_WIN=0 ;;
  --desk) if [ "$2" = none ]; then DESK=none; else DESK="$(cd "$2" && pwd)"; fi; shift ;;
  --crest) echo "--crest is retired (the Crest desks are replaced by DamIT Desk, --desk); ignored" >&2; shift ;;
  *) echo "unknown option $1" >&2; exit 2 ;; esac; shift; done
[ -n "$DWR" ] && [ -f "$DWR/tools/build_release.py" ] || { echo "--dwr <DWR_Plugins checkout> is required" >&2; exit 2; }
[ -n "$OUT" ] || { echo "--out is required" >&2; exit 2; }
if [ -z "$DESK" ] && [ -f "$DAMIT/../damit-desk/app/desktop/run.py" ]; then DESK="$(cd "$DAMIT/../damit-desk" && pwd)"; fi
[ "$DESK" != none ] || DESK=""
[ -z "$DESK" ] || [ -f "$DESK/app/desktop/run.py" ] || { echo "--desk: no app/desktop/run.py in $DESK" >&2; exit 2; }
[ -n "$DESK" ] || echo "note: no damit-desk checkout (--desk DIR): the package has no desk" >&2
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

rm -rf "$OUT"; mkdir -p "$OUT"
cp "$HERE"/install-all.sh "$HERE"/download-all.sh "$HERE"/install-all-windows.ps1 "$HERE"/install-all-windows.cmd \
   "$HERE"/download-all-windows.ps1 "$HERE"/download-all-windows.cmd "$HERE"/README.md "$OUT"/
cp -R "$HERE/locks" "$OUT/locks"
chmod +x "$OUT"/*.sh
DWR_C="$(git -C "$DWR" rev-parse --short HEAD)"; DAMIT_C="$(git -C "$DAMIT" rev-parse --short HEAD)"
DESK_C=""; [ -n "$DESK" ] && DESK_C=", damit-desk $(git -C "$DESK" rev-parse --short HEAD)"
echo "$(date +%Y-%m-%d) (DWR_Plugins $DWR_C, damit $DAMIT_C$DESK_C)" > "$OUT/VERSION"

echo "== plugins"
T="$(mktemp -d)"
DS_BOANN=(); DI_PREBUILT="$DAMIT/damit_runner/boann/hydro/prebuilt/windows-x64"; DI_PREBUILT_MADE=0
if [ "$BOANN_WIN" = 1 ]; then
  MINGW=""; for c in x86_64-w64-mingw32-g++-posix x86_64-w64-mingw32-g++; do
    if command -v "$c" >/dev/null 2>&1; then MINGW="$c"; break; fi; done
  if [ -z "$MINGW" ]; then
    echo "note: no MinGW-w64 (x86_64-w64-mingw32-g++): no Boann CPU engine for Windows in this package (Windows PCs use LISFLOOD-FP)" >&2
  elif [ -e "$DI_PREBUILT" ]; then
    echo "note: $DI_PREBUILT already exists; remove it first. No Boann CPU engine for Windows in this package" >&2
  elif python3 "$DWR/tools/build_boann_cpu.py" --out "$T/boann-ds" --platform windows-x64 --cxx "$MINGW" --extra=-static > "$T/boann-ds.log" 2>&1 \
       && python3 "$DAMIT/scripts/build_boann_cpu.py" --out "$T/boann-di" --platform windows-x64 --cxx "$MINGW" --extra=-static > "$T/boann-di.log" 2>&1; then
    DS_BOANN=(--boann-cpu "$T/boann-ds")
    mkdir -p "$DI_PREBUILT"; cp "$T"/boann-di/windows-x64/* "$DI_PREBUILT/"; DI_PREBUILT_MADE=1
    echo "Boann CPU engine for Windows: $(ls "$T/boann-ds/windows-x64" | wc -l | tr -d ' ') DamSafety + $(ls "$DI_PREBUILT" | wc -l | tr -d ' ') DamIT libraries ($MINGW)"
  else
    echo "note: the Boann Windows build failed (see $T/boann-ds.log, $T/boann-di.log): no Boann CPU engine for Windows in this package" >&2
  fi
fi
python3 "$DWR/tools/build_release.py" --out "$T/ds" "${DS_BOANN[@]}" >/dev/null
python3 "$DAMIT/scripts/package_plugins.py" "$T/di" >/dev/null
# the libraries were only borrowed into the checkout for packaging (never committed: .gitignore)
if [ "$DI_PREBUILT_MADE" = 1 ]; then rm -rf "$DI_PREBUILT"; rmdir "$(dirname "$DI_PREBUILT")" 2>/dev/null || true; fi
mkdir -p "$OUT/plugins/damsafety" "$OUT/plugins/damit"
cp "$T"/ds/*.zip "$OUT/plugins/damsafety/"; cp "$T"/di/*.zip "$OUT/plugins/damit/"
{ echo "# Plugins in this package"; echo
  echo "Source: DWR_Plugins $DWR_C (DamSafety, profile damsafety) and damit $DAMIT_C (DamIT, profile damit)."; echo
  echo "| DamSafety | version |"; echo "|---|---|"
  for z in "$OUT"/plugins/damsafety/*.zip; do b="$(basename "$z" .zip)"; echo "| ${b%_*} | ${b##*_} |"; done
  echo; echo "| DamIT | version |"; echo "|---|---|"
  for z in "$OUT"/plugins/damit/*.zip; do b="$(basename "$z" .zip)"; n="$(echo "$b" | sed -E 's/_[0-9]+_[0-9]+_[0-9]+$//')"
    v="$(echo "$b" | sed -E 's/.*_([0-9]+)_([0-9]+)_([0-9]+)$/\1.\2.\3/')"; echo "| $n | $v |"; done
} > "$OUT/plugins/VERSIONS.md"
(cd "$OUT/plugins" && sha damsafety/*.zip damit/*.zip > SHA256SUMS)

echo "== LISFLOOD-FP"
mkdir -p "$OUT/lisflood/linux-x64" "$OUT/lisflood/windows-x64" "$OUT/lisflood/build"
if [ -z "$LFBIN" ]; then
  LFBIN="$T/lfbin"; mkdir -p "$LFBIN"
  curl -fsSL --retry 3 -o "$T/lf.zip" "https://zenodo.org/records/13121119/files/LISFLOOD-FP-8.3.zip?download=1"
  # this is a gate, so let its message through: `-c` prints "FAILED" on stdout, which
  # >/dev/null was swallowing, leaving only a terse stderr warning for a checksum mismatch
  echo "f9ea2753482da1e730ba34645a2b9b773d05d0a401a3524f79825b76ec7a4e8d  $T/lf.zip" | sha -c -
  for plat in linux windows; do mkdir -p "$T/src-$plat"; unzip -q "$T/lf.zip" -d "$T/src-$plat"; done
  LISFLOOD_STATIC=1 bash "$DWR/DamSafety_Runner/scripts/build_lisflood_linux.sh" "$T/src-linux/LISFLOOD-FP-8.3/source" "$LFBIN/linux-x64" >/dev/null
  bash "$DWR/DamSafety_Runner/scripts/build_lisflood_windows_cross.sh" "$T/src-windows/LISFLOOD-FP-8.3/source" "$LFBIN/windows-x64" >/dev/null \
    || echo "  (no Windows build: MinGW-w64 missing)"
fi
cp "$LFBIN/linux-x64/lisflood" "$OUT/lisflood/linux-x64/"
[ -f "$LFBIN/windows-x64/lisflood.exe" ] && cp "$LFBIN/windows-x64/lisflood.exe" "$OUT/lisflood/windows-x64/"
for f in "$OUT"/lisflood/*/lisflood*; do grep -aq inittm_depth "$f" || { echo "unpatched LISFLOOD-FP: $f" >&2; exit 1; }; done
# the sub-grid channel (SGC) edit of the Runner patch (DamSafety Runner 3.26.0 / DamIT Runner 0.7.0):
# required on Linux; a Windows build without it (no MinGW-w64 here) still ships, and the Runners
# refuse only sub-grid-channel runs with it
SGC_MARK="nd-breach-runner: SGC arrival depth"
grep -aq "$SGC_MARK" "$OUT/lisflood/linux-x64/lisflood" || { echo "linux-x64 LISFLOOD-FP has no SGC edit (rebuild it)" >&2; exit 1; }
if [ -f "$OUT/lisflood/windows-x64/lisflood.exe" ] && ! grep -aq "$SGC_MARK" "$OUT/lisflood/windows-x64/lisflood.exe"; then
  echo "  WARNING: windows-x64 lisflood.exe has no SGC edit (sub-grid channels unavailable on Windows)" >&2; fi
cp "$DWR/tools/mac/lisflood/build_lisflood.sh" "$DWR/tools/mac/lisflood/lisflood-8.3-ndbreach.patch" \
   "$DWR/DamSafety_Runner/scripts/patch_lisflood.py" "$OUT/lisflood/build/"
cp "$HERE/tools/LISFLOOD-MAC-METAL.txt" "$OUT/lisflood/build/README.txt"
# the licence texts from the official source zip (GPL-3)
[ -f "$T/lf.zip" ] || curl -fsSL --retry 3 -o "$T/lf.zip" "https://zenodo.org/records/13121119/files/LISFLOOD-FP-8.3.zip?download=1"
unzip -p "$T/lf.zip" LISFLOOD-FP-8.3/LICENSE > "$OUT/lisflood/LICENSE"
unzip -p "$T/lf.zip" LISFLOOD-FP-8.3/source/LICENCE-3RD-PARTY.txt > "$OUT/lisflood/LICENCE-3RD-PARTY.txt"
cat > "$OUT/lisflood/README.txt" <<'EOF'
LISFLOOD-FP 8.3 (University of Bristol, GPL-3: LICENSE here; source: Zenodo record 13121119) with the DamSafety /
ND Dam Breach Runner patch (the inittm_depth keyword and the sub-grid channel arrival depth the
Runners require), built from the official source: linux-x64 with g++ (needs glibc 2.38+), windows-x64
cross-compiled with MinGW-w64 (static, no DLLs). macOS builds it at install, with its Metal (GPU) back
end when Apple's Metal compiler is installed: build/README.txt. The source zip itself is in every
offline set (offline/lisflood-src/) or at the Zenodo record.
EOF
(cd "$OUT/lisflood" && sha */lisflood* > SHA256SUMS)

echo "== damit_ai + damit_desk + Absaraka"
mkdir -p "$OUT/damit_ai"
# The trailing `|| die` matters: as the last stage of a pipeline the loop hands a failing
# `cp` (a tracked-but-deleted worktree file) straight to errexit, which aborted the build
# with only cp's own message and no indication that the package is now incomplete.
(cd "$DAMIT/damit_ai" && git ls-files) | while IFS= read -r f; do
  mkdir -p "$OUT/damit_ai/$(dirname "$f")"
  cp -p "$DAMIT/damit_ai/$f" "$OUT/damit_ai/$f" \
    || { echo "damit_ai/$f is tracked but missing from the worktree" >&2; exit 1; }
done
# DamIT Desk: install-all runs it on the ndqgis env (pyproj + qgis_process are already there). Shipped: the desktop
# app (app/desktop/, which holds the committed web bundle), the bin/ launchers, damit_catalog/handoff.py (the NID-ID
# rule; install-all refreshes it from the Catalog plugin zip), the hand-off docs and the READMEs. The JS sources,
# lockfile and vite/eslint config are build-time only.
if [ -n "$DESK" ]; then
  mkdir -p "$OUT/damit_desk"
  (cd "$DESK" && git ls-files app/desktop app/docs app/README.md bin damit_catalog README.md LICENSE.md) | while IFS= read -r f; do
    mkdir -p "$OUT/damit_desk/$(dirname "$f")"
    cp -p "$DESK/$f" "$OUT/damit_desk/$f" \
      || { echo "damit-desk/$f is tracked but missing from the worktree" >&2; exit 1; }
  done
  git -C "$DESK" rev-parse --short HEAD > "$OUT/damit_desk/COMMIT"
fi
cp -R "$DWR/tools/mac/absaraka" "$OUT/absaraka"
rm -rf "$T"

if [ "$ZIP" = 1 ]; then
  (cd "$(dirname "$OUT")" && rm -f "$(basename "$OUT").zip" && zip -q -r "$(basename "$OUT").zip" "$(basename "$OUT")")
  echo "== wrote $OUT.zip ($(du -h "$OUT.zip" | awk '{print $1}'))"
fi
echo "== package at $OUT ($(du -sh "$OUT" | awk '{print $1}'))"
