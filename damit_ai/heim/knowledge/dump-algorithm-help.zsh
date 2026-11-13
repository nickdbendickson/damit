#!/usr/bin/env zsh
# dump-algorithm-help.zsh v2 — dump every suite Processing algorithm's help text (parameters,
# defaults, descriptions) to algorithm-help/<provider>.<name>.md, with the list of ids in
# ALGORITHM-HELP.md, so Heim knows each tool's contract without running QGIS itself.
#
# Run it on a machine where the plugins are installed in a QGIS profile. qgis_process LIST
# omits FlagHideFromToolbox tools, so this also probes the known hidden ids by `help`.
#
#   ./dump-algorithm-help.zsh                              # the default QGIS profile
#   ./dump-algorithm-help.zsh damsafety                    # a profile name, found per platform
#   ./dump-algorithm-help.zsh /full/path/to/profile        # or the profile folder itself
#   QGIS_PROCESS=/path/to/qgis_process ./dump-algorithm-help.zsh damsafety
#
# v2 (2026-11-13), three things v1 got wrong:
#   - It set QGIS_CUSTOM_CONFIG_PATH to the PROFILE folder. QGIS wants the folder that
#     CONTAINS profiles/, and always uses profiles/default inside it. Given a profile folder
#     it quietly made an empty profiles/default inside the real profile and loaded no
#     plugins, so a named profile could never work. Now a throwaway root is made whose
#     profiles/default is a link to the profile asked for (what `damchain setup` does).
#   - It redirected into ALGORITHM-HELP.md before checking anything, so a run that found no
#     algorithms left a file holding a heading and nothing else. Now it writes a temporary
#     file and replaces the page only when there is something to put in it.
#   - It knew three providers. The Finder, PMP and Hazard Lite tools were never dumped.
set -e
HERE=${0:A:h}
OUT="$HERE/ALGORITHM-HELP.md"
QP=${QGIS_PROCESS:-qgis_process}
PROFILE=${1:-}
export QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}

command -v "$QP" >/dev/null 2>&1 || { print -u2 "qgis_process not found (set QGIS_PROCESS=)"; exit 1; }

ROOT=""
cleanup() { [[ -n "$ROOT" && -d "$ROOT" ]] && rm -rf "$ROOT"; return 0; }
trap cleanup EXIT

if [[ -n "$PROFILE" ]]; then
  PDIR=""
  if [[ -d "$PROFILE" ]]; then
    PDIR="${PROFILE:A}"
  else
    for base in "$HOME/Library/Application Support/QGIS/QGIS3/profiles" \
                "$HOME/.local/share/QGIS/QGIS3/profiles" \
                "${APPDATA:-$HOME/AppData/Roaming}/QGIS/QGIS3/profiles"; do
      if [[ -d "$base/$PROFILE" ]]; then
        PDIR="$base/$PROFILE"
        break
      fi
    done
  fi
  if [[ -z "$PDIR" ]]; then
    print -u2 "no QGIS profile '$PROFILE' on this machine. Looked in:"
    print -u2 "  ~/Library/Application Support/QGIS/QGIS3/profiles   (macOS)"
    print -u2 "  ~/.local/share/QGIS/QGIS3/profiles                  (Linux)"
    print -u2 "  %APPDATA%/QGIS/QGIS3/profiles                       (Windows)"
    print -u2 "Pass the profile folder itself, or list them:  ls ~/Library/Application\\ Support/QGIS/QGIS3/profiles"
    exit 1
  fi
  if [[ ! -d "$PDIR/python/plugins" ]]; then
    print -u2 "$PDIR has no python/plugins folder: it is not a profile with plugins installed."
    exit 1
  fi
  ROOT=$(mktemp -d)
  mkdir -p "$ROOT/profiles"
  ln -s "$PDIR" "$ROOT/profiles/default"
  export QGIS_CUSTOM_CONFIG_PATH="$ROOT"
  echo "profile: $PDIR"
fi

