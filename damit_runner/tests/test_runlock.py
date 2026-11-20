"""audit 2026-11-20: one driver per dam folder, and temp files unique per writer.

core/runlock.py claims a folder with an O_EXCL lock file (pid, host, thread, start time). The Runner's
workflow.run_dam and rundam.run_model, the Screener's chain (damit_screener/core/workflow.run_dam) and
the ANUGA launch (anuga_detach.launch, which used to check for a running worker and start one in two
separate steps) claim before they write. The atomic writers that used a fixed "<file>.tmp" now use
"<file>.<pid>.<thread>.tmp", fsync, and remove it when the write fails.

stdlib + the runner's pure modules; the processes started here are a few-second `python -c sleep`, never a model."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_runner.core import runlock as RL  # noqa: E402
from damit_runner.core import anuga_detach as AD  # noqa: E402
from damit_runner.core import ckpt_sign as CS  # noqa: E402


def _in_thread(fn):
    out = {}

    def run():
        try:
            out["value"] = fn()
        except BaseException as e:                          # noqa: BLE001
            out["error"] = e
    t = threading.Thread(target=run)
    t.start()
    t.join(30)
    return out


def _sleeper(seconds=30, script="sleep_worker.py", folder=None):
    """A child Python that sleeps; with `folder`, a script of that name (so /proc shows it)."""
    if folder:
        path = os.path.join(folder, script)
        with open(path, "w") as fh:
            fh.write("import time\ntime.sleep({})\n".format(seconds))
        return subprocess.Popen([sys.executable, path])
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep({})".format(seconds)])


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class Claim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "dam A")

    def tearDown(self):
        self.tmp.cleanup()

    def _plant(self, **info):
        os.makedirs(self.dir, exist_ok=True)
        base = {"pid": 1, "host": socket.gethostname(), "thread": 1, "what": "planted",
                "started": "2026-11-20 00:00:00", "started_epoch": time.time(), "token": "x"}
        base.update(info)
        with open(RL.lock_path(self.dir), "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        return base

    def test_claim_records_the_holder_and_is_removed_after(self):
        with RL.claim(self.dir, "test run") as path:
            info = RL.read_claim(self.dir)
            self.assertEqual((info["pid"], info["host"], info["what"]), (os.getpid(), socket.gethostname(), "test run"))
            self.assertEqual(info["thread"], threading.get_ident())
            self.assertTrue(os.path.isfile(path))
        self.assertIsNone(RL.read_claim(self.dir))

    def test_same_thread_nests_another_thread_is_refused(self):
        with RL.claim(self.dir, "outer"):
            with RL.claim(self.dir, "inner"):
                self.assertEqual(RL.read_claim(self.dir)["what"], "outer")
            self.assertIsNotNone(RL.read_claim(self.dir))       # the outer still holds it
            out = _in_thread(lambda: RL.acquire(self.dir, "second"))
            self.assertIsInstance(out.get("error"), RL.RunClaimError)
            self.assertIn(str(os.getpid()), str(out["error"]))
        self.assertIsNone(RL.read_claim(self.dir))
        out = _in_thread(lambda: RL.release(RL.acquire(self.dir, "after")))
        self.assertNotIn("error", out)

    def test_another_live_process_is_refused_with_its_name(self):
        p = _sleeper()
        try:
            self._plant(pid=p.pid, what="QGIS session 2")
            with self.assertRaises(RL.RunClaimError) as cm:
                RL.acquire(self.dir, "me")
            msg = str(cm.exception)
            for part in (str(p.pid), socket.gethostname(), "QGIS session 2", RL.lock_path(self.dir)):
                self.assertIn(part, msg)
        finally:
            p.kill()
            p.wait()
        RL.release(RL.acquire(self.dir, "taken over once it died"))

    def test_stale_claims_are_taken_over(self):
        self._plant(pid=_dead_pid())                               # this host, dead pid
        RL.release(RL.acquire(self.dir, "a"))
        self._plant(pid=os.getpid(), host="another-computer", started_epoch=time.time() - RL.STALE_S - 60)
        RL.release(RL.acquire(self.dir, "b"))
        self._plant(pid=os.getpid(), host="another-computer")     # fresh, elsewhere: cannot tell, refused
        with self.assertRaises(RL.RunClaimError):
            RL.acquire(self.dir, "c")

    def test_empty_claim_file_is_young_then_stale(self):
        os.makedirs(self.dir)
        open(RL.lock_path(self.dir), "w").close()
        with self.assertRaises(RL.RunClaimError):
            RL.acquire(self.dir, "x")                              # being written right now
        old = time.time() - RL.EMPTY_GRACE_S - 5
        os.utime(RL.lock_path(self.dir), (old, old))
        RL.release(RL.acquire(self.dir, "y"))

    def test_release_never_removes_someone_elses_claim(self):
        path = RL.acquire(self.dir, "mine")
        self._plant(pid=os.getpid() + 1, token="theirs")           # e.g. a wrongful takeover
        RL.release(path)
        self.assertEqual((RL.read_claim(self.dir) or {}).get("token"), "theirs")

    def test_screener_and_runner_copies_share_the_claim(self):
        from damit_screener.core import runlock as SRL
        with open(RL.__file__, "rb") as a, open(SRL.__file__, "rb") as b:
            self.assertEqual(a.read(), b.read(), "damit_screener/core/runlock.py must be a copy of the runner's")
        with SRL.claim(self.dir, "Screener chain"):
            with RL.claim(self.dir, "Runner run_dam"):              # same thread, the other copy: nested
                pass
            self.assertEqual(RL.read_claim(self.dir)["what"], "Screener chain")
            out = _in_thread(lambda: RL.acquire(self.dir, "other thread"))
            self.assertIsInstance(out.get("error"), RL.RunClaimError)
        self.assertIsNone(RL.read_claim(self.dir))

    def test_two_threads_race_one_wins(self):
        barrier = threading.Barrier(8)
        wins, errors = [], []

        def go():
            barrier.wait()
            try:
                RL.acquire(self.dir, "racer")
                wins.append(threading.get_ident())
                time.sleep(0.2)
            except RL.RunClaimError as e:
                errors.append(e)
        ts = [threading.Thread(target=go) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual((len(wins), len(errors)), (1, 7))
        RL._held.clear()


class Drivers(unittest.TestCase):
    """The drivers claim before they write anything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _held_by_child(self, folder):
        p = _sleeper()
        os.makedirs(folder, exist_ok=True)
        with open(RL.lock_path(folder), "w", encoding="utf-8") as fh:
            json.dump({"pid": p.pid, "host": socket.gethostname(), "thread": 1, "what": "the other driver",
                       "started": "now", "started_epoch": time.time(), "token": "t"}, fh)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_runner_run_dam_claims_first(self):
        try:
            from damit_runner.core import workflow as WF
        except ImportError as e:                                   # pragma: no cover - numpy missing
            self.skipTest(str(e))
        folder = os.path.join(self.tmp.name, "dam")
        self._held_by_child(folder)
        with mock.patch.object(WF, "_run_dam_claimed", side_effect=AssertionError("ran without a claim")):
            with self.assertRaises(RL.RunClaimError) as cm:
                WF.run_dam(None, (0, 0), None, None, None, folder)
        self.assertIn("the other driver", str(cm.exception))
        with mock.patch.object(WF, "_run_dam_claimed", return_value="ok") as inner:
            os.remove(RL.lock_path(folder))
            self.assertEqual(WF.run_dam("dam", (0, 0), "st", "src", "w", folder), "ok")
            inner.assert_called_once()
        self.assertIsNone(RL.read_claim(folder))

    def test_rundam_run_model_claims_the_dam_folder(self):
        try:
            from damit_runner.core import rundam as RD
        except ImportError as e:                                   # pragma: no cover
            self.skipTest(str(e))
        dams = os.path.join(self.tmp.name, "dams")
        with mock.patch.object(RD.CB, "modules", return_value=(None, None, mock.Mock(safe_name=lambda s: s))):
            self._held_by_child(os.path.join(dams, "ND00001"))
            with mock.patch.object(RD, "_run_model_claimed", side_effect=AssertionError("ran without a claim")):
                with self.assertRaises(RL.RunClaimError):
                    RD.run_model({"dam": {"dam_id": "ND00001"}}, self.tmp.name, {}, dams_folder=dams)

    def test_screener_chain_claims_the_dam_folder(self):
        from damit_screener.core import workflow as SW
        work = self.tmp.name
        with mock.patch.object(SW.CB, "modules", return_value=(None, None, mock.Mock(safe_name=lambda s: s))):
            self._held_by_child(SW.dam_folder(work, "ND00002"))
            with mock.patch.object(SW, "_run_dam_claimed", side_effect=AssertionError("ran without a claim")):
                with self.assertRaises(RuntimeError) as cm:
                    SW.run_dam(None, None, {"dam_id": "ND00002"}, {}, work)
        self.assertIn("the other driver", str(cm.exception))


