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
#   ./dump-algorithm-help.zsh damsafety                    # a specific profile name
#
set -e
HERE=${0:A:h}
OUT="$HERE/ALGORITHM-HELP.md"
QP=${QGIS_PROCESS:-qgis_process}
PROFILE=${1:-}
[[ -n "$PROFILE" ]] && export QGIS_CUSTOM_CONFIG_PATH="$HOME/.local/share/QGIS/QGIS3/profiles/$PROFILE"

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
