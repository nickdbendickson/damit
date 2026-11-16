"""dam_chain `run --set nd` must exit non-zero when a dam's chain failed, and the installer's
embedded copy of every tool must match the file in tools/.

Why: run_nd returned None whatever happened, so `dam_chain.py run --set nd` exited 0 on a chain
that failed every dam. run_lisflood_44.py and run_county.py both reported "ok" for failed dams
because of it, and now read <dam>/_chain_nd/state.json to work around it. run_dwr has always
exited 1 on failure.

No QGIS and no conda: QP is replaced with a stub whose run() returns whatever the test asks for.
"""
import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.abspath(os.path.join(HERE, ".."))
TOOLS = os.path.join(HEIM, "tools")
sys.path.insert(0, TOOLS)
import dam_chain as DC  # noqa: E402


class FakeQP(object):
    """Stands in for qgis_process. `results` is read in order; the last entry repeats."""

    anuga_py = ""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, args, set_name):      # QP(args, "nd")
        return self

    def run(self, alg, params, log_path, timeout=None, label=""):
        self.calls.append(alg)
        r = self.results[0] if len(self.results) == 1 else self.results.pop(0)
        return r


class Args(object):
    def __init__(self, dams_folder, **kw):
        self.dams_folder = dams_folder
        self.ids = ""
        self.ids_csv = ""
        self.no_screen = self.no_breach = self.no_classify = False
        self.no_getdata = False
        self.screen_param = self.breach_param = self.classify_param = None
        self.getdata_param = None
        self.param = None
        self.data_folder = ""
        self.hi_res = False
        self.triage = False
        self.redo = True
        self.dry_run = False
        self.timeout_min = 1
        self.stop_on_error = False
        self.__dict__.update(kw)


class DamChainExitTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dam-chain-exit-")
        self._qp = DC.QP

    def tearDown(self):
        DC.QP = self._qp

    def dams(self, *ids):
        for did in ids:
            folder = os.path.join(self.tmp, did)
            os.makedirs(folder, exist_ok=True)
            with io.open(os.path.join(folder, "dam.json"), "w", encoding="utf-8") as fh:
                fh.write('{"id": "%s"}\n' % did)
        return self.tmp

    def run_nd(self, results, **kw):
        """(exit code, stdout) for one run_nd call."""
        DC.QP = FakeQP(results)
        out, keep = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            DC.run_nd(Args(self.tmp, **kw))
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        finally:
            sys.stdout = keep
        return code, out.getvalue()

    OK = (True, {"ND_CLASS": "high"}, "")
    BAD = (False, {}, "qgis_process returned 1")

    def test_every_dam_succeeds_exits_zero(self):
        self.dams("DWR-2801", "DWR-4031")
        code, out = self.run_nd([self.OK])
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAILED", out)

    def test_a_failed_chain_exits_one(self):
        self.dams("DWR-2801")
        code, out = self.run_nd([self.OK, self.BAD])          # get data ok, chain fails
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED 1 of 1", out)
        self.assertIn("DWR-2801", out)

    def test_a_failed_get_data_exits_one(self):
        self.dams("DWR-2801")
        code, out = self.run_nd([self.BAD])
        self.assertEqual(code, 1, out)
        self.assertIn("failed: get data", out)

    def test_one_failure_among_several_still_exits_one(self):
        self.dams("A", "B")
        # A: get data ok, chain ok.  B: get data ok, chain fails.
        code, out = self.run_nd([self.OK, self.OK, self.OK, self.BAD])
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED 1 of 2", out)

    def test_a_dam_with_no_dam_json_is_a_failure(self):
        self.dams("DWR-2801")
        code, out = self.run_nd([self.OK], ids="DWR-2801,DWR-9999")
        self.assertEqual(code, 1, out)
        self.assertIn("no dam.json", out)

    def test_stop_on_error_says_what_was_not_attempted(self):
        self.dams("A", "B", "C")
        code, out = self.run_nd([self.BAD], stop_on_error=True)
        self.assertEqual(code, 1, out)
        self.assertIn("were not attempted", out)

    def test_a_dam_done_in_an_earlier_run_is_not_a_failure(self):
        self.dams("DWR-2801")
        state = os.path.join(self.tmp, "DWR-2801", "_chain_nd", "state.json")
        os.makedirs(os.path.dirname(state), exist_ok=True)
        with io.open(state, "w", encoding="utf-8") as fh:
            fh.write('{"status": "done", "nd_class": "high"}')
        code, out = self.run_nd([self.BAD], redo=False)       # would fail if it ran
        self.assertEqual(code, 0, out)
        self.assertIn("done earlier", out)

    def test_dry_run_does_not_exit_non_zero(self):
        self.dams("DWR-2801")
        DC.QP = FakeQP([self.BAD])
        out, keep = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            DC.run_nd(Args(self.tmp, dry_run=True))
        finally:
            sys.stdout = keep


