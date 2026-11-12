#!/usr/bin/env zsh
# refresh-library.zsh — refresh the dam-research library on a schedule: download any new/updated
# catalog + ASDSO files, then re-index them so `damresearch` answers stay current. Safe to run
# repeatedly; files already downloaded are skipped and nothing is deleted.
#
#   ./refresh-library.zsh                 # all catalog groups + ASDSO pages, then ingest
#   ./refresh-library.zsh --catalog software   # only one group (passes through to fetch_asdso.py)
#   ./refresh-library.zsh --no-ingest     # download only, skip the ingest step
#   ./refresh-library.zsh --dry-run       # list what would be fetched, fetch nothing, no ingest
#   DAMRESEARCH_HOME=/path ./refresh-library.zsh
#
# Schedule it (nothing leaves the machine; all three are user-level, no root):
#   macOS (launchd), weekly Monday 03:00 — save as
#     ~/Library/LaunchAgents/org.damsuite.research-refresh.plist  with ProgramArguments
#     [/bin/zsh, <abs path>/refresh-library.zsh] and a StartCalendarInterval of Weekday=1,Hour=3;
#     then: launchctl load ~/Library/LaunchAgents/org.damsuite.research-refresh.plist
#   Linux (cron):   crontab -e  ->  0 3 * * 1  /bin/zsh <abs path>/refresh-library.zsh >> ~/DamResearch/reports/refresh.log 2>&1
#   Windows:        use research/refresh-library.ps1 with Task Scheduler (see that file's header).
set -e
HERE=${0:A:h}
PY=${PYTHON:-python3}
HOME_DIR=${DAMRESEARCH_HOME:-$HOME/DamResearch}

INGEST=1
PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-ingest) INGEST=0; shift ;;
    --dry-run)   INGEST=0; PASS+=("$1"); shift ;;   # dry-run never ingests
    *) PASS+=("$1"); shift ;;
  esac
done
# default to all catalog groups + ASDSO pages when the caller named nothing
[[ ${#PASS} -eq 0 || "${PASS[*]}" != *--catalog* ]] && PASS=(--catalog --asdso $PASS)

echo "== dam-research library refresh =="
echo "Library root: $HOME_DIR  ($(date -u +%Y-%m-%dT%H:%MZ))"

# 1) refresh the offline URL list, then download new/updated files (skips what's already there)
mkdir -p "$HOME_DIR/library" "$HOME_DIR/reports"
$PY "$HERE/fetch_asdso.py" --urls "$HOME_DIR/library/library-urls.txt" || true
$PY "$HERE/fetch_asdso.py" $PASS

# 2) re-index, using the installed research python if present (works from cron, no alias needed)
if [[ "$INGEST" == 1 ]]; then
  DR_PY="$HOME/local-ai/research/python"; DR="$HOME/local-ai/research/damresearch.py"
  [[ -x "$DR_PY" && -f "$DR" ]] || { DR_PY="$PY"; DR="$HERE/damresearch.py"; }
  echo "Indexing new files (damresearch ingest)..."
  "$DR_PY" "$DR" ingest
fi

echo "Done. Library in $HOME_DIR/library."
[[ "$INGEST" == 1 ]] || echo "Skipped ingest — run 'damresearch ingest' when ready."
