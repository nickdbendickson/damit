#!/bin/zsh
# Double-click this file in Finder to install (or update) both local AIs, Heim and Vor, on this Mac.
# The first time, macOS may say it is from an unidentified developer: right-click it, choose Open,
# then Open again. It runs the two installers in this folder, one after the other.
cd "${0:A:h}" || exit 1
zsh heim/setup-local-heim.sh && zsh vor/setup-vor.zsh --ocr
rc=$?
echo ""
if (( rc == 0 )); then
  echo "Done. Close this window and open a NEW Terminal window: heim, vor and ai are ready there."
else
  echo "The install stopped (exit $rc). Fix what it says above, then double-click this file again:"
  echo "it carries on from where it stopped."
fi
read -k1 "?Press any key to close this window."
exit $rc
