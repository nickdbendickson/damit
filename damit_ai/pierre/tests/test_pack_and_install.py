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
PIERRE = os.path.abspath(os.path.join(HERE, ".."))
AI = os.path.abspath(os.path.join(PIERRE, ".."))
REPO = os.path.abspath(os.path.join(AI, ".."))
sys.path.insert(0, os.path.join(PIERRE, "tools"))
sys.path.insert(0, HERE)
import fixture_run as FX  # noqa: E402
from strict import StrictCase, jdump, jload, slurp, spit  # noqa: E402,F401
import run_digest as RD  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    from osgeo import gdal as _gdal  # noqa: F401
    HAVE_GDAL = True
except ImportError:
    HAVE_GDAL = False
try:
    import qgis.core  # noqa: F401
    HAVE_QGIS = True
except ImportError:
    HAVE_QGIS = False


def read(*p):
    return slurp(os.path.join(*p))


class TestKnowledgePack(StrictCase):
    def test_every_flag_id_is_documented(self):
        doc = read(PIERRE, "knowledge", "WATCHER-DIGEST.md")
        for fid in RD.KNOWN_FLAG_IDS:
            self.assertIn("`%s`" % fid, doc, fid)

    def test_documented_thresholds_match_the_code(self):
        doc = read(PIERRE, "knowledge", "WATCHER-DIGEST.md")
        th = RD.THRESHOLDS
        self.assertIn("over 0.5 %", doc)
        self.assertEqual(th["mass_error_watch_pct"], 0.5)
        self.assertEqual(th["mass_error_problem_pct"], 1.0)
        self.assertIn("1.10x", doc)
        self.assertEqual(th["domain_volume_ratio_problem"], 1.10)
        self.assertIn("900 s", doc)
        self.assertEqual(th["stall_s"], 900.0)

    def test_pinned_rules_are_in_known_behaviours(self):
        kb = read(PIERRE, "knowledge", "KNOWN-BEHAVIOURS.md")
        for needle in ("Run-watcher rules", "top of dam,\n  which is the DWR max pool", "NAVD88 only", "0-300 ft",
                       "H x (downstream slope + 1)", "3:1", "150 m", "BNSF KO subdivision = 15 trains per day",
                       "Judgment zone = Medium", "maxima over wet cells", "damit_run:rundam", "--GRID_REFINE=0"):
            self.assertIn(needle, kb, needle)

    def test_the_sunny_day_rule_is_never_stated_backwards(self):
        for name in ("KNOWN-BEHAVIOURS.md", "WATCHER-DIGEST.md"):
            t = read(PIERRE, "knowledge", name)
            self.assertNotRegex(t, r"(?i)sunny[^.\n]{0,60}(inflow equal|outlets? (are )?operational)")

    def test_eval_questions_cover_the_watcher_rules(self):
        q = json.loads(read(PIERRE, "eval", "questions.json"))["questions"]
        ids = {x["id"] for x in q}
        self.assertTrue({"sunny-day-rule", "toe-rule", "real-tool-names", "watcher-verdict"} <= ids)
        for x in q:
            for f in x["facts"]:
                re.compile(f)


