"""Helpers of DamSafety Runner tests/test_v320.py (DWR_Plugins bd9f159d) that other ported DamSafety tests import:
a small DamData and RunSettings. DamIT import paths; the values are DamSafety's."""
import sys


def _dam(**k):
    from damit_runner.core import breach as br
    d = dict(dam_id="T1", dam_height_ft=25.0, storage_top_acft=500.0, top_of_dam_ft=1850.0,
             surface_area_top_ac=60.0)
    d.update(k)
    return br.DamData(**d)


def _settings(**k):
    from damit_runner.core import workflow
    d = dict(cell_size_m=50.0, planning_cell_m=90.0, initial_length_mi=1.0, half_width_mi=0.5,
             expand_step_mi=1.0, max_iterations=2, lisflood_exe=sys.executable, sim_time_hr=4.0)
    d.update(k)
    return workflow.RunSettings(**d)


# DamSafety tests/test_v320.py fake_models (DWR_Plugins bd14874b), for the ported dam point check tests.
import contextlib  # noqa: E402
import os  # noqa: E402

import numpy as np  # noqa: E402


@contextlib.contextmanager
def fake_models(depth_m=0.50, base_m=0.40, calls=None, vary=None):
    """LISFLOOD-FP stubbed: a flood band |y| < 300 m east of the dam, `depth_m` deep with the
    breach and `base_m` without it (the "_base" run folders). `vary(wd)` -> factor on the
    depth (per-run differences)."""
    from damit_runner.core import lisflood as lf

    def fake_run(wd, par, st, progress=None, cancel=None, log=None, name="run"):
        if calls is not None:
            calls.append(wd)
        return 60.0

    def fake_read(wd, dem, st, hydrograph, name="run"):
        X, Y = np.meshgrid(dem.x_centers(), dem.y_centers())
        v = base_m if wd.rstrip(os.sep).endswith("_base") else depth_m
        if vary is not None:
            v = v * vary(wd)
        d = np.where((X > 0) & (np.abs(Y) < 300), v, np.nan)
        vel = np.where(np.isfinite(d), 1.2, np.nan)
        arr = np.where(np.isfinite(d), X / 1.0 / 3600.0 + 0.1, np.nan)
        wse = np.where(np.isfinite(d), dem.data + np.nan_to_num(d), np.nan)
        stats = {"max_volume_error_pct": 0.1, "peak_inflow_cfs": 1000.0}
        return lf.Envelopes(dem.like(d, np.nan), dem.like(vel, np.nan), dem.like(arr, np.nan),
                            dem.like(wse, np.nan), stats, [], {})
    old = (lf.run, lf.read_results)
    lf.run, lf.read_results = fake_run, fake_read
    try:
        yield
    finally:
        lf.run, lf.read_results = old
