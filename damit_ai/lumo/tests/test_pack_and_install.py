"""The knowledge pack, the generated ALGORITHM-HELP-DAMIT.md, the installers and the acceptance replay.

Pure Python. The QGIS test (the dump must match the plugin code) runs only where the QGIS bindings are importable
(the CI qgis job); the DWR-2658 replay runs only when DAMIT_REPLAY_2658 points at that run folder (a local check;
no DWR data is committed)."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUMO = os.path.abspath(os.path.join(HERE, ".."))
AI = os.path.abspath(os.path.join(LUMO, ".."))
REPO = os.path.abspath(os.path.join(AI, ".."))
sys.path.insert(0, os.path.join(LUMO, "tools"))
sys.path.insert(0, HERE)
import fixture_run as FX  # noqa: E402
import run_digest as RD  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    import qgis.core  # noqa: F401
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


class TestKnowledgePack(unittest.TestCase):
    def test_every_flag_id_is_documented(self):
        doc = read(LUMO, "knowledge", "WATCHER-DIGEST.md")
        for fid in RD.KNOWN_FLAG_IDS:
            self.assertIn("`%s`" % fid, doc, fid)

    def test_documented_thresholds_match_the_code(self):
        doc = read(LUMO, "knowledge", "WATCHER-DIGEST.md")
        th = RD.THRESHOLDS
        self.assertIn("over 0.5 %", doc)
        self.assertEqual(th["mass_error_watch_pct"], 0.5)
        self.assertEqual(th["mass_error_problem_pct"], 1.0)
        self.assertIn("1.10x", doc)
        self.assertEqual(th["domain_volume_ratio_problem"], 1.10)
        self.assertIn("900 s", doc)
        self.assertEqual(th["stall_s"], 900.0)

    def test_pinned_rules_are_in_known_behaviours(self):
        kb = read(LUMO, "knowledge", "KNOWN-BEHAVIOURS.md")
        for needle in ("Run-watcher rules", "top of dam,\n  which is the DWR max pool", "NAVD88 only", "0-300 ft",
                       "H x (downstream slope + 1)", "3:1", "150 m", "BNSF KO subdivision = 15 trains per day",
                       "Judgment zone = Medium", "maxima over wet cells", "damit_run:rundam", "--GRID_REFINE=0"):
            self.assertIn(needle, kb, needle)

    def test_the_sunny_day_rule_is_never_stated_backwards(self):
        for name in ("KNOWN-BEHAVIOURS.md", "WATCHER-DIGEST.md"):
            t = read(LUMO, "knowledge", name)
            self.assertNotRegex(t, r"(?i)sunny[^.\n]{0,60}(inflow equal|outlets? (are )?operational)")

    def test_eval_questions_cover_the_watcher_rules(self):
        q = json.loads(read(LUMO, "eval", "questions.json"))["questions"]
        ids = {x["id"] for x in q}
        self.assertTrue({"sunny-day-rule", "toe-rule", "real-tool-names", "watcher-verdict"} <= ids)
        for x in q:
            for f in x["facts"]:
                re.compile(f)


class TestAlgorithmHelp(unittest.TestCase):
    HELP = os.path.join(LUMO, "knowledge", "ALGORITHM-HELP-DAMIT.md")

    def test_the_real_ids_are_in_the_dump(self):
        t = read(self.HELP)
        for tid in ("damit_screen:handoff", "damit_run:rundam", "damit:classify", "damit_lite:classify",
                    "damit_run:checkhandoff", "damit_screen:engine2d"):
            self.assertIn("### `%s`" % tid, t)

    def test_the_real_parameters_are_in_the_dump(self):
        t = read(self.HELP)
        for prm in ("CELL", "MAX_RUNS", "DURATION_HR", "DURATION_MAX_HR", "GRID_REFINE", "TIER", "METHOD", "DS_SLOPE",
                    "TOP_FT", "BOTTOM_FT", "LISFLOOD_EXE", "FORCE_ANUGA", "RAIL_TRAINS_LOOKUP", "HANDOFF"):
            self.assertIn("| `%s` |" % prm, t, prm)
        self.assertRegex(t, r"\| `GRID_REFINE` \|[^\n]*\| True \|")           # on by default
        self.assertRegex(t, r"\| `MAX_RUNS` \|[^\n]*\| 6 \|")
        self.assertRegex(t, r"\| `DURATION_MAX_HR` \|[^\n]*\| 96 \|")

    def test_the_dump_warns_that_invented_names_do_not_exist(self):
        t = read(self.HELP)
        self.assertIn("(`damit_runner`, `--no-refine` and `damit_screener_handoff` do not exist)", t)
        self.assertEqual(t.count("--no-refine"), 1)               # named ONLY in that warning
        self.assertEqual(t.count("damit_screener_handoff"), 1)

    def test_every_dumped_id_comes_from_a_provider_in_the_repo(self):
        t = read(self.HELP)
        provs = {"damit_screen": "damit_screener", "damit_run": "damit_runner", "damit": "damit_hazard",
                 "damit_lite": "damit_hazardlite", "damit_data": "damit_data", "damit_pmp": "damit_pmp"}
        for m in re.finditer(r"^## Provider `([a-z_]+)`", t, re.M):
            self.assertIn(provs[m.group(1)], os.listdir(REPO))
            src = read(REPO, provs[m.group(1)], "provider.py")
            self.assertIn('"%s"' % m.group(1), src)

    def test_the_dump_tool_refuses_to_guess_without_qgis(self):
        if HAVE_QGIS:
            self.skipTest("QGIS present")
        r = subprocess.run([sys.executable, os.path.join(LUMO, "tools", "dump_damit_algorithm_help.py"), "--stdout"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("QGIS Python bindings not found", r.stderr)

    @unittest.skipUnless(HAVE_QGIS, "QGIS Python bindings (the CI qgis job)")
    def test_the_dump_matches_the_plugin_code(self):
        """The committed file must equal what the offscreen QGIS reads from the plugins today."""
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([sys.executable, os.path.join(LUMO, "tools", "dump_damit_algorithm_help.py"), "--check",
                            "--out", self.HELP], capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stderr[-800:] + "\nrun: python3 damit_ai/lumo/tools/dump_damit_algorithm_help.py")


class TestInstallers(unittest.TestCase):
    def test_new_tools_exist_and_are_copied_by_every_installer(self):
        for tool in ("run_digest.py", "lumo_watch.py"):
            self.assertTrue(os.path.exists(os.path.join(LUMO, "tools", tool)))
        for inst in ("install-local-ai-linux.sh", "install-local-ai-windows.ps1"):
            t = read(AI, inst)
            self.assertIn("run_digest.py", t)
            self.assertIn("lumo_watch.py", t)
            self.assertIn("qwen3:4b", t)
            self.assertIn("phi4-mini", t)
        mac = read(LUMO, "setup-local-lumo.sh")
        for needle in ("run_digest", "lumo_watch", "qwen3:4b", "--watch-model", "--no-watch-model", "v3.7"):
            self.assertIn(needle, mac)

    def test_every_tool_the_linux_installer_copies_exists(self):
        t = read(AI, "install-local-ai-linux.sh")
        names = re.search(r"for t in ([a-z_. ]+); do", t).group(1).split()
        for n in names:
            self.assertTrue(os.path.exists(os.path.join(LUMO, "tools", n)), n)

    def test_linux_installer_syntax(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        r = subprocess.run(["bash", "-n", os.path.join(AI, "install-local-ai-linux.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_big_model_stays_for_chat(self):
        t = read(AI, "install-local-ai-linux.sh")
        self.assertIn('CHAT_MODEL="qwen3:30b-a3b"', t)
        self.assertIn("keeps the big model", t)

    def test_the_gpu_note_is_documented(self):
        for f in (os.path.join(AI, "README.md"), os.path.join(LUMO, "knowledge", "WATCHER-DIGEST.md")):
            t = read(f)
            self.assertIn("NVIDIA, Apple or AMD ROCm", t)
            self.assertIn("Intel Arc", t)


class TestAcceptance(unittest.TestCase):
    """The review of the DWR-2658 run found three things the model missed. The synthetic fixture reproduces each
    shape; the optional replay checks the real run folder."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lumo_accept_")
        self.addCleanup(shutil.rmtree, self.root, True)

    @unittest.skipUnless(HAVE_NUMPY, "numpy")
    def test_synthetic_fixture_flags_all_three(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        by = {f["id"]: f for f in d["flags"]}
        self.assertEqual((by["HEIGHT_MISMATCH"]["data"]["crest_minus_bed_ft"], by["HEIGHT_MISMATCH"]["data"]["inventory_height_ft"]),
                         (39.0, 37.0))
        self.assertEqual(by["EDGE_OUTFLOW_EARLY"]["data"]["edges"], ["N", "W"])
        self.assertEqual(by["RECEPTOR_NODATA"]["data"]["ids"], ["900000001"])
        self.assertEqual(d["verdict"], "WATCH")

    @unittest.skipUnless(os.environ.get("DAMIT_REPLAY_2658") and HAVE_NUMPY, "set DAMIT_REPLAY_2658 to the run folder")
    def test_replay_dwr_2658(self):
        run = os.environ["DAMIT_REPLAY_2658"]
        dam = os.environ.get("DAMIT_REPLAY_2658_DAM")
        os.environ.setdefault("GDAL_PAM_ENABLED", "NO")
        before = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(run) for f in fs)
        d = RD.build_digest(run, dam_folder=dam)
        after = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(run) for f in fs)
        self.assertEqual(before, after, "the replay must not write into the run folder")
        by = {}
        for f in d["flags"]:
            by.setdefault(f["id"], []).append(f)
        h = by["HEIGHT_MISMATCH"][0]["data"]
        self.assertEqual((h["crest_minus_bed_ft"], h["inventory_height_ft"]), (39.0, 37.0))
        self.assertTrue(by["EDGE_OUTFLOW_EARLY"])
        self.assertIn("104270538", by["RECEPTOR_NODATA"][0]["data"]["ids"])
        self.assertEqual(d["verdict"], "WATCH")


if __name__ == "__main__":
    unittest.main()