class TestAlgorithmHelp(StrictCase):
    HELP = os.path.join(PIERRE, "knowledge", "ALGORITHM-HELP-DAMIT.md")

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
        r = subprocess.run([sys.executable, os.path.join(PIERRE, "tools", "dump_damit_algorithm_help.py"), "--stdout"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("QGIS Python bindings not found", r.stderr)

    @unittest.skipUnless(HAVE_QGIS, "QGIS Python bindings (the CI qgis job)")
    def test_the_dump_matches_the_plugin_code(self):
        """The committed file must equal what the offscreen QGIS reads from the plugins today."""
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([sys.executable, os.path.join(PIERRE, "tools", "dump_damit_algorithm_help.py"), "--check",
                            "--out", self.HELP], capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stderr[-800:] + "\nrun: python3 damit_ai/pierre/tools/dump_damit_algorithm_help.py")


class TestInstallers(StrictCase):
    def test_new_tools_exist_and_are_copied_by_every_installer(self):
        for tool in ("run_digest.py", "pierre_watch.py"):
            self.assertTrue(os.path.exists(os.path.join(PIERRE, "tools", tool)))
        for inst in ("install-local-ai-linux.sh", "install-local-ai-windows.ps1"):
            t = read(AI, inst)
            self.assertIn("run_digest.py", t)
            self.assertIn("pierre_watch.py", t)
            self.assertIn("qwen3:4b", t)
            self.assertIn("phi4-mini", t)
        mac = read(PIERRE, "setup-local-pierre.sh")
        for needle in ("run_digest", "pierre_watch", "qwen3:4b", "--watch-model", "--no-watch-model", "v3.8"):
            self.assertIn(needle, mac)

    def test_every_tool_the_linux_installer_copies_exists(self):
        t = read(AI, "install-local-ai-linux.sh")
        names = re.search(r"for t in ([a-z_. ]+); do", t).group(1).split()
        for n in names:
            self.assertTrue(os.path.exists(os.path.join(PIERRE, "tools", n)), n)

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
        for f in (os.path.join(AI, "README.md"), os.path.join(PIERRE, "knowledge", "WATCHER-DIGEST.md")):
            t = read(f)
            self.assertIn("NVIDIA, Apple or AMD ROCm", t)
            self.assertIn("Intel Arc", t)


BLOCK = re.compile(r"# >>> hf_gguf_fallback.*?# <<< hf_gguf_fallback\n", re.S)


def hf_block(path):
    m = BLOCK.search(read(path))
    assert m, path
    return m.group(0)


class TestHfGgufFallback(StrictCase):
    """`ollama pull` fails behind a proxy: the installers fall back to the Hugging Face GGUF + `ollama create`.
    The bash block is run for real against a local HTTP server and a fake `ollama`; no network, no model."""

    def setUp(self):
        super(TestHfGgufFallback, self).setUp()
        if not shutil.which("bash"):
            self.skipTest("no bash")
        if not shutil.which("curl"):
            self.skipTest("no curl (the installers need it for the GGUF download; CI installs it)")
        self.root = tempfile.mkdtemp(prefix="pierre_gguf_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.payload = b"GGUF" + os.urandom(2000)
        import hashlib
        self.sha = hashlib.sha256(self.payload).hexdigest()
        srv_dir = os.path.join(self.root, "srv", "acme", "tiny-GGUF", "resolve", "main")
        os.makedirs(srv_dir)
        with open(os.path.join(srv_dir, "tiny.gguf"), "wb") as f:
            f.write(self.payload)
        import http.server
        import threading
        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass
        self.srv = Quiet(("127.0.0.1", 0), type("H", (http.server.SimpleHTTPRequestHandler,), {
            "log_message": lambda *a, **k: None,
            "__init__": lambda h, *a, **k: http.server.SimpleHTTPRequestHandler.__init__(
                h, *a, directory=os.path.join(self.root, "srv"), **k)}))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.log = os.path.join(self.root, "ollama.log")
        self.fake = os.path.join(self.root, "ollama")
        spit(self.fake, "#!/usr/bin/env bash\n"
                        "echo \"$@\" >> '%s'\n"
                        "if [[ \"$1\" == pull ]]; then echo 'pull: manifest redirect failed' >&2; exit 1; fi\n"
                        "if [[ \"$1\" == create ]]; then cp \"$4\" '%s.modelfile'; fi\n" % (self.log, self.log))
        os.chmod(self.fake, 0o755)

    def run_block(self, script, spec=None, extra_env=None, path=None):
        src = hf_block(path or os.path.join(AI, "install-local-ai-linux.sh"))
        env = dict(os.environ, OLLAMA=self.fake, PIERRE_GGUF_DIR=os.path.join(self.root, "gg"),
                   HF_ENDPOINT="http://127.0.0.1:%d" % self.srv.server_address[1],
                   PIERRE_GGUF_SPEC=spec or "acme/tiny-GGUF tiny.gguf %s %d" % (self.sha, len(self.payload)))
        env.update(extra_env or {})
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            env.pop(k, None)
        env["no_proxy"] = "127.0.0.1"
        pre = 'ok(){ echo "OK: $*"; }; warn(){ echo "WARN: $*" >&2; }\n'
        return subprocess.run(["bash", "-c", pre + src + "\n" + script], capture_output=True, text=True, env=env, timeout=60)

    def test_pull_fails_then_the_gguf_is_downloaded_checked_and_created(self):
        r = self.run_block('"$OLLAMA" pull tiny:1 || hf_gguf_create tiny:1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = slurp(self.log).splitlines()
        self.assertEqual(calls[0], "pull tiny:1")
        self.assertRegex(calls[1], r"^create tiny:1 -f .*Modelfile\.\d+$")
        mf = slurp(self.log + ".modelfile")
        self.assertRegex(mf, r"^FROM .*tiny\.gguf\n")
        self.assertIn("PARAMETER num_ctx 4096", mf)
        self.assertEqual(os.listdir(os.path.join(self.root, "gg")), [])          # the GGUF and Modelfile are removed

    def test_a_wrong_checksum_is_refused_and_the_file_removed(self):
        r = self.run_block("hf_gguf_create tiny:1", spec="acme/tiny-GGUF tiny.gguf %s %d" % ("0" * 64, len(self.payload)))
        self.assertEqual(r.returncode, 1)
        self.assertIn("sha256", r.stderr)
        self.assertFalse(os.path.exists(self.log) and "create" in slurp(self.log))
        self.assertEqual(os.listdir(os.path.join(self.root, "gg")), [])

    def test_a_failed_download_is_reported(self):
        r = self.run_block("hf_gguf_create tiny:1", spec="acme/missing-GGUF none.gguf %s 99" % self.sha)
        self.assertEqual(r.returncode, 1)
        self.assertIn("download failed", r.stderr)

    def test_the_fallback_can_be_switched_off_and_unknown_tags_are_refused(self):
        r = self.run_block("hf_gguf_create tiny:1", extra_env={"PIERRE_NO_HF_FALLBACK": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("PIERRE_NO_HF_FALLBACK", r.stderr)
        r = self.run_block("hf_gguf_create nosuchmodel:1", extra_env={"PIERRE_GGUF_SPEC": ""})
        self.assertEqual(r.returncode, 1)
        self.assertIn("no Hugging Face GGUF is known", r.stderr)

    def test_an_embedding_model_gets_no_chat_parameters(self):
        r = self.run_block("hf_gguf_create nomic-embed-text")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("PARAMETER", slurp(self.log + ".modelfile"))

    def test_linux_and_mac_blocks_are_identical_and_both_are_used(self):
        lin, mac = os.path.join(AI, "install-local-ai-linux.sh"), os.path.join(PIERRE, "setup-local-pierre.sh")
        self.assertEqual(hf_block(lin), hf_block(mac))
        for path in (lin, mac):
            self.assertIn("|| hf_gguf_create", read(path))
        self.assertIn("hf_gguf_create \"$WATCH_MODEL\"", read(lin))
        self.assertIn("hf_gguf_create \"$WATCH_MODEL\"", read(mac))
        self.assertIn("hf_gguf_create nomic-embed-text", read(mac))

    def test_the_mac_block_is_zsh_compatible_syntax(self):
        if not shutil.which("zsh"):
            self.skipTest("no zsh")
        r = subprocess.run(["zsh", "-n", os.path.join(PIERRE, "setup-local-pierre.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_windows_table_matches_the_bash_table(self):
        bash = {}
        for m in re.finditer(r'echo "([\w./-]+) ([\w.-]+\.gguf) ([0-9a-f]{64}) (\d+)"', hf_block(os.path.join(AI, "install-local-ai-linux.sh"))):
            bash[m.group(2)] = m.groups()
        ps = {}
        for m in re.finditer(r"@\('([\w./-]+)','([\w.-]+\.gguf)','([0-9a-f]{64})','(\d+)'\)", hf_block(os.path.join(AI, "install-local-ai-windows.ps1"))):
            ps[m.group(2)] = m.groups()
        self.assertEqual(len(bash), 6)
        self.assertEqual(bash, ps)
        t = read(AI, "install-local-ai-windows.ps1")
        self.assertIn("New-OllamaFromHf $m", t)
        self.assertIn("New-OllamaFromHf $WatchModel", t)
        self.assertIn("$env:PIERRE_NO_HF_FALLBACK -eq '1'", hf_block(os.path.join(AI, "install-local-ai-windows.ps1")))

    def test_the_known_ggufs_are_the_4bit_files_of_the_official_repos(self):
        t = hf_block(os.path.join(AI, "install-local-ai-linux.sh"))
        for repo in ("Qwen/Qwen3-4B-GGUF", "unsloth/Phi-4-mini-instruct-GGUF", "nomic-ai/nomic-embed-text-v1.5-GGUF"):
            self.assertIn(repo, t)
        self.assertIn("7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5 2497280256", t)


class TestAcceptance(StrictCase):
    """The review of the DWR-2658 run found three things the model missed. The synthetic fixture reproduces each
    shape; the optional replay checks the real run folder."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pierre_accept_")
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

    @unittest.skipUnless(os.environ.get("DAMIT_REPLAY_2658"), "set DAMIT_REPLAY_2658 to the run folder")
    @unittest.skipUnless(HAVE_NUMPY, "numpy")
    @unittest.skipUnless(HAVE_GDAL, "GDAL (osgeo) is needed to read the structures and the GeoTIFF: without it the digest says "
                                    "RECEPTORS_UNCHECKED and cannot flag the NoData receptor")
    def test_replay_dwr_2658(self):
        """Needs numpy and GDAL (the QGIS env). Without GDAL it is skipped, never an error."""
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


class TestPackMatchesHazardNoDataRule(StrictCase):
    """Hazard 0.2.6 (#67): neighbourhood fill of a NoData receptor only on grids coarser than 20 m. The pack must not
    teach the older 'NoData is always dry' rule."""

    def test_known_behaviours_states_the_20_m_rule_from_the_code(self):
        src = read(REPO, "damit_hazard", "sampling", "rasters.py")
        m = re.search(r"^NODATA_NEIGHBOURHOOD_MIN_CELL_M = ([0-9.]+)", src, re.M)
        self.assertIsNotNone(m)
        kb = read(PIERRE, "knowledge", "KNOWN-BEHAVIOURS.md")
        self.assertIn("coarser than %g m" % float(m.group(1)), kb)
        code = src + read(REPO, "damit_hazard", "engine", "core.py")
        for needle in ("NODATA_NEIGHBOURHOOD_MIN_CELL_M", "centre_nodata_dry", "nodata_dry_review",
                       "nodata_neighbourhood", "neighbourhood"):
            self.assertIn(needle, kb)
            self.assertIn(needle, code)                         # the pack names only what the code really writes
        self.assertIn('"neighbourhood", True', src)             # sampling=neighbourhood
        self.assertNotIn("Hazard reads a NoData cell as dry (0 ft).", kb)
