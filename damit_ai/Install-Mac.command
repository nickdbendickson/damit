#!/bin/zsh
# Double-click this file in Finder to install (or update) both local AIs, Heim and Vor, on this Mac.
# The first time, macOS says it can't verify the file (it is not signed): System Settings >
# Privacy & Security > Open Anyway, or run it in Terminal as  zsh Install-Mac.command  (no popup).
# It runs the two installers in this folder, one after the other.
cd "${0:A:h}" || exit 1
zsh heim/setup-local-heim.sh && zsh vor/setup-vor.zsh --ocr
rc=$?
# Vor's library: the offline pack's publications (download-all-mac.sh) when the library has none yet,
# then one index of whatever is there (nothing already in the library is overwritten).
if (( rc == 0 )); then
  eval "$(grep -E '^export VOR_(HOME|EMBED|MODEL|NUM_CTX)=' ~/.zshrc 2>/dev/null)"   # what setup-vor wrote
  lib="${VOR_HOME:-$HOME/Vor}/library"
  off="$PWD/offline/Vor/library"
  has_docs() { [[ -n "$(find "$1" -type f \( -iname '*.pdf' -o -iname '*.md' -o -iname '*.txt' \) -print -quit 2>/dev/null)" ]]; }
  if ! has_docs "$lib" && [[ -n "$(find "$off" -type f -iname '*.pdf' -print -quit 2>/dev/null)" ]]; then
    echo "== Vor's library: copying the offline pack's publications into $lib"
    mkdir -p "$lib" && cp -Rn "$off/." "$lib/"
  fi
  vhome="${lib:h}"
  # "indexed" means the index holds passages: an index FILE alone can be empty (a stopped first
  # ingest, or one opened before the library was copied in), and Vor then answers from nothing.
  indexed() {
    local f
    for f in "$vhome/vor.db" "$vhome/research.db"; do
      [[ -f "$f" ]] || continue
      "$HOME/local-ai/vor/python" -c 'import sqlite3,sys; sys.exit(0 if sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchone()[0] else 1)' "$f" "SELECT COUNT(*) FROM chunks" 2>/dev/null
      return
    done
    return 1
  }
  if has_docs "$lib" && ! indexed; then
    echo "== Vor's library: indexing it (a while for a full library; Ctrl+C is safe, then run: vor ingest)"
    VOR_HOME="$vhome" "$HOME/local-ai/vor/python" "$HOME/local-ai/vor/vor.py" ingest \
      || echo "The library index stopped; in a new Terminal window run:  vor ingest"
  fi
fi
echo ""
if (( rc == 0 )); then
  echo "Done. Close this window and open a NEW Terminal window: heim, vor and ai are ready there."
else
  echo "The install stopped (exit $rc). Fix what it says above, then double-click this file again:"
  echo "it carries on from where it stopped."
fi
read -k1 "?Press any key to close this window."
exit $rc
