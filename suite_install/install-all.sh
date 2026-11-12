#!/bin/bash
# =============================================================================
# install-all.sh  -  the whole dam suite on Linux or macOS, in one go
# =============================================================================
#
# Installs, under your home folder (no sudo, no pip, no system packages):
#   * DamSafety plugins (DWR_Plugins: Core FIRST, then Setup, Data, Screening, Runner,
#     Hazard, Hazard Lite, PMP)                         -> QGIS profile "damsafety"
#   * DamIT plugins (damit: Core, Catalog, Setup, Data, Screener, Runner, Hazard,
#     Hazard Lite, PMP)                                 -> QGIS profile "damit"
#     (each set has its own profile, so their settings never mix)
#   * QGIS 3.34 (conda env ndqgis), ANUGA 4.1 + gmsh 4.15 (env ndanuga)
#   * LISFLOOD-FP 8.3 with the Runner patch: shipped binary on Linux; built from the
#     official source with conda's clang on macOS (needs Apple's Command Line Tools)
#   * the local AIs from damit_ai: Lumo (code triage) and dam-research (literature),
#     with Ollama, their conda env, the models and the reference library
#   * one launcher per profile, and the Absaraka Dam (DWR-2801) run folder
#
# OFFLINE: if offline/ is filled (an offline set unzipped here, or download-all.sh run on
# any networked machine), NOTHING is downloaded. On Linux, missing files are otherwise
# fetched first by download-all.sh, each checked against the sha256 pinned in locks/.
# On macOS the installer NEVER downloads: it stops and asks for the offline set (or for
# download-all.sh to be run first), like the earlier Mac packages. No sudo, no pip.
#
#   bash install-all.sh                  # everything
#   bash install-all.sh --offline        # refuse to download anything
#   bash install-all.sh --check          # report what is installed
#   options: --no-damsafety --no-damit --no-ai --no-lumo --no-research --skip-lisflood
#
# It never touches your data folders (~/ND_Suite_Data, DamIT data), offline packs, or
# any QGIS profile other than "damsafety" and "damit".
# =============================================================================
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STAMP="dam-suite install-all $(cat "$HERE/VERSION" 2>/dev/null || echo dev)"
PREFIX="${DAMSUITE_PREFIX:-$HOME/dam-suite}"
MINIFORGE_DIR="${DAMSUITE_MINIFORGE:-$HOME/miniforge3}"
DS_PROFILE="${DAMSAFETY_PROFILE:-damsafety}"
DI_PROFILE="${DAMIT_PROFILE:-damit}"
DS_PLUGINS="DamSafety_Core DamSafety_Setup DamSafety_Data DamSafety_Screening DamSafety_Runner DamSafety_Hazard DamSafety_HazardLite DamSafety_PMP"
DI_PLUGINS="damit_core damit_catalog damit_setup damit_data damit_screener damit_runner damit_hazard damit_hazardlite damit_pmp damit_finder"

DO_DS=1; DO_DI=1; DO_LUMO=1; DO_RESEARCH=1; SKIP_LISFLOOD=0; OFFLINE_ONLY=0; MODE=install
while [ $# -gt 0 ]; do
  case "$1" in
    --no-damsafety) DO_DS=0 ;;  --no-damit) DO_DI=0 ;;
    --no-ai) DO_LUMO=0; DO_RESEARCH=0 ;;  --no-lumo) DO_LUMO=0 ;;  --no-research) DO_RESEARCH=0 ;;
    --skip-lisflood) SKIP_LISFLOOD=1 ;;  --offline) OFFLINE_ONLY=1 ;;  --check) MODE=check ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  OK  %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
sha()  { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi; }
ver_of() { sed -n 's/^version=//p' "$1/metadata.txt" 2>/dev/null | tr -d '\r' | head -1; }

# ---------------------------------------------------------------------------
# 0. platform
# ---------------------------------------------------------------------------
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Linux-x86_64)  P=linux-64;  MF="Linux-x86_64";  LFBIN=linux-x64 ;;
  Darwin-arm64)  P=osx-arm64; MF="MacOSX-arm64";  LFBIN="" ;;
  Darwin-x86_64) P=osx-64;    MF="MacOSX-x86_64"; LFBIN="" ;;
  *) die "Unsupported system $OS $ARCH (supported: Linux x86_64, macOS Apple Silicon or Intel; Windows: install-all-windows.cmd)." ;;
