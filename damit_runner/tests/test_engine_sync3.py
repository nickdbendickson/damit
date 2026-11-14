"""DamIT Runner 0.6.1: four fixes brought over from DamSafety Runner 3.20.4 and 3.20.5, and one
of DamIT's own that the tests of the four found.

  1. LISFLOOD-FP flow sections (gauges) near the east or south edge of the model read 0
     (found by DamSafety's Lake Delhi 2010 validation run): the section is centred on the
     gauge and no longer than LISFLOOD-FP will measure
  2. a LISFLOOD-FP path that is no program is named in plain words (Windows errors 193, 216)
  3. the kill stage of a stop calls kill(), also where Python has no signal.SIGKILL (Windows)
  4. culvert prep takes the vertex count of a line before the line is replaced
  5. DamIT's own: keep_awake() takes the `log` argument the LISFLOOD-FP and ANUGA runners
     pass. It did not, so a model run stopped with a TypeError before the solver started

1 to 4 are DamSafety's tests with DamIT's names. Pure Python and numpy; no QGIS, no model."""
import inspect
import math
import os
import shutil
import signal
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.compat import keepawake as ka  # noqa: E402
from damit_runner.core import culvert_prep as cp  # noqa: E402
from damit_runner.core import lisflood as lf  # noqa: E402
from damit_runner.core import wallclock as wc  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def _lisflood_gauge_rows_cols(x, y, direction, length, nx, ny, dx):
    """What LISFLOOD-FP 8.3 measures for one .gauge line (input.cpp, LoadGauges): the cell
    range of the section after its own limit. Returns (first, last) in metres along the
    section's axis: y for E/W sections (running south), x for N/S ones (running east)."""
    gx = min(max(int(math.floor(x / dx)), 0), nx - 1)
    gy = min(max(ny - 1 - int(math.floor(y / dx)), 0), ny - 1)
    cells = int(math.ceil(length / dx))
    if direction in ("N", "S") and gy + cells > ny - 1:
        cells = ny - 1 - gy
    elif direction in ("E", "W") and gx + cells > nx - 1:
        cells = nx - 1 - gx
    if direction in ("E", "W"):
        top = (ny - gy) * dx                     # the top edge of the first row
        return top - cells * dx, top
    return gx * dx, (gx + cells) * dx


@test
def gauge_section_stays_on_the_gauge_when_lisflood_shortens_it():
    """LISFLOOD-FP limits an E/W section to (columns - 1 - the gauge's column) cells and keeps
    the first of them. A whole-grid section written from the grid's top therefore ended above
    the river: the Lake Delhi 2010 run (662 x 772 cells of 30 m) read 0 at three of four
    bridges for 48 hours."""
    nx, ny, dx = 662, 772, 30.0
    w = 23160.0                                           # the longer side of the model
    for gx, gy, direction in ((15354.9, 7969.7, "E"), (16459.3, 6216.9, "E"),
                              (17686.0, 6444.2, "W"), (9930.0, 12890.7, "S"),
                              (4000.0, 3000.0, "N")):
        x, y, d, length = lf._gauge_line(gx, gy, direction, w, nx, ny, dx)
        lo, hi = _lisflood_gauge_rows_cols(x, y, d, length, nx, ny, dx)
        along = gy if direction in ("E", "W") else gx
        assert lo + dx < along < hi - dx, (direction, gx, gy, x, y, length, lo, hi)
        # LISFLOOD-FP has nothing left to cut: the section written is the one measured
        assert abs((hi - lo) - int(math.ceil(length / dx)) * dx) < 1e-6, (direction, length)
        assert length <= lf.gauge_reach_m(gx, gy, direction, nx, ny, dx) + 1e-6
        assert length > 2000.0, (direction, length)
    # the old line for the first gauge (from the grid's top, 15,930 m) is cut by LISFLOOD-FP
    # to 150 cells, which end 3.4 km above the gauge
    lo, _hi = _lisflood_gauge_rows_cols(15354.873, 15934.721, "E", 15930.0, nx, ny, dx)
    assert lo > 7969.7 + 3000.0, lo
    # a gauge in the last column has no section at all; one near it has a short one
    assert lf._gauge_line((nx - 0.5) * dx, 9000.0, "E", w, nx, ny, dx)[3] == 0.0
    assert lf.gauge_reach_m((nx - 10.5) * dx, 9000.0, "E", nx, ny, dx) == 10 * dx