class RunDwrCountsTest(unittest.TestCase):
    """2026-11-16: run_dwr took "preflight: 0 error(s)" for a failure (it looked for the word
    "error"), so `--check-only` always said FAILED and exited 1 on a clean preflight."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dam-chain-dwr-")
        self._qp = DC.QP

    def tearDown(self):
        DC.QP = self._qp

    def run_dwr(self, counts):
        DC.QP = FakeQP([(True, {"COUNTS": counts}, "")])
        args = Args("", set="dwr", dams=os.path.join(self.tmp, "dams.gpkg"), out=self.tmp,
                    hec="skip", stop_after="end", anuga=False, check_only=True, id_field="dam_id",
                    ids="DWR-3034", dem="", screen_work="", settings_file="", overrides_csv="",
                    runner_param=None, dem_units="")
        out, keep = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            DC.run_dwr(args)
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        finally:
            sys.stdout = keep
        return code, out.getvalue()

    def test_a_clean_preflight_is_ok(self):
        code, out = self.run_dwr("preflight: 0 error(s)")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("OK"), out)

    def test_preflight_errors_and_failed_dams_still_fail(self):
        for counts in ("preflight: 1 error(s)", "2 done, 1 failed", "error: no dams layer"):
            with self.subTest(counts=counts):
                code, out = self.run_dwr(counts)
                self.assertEqual(code, 1, out)
        self.assertEqual(self.run_dwr("2 done, 0 failed")[0], 0)


class DefaultLisfloodTest(unittest.TestCase):
    """install-all puts LISFLOOD-FP in ~/dam-suite/bin; an older Mac install left one in
    ~/nd-dam-suite/bin, which dam_chain used to pick by default (as NDBREACH_LISFLOOD)."""

    def test_the_new_install_first(self):
        home = tempfile.mkdtemp(prefix="dam-chain-home-")
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            self.assertEqual(DC.default_lisflood(), "~/dam-suite/bin/lisflood")
            for d in ("nd-dam-suite", "dam-suite"):
                os.makedirs(os.path.join(home, d, "bin"))
                open(os.path.join(home, d, "bin", "lisflood"), "w").close()
                if d == "nd-dam-suite":
                    self.assertEqual(DC.default_lisflood(), "~/nd-dam-suite/bin/lisflood")
            self.assertEqual(DC.default_lisflood(), "~/dam-suite/bin/lisflood")
        finally:
            os.environ["HOME"] = old_home


class EmbeddedToolsMatchTest(unittest.TestCase):
    """setup-local-heim.sh ships each tool as a heredoc. A fix applied to tools/ only would
    leave every installed copy unfixed, with nothing to notice it."""

    def test_each_embedded_tool_matches_tools(self):
        sh = os.path.join(HEIM, "setup-local-heim.sh")
        with io.open(sh, encoding="utf-8") as fh:
            lines = fh.read().splitlines(True)
        blocks, name, tag, start = {}, None, None, None
        for i, line in enumerate(lines):
            m = re.match(r"\s*cat > \"\$LOCAL_AI/([^\"]+)\" << '(SCRIPT_EOF_[A-Z_]+)'\s*$", line)
            if m:
                name, tag, start = m.group(1), m.group(2), i + 1
                continue
            if tag and line.rstrip("\n") == tag:
                blocks[name] = "".join(lines[start:i])
                tag = None
        self.assertTrue(blocks, "no embedded tool blocks found in setup-local-heim.sh")
        for name, body in sorted(blocks.items()):
            path = os.path.join(TOOLS, name)
            with self.subTest(tool=name):
                self.assertTrue(os.path.isfile(path), "%s is embedded but not in tools/" % name)
                with io.open(path, encoding="utf-8") as fh:
                    on_disk = fh.read()
                self.assertEqual(on_disk, body,
                                 "%s differs between tools/ and setup-local-heim.sh -- "
                                 "re-copy the file into its heredoc" % name)


if __name__ == "__main__":
    unittest.main()