esac
[ "$(id -u)" != 0 ] || [ "${DAMSUITE_ALLOW_ROOT:-0}" = 1 ] || die "Do not run this with sudo; run it as yourself."
if [ "$OS" = Darwin ]; then
  PROFILES="$HOME/Library/Application Support/QGIS/QGIS3/profiles"
  NCPU="$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || sysctl -n hw.ncpu)"
  case "$HERE" in "$HOME/Downloads"*|"$HOME/Desktop"*|"$HOME/Documents"*)
    warn "macOS may stop scripts in Downloads/Desktop/Documents from reading their own folder; if files seem missing, move this folder to your home folder." ;; esac
else
  PROFILES="$HOME/.local/share/QGIS/QGIS3/profiles"; NCPU="$(nproc)"
fi
THREADS="${DAMSUITE_THREADS:-$NCPU}"
DS_DIR="$PROFILES/$DS_PROFILE"; DI_DIR="$PROFILES/$DI_PROFILE"
CONDA_PKGS="$HERE/offline/conda/$P"

locate_conda() {
  CONDA_EXE=""
  for c in "${DAMSUITE_CONDA:-}" "$MINIFORGE_DIR/bin/conda" "$(command -v conda 2>/dev/null || true)" \
           "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda"; do
    if [ -n "$c" ] && [ -x "$c" ]; then CONDA_EXE="$c"; return; fi
  done
}
locate_conda
env_prefix() { echo "$CONDA_BASE/envs/$1"; }

# ---------------------------------------------------------------------------
if [ "$MODE" = check ]; then
  say "dam suite on $P"
  if [ -n "$CONDA_EXE" ]; then CONDA_BASE="$("$CONDA_EXE" info --base)"; echo "  conda: $CONDA_EXE"
    for e in ndqgis ndanuga ndresearch ndlumo ndbuild; do
      echo "    env $e: $( [ -d "$CONDA_BASE/envs/$e/conda-meta" ] && echo present || echo missing)"; done
  else echo "  conda: not found"; fi
  L="$PREFIX/bin/lisflood"
  echo "  LISFLOOD-FP: $L $( [ -x "$L" ] && { grep -aq inittm_depth "$L" && echo 'OK (Runner patch present)' || echo UNPATCHED; } || echo missing)"
  echo "  DamSafety profile ($DS_PROFILE):"; for p in $DS_PLUGINS; do echo "    $p $( [ -d "$DS_DIR/python/plugins/$p" ] && ver_of "$DS_DIR/python/plugins/$p" || echo missing)"; done
  echo "  DamIT profile ($DI_PROFILE):";     for p in $DI_PLUGINS; do echo "    $p $( [ -d "$DI_DIR/python/plugins/$p" ] && ver_of "$DI_DIR/python/plugins/$p" || echo missing)"; done
  echo "  Ollama: $(command -v ollama 2>/dev/null || ls "$HOME/local-ai/ollama/bin/ollama" 2>/dev/null || echo 'not on PATH')"
  [ -f "$PREFIX/INSTALLED.txt" ] && { echo; cat "$PREFIX/INSTALLED.txt"; }
  exit 0
fi

mkdir -p "$PREFIX/logs"
LOG="$PREFIX/logs/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say "$STAMP on $P ($OS $ARCH).  Log: $LOG"

