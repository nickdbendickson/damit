#!/usr/bin/env bash
# Run every DamIT test: pure-Python suites with any python3, then the real-QGIS integration test
# offscreen with a throw-away scratch profile, at low priority and single-threaded.
#
#   tests/run_tests.sh                       # QGIS python from $DAMIT_QGIS_PYTHON or 'python3'
#   DAMIT_QGIS_PYTHON="conda run --no-capture-output -n qgis334 python" tests/run_tests.sh
#
# Never starts a flood model (the tests also patch subprocess.Popen to fail).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/damit_tests_XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
export QT_QPA_PLATFORM=offscreen
export QGIS_CUSTOM_CONFIG_PATH="$SCRATCH/profile"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 GDAL_NUM_THREADS=1 QT_ENABLE_HIGHDPI_SCALING=0
export TMPDIR="$SCRATCH"
unset DAMIT_CATALOG_DIR
mkdir -p "$QGIS_CUSTOM_CONFIG_PATH"
cd "$ROOT"
PY="${DAMIT_PYTHON:-python3}"
QPY="${DAMIT_QGIS_PYTHON:-python3}"
echo "== pure Python ($PY)"
nice -n 19 $PY -m unittest -v damit_catalog.tests.test_catalog damit_screener.tests.test_workflow \
    damit_runner.tests.test_rundam tests.test_metadata
nice -n 19 $PY damit_hazard/tests/run_tests.py
echo "== real QGIS, offscreen, scratch profile $QGIS_CUSTOM_CONFIG_PATH ($QPY)"
nice -n 19 $QPY -m unittest -v tests.test_qgis_integration
nice -n 19 $QPY damit_hazard/tests/run_tests.py qgis
