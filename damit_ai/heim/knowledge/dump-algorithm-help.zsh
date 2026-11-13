#!/usr/bin/env zsh
# dump-algorithm-help.zsh — dump every suite Processing algorithm's help text (parameters,
# defaults, descriptions) to ALGORITHM-HELP.md, so Heim knows each tool's contract without
# running QGIS itself.
#
# Run it on a machine where the plugins are installed in a QGIS profile. qgis_process LIST
# omits FlagHideFromToolbox tools, so this also probes the known hidden ids by `help`.
#
#   ./dump-algorithm-help.zsh                              # auto-find qgis_process, default profile
#   QGIS_PROCESS=/path/to/qgis_process ./dump-algorithm-help.zsh
#   ./dump-algorithm-help.zsh damsafety                    # a profile name, found per platform
#   ./dump-algorithm-help.zsh /full/path/to/profile        # or the profile folder itself
#
set -e
HERE=${0:A:h}
OUT="$HERE/ALGORITHM-HELP.md"
QP=${QGIS_PROCESS:-qgis_process}
PROFILE=${1:-}
# The profile folder is in a different place on each platform, and pointing
# QGIS_CUSTOM_CONFIG_PATH at one that does not exist is NOT an error: QGIS creates an empty
# profile, no plugins load, `qgis_process list` shows no suite algorithms, and this script
# writes a file with a heading and nothing under it. So resolve it, or stop.
if [[ -n "$PROFILE" ]]; then
  if [[ -d "$PROFILE" ]]; then
    export QGIS_CUSTOM_CONFIG_PATH="${PROFILE:A}"
  else
    for base in "$HOME/Library/Application Support/QGIS/QGIS3/profiles" \
                "$HOME/.local/share/QGIS/QGIS3/profiles" \
                "${APPDATA:-$HOME/AppData/Roaming}/QGIS/QGIS3/profiles"; do
      if [[ -d "$base/$PROFILE" ]]; then export QGIS_CUSTOM_CONFIG_PATH="$base/$PROFILE"; break; fi
    done
  fi
  if [[ -z "${QGIS_CUSTOM_CONFIG_PATH:-}" ]]; then
    print -u2 "no QGIS profile '$PROFILE' on this machine. Looked in:"
    print -u2 "  ~/Library/Application Support/QGIS/QGIS3/profiles   (macOS)"
    print -u2 "  ~/.local/share/QGIS/QGIS3/profiles                  (Linux)"
    print -u2 "  %APPDATA%/QGIS/QGIS3/profiles                       (Windows)"
    print -u2 "Pass the profile folder itself, or list them:  ls ~/Library/Application\\ Support/QGIS/QGIS3/profiles"
    exit 1
  fi
  echo "profile: $QGIS_CUSTOM_CONFIG_PATH"
fi

command -v "$QP" >/dev/null 2>&1 || { echo "qgis_process not found (set QGIS_PROCESS=)"; exit 1; }

# provider prefixes used by the suite (ND + DWR) + hidden ids LIST won't show
PROVIDERS=(nddam ndbreach ndhazard)
HIDDEN=(ndbreach:selftest nddam:selftest nddam:runchain)

{
  echo "# Suite Processing algorithm help"
  echo
  echo "_Generated $(date -u +%Y-%m-%dT%H:%MZ) by dump-algorithm-help.zsh from \`$QP\`._"
  echo
  # visible algorithms
  ids=$("$QP" list 2>/dev/null | grep -oE '(nddam|ndbreach|ndhazard):[a-zA-Z0-9_]+' | sort -u)
  if [[ -z "$ids" ]]; then
    print -u2 "qgis_process listed no ${(j:, :)PROVIDERS} algorithm. The plugins are not loaded in"
    print -u2 "this profile, so there is nothing to dump; ALGORITHM-HELP.md was left alone."
    exit 1
  fi
  # add the hidden ones
  for h in $HIDDEN; do ids+=$'\n'"$h"; done
  for id in ${(f)ids}; do
    [[ -z "$id" ]] && continue
    echo "## $id"
    echo '```'
    "$QP" help "$id" 2>&1 || echo "(no help for $id)"
    echo '```'
    echo
  done
} > "$OUT"
echo "Wrote $OUT"