# ---------------------------------------------------------------------------
# 1. offline files: use them, or fetch what is missing (pinned + sha256-checked)
# ---------------------------------------------------------------------------
ROLES="ndqgis ndanuga"
[ $((DO_LUMO + DO_RESEARCH)) -gt 0 ] && ROLES="$ROLES ndresearch"
# a locked package's local copy: offline/conda/<P>/<channel subdir>/<file> (noarch kept apart,
# so conda reads each package's own subdir from the file:// URL)
pkg_path() { local u="${1%/*}"; echo "$CONDA_PKGS/${u##*/}/${1##*/}"; }
missing_files() {   # prints how many locked files for this platform are absent
  local n=0 url name
  for r in $ROLES ndbuild; do
    [ -f "$HERE/locks/$P/$r.lock" ] || continue
    while read -r url _ _; do case "$url" in ''|\#*) continue ;; esac
      [ -f "$(pkg_path "$url")" ] || n=$((n+1)); done < "$HERE/locks/$P/$r.lock"
  done
  while read -r pl kind path _; do case "$pl" in ''|\#*) continue ;; esac
    [ "$pl" = "$P" ] && [ "$kind" != ollama-pull ] && [ ! -f "$HERE/$path" ] && n=$((n+1)); done < "$HERE/locks/extra.lock"
  echo "$n"
}
MISS="$(missing_files)"
if [ "$MISS" -gt 0 ]; then
  # macOS: never download from the installer (as the earlier Mac packages: nothing fetched and run
  # on the Mac by the installer). Fill offline/ with the offline set or download-all.sh first.
  [ "$OS" = Darwin ] && OFFLINE_ONLY=1
  if [ "$OFFLINE_ONLY" = 1 ]; then
    die "$MISS file(s) are missing from offline/. Unzip offline-$P.zip in this folder, or run  bash download-all.sh --platform $P  first (on this or any networked machine), then run this again."
  fi
  say "$MISS file(s) not in offline/ yet: fetching them (pinned, sha256-checked)."
  LIBFLAG=""; [ "$DO_RESEARCH" = 1 ] || LIBFLAG="--no-library"
  # models are pulled later by the AI installer itself if offline/models is empty
  bash "$HERE/download-all.sh" --platform "$P" --no-models $LIBFLAG || warn "download-all reported problems (continuing; checked below)"
else
  ok "every installer file is in offline/ (nothing will be downloaded)"
fi

# ---------------------------------------------------------------------------
# 2. conda (Miniforge 26.9.4-2 from offline/miniforge, sha256-checked)
# ---------------------------------------------------------------------------
# envs are built with mamba (in every Miniforge): it installs the locked file:// packages offline,
# which conda 26 itself refuses. A conda without mamba next to it -> use (or install) Miniforge.
if [ -n "$CONDA_EXE" ] && [ ! -x "$("$CONDA_EXE" info --base)/bin/mamba" ]; then
  warn "$CONDA_EXE has no mamba next to it; using Miniforge in $MINIFORGE_DIR instead"
  CONDA_EXE=""; [ -x "$MINIFORGE_DIR/bin/conda" ] && CONDA_EXE="$MINIFORGE_DIR/bin/conda"
fi
if [ -z "$CONDA_EXE" ]; then
  [ -e "$MINIFORGE_DIR" ] && die "$MINIFORGE_DIR exists but has no conda/mamba; move it aside or set DAMSUITE_MINIFORGE to a new folder."
  MFS="$(awk -v p="$P" '!/^#/ && $1==p && $2=="miniforge" {print $3, $5}' "$HERE/locks/extra.lock")"
  MFF="$HERE/${MFS%% *}"; MFH="${MFS##* }"
  [ -f "$MFF" ] || die "No conda found and no Miniforge installer at $MFF."
  [ "$(sha "$MFF")" = "$MFH" ] || die "Miniforge installer failed its sha256 check: $MFF"
  say "Installing Miniforge (checked) to $MINIFORGE_DIR"
  bash "$MFF" -b -p "$MINIFORGE_DIR"
  CONDA_EXE="$MINIFORGE_DIR/bin/conda"
else ok "conda: $CONDA_EXE"; fi
CONDA_BASE="$("$CONDA_EXE" info --base)"
MAMBA="$CONDA_BASE/bin/mamba"
[ -x "$MAMBA" ] || die "no mamba in $CONDA_BASE"

