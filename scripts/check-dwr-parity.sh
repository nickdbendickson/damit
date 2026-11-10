#!/usr/bin/env bash
# Check engine parity between damit_runner and DamSafety_Runner.
#
# The damit_runner core/ modules were ported from DamSafety_Runner. This script
# compares key files to detect divergence. Run it after pulling both repos:
#
#   ./scripts/check-dwr-parity.sh /path/to/dwr_plugins
#
# Exit 0: in sync (or expected divergence). Exit 1: unexpected differences.
set -euo pipefail

DWR="${1:-../dwr_plugins}"
DAMIT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$DWR/DamSafety_Runner/core" ]; then
    echo "ERROR: DamSafety_Runner not found at $DWR"
    echo "Usage: $0 /path/to/dwr_plugins"
    exit 1
fi

echo "DamIT Runner: $DAMIT/damit_runner/core/"
echo "DWR Runner:   $DWR/DamSafety_Runner/core/"
echo ""

# Files that should stay identical (shared pure-Python logic, no ND references)
SHARED_FILES=(
    "warp_opts.py"
    "dem_zunit.py"
)

# Files ported and intentionally diverged (ND→US generalization)
DIVERGED_FILES=(
    "units.py"              # ND DWR comment → FEMA 333 comment
    "builtin_lisflood.py"   # NAME string changed
    "lisflood.py"           # provider name changed
    "breach.py"             # ND references stripped
    "grid.py"               # generalized
    "grid_default.py"       # generalized
)

ok=0
warn=0

echo "=== Shared files (should be identical) ==="
for f in "${SHARED_FILES[@]}"; do
    a="$DAMIT/damit_runner/core/$f"
    b="$DWR/DamSafety_Runner/core/$f"
    if [ ! -f "$a" ]; then
        echo "  MISSING (damit): $f"
        ((warn++)) || true
        continue
    fi
    if [ ! -f "$b" ]; then
        echo "  MISSING (dwr): $f"
        ((warn++)) || true
        continue
    fi
    if diff -q "$a" "$b" > /dev/null 2>&1; then
        echo "  OK: $f"
    else
        echo "  DIFFERS: $f"
        diff --unified=0 "$b" "$a" | head -20
        ((warn++)) || true
    fi
done

echo ""
echo "=== Ported files (expected divergence) ==="
for f in "${DIVERGED_FILES[@]}"; do
    a="$DAMIT/damit_runner/core/$f"
    b="$DWR/DamSafety_Runner/core/$f"
    if [ -f "$a" ] && [ -f "$b" ]; then
        lines=$(diff "$a" "$b" 2>/dev/null | grep "^[<>]" | wc -l)
        echo "  $f: $lines line differences (expected)"
    else
        echo "  $f: one side missing"
    fi
done

echo ""
echo "=== Compat shims (damit-only, no DWR counterpart) ==="
ls "$DAMIT/damit_runner/compat/"*.py | while read f; do
    echo "  $(basename "$f")"
done

echo ""
if [ $warn -eq 0 ]; then
    echo "Parity check: OK (${#SHARED_FILES[@]} shared files match)"
    exit 0
else
    echo "Parity check: $warn file(s) need attention"
    exit 1
fi
