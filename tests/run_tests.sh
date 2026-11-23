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
unset DAMIT_CATALOG_DIR NDSUITE_SETTINGS
for v in $(env | sed -n 's/^\(NDBREACH_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
mkdir -p "$QGIS_CUSTOM_CONFIG_PATH"
cd "$ROOT"
PY="${DAMIT_PYTHON:-python3}"
QPY="${DAMIT_QGIS_PYTHON:-python3}"
echo "== pure Python ($PY)"
nice -n 19 $PY -m unittest -v damit_catalog.tests.test_catalog damit_screener.tests.test_workflow damit_screener.tests.test_pack_terrain \
    damit_screener.tests.test_engine2d damit_runner.tests.test_rundam damit_runner.tests.test_flood damit_runner.tests.test_scenarios damit_runner.tests.test_followups damit_runner.tests.test_batch_workers damit_runner.tests.test_ckpt_sign damit_runner.tests.test_qa_maps_headless damit_runner.tests.test_engine_sync3 damit_runner.tests.test_sgc damit_runner.tests.test_anuga_passes damit_runner.tests.test_dam_point_line damit_runner.tests.test_zunit_hecras damit_runner.tests.test_nodata_true_hole damit_runner.tests.test_port_robustness damit_runner.tests.test_pothole_fill damit_runner.tests.test_inflow_order damit_runner.tests.test_breach_xu_zhang damit_runner.tests.test_refill_tile_check damit_runner.tests.test_spread_rule damit_runner.tests.test_report_provenance damit_runner.tests.test_crossing_barriers damit_runner.tests.test_h12_tailwater_disclosure damit_runner.tests.test_channel_burn_width_warn damit_runner.tests.test_dem_edits damit_runner.tests.test_breach_vtg damit_runner.tests.test_culvert_on_dam tests.test_metadata tests.test_engine_parity tests.test_atlas14_shared damit_runner.tests.test_runner_min_install tests.test_true_hole_parity damit_runner.tests.test_gdal_mode damit_runner.tests.test_atomicio \
    tests.test_hazard_screener_agree tests.test_class_benchmark tests.test_placeholder_tables
nice -n 19 $PY damit_hazard/tests/run_tests.py
echo "== DamIT Core, Setup, Data, Hazard Lite, PMP: pure Python ($PY)"
export DAMIT_SETTINGS="$SCRATCH/damit_settings.json"
nice -n 19 $PY -m unittest -v damit_core.tests.test_core damit_setup.tests.test_setup damit_data.tests.test_data damit_data.tests.test_providers \
    damit_hazardlite.tests.test_engine damit_pmp.tests.test_atlas14 damit_pmp.tests.test_green_ampt tests.test_metadata_suite
echo "== real QGIS, offscreen, scratch profile $QGIS_CUSTOM_CONFIG_PATH ($QPY)"
nice -n 19 $QPY -m unittest -v tests.test_qgis_integration
nice -n 19 $QPY damit_hazard/tests/run_tests.py qgis
nice -n 19 $QPY -m unittest -v tests.test_qgis_new_plugins
nice -n 19 $QPY -m unittest -v damit_finder.tests.test_core damit_finder.tests.test_finder damit_finder.tests.test_qgis