# make_env <env name> <lock role>: build the env from the locked packages in offline/conda/<P>
make_env() {
  local name="$1" role="$2" lock="$HERE/locks/$P/$2.lock" spec url want md5 f enc
  if [ -d "$(env_prefix "$name")/conda-meta" ]; then ok "conda env $name already exists (kept)"; return 0; fi
  [ -f "$lock" ] || { warn "no lock for $role on $P"; return 1; }
  spec="$(mktemp)"; echo "@EXPLICIT" > "$spec"
  while read -r url want md5; do case "$url" in ''|\#*) continue ;; esac
    f="$(pkg_path "$url")"
    [ -f "$f" ] && [ "$(sha "$f")" = "$want" ] || { warn "package missing or bad sha256: ${url##*/}"; rm -f "$spec"; return 1; }
    enc="$(printf '%s' "$f" | sed 's/%/%25/g; s/ /%20/g; s/#/%23/g')"
    echo "file://$enc#$md5" >> "$spec"
  done < "$lock"
  say "Creating conda env $name from $(($(wc -l < "$spec") - 1)) local packages (no download)"
  "$MAMBA" create -y --offline -n "$name" --file "$spec" || { rm -f "$spec"; return 1; }
  rm -f "$spec"
}

say "Conda environments"
make_env ndqgis ndqgis || die "the QGIS env could not be built"
make_env ndanuga ndanuga || warn "the ANUGA env could not be built: the ANUGA tier will be off"
QP="$(env_prefix ndqgis)"
qpy() { env PYTHONPATH="$QP/share/qgis/python:$QP/share/qgis/python/plugins" QT_PLUGIN_PATH="$QP/plugins" \
            QGIS_PREFIX_PATH="$QP" PROJ_DATA="$QP/share/proj" GDAL_DATA="$QP/share/gdal" QT_QPA_PLATFORM=offscreen \
            "$QP/bin/python" "$@"; }
qpy -c "import qgis.core" >/dev/null 2>&1 || die "QGIS does not import in env ndqgis (see $LOG)"
ANUGA_PY="$(env_prefix ndanuga)/bin/python"
"$ANUGA_PY" -c "import anuga, gmsh" >/dev/null 2>&1 || { warn "anuga/gmsh do not import: ANUGA tier off"; ANUGA_PY=""; }

# ---------------------------------------------------------------------------
# 3. plugins (zips in plugins/; Core first so every dependency is in place)
# ---------------------------------------------------------------------------
install_set() {  # install_set <profile dir> <zip folder> <plugin names in order>
  local dest="$1/python/plugins" zdir="$2" p z; shift 2
  mkdir -p "$dest"
  for p in "$@"; do
    z="$(ls "$zdir/${p}_"[0-9]*.zip 2>/dev/null | head -1)"
    [ -n "$z" ] || { warn "no zip for $p in $zdir"; continue; }
    rm -rf "${dest:?}/$p"; unzip -q -o "$z" -d "$dest"
    printf '    %-22s %s\n' "$p" "$(ver_of "$dest/$p")"
  done
}
if [ "$DO_DS" = 1 ]; then say "DamSafety plugins -> profile '$DS_PROFILE' (DamSafety Core first)"
  # shellcheck disable=SC2086
  install_set "$DS_DIR" "$HERE/plugins/damsafety" $DS_PLUGINS; fi
if [ "$DO_DI" = 1 ]; then say "DamIT plugins -> profile '$DI_PROFILE' (DamIT Core and Catalog first)"
  # shellcheck disable=SC2086
  install_set "$DI_DIR" "$HERE/plugins/damit" $DI_PLUGINS; fi

