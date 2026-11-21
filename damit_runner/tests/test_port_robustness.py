"""Ported from DamSafety Runner (DWR_Plugins) with no number changes (DamIT Runner 0.7.x port, group A):

* #394 (8a153696) anuga_detach.signalable / Attached._signal: a cancel never signals a pid from another host,
  a dead pid, or (where /proc can tell) a recycled pid that no longer runs the worker script;
* #379 (8d43bf62) anuga_model.omp_duplicate_hint: the "OMP: Error #15" (two OpenMP runtimes) message;
* #412 (e2725333) chain.raise_open_files / open_files_note: batch runs lift the open-file limit.

Same checks as DamSafety's tests/test_anuga_detach.py and tests/test_chain_batch.py, as unittest. No QGIS, no
model run.
"""
import os
import signal
import socket
import tempfile
import unittest

from damit_runner.core import anuga_detach as D
from damit_runner.core import anuga_model as AM
from damit_runner.core import chain as CH


def _script_token_in_our_cmdline():
    """A basename that really appears in this process's /proc cmdline, or None without /proc."""
    cmd = D._cmdline(os.getpid())
    if not cmd:
        return None
    for part in cmd.replace("\x00", " ").split():
        base = os.path.basename(part)
        if base and base in cmd:
            return base
    return None


class Signalable(unittest.TestCase):
    def test_cross_host_dead_and_recycled_pids_are_never_signalable(self):
        self.assertIs(D.signalable(None), False)
        self.assertIs(D.signalable({"pid": 2 ** 31 - 1}), False)
        self.assertIs(D.signalable({"pid": os.getpid(), "host": "some-other-host"}), False)
        self.assertIs(D.signalable({"pid": os.getpid(), "host": socket.gethostname()}), True)
        if D._cmdline(os.getpid()) is not None:
            self.assertIs(D.signalable({"pid": os.getpid(), "host": socket.gethostname(),
                                        "script": "no_such_worker_xyz.py"}), False)
            here = _script_token_in_our_cmdline()
            if here:
                self.assertIs(D.signalable({"pid": os.getpid(), "host": socket.gethostname(),
                                            "script": here}), True)

    def test_attached_signal_refuses_a_pid_it_cannot_confirm(self):
        signals = []
        real_kill = os.kill

        def fake_kill(pid, sig):
            if sig == 0:
                return real_kill(pid, sig)
            signals.append((pid, sig))

        os.kill = fake_kill
        try:
            no_status = os.path.join(tempfile.gettempdir(), "damit_anudet_no_such_status.json")
            D.Attached({"pid": os.getpid(), "host": "some-other-host", "state": D.RUNNING}, no_status).terminate()
            self.assertEqual(signals, [])
            here = _script_token_in_our_cmdline()
            if here:
                D.Attached({"pid": os.getpid(), "host": socket.gethostname(), "script": here,
                            "state": D.RUNNING}, no_status).terminate()
                self.assertEqual(signals, [(os.getpid(), signal.SIGTERM)])
        finally:
            os.kill = real_kill


class OmpHint(unittest.TestCase):
    def test_hint_only_for_omp_error_15(self):
        self.assertEqual(AM.omp_duplicate_hint("Traceback ...\nValueError: x"), "")
        self.assertEqual(AM.omp_duplicate_hint(None), "")
        h = AM.omp_duplicate_hint("OMP: Error #15: Initializing libomp.dylib, but found libiomp5.dylib",
                                  "/opt/envs/anuga/bin/python")
        self.assertIn("two copies of the OpenMP runtime", h)
        self.assertIn("(/opt/envs/anuga/bin/python)", h)
        self.assertIn("KMP_DUPLICATE_LIB_OK is not a fix", h)


class _FakeRlimit(object):
    RLIMIT_NOFILE = 8
    RLIM_INFINITY = -1

    def __init__(self, soft, hard, refuse_above=None):
        self.lim, self.refuse_above, self.calls = (soft, hard), refuse_above, []

    def getrlimit(self, which):
        return self.lim

    def setrlimit(self, which, lim):
        self.calls.append(lim)
        if self.refuse_above is not None and lim[0] > self.refuse_above:
            raise ValueError("not allowed")
        self.lim = lim


class OpenFiles(unittest.TestCase):
    def test_raise_open_files(self):
        r = _FakeRlimit(256, -1)
        self.assertEqual(CH.raise_open_files(resource_mod=r), (256, 10240))
        self.assertEqual(r.lim, (10240, -1))
        self.assertIn("raised from 256 to 10240", CH.open_files_note((256, 10240)))
        self.assertEqual(CH.raise_open_files(resource_mod=_FakeRlimit(256, 2048)), (256, 2048))
        self.assertEqual(CH.raise_open_files(resource_mod=_FakeRlimit(256, -1, refuse_above=4096)), (256, 4096))
        r = _FakeRlimit(65536, -1)
        self.assertEqual(CH.raise_open_files(resource_mod=r), (65536, 65536))
        self.assertEqual(r.calls, [])
        self.assertEqual(CH.open_files_note((65536, 65536)), "")
        self.assertEqual(CH.raise_open_files(resource_mod=_FakeRlimit(256, 256)), (256, 256))
        self.assertIn("ulimit -n 10240", CH.open_files_note((256, 256)))
        self.assertEqual(CH.open_files_note(None), "")

    def test_batch_tool_lifts_the_limit_first(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "algorithms", "engine.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        batch = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BatchAlgorithm")
        proc = next(n for n in batch.body if isinstance(n, ast.FunctionDef) and n.name == "processAlgorithm")
        src = ast.unparse(proc.body[0]) + ast.unparse(proc.body[1])
        self.assertIn("from ..core import chain as _chain", src)
        self.assertIn("raise_open_files()", src)


if __name__ == "__main__":
    unittest.main()
