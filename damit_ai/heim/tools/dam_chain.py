#!/usr/bin/env python3
# dam_chain.py v1.6.0 — run the dam-plugin sets headless from Terminal (conda), stdlib only.
#
#   dam_chain.py setup                       one-time: batch profiles that point at your QGIS
#                                            profiles "nd", "damsafety" and "damit", plugins enabled
#   dam_chain.py plugins --set nd|dwr|damit  load every plugin of the set, check the chain's
#                                            algorithms are there, run the self-tests
#   dam_chain.py open --set nd|dwr|damit     open QGIS (GUI) with that set's profile
#   dam_chain.py seed --dams-folder D --csv dams.csv
#                                            make <D>/<dam_id>/dam.json for each row (never overwrites)
#   dam_chain.py run --set nd  --dams-folder D --ids DWR-2801,DWR-4031
#                                            per dam: Get data -> Screening -> Runner -> Hazard
#                                            (ndhazard:getdamdata, then ndhazard:suitechain)
#                                            --hi-res downloads a 1 m DEM (DEM_CELL_M=1).
#                                            --triage asks the local Ollama model to explain a
#                                            failed step (writes TRIAGE.txt next to the run log).
#                                            Defaults can live in the environment (a --flag still wins):
#                                              DAMCHAIN_GETDATA_PARAM, DAMCHAIN_BREACH_PARAM,
#                                              DAMCHAIN_SCREEN_PARAM, DAMCHAIN_CLASSIFY_PARAM
#                                            each a space-separated list of KEY=VALUE, e.g.
#                                              export DAMCHAIN_GETDATA_PARAM="DEM_CELL_M=1 DEM_MI=15"
#   dam_chain.py run --set dwr --dams LAYER --ids 2801,4031 --out D --dem DEM --screen-work W
#                                            the DamSafety Runner's own list chain
#                                            (ndbreach:chainbatch: Screening -> Runner -> Hazard)
#   dam_chain.py run --set damit --dams LAYER --ids A,B --out D --dem DEM [--cell 5 --solver fv2]
#                                            DamIT Runner breach runs for a dams layer
#                                            (damit_run:batch; DamIT Hazard has no batch classifier
#                                            yet). Checks first: files, the dam ids in the layer,
#                                            and every option name against the installed Runner.
#   --cell / --solver / --manning / --runner-param KEY=VALUE (and, for the damit set, --param) are
#   checked against the Runner's own parameter list (qgis_process help) before anything runs; an
#   enum takes its option text (--runner-param SCENARIO=sunny) or its number; text that fits two
#   options is refused. --check-only runs only those checks. The damit set passes --lisflood only
#   when you give it (a binary, or builtin / gpu / gpu-sgc); otherwise the Runner's setting is used.
#   dam_chain.py vor ask|research|search|ingest|chat|list ...
#                                            the literature research assistant (vor, a
#                                            separate model and library from heim); same as typing
#                                            vor ...  (v1.4)
#   dam_chain.py audit [--repo R] [--zips Z] [--heim] [--golden --results D] ...
#                                            local repo audit: release/packaging, security patterns,
#                                            network hosts, optional Heim diff review, golden runs.
#                                            Report in ~/local-ai/reports (repo_audit.py, v1.5)
#   dam_chain.py crest --set nd|dwr          open the Crest desk wired to that set: its Report-step
#                                            buttons (dam folder, screening, flood model) run that
#                                            set's plugins, in ~/CrestDams/<set>
#
# Every run goes through qgis_process in the conda env (ndqgis), with the set's own QGIS
# profile, so ND, DamSafety and DamIT never load together (they share Processing ids).
# v1.6.0 (2026-11-23): the DamIT set (--set damit, profile "damit"), the QGIS profiles folder
# of Linux and Windows as well as macOS, and option names checked before a run.
# --dry-run prints the commands without running them. Logs: <dams folder>/_chain_logs/.
import os, sys, re, csv, json, time, shutil, argparse, subprocess, threading, urllib.request, urllib.error
from datetime import datetime

def _default_profiles():
    """Where QGIS keeps its profiles on this computer (the installers use the same folders)."""
    if sys.platform == "darwin":
        return "~/Library/Application Support/QGIS/QGIS3/profiles"
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", "~"), "QGIS", "QGIS3", "profiles")
    return "~/.local/share/QGIS/QGIS3/profiles"


QGIS_PROFILES = os.path.expanduser(os.environ.get("DAMCHAIN_QGIS_PROFILES", _default_profiles()))
BATCH_ROOT = os.path.expanduser(os.environ.get("DAMCHAIN_BATCH_ROOT", "~/local-ai/qgis-batch"))
CREST_DIR = os.path.expanduser(os.environ.get("DAMCHAIN_CREST_DIR", "~/local-ai/crest-desktop"))

# Local Ollama triage (shared convention with suite_check.py / audit_plugin.py): optional, advisory.
HEIM_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat"
HEIM_MODEL = os.environ.get("HEIM_MODEL", "heim")
HEIM_NUM_CTX = int(os.environ.get("HEIM_NUM_CTX", "16384"))
SETS = {
    "nd": {"profile": "nd", "runner": "nd_breach_runner",
           "plugins": ["ND_Dam_Hazard_Helper", "nd_breach_runner", "nd_dam_screening",
                       "nd_data_updater"],
           "needs": ["ndhazard:getdamdata", "ndhazard:suitechain", "nddam:runchain",
                     "ndbreach:rundam", "ndhazard:classify", "ndbreach:selftest", "nddam:selftest"]},
    "dwr": {"profile": "damsafety", "runner": "DamSafety_Runner",
            "plugins": ["DamSafety_Core", "DamSafety_Setup", "DamSafety_Data", "DamSafety_Screening",
                        "DamSafety_Runner", "DamSafety_Hazard", "DamSafety_HazardLite",
                        "DamSafety_PMP"],
            "needs": ["ndbreach:chainbatch", "nddam:runchain", "ndbreach:batch",
                      "ndhazard:classify", "ndbreach:selftest", "nddam:selftest"]},
    # v1.6.0: DamIT (the national suite). No self-test tools: `plugins --selftest` runs damit_run:check.
    "damit": {"profile": "damit", "runner": "damit_runner",
              "plugins": ["damit_core", "damit_catalog", "damit_setup", "damit_data", "damit_screener",
                          "damit_runner", "damit_hazard", "damit_hazardlite", "damit_pmp", "damit_finder"],
              "needs": ["damit_run:batch", "damit_run:rundam", "damit_run:check", "damit_run:checkhandoff",
                        "damit_screen:preflight", "damit_screen:runchain", "damit:classify"]},
}
# The Runner tool whose options --cell / --solver / --manning / --runner-param set, per set.
RUNNER_ALG = {"dwr": "ndbreach:batch", "damit": "damit_run:batch"}
SOLVER_WORDS = ("default", "acc", "fv2", "mwdg2")
# --lisflood may name the DamIT Runner's in-process engines instead of a binary (damit_runner/core/lisflood.py)
DAMIT_ENGINE_WORDS = ("builtin", "built-in", "built in", "internal", "gpu", "metal", "gpu engine", "metalflood",
                      "gpu-sgc", "metal-sgc", "sgc", "boann-sgc", "gpu sgc", "subgrid channels",
                      "sub-grid channels")
DWR_HEC = {"run": 0, "wait": 1, "skip": 2}
DWR_STOP = {"end": 0, "screening": 1, "runner": 2}
DEM_UNITS = {"detect": 0, "feet": 1, "us-feet": 2, "meters": 3}


# ------------------------------------------------------------------ plumbing
def conda_exe():
    for c in (os.environ.get("CONDA_EXE"), shutil.which("conda"),
              os.path.expanduser("~/miniconda3/bin/conda"), os.path.expanduser("~/miniconda/bin/conda"),
              os.path.expanduser("~/miniforge3/bin/conda")):
        if c and os.path.exists(c):
            return c
    sys.exit("conda not found. Open a Terminal where `conda` works, or set CONDA_EXE.")