@test
def a_lisflood_file_that_is_no_program_is_named_in_plain_words():
    from damit_runner.core.breach import Hydrograph
    from damit_runner.core.grid import Grid
    d = tempfile.mkdtemp(prefix="damit_sync3_")
    try:
        exe = os.path.join(d, "lisflood.exe" if os.name == "nt" else "lisflood")
        with open(exe, "w") as f:
            f.write("this is not a program\n")
        os.chmod(exe, 0o755)
        nr, nc, dx = 20, 100, 20.0
        X, Y = np.meshgrid((np.arange(nc) + 0.5) * dx, (np.arange(nr) + 0.5) * dx)
        z = 100.0 - 0.002 * X + 0.02 * np.abs(Y - nr * dx / 2)
        dem = Grid(z[::-1], 0.0, nr * dx, dx)
        hy = Hydrograph(np.array([0.0, 600.0, 1200.0]), np.array([30.0, 30.0, 0.0]), "test")
        st = lf.LisfloodSettings(exe, arrival_depth_m=0.3, sim_time_s=600.0, massint_s=60.0,
                                 initial_tstep_s=1.0)
        wd = os.path.join(d, "wd")
        par = lf.write_inputs(wd, dem, (30.0, nr * dx / 2 + 5), hy, st)
        try:
            lf.run(wd, par, st)
            raise AssertionError("expected ModelError")
        except lf.ModelError as e:
            assert "could not be started" in str(e) and exe in str(e), str(e)
            assert "is not executable on this computer" in str(e), str(e)
        assert lf._not_a_program(OSError(8, "Exec format error"))
        for code in (193, 216):
            win = OSError(22, "not a program")
            win.winerror = code
            assert lf._not_a_program(win), code
        assert not lf._not_a_program(FileNotFoundError(2, "No such file or directory"))
        assert not lf._not_a_program(PermissionError(13, "Permission denied"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _Proc:
    """A process that ignores the first request and has no process group."""

    def __init__(self):
        self.pid, self.returncode, self.calls = 4242, None, []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")
        self.returncode = -9


@test
def the_kill_stage_kills_also_where_python_has_no_sigkill():
    assert wc.SIGKILL == getattr(signal, "SIGKILL", 9)
    clock = [0.0]

    def no_group(pid, sig):
        raise PermissionError("not ours")
    p = _Proc()
    r = wc.stop_group(p, grace=5, wall=lambda: clock[0], mono=lambda: clock[0],
                      sleep=lambda s: clock.__setitem__(0, clock[0] + s), killpg=no_group)
    assert p.calls == ["terminate", "kill"], p.calls
    assert r["sent"] == ["SIGTERM to the process", "SIGKILL to the process"], r
    assert r["exited_after"] == "SIGKILL", r
    # the comparison is with the module's own number, not with a missing signal.SIGKILL
    assert 'getattr(signal, "SIGKILL", None)' not in inspect.getsource(wc._signal_group)


@test
def culvert_prep_counts_the_vertices_before_the_line_is_replaced():
    """Reading the old geometry after Feature.SetGeometry replaced it ended the process on
    Windows. The fault needs GDAL and a structures layer to show; here the order is checked
    in the source: the count is taken, and the reference dropped, before SetGeometry."""
    src = inspect.getsource(cp.write_copy)
    take, drop, put = src.index("n_old = g.GetPointCount()"), src.index("g = None"), \
        src.index("f.SetGeometry(")
    assert take < drop < put, (take, drop, put)
    assert "g.GetPointCount() - 2" not in src
    assert "n_old - 2" in src


def _fresh_keepawake():
    ka._state.update(count=0, proc=None, method=None, checked=None, warned=False)


@test
def keep_awake_takes_the_log_the_model_runners_pass():
    """The runners call keep_awake(name, log=log). The block must run whether or not this
    computer has a sleep blocker, and an error of the block must come out unchanged."""
    from damit_runner.core import anuga_model as am
    assert "keep_awake(engine_name(st.exe), log=log)" in inspect.getsource(lf)
    assert 'keep_awake("ANUGA", log=log)' in inspect.getsource(am)
    assert "log" in inspect.signature(ka.keep_awake).parameters
    old_cmd, old_env = ka._side_command, os.environ.get(ka.ENV_SWITCH)
    try:
        os.environ.pop(ka.ENV_SWITCH, None)
        # no sleep blocker on this computer: said once, the block still runs
        ka._side_command = lambda why: (None, None, "no blocker here")
        _fresh_keepawake()
        said, ran = [], []
        for _ in range(2):
            with ka.keep_awake("LISFLOOD-FP", log=said.append) as on:
                ran.append(on)
        assert ran == [False, False], ran
        assert len(said) == 1 and "no blocker here" in said[0], said
        # a blocker that works is started once, shared by nested blocks, and stopped
        _fresh_keepawake()
        ka._side_command = lambda why: ([sys.executable, "-c", "import time; time.sleep(60)"],
                                        "stand-in", None)
        said = []
        with ka.keep_awake("ANUGA", log=said.append) as on:
            proc = ka._state["proc"]
            assert on and proc is not None and proc.poll() is None
            with ka.keep_awake("ANUGA", log=said.append):
                assert ka._state["proc"] is proc and ka._state["count"] == 2
        assert ka._state["proc"] is None and proc.poll() is not None
        assert said == ["Keeping the computer awake while ANUGA runs (stand-in)."], said
        # an error of the block passes through, and the blocker is stopped
        try:
            with ka.keep_awake("ANUGA"):
                proc = ka._state["proc"]
                raise ValueError("the model failed")
        except ValueError as e:
            assert str(e) == "the model failed"
        else:
            raise AssertionError("the error was swallowed")
        assert ka._state["proc"] is None and proc.poll() is not None
        # the switch
        os.environ[ka.ENV_SWITCH] = "0"
        ka._side_command = lambda why: 1 / 0
        with ka.keep_awake("ANUGA", log=said.append) as on:
            assert on is False
        # a log that fails does not stop a run either
        os.environ.pop(ka.ENV_SWITCH, None)
        _fresh_keepawake()
        ka._side_command = lambda why: (None, None, "no blocker here")
        with ka.keep_awake("ANUGA", log=lambda m: 1 / 0):
            pass
    finally:
        ka._side_command = old_cmd
        _fresh_keepawake()
        if old_env is None:
            os.environ.pop(ka.ENV_SWITCH, None)
        else:
            os.environ[ka.ENV_SWITCH] = old_env


class Ported(unittest.TestCase):
    """The DamSafety tests of these changes, each as one unittest case."""


for _fn in TESTS:
    setattr(Ported, "test_" + _fn.__name__, (lambda fn: lambda self: fn())(_fn))


if __name__ == "__main__":
    unittest.main()