# ---------------------------------------------------------------------------
# 4. LISFLOOD-FP 8.3 + Runner patch (shared by both sets)
# ---------------------------------------------------------------------------
LISFLOOD_EXE=""; mkdir -p "$PREFIX/bin"
lf_ok() { [ -x "$1" ] && "$1" -version 2>&1 | grep -qi lisflood && grep -aq inittm_depth "$1"; }
if [ "$SKIP_LISFLOOD" = 1 ]; then warn "LISFLOOD-FP skipped (--skip-lisflood): the Runners use their built-in engine"
else
  if [ -n "$LFBIN" ] && [ -f "$HERE/lisflood/$LFBIN/lisflood" ]; then
    cp "$HERE/lisflood/$LFBIN/lisflood" "$PREFIX/bin/lisflood"; chmod +x "$PREFIX/bin/lisflood"
    lf_ok "$PREFIX/bin/lisflood" && LISFLOOD_EXE="$PREFIX/bin/lisflood" \
      || warn "the shipped LISFLOOD-FP does not run here (it needs glibc 2.38+); building it instead"
  fi
  if [ -z "$LISFLOOD_EXE" ] && lf_ok "$PREFIX/bin/lisflood"; then LISFLOOD_EXE="$PREFIX/bin/lisflood"; fi
  if [ -z "$LISFLOOD_EXE" ]; then
    SRCZIP="$HERE/offline/lisflood-src/LISFLOOD-FP-8.3.zip"
    PATCHER="$DS_DIR/python/plugins/DamSafety_Runner/scripts/patch_lisflood.py"
    [ -f "$PATCHER" ] || PATCHER="$HERE/lisflood/build/patch_lisflood.py"
    if [ -f "$SRCZIP" ] && make_env ndbuild ndbuild; then
      say "Building LISFLOOD-FP 8.3 with the Runner patch (conda compilers)"
      BARGS="--conda $CONDA_EXE --env ndbuild --out $PREFIX --zip $SRCZIP --python $QP/bin/python --patcher $PATCHER"
      # shellcheck disable=SC2086
      BUILT="$(bash "$HERE/lisflood/build/build_lisflood.sh" $BARGS | tail -n 1)" || BUILT=""
      if [ -z "$BUILT" ] && [ "$OS" = Darwin ]; then
        warn "conda clang failed; retrying with Apple's clang (Command Line Tools)"
        # shellcheck disable=SC2086
        BUILT="$(bash "$HERE/lisflood/build/build_lisflood.sh" $BARGS --apple-clang | tail -n 1)" || BUILT=""
      fi
      if [ -n "$BUILT" ] && [ -x "$BUILT" ]; then
        cp "$BUILT" "$PREFIX/bin/lisflood"; chmod +x "$PREFIX/bin/lisflood"
        lf_ok "$PREFIX/bin/lisflood" && LISFLOOD_EXE="$PREFIX/bin/lisflood"
      fi
    fi
    [ -n "$LISFLOOD_EXE" ] || warn "no LISFLOOD-FP (macOS: install Apple's Command Line Tools with  xcode-select --install  and re-run). The Runners use their built-in engine meanwhile."
  fi
  [ -n "$LISFLOOD_EXE" ] && ok "LISFLOOD-FP: $LISFLOOD_EXE ($("$LISFLOOD_EXE" -version 2>&1 | grep -o 'LISFLOOD-FP [0-9.]*' | head -1), Runner patch present)"
fi

# ---------------------------------------------------------------------------
# 5. Absaraka folder, settings, launchers
# ---------------------------------------------------------------------------
RUN="$PREFIX/absaraka-run"
if [ -d "$HERE/absaraka" ]; then
  mkdir -p "$RUN"
  (cd "$HERE/absaraka" && find . -type d -exec mkdir -p "$RUN/{}" \; )
  (cd "$HERE/absaraka" && find . -type f | while IFS= read -r f; do [ -e "$RUN/$f" ] || cp -p "$f" "$RUN/$f"; done)
  mkdir -p "$RUN/work"
fi