def env_prefix(conda, name):
    # the suite's env is <conda base>/envs/<name> (made by path); a same-named env elsewhere (an
    # older install's ~/micromamba/envs/<name>) sorts first in `env list`, so it is the fallback
    try:
        base = subprocess.run([conda, "info", "--base"], capture_output=True, text=True).stdout.strip()
    except OSError:
        base = ""
    if base and os.path.isdir(os.path.join(base, "envs", name, "conda-meta")):
        return os.path.join(base, "envs", name)
    out = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True)
    try:
        for p in json.loads(out.stdout)["envs"]:
            if os.path.basename(p) == name:
                return p
    except (ValueError, KeyError):
        pass
    sys.exit("conda env '%s' not found — run the suite installer first." % name)


def find_qgis_process(prefix, override=""):
    if override:
        return override
    for c in (os.path.join(prefix, "bin", "qgis_process"),
              os.path.join(prefix, "QGIS.app", "Contents", "MacOS", "bin", "qgis_process"),
              os.path.join(prefix, "QGIS.app", "Contents", "MacOS", "qgis_process")):
        if os.path.isfile(c):
            return c
    return "qgis_process"          # on the env's PATH after activation


class QP:
    """qgis_process inside the conda env, with one set's batch profile."""

    def __init__(self, args, set_name):
        self.dry = args.dry_run
        self.quiet = getattr(args, "quiet", False)
        if self.dry:
            self.conda, self.prefix = shutil.which("conda") or "conda", "<%s>" % args.env
        else:
            self.conda = conda_exe()
            self.prefix = env_prefix(self.conda, args.env)
        self.qp = find_qgis_process(self.prefix, args.qgis_process)
        self.base = os.path.join(BATCH_ROOT, set_name)
        self.env = dict(os.environ)
        self.env.pop("PYTHONPATH", None)
        self.env.update({"QGIS_CUSTOM_CONFIG_PATH": self.base, "QT_QPA_PLATFORM": "offscreen",
                         "OMP_NUM_THREADS": str(args.threads), "NDBREACH_ANUGA_MESHER": "gmsh"})
        self.envname = args.env
        self.anuga_py = ""
        if not self.dry:
            self._pick_anuga()
        lis = os.path.expanduser(args.lisflood or "")
        if set_name == "damit" and not getattr(args, "lisflood_given", True):
            lis = ""        # the DamIT Runner's own engine setting decides (it finds ~/dam-suite/bin itself)
        if lis and os.path.isfile(lis):
            # Also read by tools that get no EXE parameter (DamSafety Screening's self-test before 0.18.5).
            self.env["NDBREACH_LISFLOOD"] = lis

    def _pick_anuga(self):
        """v1.5.1: the Runner takes its saved provider setting, else the first conda env named
        *anuga* in alphabetical order, so an older env "anuga" (no gmsh) wins over the suite's
        "ndanuga" (the env variable alone does not beat the saved setting, so the self-test and
        runs also get ANUGA_PYTHON as a parameter). Point it at ndanuga unless
        NDBREACH_ANUGA_PYTHON is set, and ask for gmsh only when that Python can import gmsh
        (otherwise gmsh_or_default: the default ANUGA mesh, with a note in the log)."""
        py = self.env.get("NDBREACH_ANUGA_PYTHON", "")
        if not py:
            cand = os.path.join(os.path.dirname(self.prefix), "ndanuga", "bin", "python")
            if os.path.isfile(cand):
                py = self.env["NDBREACH_ANUGA_PYTHON"] = cand
        self.anuga_py = py
        if py and "NDBREACH_ANUGA_MESHER" not in os.environ:
            try:
                ok = subprocess.run([py, "-c", "import gmsh"], capture_output=True, timeout=120).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if not ok:
                self.env["NDBREACH_ANUGA_MESHER"] = "gmsh_or_default"
                print("  note: %s has no gmsh; ANUGA uses its default mesh (conda install -n <env> "
                      "python-gmsh gmsh to add it)" % py)

    def argv(self, *qp_args):
        return [self.conda, "run", "--no-capture-output", "-n", self.envname, self.qp] + list(qp_args)

    @staticmethod
    def _is_noise(t):
        return (not t) or ("XDG_RUNTIME_DIR" in t) or t.startswith("Warning 1:") \
            or t.startswith("QStandardPaths") or t.startswith("Warning:")

    def run(self, alg, params, log_path, timeout=None, label=""):
        """Returns (ok, results dict, last error lines). Streams the plugin's own progress lines
        to the terminal (unless --quiet) with a heartbeat, so a long step never looks frozen."""
        cmd = self.argv("--json", "run", alg, "--") + ["%s=%s" % (k, v) for k, v in params.items()]
        shown = " ".join(_q(c) for c in cmd)
        if self.dry:
            print("  DRY  QGIS_CUSTOM_CONFIG_PATH=%s %s" % (_q(self.base), shown))
            return True, {}, ""
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        tag = label or alg
        out_chunks, start, last, in_json = [], time.time(), [time.time()], [False]
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("$ %s\n\n" % shown)
            log.flush()
            try:
                p = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1)
            except OSError as e:
                log.write("\n[LAUNCH FAILED] %s\n" % e)
                return False, {}, str(e)

            def pump_out():
                for line in p.stdout:
                    out_chunks.append(line)
                    last[0] = time.time()
                    t = line.strip()
                    if t.startswith("{"):
                        in_json[0] = True           # the --json result block begins; stop echoing
                    if not self.quiet and not in_json[0] and not self._is_noise(t):
                        sys.stdout.write("      %s\n" % t)
                        sys.stdout.flush()

            def pump_err():
                for line in p.stderr:
                    log.write(line)
                    log.flush()

            stop = threading.Event()

            def beat():
                while not stop.wait(20):
                    if not self.quiet and time.time() - last[0] >= 18:
                        sys.stdout.write("      ... %s running (%ds elapsed)\n"
                                         % (tag, int(time.time() - start)))
                        sys.stdout.flush()

            threads = [threading.Thread(target=f, daemon=True) for f in (pump_out, pump_err, beat)]
            for th in threads:
                th.start()
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                stop.set()
                threads[0].join(2); threads[1].join(2)
                log.write("\n[TIMEOUT]\n")
                return False, {}, "timeout"
            stop.set()
            threads[0].join(2); threads[1].join(2)
            out = "".join(out_chunks)
            log.write("\n--- stdout ---\n" + (out or ""))
        res = _json_results(out)
        if p.returncode == 0 and res.get("OK") is not False:
            return True, res, ""
        if p.returncode == 0:      # the algorithm finished but reports a failure (self-tests)
            return False, res, "failed step %s, see %s" % (res.get("FAILED_STEP", "?"),
                                                           res.get("REPORT") or log_path)
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            tail = []
            for l in fh.read().split("\n--- stdout ---")[0].splitlines():
                l = l.strip()
                if l and not self._is_noise(l) and (not tail or tail[-1] != l):
                    tail.append(l)
        return False, res, " | ".join(tail[-2:])

    def plain(self, *qp_args):
        cmd = self.argv(*qp_args)
        if self.dry:
            print("  DRY  %s" % " ".join(_q(c) for c in cmd))
            return 0, ""
        p = subprocess.run(cmd, env=self.env, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def _json_results(out):
    """qgis_process --json results. Plugins print log lines to stdout before the JSON, so parse
    from the first line that is just "{"."""
    out = out or ""
    for start in [0] + [m.start() + 1 for m in re.finditer(r"\n\{", out)]:
        try:
            return json.loads(out[start:]).get("results") or {}
        except (ValueError, AttributeError):
            continue
    return {}


def _q(s):
    s = str(s)
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def _heim_chat(prompt, timeout=1800):
    """Ask the local Ollama model once; return its text (thinking stripped). Raises on transport error."""
    payload = {"model": HEIM_MODEL, "messages": [{"role": "user", "content": prompt}],
               "stream": False, "think": True,
               "options": {"temperature": 0.6, "top_p": 0.95, "top_k": 20,
                           "num_ctx": HEIM_NUM_CTX, "num_predict": 4096}}
    def _post(pl):
        req = urllib.request.Request(HEIM_URL, data=json.dumps(pl).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    try:
        out = _post(payload)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        payload.pop("think")                       # some models reject the think flag
        out = _post(payload)
    txt = (out.get("message") or {}).get("content") or ""
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()


def triage_failure(step_name, err, log_path, out_dir):
    """Send a failed step's log tail to the local model and append an advisory note to TRIAGE.txt.
    Advisory only: the log is the fact. Never raises (a triage problem must not fail the run)."""
    tail = ""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            tail = "\n".join(fh.read().splitlines()[-150:])
    except Exception:                                                        # noqa
        tail = "(log not readable: %s)" % log_path
    prompt = ("A dam-suite step failed while running headless in QGIS (qgis_process). In a few lines, "
              "say (1) whether this is an ENVIRONMENT/DATA problem (no offline pack or chosen layers, "
              "missing DEM, DEM no-data at the flood edge, LISFLOOD-FP/ANUGA missing, wrong DEM units, "
              "network/proxy) or a CODE bug, (2) the most likely cause citing log lines, (3) the "
              "smallest next check or fix. Do not invent anything you cannot see in the log; say UNSURE "
              "when unsure.\n\nSTEP: %s\nERROR: %s\n\n=== LOG TAIL ===\n%s"
              % (step_name, err or "(none)", tail))
    print("   triage (%s): asking %s ..." % (step_name, HEIM_MODEL), flush=True)
    try:
        ans = _heim_chat(prompt)
    except Exception as e:                                                   # noqa
        ans = ("TRIAGE UNAVAILABLE: could not reach Ollama at %s (%s). Start Ollama and pull the "
               "model, or set OLLAMA_URL / HEIM_MODEL." % (HEIM_URL, e))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "TRIAGE.txt")
    block = ["", "=" * 72, "%s  STEP: %s" % (_stamp(), step_name),
             "error: %s" % (err or "(none)"), "log:   %s" % log_path,
             "model: %s (advisory; the log is the fact)" % HEIM_MODEL, "-" * 72, ans]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")
    print("   triage -> %s" % path, flush=True)
    for ln in ans.splitlines()[:6]:
        print("      | " + ln, flush=True)
    return path


def parse_kv(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            sys.exit("--param needs KEY=VALUE, got: %s" % it)
        k, v = it.split("=", 1)
        out[k.strip()] = v
    return out


def _env_kv(env_name):
    """KEY=VALUE defaults from an environment variable, split on whitespace.
    e.g.  export DAMCHAIN_BREACH_PARAM="CELL=10 MANNING=0.06"
    """
    raw = (os.environ.get(env_name) or "").strip()
    return [tok for tok in re.split(r"\s+", raw) if tok] if raw else []


def kv(items, env_name=None):
    """parse_kv with environment defaults applied first; a --flag value overrides the env."""
    out = {}
    if env_name:
        out.update(parse_kv(_env_kv(env_name)))
    out.update(parse_kv(items))
    return out


def read_ids(args):
    ids = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    if args.ids_csv:
        with open(os.path.expanduser(args.ids_csv), newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                v = (row.get("dam_id") or "").strip()
                if v and v not in ids:
                    ids.append(v)
    return ids


def write_atomic(path, text):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- commands
def cmd_setup(args):
    """~/local-ai/qgis-batch/<set>/profiles/default -> your real QGIS profile, plugins enabled."""
    for set_name, spec in SETS.items():
        prof = getattr(args, "%s_profile" % set_name, "") or spec["profile"]
        real = os.path.join(QGIS_PROFILES, prof)
        link_dir = os.path.join(BATCH_ROOT, set_name, "profiles")
        link = os.path.join(link_dir, "default")
        if not os.path.isdir(real):
            print("! %s: no QGIS profile '%s' at %s — install that set first (skipped)" % (set_name, prof, real))
            continue
        os.makedirs(link_dir, exist_ok=True)
        if os.path.islink(link):
            os.remove(link)
        elif os.path.exists(link):
            sys.exit("%s exists and is not a link; move it away first" % link)
        os.symlink(real, link)
        print("%s: batch profile -> %s" % (set_name, real))
        qp = QP(args, set_name)
        failed = []
        for p in spec["plugins"]:
            if os.path.isdir(os.path.join(real, "python", "plugins", p)):
                rc, out = qp.plain("plugins", "enable", p)
                # rc 1 also means "already enabled" or "no Processing provider" (damit_core); only a
                # qgis_process that could not start at all (126/127, a crash) is a failure here
                if rc not in (0, 1) and not args.dry_run:
                    failed.append(p)
        if failed:
            print("   ! qgis_process could not start to enable %s. Is QGIS installed in the conda "
                  "environment '%s'?" % (", ".join(failed), args.env))
        else:
            print("   plugins enabled for qgis_process; `dam_chain.py plugins --set %s` checks the tools"
                  % set_name)


def cmd_plugins(args):
    spec = SETS[args.set]
    qp = QP(args, args.set)
    rc, out = qp.plain("list")
    if not args.dry_run:
        have = set(re.findall(r"\b(\w+:\w+)\b", out))
        # v1.5: `qgis_process list` leaves out tools hidden from the toolbox (the DamSafety
        # self-tests, Screening's run-chain): ask for each one by id before calling it missing
        for alg in spec["needs"]:
            if alg not in have:
                rc_h, _ = qp.plain("help", alg)
                if rc_h == 0:
                    have.add(alg)
        for alg in spec["needs"]:
            print("  %-4s %s" % ("ok" if alg in have else "MISSING", alg))
        providers = sorted({a.split(":")[0] for a in have
                            if a.split(":")[0].startswith(("nd", "damit"))})
        print("  providers loaded: %s" % ", ".join(providers))
        missing = [a for a in spec["needs"] if a not in have]
        if missing:
            print("  -> run `dam_chain.py setup`, and check the plugins are installed in profile '%s'"
                  % spec["profile"])
    if args.selftest and args.set == "damit":
        # DamIT has no self-test tools; damit_run:check runs LISFLOOD-FP on a tiny channel and imports ANUGA.
        logs = os.path.join(os.path.expanduser(args.log_dir), "selftest_%s_%s" % (args.set, _stamp()))
        # checks the engine the DamIT Runner is set to use, unless --lisflood names another
        lis = os.path.expanduser(args.lisflood or "") if getattr(args, "lisflood_given", True) else ""
        p = {}
        if os.path.isfile(lis) or lis.strip().lower() in DAMIT_ENGINE_WORDS:
            p["LISFLOOD_EXE"] = lis
        if qp.anuga_py:
            p["ANUGA_PYTHON"] = qp.anuga_py
        ok, res, err = qp.run("damit_run:check", p, os.path.join(logs, "damit_run_check.log"), timeout=1800)
        result = res.get("RESULT") or ""
        # the check finishes (exit 0) even when LISFLOOD-FP is missing; its lines say OK or PROBLEM
        ok = ok and bool(result) and not any(ln.startswith("PROBLEM") for ln in result.splitlines())
        if not args.dry_run:
            print("  %-4s %s  %s" % ("PASS" if ok else "FAIL", "damit_run:check", result or err))
        if not args.dry_run:
            print("  logs: %s" % logs)
    elif args.selftest:
        logs = os.path.join(os.path.expanduser(args.log_dir), "selftest_%s_%s" % (args.set, _stamp()))
        lis = os.path.expanduser(args.lisflood)
        # ND Screening takes the step-7 cell in feet (CELL_FT), DamSafety Screening in metres (CELL).
        cell = {"CELL_FT": 100} if args.set == "nd" else {"CELL": 30}
        scr = dict(cell, ENGINE=2, SIMH=2, REPORT=os.path.join(logs, "nddam_selftest.txt"))
        run = {"RUN_MODEL": "true", "THREADS": args.threads}
        if qp.anuga_py:          # the Runner's saved provider setting beats the environment
            run["ANUGA_PYTHON"] = qp.anuga_py
        if os.path.isfile(lis):                  # test the real engine too, not only the built-in one
            scr.update(ENGINE=0, EXE=lis)        # both sets take EXE (DamSafety Screening from 0.18.5)
            run["LISFLOOD_EXE"] = lis
        for alg, params in (("ndbreach:selftest", run), ("nddam:selftest", scr)):
            ok, res, err = qp.run(alg, params, os.path.join(logs, alg.replace(":", "_") + ".log"),
                                  timeout=1800)
            print("  %-4s %s  %s" % ("PASS" if ok else "FAIL", alg,
                                     res.get("RESULT") or res.get("SUMMARY") or err))
        if not args.dry_run:
            print("  logs: %s" % logs)


def cmd_open(args):
    spec = SETS[args.set]
    conda = conda_exe()
    prefix = env_prefix(conda, args.env)
    app = os.path.join(prefix, "QGIS.app", "Contents", "MacOS", "QGIS")
    exe = app if os.path.isfile(app) else "qgis"
    cmd = [conda, "run", "-n", args.env, "env", "NDBREACH_ANUGA_MESHER=gmsh", exe,
           "--profile", getattr(args, "profile", None) or spec["profile"]]
    print(" ".join(_q(c) for c in cmd))
    if not args.dry_run:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        subprocess.Popen(cmd, env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_pack(args):
    """Build / refresh the offline data pack with the ND Data Updater plugin, into the data folder.
    The pack build (structures, roads, rail, 3DHP, ABI barriers, NLCD, counties ...) is a statewide, multi-
    gigabyte download; it has no headless processing algorithm, so this opens QGIS to the Updater,
    which creates the pack in the folder you point it at and tells the dam plugins to read it there."""
    folder = os.path.expanduser(args.data_folder) if args.data_folder else "~/ND_Suite_Data"
    bar = "=" * 72
    print(bar)
    print("Build the offline pack into:  %s" % folder)
    print(bar)
    print("QGIS is opening with the '%s' profile. In QGIS:" % (getattr(args, "profile", None) or SETS[args.set]["profile"]))
    print("  1. Plugins menu > ND Data Updater > 'Settings and status...'.")
    print("  2. Local data > 'Choose...' > %s  (the three dam plugins follow it)." % folder)
    print("  3. Keep 'Offline pack for the ND dam plugins (all layers)' and")
    print("     'Make the ND dam plugins read this pack' ticked; 3DHP on 'auto'.")
    print("  4. Click 'Save and Check All Now'. Statewide, several GB, an hour or more the")
    print("     first time; 'Rebuild Only Missing Layers' resumes an interrupted build.")
    print("  The pack lands at %s/ND_Dam_Suite_Pack/; 'Offline pack and data folder...'" % folder)
    print("  in the same menu shows it layer by layer. Every later run reads it offline.")
    print(bar)
    if getattr(args, "print_only", False):
        return
    cmd_open(args)


def cmd_seed(args):
    """dam.json per CSV row. Columns: dam_id (required), name, lat, lon, height_ft, storage_acft,
    dam_length_ft, dwr_structure_id, nid_id, existing_hazard_class. Existing dam.json is kept."""
    dams = os.path.expanduser(args.dams_folder)
    num = {"lat", "lon", "height_ft", "storage_acft", "dam_length_ft"}
    made = kept = 0
    if not os.path.isfile(os.path.expanduser(args.csv)):
        sys.exit("No CSV at %s. Make one with a header line, e.g.\n"
                 "  dam_id,name,lat,lon,height_ft,storage_acft,dwr_structure_id,nid_id\n"
                 "  DWR-2801,Swan Buffalo 12,46.984382,-97.390918,27.5,1615.344,2801,ND00199"
                 % os.path.expanduser(args.csv))
    with open(os.path.expanduser(args.csv), newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            did = (row.get("dam_id") or "").strip()
            if not did:
                continue
            folder = os.path.join(dams, did)
            path = os.path.join(folder, "dam.json")
            if os.path.exists(path):
                kept += 1
                continue
            fields = {"dam_id": did}
            for k, v in row.items():
                if k == "dam_id" or v is None or not str(v).strip():
                    continue
                k = k.strip()
                try:
                    fields[k] = float(v) if k in num else str(v).strip()
                except ValueError:
                    sys.exit("%s: %s is not a number: %r" % (did, k, v))
            if "lat" not in fields or "lon" not in fields:
                print("! %s: no lat/lon — skipped" % did)
                continue
            rec = {"format": "nd_dam_suite/dam_record", "format_version": 1, "fields": fields,
                   "sources": {"_seed": {"tool": "dam_chain.py seed", "when": _stamp()[:8],
                                         "note": "from %s" % os.path.basename(args.csv)}},
                   "status": []}
            if args.dry_run:
                print("  DRY  %s" % path)
                continue
            os.makedirs(folder, exist_ok=True)
            write_atomic(path, json.dumps(rec, indent=1) + "\n")
            made += 1
    print("dam.json written: %d, already there (kept): %d" % (made, kept))


def run_nd(args):
    dams = os.path.abspath(os.path.expanduser(args.dams_folder))
    ids = read_ids(args) or sorted(d for d in os.listdir(dams)
                                   if os.path.isfile(os.path.join(dams, d, "dam.json")))
    if not ids:
        sys.exit("No dams: give --ids / --ids-csv, or seed dam folders first.")
    qp = QP(args, "nd")
    logs = os.path.join(dams, "_chain_logs", _stamp())
    summary = os.path.join(dams, "Chain_Summary_ND.csv")
    rows, not_tried = [], 0
    flags = {"SCREEN": str(not args.no_screen).lower(), "BREACH": str(not args.no_breach).lower(),
             "CLASSIFY": str(not args.no_classify).lower()}
    _env = {"SCREEN_PARAMETERS": "DAMCHAIN_SCREEN_PARAM",
            "BREACH_PARAMETERS": "DAMCHAIN_BREACH_PARAM",
            "CLASSIFY_PARAMETERS": "DAMCHAIN_CLASSIFY_PARAM"}
    for k, items in (("SCREEN_PARAMETERS", args.screen_param), ("BREACH_PARAMETERS", args.breach_param),
                     ("CLASSIFY_PARAMETERS", args.classify_param)):
        kvv = kv(items, _env[k])
        if k == "BREACH_PARAMETERS" and qp.anuga_py and "ANUGA_PYTHON" not in (kvv or {}):
            kvv = dict(kvv or {}, ANUGA_PYTHON=qp.anuga_py)
        if kvv:
            flags[k] = json.dumps(kvv)
    for n, did in enumerate(ids, 1):
        folder = os.path.join(dams, did)
        state_path = os.path.join(folder, "_chain_nd", "state.json")
        t0 = time.time()
        print("[%d/%d] %s" % (n, len(ids), did), flush=True)
        if not os.path.isfile(os.path.join(folder, "dam.json")):
            rows.append([did, "no dam.json", "", "0", "", "seed it first (dam_chain.py seed)"])
            print("   no dam.json — skipped")
            continue
        if not args.redo and os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as fh:
                st = json.load(fh)
            if st.get("status") == "done":
                rows.append([did, "done (earlier run)", st.get("nd_class", ""), "0", st.get("log", ""), ""])
                print("   done earlier (class %s) — skipped; --redo to run again" % st.get("nd_class", "?"))
                continue
        status, nd_class, err, log = "done", "", "", ""
        if not args.no_getdata:
            gp = {"DAM_FOLDER": folder}
            if args.data_folder:
                gp["DATA_FOLDER"] = os.path.expanduser(args.data_folder)
            gp.update(kv(args.getdata_param, "DAMCHAIN_GETDATA_PARAM"))
            if getattr(args, "hi_res", False) and "DEM_CELL_M" not in gp:
                gp["DEM_CELL_M"] = "1"
            log = os.path.join(logs, "%s_1_getdamdata.log" % did)
            ok, _r, err = qp.run("ndhazard:getdamdata", gp, log, timeout=args.timeout_min * 60,
                                  label="get data for %s" % did)
            print("   get data: %s" % ("ok" if ok else "FAILED " + err))
            if not ok:
                status = "failed: get data"
                if getattr(args, "triage", False):
                    triage_failure("get data (%s)" % did, err, log, logs)
        if status == "done":
            cp = dict(flags, DAM_FOLDER=folder)
            cp.update(parse_kv(args.param))
            log = os.path.join(logs, "%s_2_suitechain.log" % did)
            ok, res, err = qp.run("ndhazard:suitechain", cp, log, timeout=args.timeout_min * 60,
                                   label="screening/runner/hazard for %s" % did)
            nd_class = str(res.get("ND_CLASS") or "")
            print("   chain: %s" % (("ok, ND class %s" % (nd_class or "?")) if ok else "FAILED " + err))
            if not ok:
                status = "failed: chain"
                if getattr(args, "triage", False):
                    triage_failure("chain (%s)" % did, err, log, logs)
        mins = "%.1f" % ((time.time() - t0) / 60)
        rows.append([did, status, nd_class, mins, log, err])
        if not args.dry_run:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            write_atomic(state_path, json.dumps({"status": "done" if status == "done" else "failed",
                                                 "nd_class": nd_class, "log": log, "error": err,
                                                 "when": _stamp()}, indent=1))
            _write_summary(summary, rows)
        if status != "done" and args.stop_on_error:
            not_tried = len(ids) - n
            break
    if args.dry_run:
        return
    print("\nSummary: %s" % summary)
    # v1.5.2: a failed dam has to reach the shell. This returned None whatever happened, so
    # `dam_chain.py run --set nd` exited 0 on a chain that failed every dam, and a script that
    # tested $? was told the run was fine -- run_lisflood_44.py and run_county.py both reported
    # "ok" for dams that had failed, and now read state.json to work around it. run_dwr has
    # always exited 1 on failure; this makes the two sets agree.
    bad = [r for r in rows if not r[1].startswith("done")]
    if bad:
        print("FAILED %d of %d dam(s): %s%s" % (
            len(bad), len(rows), ", ".join("%s [%s]" % (r[0], r[1]) for r in bad[:6]),
            ", ..." if len(bad) > 6 else ""))
        if not_tried:
            print("stopped on the first failure; %d dam(s) were not attempted" % not_tried)
    sys.exit(1 if bad else 0)


def _write_summary(path, rows):
    """One row per dam: this run's rows replace earlier rows of the same dam, others are kept."""
    import io
    head = ["dam_id", "status", "nd_class", "minutes", "log", "error"]
    merged = {}
    if os.path.isfile(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.reader(fh):
                if r and r[0] != "dam_id":
                    merged[r[0]] = r
    for r in rows:
        merged[r[0]] = r
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    w.writerows(merged[k] for k in sorted(merged))
    write_atomic(path, buf.getvalue())


def run_dwr(args):
    if not args.dams:
        sys.exit("--set dwr needs --dams (a points layer: .gpkg, .shp, .geojson, or a 'path|layername=x')")
    p = {"DAMS": os.path.expanduser(args.dams), "OUT_FOLDER": os.path.expanduser(args.out or ""),
         "HEC_MODE": DWR_HEC[args.hec], "STOP_AFTER": DWR_STOP[args.stop_after],
         "RUNNER_MODELS": 1 if args.anuga else 0, "SCREENING": str(not args.no_screen).lower(),
         "KEEP_GOING": str(not args.stop_on_error).lower(), "SKIP_DONE": str(not args.redo).lower(),
         "CHECK_ONLY": str(args.check_only).lower()}
    if not p["OUT_FOLDER"]:
        sys.exit("--set dwr needs --out (the dams folder the chain writes into)")
    for key, val in (("DAM_ID_FIELD", args.id_field), ("DAM_IDS", args.ids),
                     ("IDS_CSV", args.ids_csv), ("DEM", args.dem), ("SCREEN_WORK", args.screen_work),
                     ("SETTINGS_FILE", args.settings_file), ("OVERRIDES_CSV", args.overrides_csv)):
        if val:
            p[key] = os.path.expanduser(val) if key not in ("DAM_IDS", "DAM_ID_FIELD") else val
    p.update(parse_kv(args.param))
    # Per-tool settings (e.g. the Runner's DEM units) reach chainbatch only through the
    # settings file or an overrides CSV; write the overrides CSV for the listed dams.
    runner_kv = runner_settings(args)
    if runner_kv and not args.dry_run:
        runner_kv = check_runner_params(QP(args, "dwr"), RUNNER_ALG["dwr"], runner_kv)
    tool_kv = {"ndbreach.batch.%s" % k: v for k, v in runner_kv.items()}
    tool_kv.update({"ndhazard.classify.%s" % k: v for k, v in parse_kv(args.classify_param).items()})
    if args.dem_units:
        tool_kv["ndbreach.batch.DEM_Z"] = DEM_UNITS[args.dem_units]
    if args.anuga and "ndbreach.batch.ANUGA_PYTHON" not in tool_kv:
        py = QP(args, "dwr").anuga_py if not args.dry_run else ""
        if py:
            tool_kv["ndbreach.batch.ANUGA_PYTHON"] = py
    logs = os.path.join(p["OUT_FOLDER"], "_chain_logs")
    if tool_kv:
        ids = read_ids(args)
        if not ids:
            sys.exit("--dem-units / --runner-param / --classify-param need the dams named (--ids or --ids-csv)")
        if args.overrides_csv:
            sys.exit("give either --overrides-csv or --dem-units/--runner-param/--classify-param, not both")
        ov = os.path.join(logs, "overrides_%s.csv" % _stamp())
        cols = sorted(tool_kv)
        lines = [",".join(["dam_id"] + cols)] + [",".join([i] + [str(tool_kv[c]) for c in cols]) for i in ids]
        if not args.dry_run:
            os.makedirs(logs, exist_ok=True)
            write_atomic(ov, "\n".join(lines) + "\n")
        p["OVERRIDES_CSV"] = ov
    qp = QP(args, "dwr")
    log = os.path.join(logs, "chainbatch_%s.log" % _stamp())
    ok, res, err = qp.run("ndbreach:chainbatch", p, log, label="DamSafety chain")
    if args.dry_run:
        return
    counts = str(res.get("COUNTS") or "")
    m = re.search(r"(\d+)\s+failed", counts)
    # "preflight: 0 error(s)" is a clean preflight: count the errors, don't look for the word
    errs = re.search(r"(\d+)\s+error", counts)
    if ok and (m and int(m.group(1)) > 0 or (errs and int(errs.group(1)) > 0)
               or ("error" in counts and not errs)):
        ok = False                       # the chain finished, but some dams (or the preflight) failed
    print("%s  %s" % ("OK" if ok else "FAILED", counts or err))
    print("log: %s" % log)
    if res.get("SUMMARY"):
        print("summary: %s" % res["SUMMARY"])
    if not ok and getattr(args, "triage", False):
        triage_failure("DamSafety chain", err or counts, log, os.path.dirname(log))
    sys.exit(0 if ok else 1)


def runner_settings(args):
    """--runner-param KEY=VALUE plus the named options (--cell, --solver, --manning), which win."""
    kv = parse_kv(getattr(args, "runner_param", None))
    if getattr(args, "cell", None) is not None:
        kv["CELL"] = _num_text(args.cell)
    if getattr(args, "manning", None) is not None:
        kv["MANNING"] = _num_text(args.manning)
    if getattr(args, "solver", ""):
        kv["SOLVER"] = args.solver
    return kv


def _num_text(x):
    return ("%.6f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def tool_params(qp, alg):
    """{name: definition} of a Processing tool, from `qgis_process --json help` (QGIS 3.22+).
    None when it cannot be read (an older QGIS, or the tool is not installed)."""
    rc, out = qp.plain("--json", "help", alg)
    if rc != 0:
        return None
    m = re.search(r"^\{", out or "", re.M)          # warnings may come first
    if not m:
        return None
    try:
        return json.loads(out[m.start():]).get("parameters") or None
    except ValueError:
        try:                                          # anything after the JSON block
            return json.JSONDecoder().raw_decode(out[m.start():])[0].get("parameters") or None
        except ValueError:
            return None


def enum_value(name, value, options):
    """An enum option given by its number or by its text ('fv2' -> the 'FV2 ...' option's number).
    Returns (number text, None) or (None, the reason)."""
    opts = {str(k): str(v) for k, v in (options or {}).items()}
    v = str(value).strip()
    if v in opts:
        return v, None
    low = v.lower()
    exact = [k for k, t in opts.items() if t.lower() == low]
    if len(exact) == 1:
        return exact[0], None
    # the start of an option's text ('sunny' -> 'Sunny day: ...'), then a whole word anywhere in it
    # ('fv2' -> 'FV2 (finite volume)'); text that fits more than one option is refused, never guessed
    # A value with a digit (fv2, dg2) is a code: only the start of an option counts, so 'dg2' is not
    # read as the 'MWDG2 (... DG2 ...)' option the Runner offers instead of DG2.
    anywhere = [] if re.search(r"\d", low) else [k for k, t in opts.items()
                                                  if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(low),
                                                               t.lower())]
    for hits in ([k for k, t in opts.items() if re.match(r"%s(?![a-z0-9])" % re.escape(low), t.lower())],
                 anywhere):
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            break
    return None, "%s=%s is not one of its options: %s" % (
        name, value, "; ".join("%s = %s" % (k, t) for k, t in sorted(opts.items(), key=lambda x: int(x[0]))))


def check_runner_params(qp, alg, kv):
    """v1.6.0: every KEY must be a real parameter of the Runner tool, and an enum's text is turned
    into its number. A wrong name is refused here, before anything runs: the tool itself would
    ignore it and the run would quietly use the default. Exits with the reasons."""
    defs = tool_params(qp, alg)
    if defs is None:
        sys.exit("cannot read the options of %s (qgis_process --json help %s failed): is the set "
                 "installed and `dam_chain.py setup` done? Nothing was run." % (alg, alg))
    out, bad = {}, []
    for k, v in kv.items():
        d = defs.get(k)
        if d is None:
            near = [n for n in defs if k.lower() in n.lower() or n.lower() in k.lower()]
            bad.append("%s is not an option of %s%s" % (k, alg, (" (did you mean %s?)" % ", ".join(sorted(near)[:4]))
                                                       if near else ""))
            continue
        opts = d.get("available_options")
        if opts:
            n, why = enum_value(k, v, opts)
            if why:
                bad.append(why)
                continue
            out[k] = n
        else:
            out[k] = v
    if bad:
        sys.exit("Not run:\n  " + "\n  ".join(bad))
    return out


def layer_ids(path, field=""):
    """The dam ids in a dams layer, stdlib only: a GeoPackage (first feature table, or
    'file.gpkg|layername=x') or a CSV. Returns (field, set of ids), or (None, None) when the
    format cannot be read here (the Runner still reads it)."""
    src, _, rest = path.partition("|")
    key, _, layer = rest.partition("=")
    if rest and key.strip().lower() != "layername":
        return None, None              # e.g. |layerid=1: OGR's order is not read here; the Runner reads it
    src = os.path.expanduser(src)
    ext = os.path.splitext(src)[1].lower()
    try:
        if ext == ".gpkg":
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro&immutable=1" % src.replace("?", "%3f"), uri=True)
            try:
                tables = [r[0] for r in con.execute(
                    "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")]
                if layer:
                    table = next((t for t in tables if t.lower() == layer.strip().lower()), "")
                else:
                    table = tables[0] if len(tables) == 1 else ""      # several layers: name one
                if not table:
                    return None, None
                cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % table.replace('"', '""'))]
                col = _id_field(cols, field)
                if not col:
                    return None, None
                vals = {str(r[0]).strip() for r in con.execute('SELECT "%s" FROM "%s"' % (
                    col.replace('"', '""'), table.replace('"', '""'))) if r[0] is not None}
                return col, vals
            finally:
                con.close()
        if ext == ".csv":
            with open(src, newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            col = _id_field(list(rows[0].keys()) if rows else [], field)
            if not col:
                return None, None
            return col, {(r.get(col) or "").strip() for r in rows if (r.get(col) or "").strip()}
    except Exception:        # noqa: BLE001 - an unreadable layer is reported, not fatal here
        return None, None
    return None, None


# The DamIT Runner's own id-field names, in its order (damit_runner/core/data_conventions.py
# FIELD_SYNONYMS["F_ID"]), matched the way it matches them (letters and digits only, any case), so
# the ids checked here are the ids the Runner reads. run_damit passes the field it found as F_ID.
ID_FIELD_SYNONYMS = ("nationalid", "nidid", "nid_id", "damid", "dam_id", "ndid", "structureid", "id",
                     "damnumber", "damno", "swcid", "nidfedid")


def _norm_field(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _id_field(cols, field):
    norm = {}
    for c in cols:
        norm.setdefault(_norm_field(c), c)
    if field:
        for c in cols:
            if c.lower() == str(field).lower():
                return c
        return norm.get(_norm_field(field))
    for s in ID_FIELD_SYNONYMS:
        if _norm_field(s) in norm:
            return norm[_norm_field(s)]
    for s in ID_FIELD_SYNONYMS:                    # a name that contains one (e.g. 'NIDID_2024')
        ns = _norm_field(s)
        if len(ns) >= 5:
            cand = [c for k, c in norm.items() if ns in k]
            if cand:
                return sorted(cand, key=len)[0]
    return None


def damit_preflight(args, ids):
    """v1.6.0: what would make a DamIT batch fail or run the wrong dams, checked in a second.
    Returns a list of problems (empty = go)."""
    bad = []
    dams = os.path.expanduser((args.dams or "").partition("|")[0])
    if not args.dams:
        bad.append("--dams is missing (the dams points layer)")
    elif not os.path.exists(dams):
        bad.append("the dams layer is not there: %s" % dams)
    if not args.out:
        bad.append("--out is missing (the folder the runs are written to)")
    else:
        parent = os.path.dirname(os.path.abspath(os.path.expanduser(args.out))) or "."
        if not os.path.isdir(parent):
            bad.append("the folder above --out does not exist: %s" % parent)
    if not args.dem:
        bad.append("--dem is missing (DEM or VRT covering every dam; DamIT batch needs one)")
    elif not os.path.exists(os.path.expanduser(args.dem)):
        bad.append("the DEM is not there: %s" % os.path.expanduser(args.dem))
    args._id_col = None
    if args.dams and os.path.exists(dams):
        col, have = layer_ids(args.dams, args.id_field)
        args._id_col = col
        if have is None:
            if ids:
                print("  note: cannot read the dam ids of %s here; the Runner will match them" % args.dams)
        else:
            missing = [i for i in ids if i not in have]
            if missing:
                low = {h.lower(): h for h in have}
                bad.append("not in the dams layer (field %s): %s" % (col, ", ".join(
                    i + (" (did you mean %s?)" % low[i.lower()] if i.lower() in low else "") for i in missing)))
    return bad


def run_damit(args):
    """v1.6.0: DamIT Runner breach runs for a dams layer (damit_run:batch), one folder per dam
    under --out. Classification is not part of it: DamIT Hazard has no batch classifier yet."""
    ids = read_ids(args)
    bad = damit_preflight(args, ids)
    qp = QP(args, "damit")
    # --param goes through the same name check as --runner-param here: the DamIT Runner is the one tool
    runner_kv = dict(parse_kv(args.param), **runner_settings(args))
    if not bad and not args.dry_run:
        runner_kv = check_runner_params(qp, RUNNER_ALG["damit"], runner_kv)
    elif runner_kv and args.dry_run:
        print("  note: --dry-run does not check option names or turn option text into numbers")
    print("preflight: %d error(s)" % len(bad))
    for b in bad:
        print("  ERROR  " + b)
    if bad:
        sys.exit(1)
    out = os.path.abspath(os.path.expanduser(args.out))
    p = {"DAMS": os.path.expanduser(args.dams), "DEM": os.path.expanduser(args.dem), "DAMS_FOLDER": out,
         "SKIP_DONE": str(not args.redo).lower(), "CLASSIFY": "false", "THREADS": args.threads,
         "WORKERS": max(1, args.workers)}
    if args.dem_units:
        p["DEM_Z"] = DEM_UNITS[args.dem_units]
    if args.id_field or getattr(args, "_id_col", None):
        p["F_ID"] = getattr(args, "_id_col", None) or args.id_field   # the field the ids were checked in
    if ids:
        p["ONLY_IDS"] = ",".join(ids)
        if args.workers > 1:
            print("  note: with --ids the Runner runs one dam after another (ONLY_IDS uses one worker)")
    # Only a --lisflood you typed is passed on; otherwise the DamIT Runner uses its own setting (and
    # finds ~/dam-suite/bin/lisflood itself when nothing is set), so an engine chosen in QGIS stays chosen.
    lis = os.path.expanduser(args.lisflood or "") if getattr(args, "lisflood_given", True) else ""
    if lis:
        if os.path.isfile(lis) or lis.strip().lower() in DAMIT_ENGINE_WORDS:
            p["LISFLOOD_EXE"] = lis      # a binary, or the DamIT Runner's own engines by name
        else:
            bad.append("--lisflood %s is not a file and not one of the Runner's engines (%s)"
                       % (lis, "builtin, gpu, gpu-sgc"))
            print("  ERROR  " + bad[-1])
            sys.exit(1)
    if args.anuga:
        p["TIER"] = 1
        if qp.anuga_py:
            p["ANUGA_PYTHON"] = qp.anuga_py
    p.update(runner_kv)
    if args.check_only:
        print("OK  checks passed; nothing was run (--check-only)")
        return
    if not args.dry_run and os.path.isfile(qp.qp):
        qp.env.setdefault("NDBREACH_QGIS_PROCESS", qp.qp)     # the batch's worker processes start qgis_process
    logs = os.path.join(out, "_chain_logs")
    log = os.path.join(logs, "damit_batch_%s.log" % _stamp())
    ok, res, err = qp.run(RUNNER_ALG["damit"], p, log, label="DamIT batch")
    if args.dry_run:
        return
    counts = str(res.get("COUNTS") or "")
    m = re.search(r"(\d+)\s+failed", counts)
    if ok and m and int(m.group(1)) > 0:
        ok = False                     # qgis_process exits 0 when dams fail; the counts say so
    if ok and not counts:
        ok, err = False, err or "the Runner reported no counts; see the log"
    done = sum(int(x) for x in re.findall(r"(\d+)\s+(?:run|failed|skipped|with no breach|flagged)\b", counts))
    want = len(set(ids))
    if ok and ids and done < want:
        # ONLY_IDS that match no dam are skipped by the Runner without a word ("0 run, 0 failed ...")
        where = p.get("F_ID") or "(its own choice)"
        ok, err = False, ("none of --ids %s was found by the Runner in field %s" % (",".join(ids), where)
                          if done == 0 else "the Runner found only %d of the %d --ids (%s) in field %s; see %s"
                          % (done, want, ",".join(ids), where, "the summary"))
        err, counts = "%s (%s)" % (err, counts), ""
    print("%s  %s" % ("OK" if ok else "FAILED", counts or err))
    print("log: %s" % log)
    if res.get("SUMMARY"):
        print("summary: %s" % res["SUMMARY"])
    if not ok and getattr(args, "triage", False):
        triage_failure("DamIT batch", err or counts, log, os.path.dirname(log))
    sys.exit(0 if ok else 1)


def default_lisflood():
    """The suite's LISFLOOD-FP: install-all puts it in ~/dam-suite/bin, the older Mac installer in
    ~/nd-dam-suite/bin. The newer one first, so an old build left behind is not the one used."""
    for p in ("~/dam-suite/bin/lisflood", "~/nd-dam-suite/bin/lisflood"):
        if os.path.isfile(os.path.expanduser(p)):
            return p
    return "~/dam-suite/bin/lisflood"


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _wrapper(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n# written by dam_chain.py crest; safe to delete (it is rewritten)\n")
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)


def crest_env(args, set_name):
    """Wrapper scripts + environment that point the Crest desk at one plugin set.
    Crest calls `qgis_process` (QGIS_PROCESS) and the Runner's ndbreach_cli.py (CREST_NDBREACH_CLI,
    run with CREST_PYTHON); both wrappers run inside the conda env with that set's batch profile."""
    spec = SETS[set_name]
    qp = QP(args, set_name)
    base = qp.base
    real = os.path.realpath(os.path.join(base, "profiles", "default"))
    if not os.path.isdir(real):
        sys.exit("No batch profile for '%s' at %s: run `dam_chain.py setup` first." % (set_name, base))
    cli = os.path.join(real, "python", "plugins", spec["runner"], "scripts", "ndbreach_cli.py")
    if not os.path.isfile(cli):
        sys.exit("%s not found: is the %s set installed in profile '%s'?" % (cli, set_name, spec["profile"]))
    exports = ["export QGIS_CUSTOM_CONFIG_PATH=%s" % _q(base), "export QT_QPA_PLATFORM=offscreen",
               "export NDBREACH_ANUGA_MESHER=gmsh", "export OMP_NUM_THREADS=%d" % args.threads,
               "unset PYTHONPATH"]
    if qp.env.get("NDBREACH_LISFLOOD"):
        exports.append("export NDBREACH_LISFLOOD=%s" % _q(qp.env["NDBREACH_LISFLOOD"]))
    bindir = os.path.join(base, "bin")
    run = "exec %s run --no-capture-output -n %s" % (_q(qp.conda), _q(qp.envname))
    _wrapper(os.path.join(bindir, "qgis_process"), exports + ['%s %s "$@"' % (run, _q(qp.qp))])
    _wrapper(os.path.join(bindir, "python3"), exports + ['%s python "$@"' % run])
    work = os.path.expanduser(args.work or os.path.join("~/CrestDams", set_name))
    os.makedirs(work, exist_ok=True)
    env = {"QGIS_PROCESS": os.path.join(bindir, "qgis_process"),
           "CREST_PYTHON": os.path.join(bindir, "python3"),
           "CREST_NDBREACH_CLI": cli,
           "CREST_WORK": work,
           "CREST_WORK_ROOTS": os.pathsep.join([os.path.expanduser("~/CrestDams"), work])}
    if args.data_folder:
        env["NDSUITE_DATA"] = os.path.expanduser(args.data_folder)
    return env


def cmd_crest(args):
    env = crest_env(args, args.set)
    for k in sorted(env):
        print("export %s=%s" % (k, _q(env[k])))
    if args.print_env:
        return
    crest = os.path.expanduser(args.crest_dir)
    run_py = os.path.join(crest, "run.py")
    if not os.path.isfile(run_py):
        sys.exit("Crest desk not found at %s (run.py). Install it with install_all.zsh or pass --crest-dir." % crest)
    py = args.crest_python
    if not py:
        try:
            py = os.path.join(env_prefix(conda_exe(), "ndcrest"), "bin", "python")
        except SystemExit:
            py = sys.executable              # no ndcrest env: the desk opens in the browser instead
    full = dict(os.environ)
    full.pop("PYTHONPATH", None)
    full.update(env)
    print("Crest desk -> %s plugins (profile '%s'), work folder %s. Leave this Terminal open."
          % ("ND" if args.set == "nd" else "DamSafety", SETS[args.set]["profile"], env["CREST_WORK"]))
    if args.dry_run:
        print("  DRY  %s %s" % (_q(py), _q(run_py)))
        return
    sys.exit(subprocess.call([py, run_py], cwd=crest, env=full))


def vor_passthrough(argv):
    """`damchain vor ...` (or the older `damchain research ...`) -> the vor tool, with its own Python (ndvor env)."""
    tool = os.path.expanduser(os.environ.get("VOR_TOOL", "~/local-ai/vor/vor.py"))
    py = os.path.expanduser(os.environ.get("VOR_PY", "") or "~/local-ai/vor/python")
    if not os.path.isfile(tool):
        sys.exit("vor is not installed. Run: zsh setup-vor.zsh (from the vor folder)")
    if not os.path.exists(py):
        py = sys.executable
    os.execv(py, [py, tool] + argv)


def audit_passthrough(argv):
    """`damchain audit ...` -> repo_audit.py next to this file (or in ~/local-ai)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for tool in (os.path.join(here, "repo_audit.py"), os.path.expanduser("~/local-ai/repo_audit.py")):
        if os.path.isfile(tool):
            os.execv(sys.executable, [sys.executable, tool] + argv)
    sys.exit("repo_audit.py is not installed next to dam_chain.py; rerun setup-local-heim.sh")


def main():
    # v1.5.3: the literature assistant is `vor`; `research` stays as an alias so anything
    # written before the rename keeps working.
    if len(sys.argv) > 1 and sys.argv[1] in ("vor", "research"):
        vor_passthrough(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "audit":
        audit_passthrough(sys.argv[2:])
    ap = argparse.ArgumentParser(description="Run the ND, DamSafety and DamIT dam plugins headless. "
                                             "`vor ...` runs the literature assistant (`research` is an alias); "
                                             "`audit ...` the local repo audit (audit --help).")
    ap.add_argument("--env", default="ndqgis", help="conda env with QGIS (default ndqgis)")
    ap.add_argument("--qgis-process", default="", help="path to qgis_process (default: found in the env)")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--lisflood", default=None,
                    help="LISFLOOD-FP binary (nd/dwr sets: default ~/dam-suite/bin/lisflood; damit set: "
                         "passed only when given, and may be builtin, gpu or gpu-sgc)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    ap.add_argument("--quiet", action="store_true", help="don't stream each step's progress lines to the terminal (the full log is still written)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup")
    s.add_argument("--nd-profile", default="")
    s.add_argument("--dwr-profile", default="")
    s.add_argument("--damit-profile", default="")

    s = sub.add_parser("plugins")
    s.add_argument("--set", choices=SETS, required=True)
    s.add_argument("--selftest", action="store_true")
    s.add_argument("--log-dir", default="~/local-ai/reports")

    s = sub.add_parser("open")
    s.add_argument("--set", choices=SETS, required=True)
    s.add_argument("--profile", default="")

    s = sub.add_parser("pack", help="build/refresh the offline data pack into the data folder (opens the Updater)")
    s.add_argument("--set", choices=SETS, default="nd")
    s.add_argument("--data-folder", default="", help="where the pack is built (default ~/ND_Suite_Data)")
    s.add_argument("--profile", default="")
    s.add_argument("--print-only", action="store_true", help="print the steps, do not open QGIS")

    s = sub.add_parser("crest", help="open the Crest desk wired to one plugin set")
    s.add_argument("--set", choices=SETS, required=True)
    s.add_argument("--work", default="", help="Crest work folder (default ~/CrestDams/<set>)")
    s.add_argument("--data-folder", default="", help="ND offline pack / suite data folder (NDSUITE_DATA)")
    s.add_argument("--crest-dir", default=CREST_DIR, help="the crest-desktop folder (default ~/local-ai/crest-desktop)")
    s.add_argument("--crest-python", default="", help="Python for the desk (default: the ndcrest env)")
    s.add_argument("--print-env", action="store_true", help="write the wrappers, print the exports, do not open")

    s = sub.add_parser("seed")
    s.add_argument("--dams-folder", required=True)
    s.add_argument("--csv", required=True)

    s = sub.add_parser("run")
    s.add_argument("--set", choices=SETS, required=True)
    s.add_argument("--ids", default="", help="comma separated dam ids")
    s.add_argument("--ids-csv", default="", help="CSV with a dam_id column")
    s.add_argument("--no-screen", action="store_true")
    s.add_argument("--redo", action="store_true", help="run dams again that finished before")
    s.add_argument("--stop-on-error", action="store_true")
    s.add_argument("--param", action="append", help="extra KEY=VALUE for the chain algorithm")
    s.add_argument("--triage", action="store_true",
                   help="on a failed step, send the log tail to the local Ollama model and write "
                        "an advisory TRIAGE.txt next to the run log")
    s.add_argument("--heim-model", default="", help="Ollama model for --triage (default: $HEIM_MODEL or 'heim')")
    g = s.add_argument_group("nd set (ndhazard:suitechain per dam folder)")
    g.add_argument("--dams-folder", default="", help="folder of <dam_id>/dam.json folders")
    g.add_argument("--data-folder", default="", help="suite data folder / offline pack for Get data")
    g.add_argument("--no-getdata", action="store_true")
    g.add_argument("--hi-res", action="store_true",
                   help="download a 1 m 3DEP DEM (DEM_CELL_M=1) unless --getdata-param sets it; "
                        "pair with DEM_MI to bound the download")
    g.add_argument("--no-breach", action="store_true")
    g.add_argument("--no-classify", action="store_true")
    g.add_argument("--getdata-param", action="append",
                   help="KEY=VALUE for ndhazard:getdamdata, e.g. DEM_CELL_M=5, DEM_MI=10, OVERWRITE=true")
    g.add_argument("--screen-param", action="append", help="KEY=VALUE for nddam:runchain")
    g.add_argument("--breach-param", action="append", help="KEY=VALUE for ndbreach:rundam")
    g.add_argument("--classify-param", action="append", help="KEY=VALUE for ndhazard:classify")
    g.add_argument("--timeout-min", type=int, default=480)
    g = s.add_argument_group("dwr and damit sets (ndbreach:chainbatch / damit_run:batch)")
    g.add_argument("--dams", default="", help="dams points layer")
    g.add_argument("--id-field", default="", help="dam id field of the layer")
    g.add_argument("--out", default="", help="output folder, one folder per dam")
    g.add_argument("--dem", default="", help="DEM or VRT covering every dam")
    g.add_argument("--cell", type=float, default=None, help="model cell size, metres (the Runner's CELL)")
    g.add_argument("--solver", choices=SOLVER_WORDS, default="", help="LISFLOOD-FP solver (the Runner's SOLVER)")
    g.add_argument("--manning", type=float, default=None, help="Manning's n (the Runner's MANNING)")
    g.add_argument("--workers", type=int, default=1, help="damit: dams run side by side (WORKERS)")
    g.add_argument("--screen-work", default="", help="Screening work folder (statewide run + data package)")
    g.add_argument("--hec", choices=DWR_HEC, default="skip",
                   help="HEC-RAS 2D stage (default skip: it cannot run on a Mac)")
    g.add_argument("--anuga", action="store_true", help="LISFLOOD-FP then ANUGA")
    g.add_argument("--stop-after", choices=DWR_STOP, default="end")
    g.add_argument("--settings-file", default="")
    g.add_argument("--overrides-csv", default="")
    g.add_argument("--check-only", action="store_true", help="preflight only (damit: the checks, nothing run)")
    g.add_argument("--dem-units", choices=DEM_UNITS, default="",
                   help="the Runner's DEM elevation units (needed when the DEM records none, e.g. a VRT)")
    g.add_argument("--runner-param", action="append",
                   help="KEY=VALUE for the Runner (ndbreach:batch / damit_run:batch); names are checked")

    args = ap.parse_args()
    # v1.6.0: remember whether --lisflood was typed (the DamIT set then passes it on; otherwise the
    # DamIT Runner's own engine setting is used). The ND and DamSafety sets keep the suite default.
    args.lisflood_given = args.lisflood is not None
    if args.lisflood is None:
        args.lisflood = default_lisflood()
    if getattr(args, "heim_model", ""):
        globals()["HEIM_MODEL"] = args.heim_model
    if args.cmd == "setup":
        cmd_setup(args)
    elif args.cmd == "plugins":
        cmd_plugins(args)
    elif args.cmd == "open":
        cmd_open(args)
    elif args.cmd == "pack":
        cmd_pack(args)
    elif args.cmd == "seed":
        cmd_seed(args)
    elif args.cmd == "crest":
        cmd_crest(args)
    elif args.set == "nd":
        if not args.dams_folder:
            sys.exit("--set nd needs --dams-folder")
        run_nd(args)
    elif args.set == "damit":
        run_damit(args)
    else:
        run_dwr(args)


if __name__ == "__main__":
    main()
