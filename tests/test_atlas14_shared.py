"""The shared Atlas 14 core guard (scripts/check_atlas14_shared.py). Pure Python.

The five modules are checked against a DWR_Plugins checkout in CI (.github/workflows/atlas14_shared.yml) and here
when DAMIT_DWR_CHECKOUT names one."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("check_atlas14_shared",
                                               os.path.join(ROOT, "scripts", "check_atlas14_shared.py"))
AS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AS)

FILES = {n: "# {}\nVALUE = {}\n".format(n, i) for i, n in enumerate(AS.NAMES)}


def _tree(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


def _git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false"] + list(args),
                          capture_output=True, text=True, check=True, env=env).stdout.strip()


def _has_git():
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _run(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = AS.main(argv, **kw)
        except SystemExit as e:          # argparse errors
            code = e.code
    return code, out.getvalue(), err.getvalue()


class _Fixture(unittest.TestCase):
    """Fake DamIT and DWR_Plugins checkouts in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_atlas14_shared_")
        self.me, self.dwr = os.path.join(self.tmp, "damit"), os.path.join(self.tmp, "dwr")
        _tree(self.me, {"damit_pmp/{}.py".format(n): t for n, t in FILES.items()})
        _tree(self.dwr, {"DamSafety_PMP/noaa14/{}.py".format(n): t for n, t in FILES.items()})
        self.record = os.path.join(self.me, "damit_pmp", "SHARED_ATLAS14.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *argv):
        return _run(list(argv), root=self.me, record=self.record)


class Checkouts(_Fixture):
    def test_identical_passes(self):
        problems, counts = AS.check(self.dwr, self.me)
        self.assertEqual(problems, [])
        self.assertEqual(counts, {"identical": 5, "differ": 0, "missing": 0})
        code, out, _ = self.main("--dwr", self.dwr)
        self.assertEqual(code, 0)
        self.assertIn("5 identical, 0 differ, 0 missing", out)

    def test_one_differing_file_fails_and_shows_the_diff(self):
        _tree(self.dwr, {"DamSafety_PMP/noaa14/storm.py": "# storm\nVALUE = 99\n"})
        code, out, _ = self.main("--dwr", self.dwr)
        self.assertEqual(code, 1)
        self.assertIn("DIFFERS damit_pmp/storm.py <-> DamSafety_PMP/noaa14/storm.py", out)
        self.assertIn("-VALUE = 2", out)
        self.assertIn("+VALUE = 99", out)
        self.assertIn("4 identical, 1 differ", out)

    def test_a_damit_edit_is_a_difference_too(self):
        _tree(self.me, {"damit_pmp/atlas14.py": FILES["atlas14"] + "EXTRA = 1\n"})
        problems, counts = AS.check(self.dwr, self.me)
        self.assertEqual(counts["differ"], 1)
        self.assertIn("damit_pmp/atlas14.py", problems[0])

    def test_line_endings_alone_are_a_difference(self):
        _tree(self.dwr, {"DamSafety_PMP/noaa14/gisgrid.py": FILES["gisgrid"].replace("\n", "\r\n")})
        problems, _ = AS.check(self.dwr, self.me)
        self.assertEqual(len(problems), 1)
        self.assertIn("line endings differ", problems[0])

    def test_a_long_diff_is_cut(self):
        _tree(self.dwr, {"DamSafety_PMP/noaa14/temporal.py": "".join("L{} = 1\n".format(i) for i in range(200))})
        problems, _ = AS.check(self.dwr, self.me)
        self.assertIn("more diff lines", problems[0])
        self.assertLess(problems[0].count("\n"), AS.DIFF_LINES + 5)

    def test_a_missing_file_fails(self):
        os.remove(os.path.join(self.dwr, "DamSafety_PMP", "noaa14", "gridstats.py"))
        code, out, _ = self.main("--dwr", self.dwr)
        self.assertEqual(code, 1)
        self.assertIn("MISSING DamSafety_PMP/noaa14/gridstats.py", out)
        os.remove(os.path.join(self.me, "damit_pmp", "temporal.py"))
        problems, counts = AS.check(self.dwr, self.me)
        self.assertEqual(counts["missing"], 2)
        self.assertTrue(any(p.startswith("MISSING damit_pmp/temporal.py") for p in problems))

    def test_a_path_without_noaa14_is_refused(self):
        other = os.path.join(self.tmp, "other")
        _tree(other, {"DamSafety_Runner/core/breach.py": "A = 1\n"})        # a DWR_Plugins main without noaa14
        for path in (other, os.path.join(self.tmp, "nowhere")):
            code, out, err = self.main("--dwr", path)
            self.assertEqual(code, 2)
            self.assertIn("not a DWR_Plugins checkout", err)
            self.assertIn("DamSafety_PMP/noaa14", err)
            self.assertEqual(out, "")

    def test_dwr_is_required_to_check(self):
        code, _, err = self.main()
        self.assertEqual(code, 2)
        self.assertIn("--dwr", err)

    def test_print_synced_to_without_a_record(self):
        code, _, err = self.main("--print-synced-to")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_update_refuses_a_difference(self):
        _tree(self.dwr, {"DamSafety_PMP/noaa14/storm.py": "# storm\nVALUE = 99\n"})
        code, _, err = self.main("--dwr", self.dwr, "--update")
        self.assertEqual(code, 1)
        self.assertIn("not written", err)
        self.assertFalse(os.path.exists(self.record))

    def test_update_needs_a_git_checkout(self):
        if _has_git() and AS._commit(self.dwr):
            self.skipTest("the temporary folder is inside a git checkout")
        code, _, err = self.main("--dwr", self.dwr, "--update")
        self.assertEqual(code, 2)
        self.assertIn("HEAD commit", err)
        self.assertFalse(os.path.exists(self.record))


@unittest.skipUnless(_has_git(), "git not installed")
class UpdateRoundTrip(_Fixture):
    def setUp(self):
        super().setUp()
        _git(self.dwr, "init", "-q")
        _git(self.dwr, "add", "-A")
        _git(self.dwr, "commit", "-q", "-m", "shared core")
        self.head = _git(self.dwr, "rev-parse", "HEAD")

    def test_update_then_print_synced_to(self):
        code, out, err = self.main("--dwr", self.dwr, "--update")
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertIn(self.head, out)
        rec = AS.load_record(self.record)
        self.assertEqual(rec["schema"], "damit.atlas14_shared")
        self.assertEqual(rec["synced_to"], self.head)
        self.assertEqual(sorted(rec["pairs"]), sorted("damit_pmp/{}.py".format(n) for n in AS.NAMES))
        for mine, p in rec["pairs"].items():
            self.assertEqual(p["dwr"], "DamSafety_PMP/noaa14/" + os.path.basename(mine))
            self.assertEqual(p["sha256"], AS.sha256(os.path.join(self.me, mine)))
        code, out, _ = self.main("--print-synced-to")
        self.assertEqual((code, out.strip()), (0, self.head))

    def test_a_new_dwr_commit_moves_the_pin(self):
        self.main("--dwr", self.dwr, "--update")
        for rel in ("damit_pmp/storm.py", "DamSafety_PMP/noaa14/storm.py"):        # the same edit on both sides
            _tree(self.me if rel.startswith("damit") else self.dwr, {rel: "# storm\nVALUE = 7\n"})
        _git(self.dwr, "commit", "-q", "-am", "storm fix")
        new = _git(self.dwr, "rev-parse", "HEAD")
        self.assertEqual(self.main("--dwr", self.dwr, "--update")[0], 0)
        rec = AS.load_record(self.record)
        self.assertEqual(rec["synced_to"], new)
        self.assertEqual(rec["pairs"]["damit_pmp/storm.py"]["sha256"],
                         AS.sha256(os.path.join(self.me, "damit_pmp", "storm.py")))

    def test_update_warns_about_files_not_committed_in_dwr(self):
        for rel in ("damit_pmp/storm.py", "DamSafety_PMP/noaa14/storm.py"):
            _tree(self.me if rel.startswith("damit") else self.dwr, {rel: "# storm\nVALUE = 7\n"})
        code, _, err = self.main("--dwr", self.dwr, "--update")
        self.assertEqual(code, 0)
        self.assertIn("not committed in DWR_Plugins: DamSafety_PMP/noaa14/storm.py", err)
        self.assertEqual(AS.load_record(self.record)["synced_to"], self.head)


class Record(unittest.TestCase):
    """The committed damit_pmp/SHARED_ATLAS14.json."""

    def setUp(self):
        self.rec = AS.load_record()

    def test_shape(self):
        self.assertEqual(self.rec["schema"], "damit.atlas14_shared")
        self.assertEqual(self.rec["source"], "nickdbendickson/DWR_Plugins")
        self.assertRegex(self.rec["synced_to"], r"^[0-9a-f]{40}$")
        self.assertEqual(sorted(self.rec["pairs"]), sorted(m for m, _ in AS.pairs()))
        for mine, theirs in AS.pairs():
            self.assertEqual(self.rec["pairs"][mine]["dwr"], theirs)

    def test_damit_files_match_the_record(self):
        # an edit to a shared module has to be copied to DWR_Plugins, committed there and re-recorded
        for mine, p in self.rec["pairs"].items():
            self.assertEqual(AS.sha256(os.path.join(ROOT, mine)), p["sha256"],
                             "{} changed since SHARED_ATLAS14.json was recorded: copy it to DWR_Plugins "
                             "DamSafety_PMP/noaa14/, commit there and run scripts/check_atlas14_shared.py "
                             "--dwr <DWR_Plugins> --update".format(mine))

    def test_against_a_real_checkout(self):
        dwr = os.environ.get("DAMIT_DWR_CHECKOUT")
        if not dwr or not AS.is_dwr(dwr):
            self.skipTest("DAMIT_DWR_CHECKOUT not set or has no DamSafety_PMP/noaa14")
        problems, _ = AS.check(dwr)
        self.assertEqual(problems, [])

    def test_json_is_stable(self):
        with open(AS.RECORD, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, json.dumps(self.rec, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