# write_settings <ini> <set: damsafety|damit> <plugins...>
write_settings() {
  local ini="$1" set="$2"; shift 2
  mkdir -p "$(dirname "$ini")"
  qpy - "$ini" "$set" "$ANUGA_PY" "$LISFLOOD_EXE" "$THREADS" "$RUN/Dams" "$STAMP" "$@" <<'PY'
import sys
from qgis.PyQt.QtCore import QSettings
ini, which, anuga, lisflood, threads, dams, stamp = sys.argv[1:8]
plugins = sys.argv[8:]
s = QSettings(ini, QSettings.IniFormat)
s.setValue("PythonPlugins/processing", True)
for p in plugins:
    s.setValue("PythonPlugins/" + p, True)
c = "Processing/Configuration/"
if anuga:
    s.setValue(c + "NDBREACH_ANUGA_PYTHON", anuga)
s.setValue(c + "NDBREACH_THREADS", threads)
# written even when empty (= "not set": the built-in engine), so an old path never lingers
s.setValue(c + "NDBREACH_LISFLOOD_EXE", lisflood)
if which == "damsafety":
    if anuga:
        s.setValue("ndsuite/anuga_python", anuga)
    s.setValue("ndsuite/lisflood_exe", lisflood)
    s.setValue("ndsuite/dams_folder", dams)
    s.setValue("ndsuite/setup_version", stamp)
else:
    s.setValue(c + "DAMIT_RUN_LISFLOOD_EXE", lisflood)
s.sync()
print("  wrote", ini)
PY
}
mk_launcher() {  # mk_launcher <file> <profile>
  { echo '#!/bin/bash'
    echo "# QGIS 3.34 (conda env ndqgis) in profile '$2'. Written by $STAMP."
    printf 'export PYTHONPATH=%q\n' "$QP/share/qgis/python:$QP/share/qgis/python/plugins"
    printf 'export QT_PLUGIN_PATH=%q QGIS_PREFIX_PATH=%q\n' "$QP/plugins" "$QP"
    printf 'export PROJ_DATA=%q GDAL_DATA=%q\n' "$QP/share/proj" "$QP/share/gdal"
    printf 'export NDBREACH_ANUGA_MESHER=gmsh NDBREACH_ANUGA_PYTHON=%q NDBREACH_LISFLOOD=%q\n' "$ANUGA_PY" "$LISFLOOD_EXE"
    printf 'exec %q --profile %q "$@"\n' "$QP/bin/qgis" "$2"; } > "$1"
  chmod +x "$1"
  if [ "$OS" = Darwin ]; then cp "$1" "${1%.sh}.command"; chmod +x "${1%.sh}.command"; fi
}
say "Settings and launchers"
if [ "$DO_DS" = 1 ]; then
  # shellcheck disable=SC2086
  write_settings "$DS_DIR/QGIS/QGIS3.ini" damsafety $DS_PLUGINS; mk_launcher "$PREFIX/open-damsafety-qgis.sh" "$DS_PROFILE"; fi
if [ "$DO_DI" = 1 ]; then
  # shellcheck disable=SC2086
  write_settings "$DI_DIR/QGIS/QGIS3.ini" damit $DI_PLUGINS; mk_launcher "$PREFIX/open-damit-qgis.sh" "$DI_PROFILE"; fi

# ---------------------------------------------------------------------------
# 6. the local AIs (damit_ai's own installers; envs + Ollama + models from offline/)
# ---------------------------------------------------------------------------
AI_OK=""
if [ $((DO_LUMO + DO_RESEARCH)) -gt 0 ]; then
  say "Local AIs (Lumo $( [ "$DO_LUMO" = 1 ] && echo on || echo off), dam-research $( [ "$DO_RESEARCH" = 1 ] && echo on || echo off))"
  # both AIs reuse these envs when they exist, so they come from the locked local packages
  [ "$DO_RESEARCH" = 1 ] && { make_env ndresearch ndresearch || warn "ndresearch env not built from offline/ (the AI installer will try conda-forge)"; }
  [ "$DO_LUMO" = 1 ] && { make_env ndlumo ndresearch || warn "ndlumo env not built from offline/ (the AI installer will try conda-forge)"; }
  if [ -d "$HERE/damit_ai/offline/models/manifests" ]; then
    mkdir -p "$HOME/local-ai/models"
    cp -R -n "$HERE/damit_ai/offline/models/." "$HOME/local-ai/models/" 2>/dev/null || true
    ok "models copied to ~/local-ai/models (no pull needed)"
  fi
  if [ "$DO_RESEARCH" = 1 ] && [ -d "$HERE/damit_ai/offline/DamResearch/library" ]; then
    mkdir -p "$HOME/DamResearch/library"
    cp -R -n "$HERE/damit_ai/offline/DamResearch/library/." "$HOME/DamResearch/library/" 2>/dev/null || true
    ok "reference library copied to ~/DamResearch/library"
  fi
  export CONDA_EXE
  if [ "$OS" = Linux ]; then
    AIF=""; [ "$DO_LUMO" = 1 ] || AIF="--no-lumo"; [ "$DO_RESEARCH" = 1 ] || AIF="--no-research"
    # shellcheck disable=SC2086
    if PATH="$CONDA_BASE/bin:$PATH" bash "$HERE/damit_ai/install-local-ai-linux.sh" $AIF; then AI_OK=yes
    else warn "local AI setup failed (the plugin sets are installed anyway); re-run: bash damit_ai/install-local-ai-linux.sh"; fi
  else
    command -v zsh >/dev/null 2>&1 || die "zsh is needed for the macOS AI installers"
    AI_OK=yes
    [ "$DO_LUMO" = 1 ] && { PATH="$CONDA_BASE/bin:$PATH" zsh "$HERE/damit_ai/lumo/setup-local-lumo.sh" \
      || { AI_OK=""; warn "Lumo setup failed; re-run: zsh damit_ai/lumo/setup-local-lumo.sh"; }; }
    [ "$DO_RESEARCH" = 1 ] && { PATH="$CONDA_BASE/bin:$PATH" zsh "$HERE/damit_ai/research/setup-dam-research.zsh" \
      || { AI_OK=""; warn "dam-research setup failed; re-run: zsh damit_ai/research/setup-dam-research.zsh"; }; }
  fi
