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