class AnugaLaunch(unittest.TestCase):
    """anuga_detach.launch claims the workdir and looks for a live worker before it deletes the status."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = self.tmp.name
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self.tmp.cleanup()

    def _launch(self, seconds=30):
        script = os.path.join(self.work, "fake_anuga_worker.py")
        with open(script, "w") as fh:
            fh.write("import sys, time\ntime.sleep({})\n".format(seconds))
        proc, log, spath = AD.launch([sys.executable, "-u", script, "job.json", "result.npz"], self.work,
                                     dict(os.environ), script=script)
        self.procs.append(proc)
        return proc, spath

    def test_second_launch_while_the_first_runs_is_refused(self):
        proc, spath = self._launch()
        self.assertEqual(AD.read_status(spath)["pid"], proc.pid)
        self.assertFalse(os.path.exists(os.path.join(self.work, AD.LAUNCH_CLAIM)))   # let go after the launch
        with self.assertRaises(RL.RunClaimError) as cm:
            self._launch()
        self.assertIn(str(proc.pid), str(cm.exception))
        self.assertEqual(AD.read_status(spath)["pid"], proc.pid)                     # status not deleted
        self.assertEqual(len(self.procs), 1)

    def test_launch_waits_its_turn_behind_another_launcher(self):
        p = _sleeper()
        self.procs.append(p)
        with open(os.path.join(self.work, AD.LAUNCH_CLAIM), "w", encoding="utf-8") as fh:
            json.dump({"pid": p.pid, "host": socket.gethostname(), "thread": 1, "what": "ANUGA worker launch",
                       "started": "now", "started_epoch": time.time(), "token": "t"}, fh)
        with open(AD.status_path(self.work), "w") as fh:
            json.dump({"state": "finished", "pid": 1}, fh)
        with self.assertRaises(RL.RunClaimError):
            self._launch()
        self.assertTrue(os.path.isfile(AD.status_path(self.work)))                    # untouched

    def test_a_finished_worker_does_not_block_a_new_launch(self):
        proc, spath = self._launch(seconds=0)
        proc.wait()
        AD.finish_status(spath, proc.pid, proc.returncode)
        proc2, _ = self._launch(seconds=0)
        self.assertNotEqual(proc2.pid, proc.pid)


class UniqueTemps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _no_temps(self):
        return [f for f in os.listdir(self.d) if ".tmp" in f]

    def _check_writer(self, write, path, read=_load):
        """write(obj) replaces `path`; a failure mid-write keeps the old file and leaves no temp."""
        seen = []
        real_open = open

        def spy(p, *a, **k):
            if str(p).endswith(".tmp"):
                seen.append(os.path.basename(str(p)))
            return real_open(p, *a, **k)
        with mock.patch("builtins.open", spy):
            write({"n": 1})
        self.assertEqual(read(path), {"n": 1})
        self.assertTrue(seen and all(".{}.{}.tmp".format(os.getpid(), threading.get_ident()) in s for s in seen), seen)
        with self.assertRaises(TypeError):
            write({"bad": object()})                       # json cannot write it (default=str writers excepted)
        self.assertEqual(read(path), {"n": 1})
        self.assertEqual(self._no_temps(), [])

    def test_runner_workflow_writers(self):
        try:
            from damit_runner.core import workflow as WF
        except ImportError as e:                           # pragma: no cover
            self.skipTest(str(e))
        p = os.path.join(self.d, "run_report.json")
        with mock.patch.object(WF, "_json_default", side_effect=TypeError("no")):
            self._check_writer(lambda o: WF._write_json(p, o), p)
        t = os.path.join(self.d, "README.md")
        WF._write_text(t, "hello")
        self.assertEqual(_text(t), "hello")
        self.assertEqual(self._no_temps(), [])

    def test_anuga_worker_writers(self):
        try:
            from damit_runner.core import anuga_worker as AW
        except ImportError as e:                           # pragma: no cover - numpy missing
            self.skipTest(str(e))
        p = os.path.join(self.d, "anuga_status.json")
        self._check_writer(lambda o: AW.write_json_atomic(p, o), p)
        self.assertTrue(AW._tmp_name(p).startswith(p + ".{}.".format(os.getpid())))

    def test_default_str_writers_use_unique_temps(self):
        from damit_runner.core import rundam as RD
        from damit_screener.core import workflow as SW
        from damit_catalog import handoff as HO
        for name, write, path in (
                ("rundam._save", lambda o: RD._save(self.d, o), os.path.join(self.d, RD.RUN_SETUP)),
                ("screener._write_json", lambda o: SW._write_json(os.path.join(self.d, "s.json"), o),
                 os.path.join(self.d, "s.json")),
                ("handoff.write", lambda o: HO.write(o, self.d), os.path.join(self.d, HO.FILENAME))):
            with self.subTest(name):
                with mock.patch("os.replace", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        write({"n": 0})
                self.assertEqual(self._no_temps(), [], name)
                write({"n": 2})
                self.assertEqual(_load(path), {"n": 2})
                self.assertEqual(self._no_temps(), [], name)

    def test_ckpt_sign_unique_temp_and_cleanup(self):
        key = os.path.join(self.d, "key")
        env = dict(os.environ, NDBREACH_CKPT_KEY_FILE=key)
        ck = os.path.join(self.d, "domain_1.0.pickle")
        with open(ck, "wb") as fh:
            fh.write(b"x" * 10)
        with mock.patch.dict(os.environ, env):
            self.assertEqual(CS.sign(ck), "")
            self.assertTrue(os.path.isfile(CS.sig_path(ck)))
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                self.assertIn("disk full", CS.sign(ck))
        self.assertEqual(self._no_temps(), [])


if __name__ == "__main__":
    unittest.main()
