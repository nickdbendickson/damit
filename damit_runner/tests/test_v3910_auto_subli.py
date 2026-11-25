"""DamIT port of DamSafety Runner tests/test_v3910_auto_subli.py (DWR_Plugins c86ba915, Runner 3.93.0 / Boann 6.0.0), run by
unittest through damit_runner/tests/_dwr_registry.py. The test bodies are DamSafety's; only import paths
changed. Not ported: v3910_cli_auto_reads_the_model_cell (DamSafety-only CLI / record)."""
"""3.91.0: "Recommended (auto)" runs Boann's sub-grid local inertial on a model cell of 3 m or finer.

Nick 2026-11-24, on the DWR-2801 2 m LiDAR test (88 M cells, 24 h, M2 Pro GPU): against the plain
2 m run (121 min), sub-grid r4 (8 m solver cells on the 2 m ground) was within 0.08 ft in the median
cell, 0.23 ft at the 90th percentile, CSI 0.93, in 7.8 min; plain ACC on 8 m cells 0.24 / 0.83 ft,
CSI 0.75. Where auto would run Boann ACC (an Apple GPU, or the CPU build with no LISFLOOD-FP) and the
cell is fine, it now runs gpu-subli; a coarser cell, an unknown cell, LISFLOOD-FP and every engine
picked by name are unchanged."""
import os
import tempfile
from unittest import mock

from damit_runner.tests._dwr_registry import test


@test
def v3910_auto_fine_cell_threshold():
    from damit_runner.core import lisflood as lf
    assert lf.AUTO_SUBLI_MAX_CELL_M == 3.0
    for c in (1, 1.0, 2, 2.5, 3, 3.0, "2"):
        assert lf.auto_fine_cell(c), c
    for c in (None, "", "x", 0, -1, 3.01, 5, 10.0, 30):
        assert not lf.auto_fine_cell(c), c


@test
def v3910_auto_picks_subli_on_a_fine_cell_where_it_would_run_boann():
    from damit_runner.core import lisflood as lf
    from damit_runner.core.metalflood import backends as mfb
    fake_lf = os.path.join(tempfile.mkdtemp(prefix="ndbr_v3910_"), "lisflood")
    open(fake_lf, "w").close()
    with mock.patch.object(mfb, "metal_available", return_value=(True, "M2 Pro")):
        exe, why = lf.choose_auto(fake_lf, 2.0)
        assert exe == lf.GPU_SUBLI_EXE and lf.is_gpu_subli(exe), why
        assert "sub-grid local inertial" in why and "8 m" in why and "GPU" in why, why
        exe, why = lf.choose_auto(fake_lf, 3.0)
        assert exe == lf.GPU_SUBLI_EXE, why
        for coarse in (5.0, 10.0, None):              # coarser or unknown: plain ACC as before
            exe, why = lf.choose_auto(fake_lf, coarse)
            assert exe == lf.GPU_EXE and "sub-grid" not in why, (coarse, why)
        assert lf.choose_auto(fake_lf)[0] == lf.GPU_EXE   # old call signature unchanged
    with mock.patch.object(mfb, "metal_available", return_value=(False, "not macOS")):
        # LISFLOOD-FP installed: it stays the engine, whatever the cell
        exe, why = lf.choose_auto(fake_lf, 2.0)
        assert exe == fake_lf and "LISFLOOD-FP" in why, why
        with mock.patch.object(mfb, "prebuilt_available", return_value=True):
            exe, why = lf.choose_auto("", 1.0)
            assert exe == lf.GPU_SUBLI_EXE and "CPU" in why, why
            exe, why = lf.choose_auto("", 10.0)
            assert exe == lf.GPU_EXE, why
        with mock.patch.object(mfb, "prebuilt_available", return_value=False), \
                mock.patch.object(mfb, "find_compiler", return_value=None):
            exe, why = lf.choose_auto("", 2.0)
            assert exe == "" and "no flood engine" in why, why


@test
def v3910_named_engines_are_not_swapped():
    """Only the auto word changes; a Boann engine named by word stays that engine at any cell."""
    from damit_runner.core import lisflood as lf
    assert lf.resolve_exe("gpu") == lf.GPU_EXE
    assert lf.resolve_exe("gpu-subli") == lf.GPU_SUBLI_EXE
    assert lf.resolve_exe("lisflood") == "lisflood"


from damit_runner.tests._dwr_registry import make_case  # noqa: E402

DamSafetyTests = make_case(__name__)
