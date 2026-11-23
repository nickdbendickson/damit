"""DamIT port of the generic tests of DamSafety Runner tests/test_dwr_line_batch.py (DWR_Plugins cd6345c7), run
by unittest through damit_runner/tests/_dwr_registry.py. The test bodies are DamSafety's.

DamIT: the rest of that file tests core/dwr_lines.py (a batch dam's line from the ND DWR offline pack, matched by
DWR structure id), its CLI and chain wiring; dwr_lines is not ported (RUNNER_PORT_PLAN D'), so only the dam point
check's centre snap and default, the arched-line side check and the once-per-run crest warning are here."""
import numpy as np

from damit_runner.core import dam_point_check as dpc
from damit_runner.core import workflow
from damit_runner.tests._dwr_registry import test


@test
def dam_point_check_default_move_and_centre_snap():
    """3.20.13: move is the default; a point on the embankment but off the found line's centre
    moves along to the centre (C1) in move mode only, when every gate and V pass; a point at
    the centre stays."""
    from damit_runner.tests import dwr_synthetic_dams as S
    from damit_runner.tests.test_dam_point_check import _survey, _check
    assert dpc.DEFAULT_MODE == "move" == workflow.RunSettings().dam_point_check
    sv, rp = _survey(S.enclosed, (0.0, 60.0))                 # on the crest, 60 m off centre
    d = dpc.decide(sv, rp, S.H, mode="move")
    assert d["outcome"] == "move" and d.get("centre_snap") and not d["gates_failed"], d
    assert [t[0] for t in d["triggers"]] == ["C1"] and d["centre_m"] > 55.0, d
    w = dpc.decide(sv, rp, S.H, mode="warn")
    assert w["outcome"] == "kept" and not w["warn"] and not w["would_move"], w
    assert "\"move\" would put it there" in w["kept_why"], w
    rec = _check(S.enclosed, (0.0, 60.0))
    assert rec["outcome"] == "moved" and rec["centre_snap"], rec
    assert abs(rec["_mid_xy"][1]) < 5.0 and abs(rec["_mid_xy"][0]) < 5.0, rec["_mid_xy"]
    assert dpc.batch_text(rec) == "moved {:.0f} m (to the embankment's centre)".format(
        rec["moved_m"])
    assert "the point given is on the embankment" in dpc.warning_text(rec)
    # at the centre (closer than CENTRE_MIN_M): kept
    sv0, rp0 = _survey(S.enclosed, (0.0, 4.0))
    d0 = dpc.decide(sv0, rp0, S.H, mode="move")
    assert d0["outcome"] == "kept" and d0["centre_m"] < dpc.CENTRE_MIN_M, d0
    # a gate that fails keeps the point (no REVIEW warning)
    dg = dpc.decide(sv, rp, S.H, mode="move", crest_length_m=20.0)        # G7d
    assert dg["outcome"] == "kept" and not dg["warn"] and "G7d" in {g[0] for g in
                                                                  dg["gates_failed"]}, dg
    assert "not moved there" in dg["kept_why"], dg


@test
def inflow_side_check_on_an_arched_dam_line():
    """3.20.13 review (DWR-3034): the line normal of check (f) is taken at the segment nearest
    the inflow, not from the end-to-end chord. An inflow below an arched line but on the
    reservoir side of its chord, the trace running downstream: no problem."""
    import math
    from damit_runner.core import terrain
    arc = [(x, 60.0 * math.sin(math.pi * x / 170.0)) for x in np.linspace(0.0, 170.0, 18)]
    inflow = (56.0, 15.0)
    path = [(56.0, 15.0 - 10.0 * k) for k in range(30)]
    chk = terrain.inflow_side_check((85.0, 60.0), inflow, path, (0.0, -1.0), crest_line=arc)
    assert chk["ok"] and chk["trace_vs_dam_line_normal"] > 0.5, chk
    # a trace that runs back up to the arc is still caught
    back = [(56.0, 15.0 + 5.0 * k) for k in range(30)]
    chk = terrain.inflow_side_check((85.0, 60.0), inflow, back, None, crest_line=arc)
    assert not chk["ok"] and chk["trace_vs_dam_line_normal"] < 0, chk
    # a straight line: as before (the chord)
    line = [(0.0, 0.0), (170.0, 0.0)]
    chk = terrain.inflow_side_check((85.0, 0.0), (56.0, -15.0), [(56.0, -15.0 - 10.0 * k)
                                                                 for k in range(30)],
                                    (0.0, -1.0), crest_line=line)
    assert chk["ok"] and chk["trace_vs_dam_line_normal"] == 1.0, chk


@test
def crest_raised_warning_is_added_once_per_run():
    # Nick's 2026-11-16 two-dam run listed it once per LISFLOOD-FP pass (six times on DWR-4031)
    w = []
    assert workflow.add_crest_raised_warning(w, 12, "at the crest point")
    assert not workflow.add_crest_raised_warning(w, 12, "at the crest point")
    assert not workflow.add_crest_raised_warning(w, 15, "along the dam line")
    assert not workflow.add_crest_raised_warning([], 0, "at the crest point")
    assert len(w) == 1 and w[0].startswith("Crest raised to the top of dam") and "12 cells" in w[0]


from damit_runner.tests._dwr_registry import make_case  # noqa: E402

DamSafetyTests = make_case(__name__)