fi

# ---------------------------------------------------------------------------
# 7. self-check + record
# ---------------------------------------------------------------------------
say "Self-check"
FAIL=0
QV="$(qpy -c 'import qgis.core as q, numpy; print(q.Qgis.QGIS_VERSION, "| numpy", numpy.__version__)' 2>/dev/null | tail -n 1)"
case "$QV" in 3.34.*) ok "QGIS $QV" ;; *) warn "QGIS 3.34 does not import"; FAIL=1 ;; esac
[ -n "$ANUGA_PY" ] && ok "ANUGA $("$ANUGA_PY" -c 'import anuga,gmsh;print(anuga.__version__,"| gmsh",gmsh.__version__)' 2>/dev/null | tail -n 1)"
[ -n "$ANUGA_PY" ] || { warn "no ANUGA tier"; FAIL=1; }
[ -n "$LISFLOOD_EXE" ] || [ "$SKIP_LISFLOOD" = 1 ] || FAIL=1
chk() { local dir="$1" p; shift; for p in "$@"; do
  if [ -f "$dir/python/plugins/$p/metadata.txt" ]; then ok "$p $(ver_of "$dir/python/plugins/$p")"; else warn "$p missing"; FAIL=1; fi; done; }
# shellcheck disable=SC2086
[ "$DO_DS" = 1 ] && chk "$DS_DIR" $DS_PLUGINS
# shellcheck disable=SC2086
[ "$DO_DI" = 1 ] && chk "$DI_DIR" $DI_PLUGINS
if [ $((DO_LUMO + DO_RESEARCH)) -gt 0 ]; then [ -n "$AI_OK" ] && ok "local AIs installed" || FAIL=1; fi

{ echo "Installed by $STAMP on $(date)"
  [ -f "$HERE/plugins/VERSIONS.md" ] && grep -E '^Source|^- ' "$HERE/plugins/VERSIONS.md" | head -4
  echo "  platform $P | QGIS ${QV:-?} | ANUGA python ${ANUGA_PY:-none} | LISFLOOD-FP ${LISFLOOD_EXE:-built-in engine}"
  [ "$DO_DS" = 1 ] && echo "  DamSafety -> profile $DS_PROFILE  (open: $PREFIX/open-damsafety-qgis.sh)"
  [ "$DO_DI" = 1 ] && echo "  DamIT     -> profile $DI_PROFILE  (open: $PREFIX/open-damit-qgis.sh)"
  true; } > "$PREFIX/INSTALLED.txt"

say "Done$( [ "$FAIL" = 0 ] && echo ': all checks passed.' || echo ", with warnings (see above and $LOG).")"
cat "$PREFIX/INSTALLED.txt"
cat <<EOF

  Open one profile at a time with its launcher$( [ "$OS" = Darwin ] && echo ' (or double-click the .command file)').
  Absaraka run folder: $RUN     Check later:  bash install-all.sh --check
EOF
[ "$OS" = Linux ] && cat <<'EOF'
  If QGIS will not open on Linux ("could not load the Qt platform plugin xcb"), install once:
    openSUSE:      sudo zypper install Mesa-libGL1 libxcb-cursor0 xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11-0
    Debian/Ubuntu: sudo apt install libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0
EOF
exit 0