# every provider of the suite starts with "nd": nddam, ndbreach, ndhazard, ndfind, ndpmp, ndlite
ids=$("$QP" list 2>/dev/null | grep -oE '\bnd[a-z]+:[A-Za-z0-9_]+' | sort -u || true)
if [[ -z "$ids" ]]; then
  print -u2 "qgis_process listed no suite algorithm (no id starting nddam:, ndbreach:, ndhazard: ...)."
  print -u2 "The plugins are not installed or not enabled in this profile. ALGORITHM-HELP.md was left alone."
  print -u2 "Check with:  $QP plugins"
  exit 1
fi
# hidden from `list`: each provider's self-test where it has one, and the headless chain
providers=(${(u)${(f)ids}%%:*})
hidden=(nddam:runchain)
# ${p}, with the braces: a bare $p:selftest is read by zsh as the :s modifier on $p
for p in $providers; do hidden+=("${p}:selftest"); done
for h in $hidden; do
  if ! print -r -- "$ids" | grep -qx "$h" && "$QP" help "$h" >/dev/null 2>&1; then
    ids+=$'\n'"$h"
  fi
done
ids=$(print -r -- "$ids" | sort -u)

# One file per algorithm, in algorithm-help/. A single page for all of them is about 800 KB,
# and rag_index.py skips any text file over 256 KB ("too big, skipped"), so one page would
# have been committed, installed and never read. A file per tool also puts the algorithm id
# in the path of every passage Heim is handed.
TMPD=$(mktemp -d)
INDEX="$TMPD/ALGORITHM-HELP.md"
LIMIT=262144
{
  echo "# Suite Processing algorithm help"
  echo
  echo "_Generated $(date -u +%Y-%m-%d) by dump-algorithm-help.zsh from \`${QP:t}\` ($("$QP" --version 2>/dev/null | head -1))._"
  echo "_Do not edit: run the script again. Heim: for these providers, an algorithm id that is not in this table does not exist, and a parameter that is not in that algorithm's page does not exist. The DaMiT tools (damit_*) are in ALGORITHM-HELP-DAMIT.md._"
  echo
  echo "Providers: ${(j:, :)providers}. Algorithms: $(print -r -- "$ids" | grep -c .)."
  echo
  echo "| Algorithm id | What it is | Full help |"
  echo "|---|---|---|"
} > "$INDEX"
mkdir "$TMPD/algorithm-help"
n=0
for id in ${(f)ids}; do
  [[ -z "$id" ]] && continue
  f="algorithm-help/${id/:/.}.md"
  # stderr is dropped: a provider can log while describing itself (a default layer it
  # looks for and does not find), and that line is about this machine, not the tool
  body=$("$QP" help "$id" 2>/dev/null | sed -e "s|${ROOT:-/nonexistent-root}/profiles/default|<QGIS profile>|g" -e "s|$HOME|~|g" || true)
  [[ -z "$body" ]] && body="(no help for $id)"
  # the first line of the help is "<display name> (<id>)"
  title=${${body%%$'\n'*}% \(${id}\)}
  {
    echo "# $id"
    echo
    echo "_Generated by dump-algorithm-help.zsh from \`qgis_process help $id\`. Do not edit. The full list of ids is in ../ALGORITHM-HELP.md._"
    echo
    echo '```'
    print -r -- "$body"
    echo '```'
  } > "$TMPD/$f"
  if (( $(wc -c < "$TMPD/$f") > LIMIT )); then
    print -u2 "$f is over $((LIMIT / 1024)) KB: rag_index.py would skip it. Nothing was replaced."
    rm -rf "$TMPD"
    exit 1
  fi
  echo "| \`$id\` | ${title//|/\\|} | [$f]($f) |" >> "$INDEX"
  n=$((n + 1))
done

# replace the generated folder and the index together, so a tool that was removed loses its page
rm -rf "$HERE/algorithm-help"
mv "$TMPD/algorithm-help" "$HERE/algorithm-help"
mv "$INDEX" "$OUT"
rmdir "$TMPD" 2>/dev/null || true
echo "Wrote $OUT and $n pages in $HERE/algorithm-help ($n algorithms from ${#providers} providers)"
