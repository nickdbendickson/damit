"""DamIT Runner 0.6.0: a batch runs several dams at the same time, each in its own qgis_process
worker (core/batch_workers.py, ported from DamSafety Runner 3.20.0; `WORKERS` on damit_run:batch).

These are DamSafety's tests of the pure module (the plan, the children, the time limit, the merged
row, finding qgis_process and sharing the QGIS profile), with DamIT's names. The child processes
are doubles. The tool itself is checked in tests/test_qgis_integration.py."""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import batch_workers as bw  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn



class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _Proc:
    """A child that ends with `code` after `secs` of the fake clock (None = never)."""
    live = []

    def __init__(self, clock, secs, code=0, on_end=None):
        self.clock, self.t_end, self.code, self.on_end = clock, clock() + secs if secs is not None else None, code, on_end
        self.killed = False
        _Proc.live.append(self)

    def poll(self):
        if self.killed:
            return -9
        if self.t_end is not None and self.clock() >= self.t_end:
            if self.on_end:
                self.on_end()
                self.on_end = None
            return self.code
        return None

    def terminate(self):
        self.killed = True

    kill = terminate


def _jobs(d, names):
    return [{"key": i, "name": n, "cmd": ["x", n], "log": os.path.join(d, n + ".log")}
            for i, n in enumerate(names)]


# --------------------------------------------------------------------------- the plan
@test
def workers_plan_shares_the_cores_and_never_exceeds_the_dams():
    assert bw.clamp_workers("x") == 1 and bw.clamp_workers(0) == 1 and bw.clamp_workers(3) == 3
    assert bw.clamp_workers(999) == bw.MAX_WORKERS
    used, each, text = bw.plan(4, 10, cpus=8)
    assert (used, each) == (4, 2) and "4 dam(s) at a time, 2 thread(s) each" in text
    used, each, text = bw.plan(4, 2, cpus=8)              # two dams: two workers
    assert (used, each) == (2, 4) and "4 were asked for" in text
    used, each, text = bw.plan(8, 20, cpus=4)             # never more workers than CPUs
    assert (used, each) == (4, 1)
    used, each, text = bw.plan(4, 10, threads=6, cpus=8)  # the user's own thread count is kept
    assert (used, each) == (4, 6) and "more threads than CPUs" in text
    assert bw.plan(1, 5, cpus=8)[:2] == (1, 8)


# ----------------------------------------------------------------------- the children
@test
def workers_run_at_most_n_children_and_report_each_one():
    d = tempfile.mkdtemp()
    try:
        clock, seen, log = _Clock(), [], []
        peak = [0]

        def popen(cmd, **kw):
            assert kw["stdout"] is not None and kw["env"] == {"A": "1"}
            running = sum(1 for p in _Proc.live if p.poll() is None)
            peak[0] = max(peak[0], running + 1)
            seen.append(cmd[1])
            return _Proc(clock, 10.0, 0 if cmd[1] != "D3" else 4)
        _Proc.live = []
        res = bw.run_children(_jobs(d, ["D1", "D2", "D3", "D4", "D5"]), 2, log=log.append,
                              env={"A": "1"}, popen=popen, sleep=clock.sleep, clock=clock,
                              poll_s=1.0)
        assert seen == ["D1", "D2", "D3", "D4", "D5"] and peak[0] == 2, (seen, peak)
        assert [res[i][0] for i in range(5)] == [0, 0, 4, 0, 0]
        assert "ended with code 4" in res[2][1]
        assert any(m.startswith("D3 (") and "code 4" in m for m in log)
        assert any("D1: started (1 running)" == m for m in log)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@test
def workers_time_limit_cancel_and_a_child_that_cannot_start():
    d = tempfile.mkdtemp()
    try:
        clock = _Clock()
        _Proc.live = []
        procs = {}

        def popen(cmd, **kw):
            if cmd[1] == "BAD":
                raise OSError("no such program")
            procs[cmd[1]] = _Proc(clock, None if cmd[1] == "SLOW" else 5.0)
            return procs[cmd[1]]
        res = bw.run_children(_jobs(d, ["BAD", "SLOW", "OK"]), 3, timeout_s=60.0, popen=popen,
                              sleep=clock.sleep, clock=clock, poll_s=1.0)
        assert res[0][0] == bw.NOT_STARTED and "could not be started" in res[0][1]
        assert res[1][0] == bw.TIMED_OUT and "1 min" in res[1][1] and procs["SLOW"].killed
        assert res[2] == (0, "")
        # cancel: the running child is ended, the one waiting never starts and has no result
        clock, n = _Clock(), [0]
        procs.clear()

        def cancelled():
            n[0] += 1
            return n[0] > 3
        res = bw.run_children(_jobs(d, ["SLOW", "LATER"]), 1, cancelled=cancelled, popen=popen,
                              sleep=clock.sleep, clock=clock, poll_s=1.0)
        assert res == {0: (bw.CANCELLED, "cancelled")} and procs["SLOW"].killed
        assert "LATER" not in procs
        # stdin goes through a file next to the log
        got = {}

        def popen2(cmd, **kw):
            got["stdin"] = kw["stdin"].read()
            return _Proc(clock, 0.0)
        job = dict(_jobs(d, ["J"])[0], stdin=bw.stdin_json({"A": 1}))
        bw.run_children([job], 1, popen=popen2, sleep=clock.sleep, clock=clock)
        assert json.loads(got["stdin"]) == {"inputs": {"A": 1}}
    finally:
        shutil.rmtree(d, ignore_errors=True)


@test
def workers_row_comes_from_the_child_or_says_why_not():
    d = tempfile.mkdtemp()
    try:
        fields = ("Dam", "Folder", "Status", "Peak_Breach_cfs", "Message")
        p = os.path.join(d, "a.csv")
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerow({"Dam": "A1", "Folder": "/child/A1", "Status": "done",
                        "Peak_Breach_cfs": "1234.0", "Message": ""})
        row = dict.fromkeys(fields, "")
        row.update({"Dam": "A1", "Folder": "/parent/A1"})
        bw.fill_row(row, fields, (0, ""), p, "a.log")
        assert row["Status"] == "done" and row["Peak_Breach_cfs"] == "1234.0"
        assert row["Folder"] == "/parent/A1"
        # a failed dam is the child's own row (the CLI child exits 3 for it)
        row2 = dict(row, Status="")
        bw.fill_row(row2, fields, (3, "ended with code 3"), p, "a.log")
        assert row2["Status"] == "done"
        # no row: failed, with the reason and the log
        row3 = dict.fromkeys(fields, "")
        row3["Dam"] = "A2"
        bw.fill_row(row3, fields, (1, "ended with code 1: Traceback | boom"),
                    os.path.join(d, "none.csv"), "/w/0002_A2.log")
        assert row3["Status"] == "failed" and "boom" in row3["Message"]
        assert "/w/0002_A2.log" in row3["Message"]
        row4 = dict.fromkeys(fields, "")
        row4["Dam"] = "A1"                                   # a time limit beats a stale row
        bw.fill_row(row4, fields, (bw.TIMED_OUT, "stopped after 5 min"), p, "a.log")
        assert row4["Status"] == "failed" and "5 min" in row4["Message"]
        row5 = dict.fromkeys(fields, "")
        bw.fill_row(row5, fields, (bw.CANCELLED, "cancelled"), os.path.join(d, "none.csv"), "l")
        assert row5["Status"] == "cancelled"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ----------------------------------------------------------------------- qgis_process
@test
def workers_find_qgis_process_and_share_the_profile():
    d = tempfile.mkdtemp()
    try:
        exe = os.path.join(d, "bin", "qgis_process.exe" if os.name == "nt" else "qgis_process")
        os.makedirs(os.path.dirname(exe))
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        assert bw.find_qgis_process([d], env={}) == (exe, "")
        assert bw.find_qgis_process([], env={bw.ENV_QGIS_PROCESS: exe}) == (exe, "")
        got, why = bw.find_qgis_process([os.path.join(d, "nowhere")],
                                        env={bw.ENV_QGIS_PROCESS: os.path.join(d, "no")})
        if got is None:                                    # (a qgis_process on PATH is fine)
            assert "not a program" in why and bw.ENV_QGIS_PROCESS in why
        # the session's profile is the default one: the children get its configuration folder
        root = os.path.join(d, "QGIS3")
        for name in ("default", "damsafety"):
            os.makedirs(os.path.join(root, "profiles", name))
        work = os.path.join(d, "work")
        os.makedirs(work)
        env, note = bw.profile_env({"X": "1"}, os.path.join(root, "profiles", "default") + os.sep,
                                   work)
        assert env == {"X": "1", "QGIS_CUSTOM_CONFIG_PATH": root} and note == ""
        # another profile: a configuration folder whose default profile links to it
        links = []
        env, note = bw.profile_env({}, os.path.join(root, "profiles", "damsafety"), work,
                                   link=lambda link, target: links.append((link, target)))
        cfg = os.path.join(work, "qgis_config")
        assert env["QGIS_CUSTOM_CONFIG_PATH"] == cfg and "damsafety" in note
        assert links == [(os.path.join(cfg, "profiles", "default"),
                          os.path.join(root, "profiles", "damsafety"))]
        # qgis_process 3.34 opens 'default' whatever profiles.ini says, so a profile that
        # profiles.ini names as the default is linked all the same, and 'default' itself is
        # linked too when profiles.ini names another one (a later QGIS might follow it)
        with open(os.path.join(root, "profiles", "profiles.ini"), "w") as f:
            f.write("[core]\ndefaultProfile=damsafety\n")
        for name in ("damsafety", "default"):
            shutil.rmtree(cfg, ignore_errors=True)
            env, note = bw.profile_env({}, os.path.join(root, "profiles", name), work,
                                       link=lambda link, target: None)
            assert env["QGIS_CUSTOM_CONFIG_PATH"] == cfg, name
        # a link that cannot be made: no workers, with the reason
        os.remove(os.path.join(root, "profiles", "profiles.ini"))

        def no_link(link, target):
            raise OSError("not permitted")
        shutil.rmtree(cfg, ignore_errors=True)
        try:
            bw.profile_env({}, os.path.join(root, "profiles", "damsafety"), work, link=no_link)
            raise AssertionError("expected WorkersUnavailable")
        except bw.WorkersUnavailable as e:
            assert "damsafety" in str(e) and "not permitted" in str(e)
        # not a profile folder (a script, a test): the environment is inherited as it is
        assert bw.profile_env({"X": "1"}, "", work) == ({"X": "1"}, "")
        # the probe
        class R:
            returncode = 1
        try:
            bw.probe(exe, "damit_run:batch", {}, run=lambda *a, **k: R())
            raise AssertionError("expected WorkersUnavailable")
        except bw.WorkersUnavailable as e:
            assert "damit_run:batch" in str(e) and "plugins" in str(e)
        R.returncode = 0
        bw.probe(exe, "damit_run:batch", {}, run=lambda *a, **k: R())
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Ported(unittest.TestCase):
    """The DamSafety tests of this module, each as one unittest case."""


for _fn in TESTS:
    setattr(Ported, "test_" + _fn.__name__, (lambda fn: lambda self: fn())(_fn))


if __name__ == "__main__":
    unittest.main()
