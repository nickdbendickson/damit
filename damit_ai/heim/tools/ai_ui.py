#!/usr/bin/env python3
"""ai_ui.py 1.2.0 - one local page for both assistants (the `ai` command, and the Local AI app).

    ai                 open the page in your browser (http://127.0.0.1:<port>/, this computer only)
    ai --port 8765     a fixed port
    ai --no-browser    print the address instead of opening it
    ai --app           the Local AI icon: the page in its own window, one copy running (1.2.0)

What it is: a page served by this script on 127.0.0.1 only, so nothing leaves the machine and
nothing on the network can reach it. It runs the same commands you would type (`heim`,
`vor ask`, `heim runs ...`, `ai-doctor`) and shows their output as it is written, so it never
answers differently from the terminal. On the page:

  Ask      one box. "Pick for me": a question that names a dam you have read in and asks for a
           result goes to the run results; a question about this software (a file, a setting, a
           plugin, an error, an id like REFINE_NEAR) goes to Heim; anything else goes to Vor, the
           publications (Heim when Vor is not installed). 1.1.0: anything else went to Heim, so a
           question about a standard was answered from the code's notes. The page says which one
           answered. Vor's citations open the PDF at the cited page.
  Runs     the run list, a dam's numbers, compare (engine against engine), depth at a place, and
           the breach hydrograph drawn as a chart.
  Add      a file or folder by its path: a run folder goes to the run results, a PDF to Vor's
           library or Heim's index.
  Health   ai-doctor, with one line per assistant.

  Library  (1.2.0) what Vor has indexed, "Get more documents" (the download catalog, a group at a time,
           then indexed), and files dropped on the page copied into the library and indexed.
  Check answers  (1.2.0) ai-score at a press, and the score history.
  Health & update  ai-doctor; where a line says what to run (vor ingest, vor tables, vor ocr,
           heim-index ..., heim-start) a button runs it. Start Ollama. Install an update: choose the
           downloaded dam-local-ai zip, it is checked, unpacked under ~/local-ai/updates and its own
           installer runs (library, indexes, models and results are kept).

1.2.0, the Local AI app: `ai --app` is what the Local AI icon runs (the installers put it in
~/Applications on a Mac, the Start menu on Windows, the applications menu on Linux). It opens the page
in a window of its own (Chrome, Edge or Brave in app mode; the default browser when none is there),
starting the page's server in the background first when it is not running. One copy runs; it stops by
itself ten minutes after its last window closed, never while a job runs. Long commands (indexing,
downloads, OCR, the answer test, an update) run as jobs: their output goes to a log under
~/local-ai/logs/ui-jobs that the page reads as it grows, so closing the window loses nothing. Nothing
needs sudo or admin rights, and nothing beyond Python's standard library.

Safety: the server binds 127.0.0.1, answers only requests whose Host is that address, and every
request must carry the random key printed at start (other web pages in your browser cannot run
commands through it). Commands are fixed argument lists, never a shell. A PDF is served only from
Vor's library or Heim's index folders. The app never puts the key on a command line (where other
users of this computer could list it): it writes a small page only you can read (~/local-ai/
ai-ui-open.html) that hands the key to the window in the address's #fragment, which is never sent
over the network, and the page keeps it for that window only. Before the app trusts a running server
with the key, the server must prove it holds the key (an HMAC of a fresh random number). No cookie.
Stdlib only. Ctrl+C stops `ai`.
"""
import argparse
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess  # nosec B404 - runs the assistants' own tools with fixed argument lists
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
RUN_SECONDS = 3600


def tool(name):
    return os.path.join(HERE, name)


def vor_command():
    """[python, vor.py], or None when Vor is not installed (the same rule as ai-doctor)."""
    tool_path = os.environ.get("VOR_TOOL") or os.path.join(HOME, "local-ai", "vor", "vor.py")
    if not os.path.isfile(tool_path):
        return None
    d = os.path.dirname(tool_path)
    py = os.environ.get("VOR_PYTHON") or next(
        (p for p in (os.path.join(d, "python"), os.path.join(d, "python.exe")) if os.path.isfile(p)), sys.executable)
    return [py, tool_path]


def vor_home():
    """The folder Vor reads, by vor.py's rule: VOR_HOME, else the folder that holds the index
    (~/Vor, or the pre-rename ~/DamResearch), else ~/Vor."""
    if os.environ.get("VOR_HOME"):
        return os.path.expanduser(os.environ["VOR_HOME"])
    new, old = os.path.join(HOME, "Vor"), os.path.join(HOME, "DamResearch")
    legacy = os.path.expanduser(os.environ.get("DAMRESEARCH_HOME") or old)
    for d in (new, legacy, old):
        if any(os.path.isfile(os.path.join(d, f)) for f in ("vor.db", "research.db")):
            return d
    return old if (not os.path.isdir(new) and os.path.isdir(old)) else new


def runs_db():
    return os.path.expanduser(os.environ.get("HEIM_RUNS_DB", os.path.join(HOME, "local-ai", "runs.db")))


def runs_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_results_for_ui", tool("run_results.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A question about this software (Heim's side), not about the literature: file names, identifiers,
# and the suite's own words. Breach / hydraulics words are not here: the publications hold those.
CODE_WORDS = re.compile(
    r"\.(?:py|json|tif|tiff|gpkg|par|csv|log|qgz|ps1|sh|zsh|txt|md)\b|"            # a file name
    r"\b[A-Za-z]+_[A-Za-z0-9_]+\b|"                                                  # REFINE_NEAR, run_dam
    r"\b[a-z]+[A-Z][A-Za-z]+\b|"                                                     # camelCase
    r"\b[a-z_]+:[a-z_]+\b|"                                                          # damit_run:batch
    r"\b(?i:module|script|plugins?|qgis|algorithm|damchain|damit|damsafety|runner|screener|"
    r"heim|vor|boann\w*|watcher|traceback|exception|crash\w*|bugs?|installer|ollama|conda|"
    r"gpu|metal|cli|command|terminal|python)\b")
# Words left out on purpose, because the publications use them too: class (hazard class), function,
# code (building code), parameters (breach parameters), profile (water surface profile), log
# (log-Pearson), error (standard error), setting, screening, installation, test, version, crest (the
# dam crest), finder, switch, flag.


def route(question, target="auto"):
    """(who, argv) for a question. target: auto | heim | vor | runs."""
    py = sys.executable
    if target == "vor":
        vc = vor_command()
        return ("Vor", vc + ["ask", question]) if vc else ("Vor", None)
    if target == "runs":
        return "Run results", [py, tool("run_results.py"), "ask", question]
    if target == "auto":
        try:
            rr = runs_module()
            low = question.lower()
            import importlib.util
            spec = importlib.util.spec_from_file_location("rag_query_for_ui", tool("rag_query.py"))
            rq = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rq)
            if any(w in low for w in rq.RUN_WORDS) and rr.dams_named_in(question, runs_db()):
                return "Run results", [py, tool("run_results.py"), "ask", question]
        except Exception:  # noqa: BLE001 - no run database or an older install: go on
            pass
        # 1.1.0: about this software -> Heim; anything else -> the publications (Vor), when installed
        vc = vor_command()
        if vc and not CODE_WORDS.search(question):
            return "Vor", vc + ["ask", question]
    return "Heim", [py, tool("rag_query.py"), question]


def action_argv(action, args):
    """The argv for a Runs / Add / Health action, or None for an unknown one."""
    py, rr = sys.executable, tool("run_results.py")
    dam = (args.get("dam") or "").strip()
    if action == "list":
        return [py, rr, "list"]
    if action in ("show", "compare", "hydrograph") and dam:
        return [py, rr, action, dam]
    if action == "at" and dam and (args.get("place") or "").strip():
        return [py, rr, "at", dam, args["place"].strip()]
    if action == "doctor":
        return [py, tool("ai_doctor.py")]
    if action == "add":
        path = os.path.expanduser((args.get("path") or "").strip())
        if not path or not os.path.exists(path):
            return None
        if args.get("to") == "vor":
            vc = vor_command()
            return vc + ["add", path] if vc else None
        return [py, tool("rag_query.py"), "add", path]      # a run folder goes to the run results
    return None


def allowed_pdf(path):
    """A PDF may be served only from Vor's library or a folder Heim has indexed."""
    real = os.path.realpath(path)
    if not real.lower().endswith(".pdf") or not os.path.isfile(real):
        return False
    roots = [os.path.join(vor_home(), "library"), os.path.join(HOME, "local-ai")]
    try:
        db = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(os.path.join(HOME, "local-ai", "knowledge.db")),
                             uri=True)
        try:
            for (r,) in db.execute("SELECT roots FROM roots"):
                roots += json.loads(r)
        finally:
            db.close()
    except (sqlite3.Error, ValueError):
        pass
    return any(real == os.path.realpath(r) or real.startswith(os.path.realpath(r) + os.sep) for r in roots)


def hydrograph_points(dam):
    """[{label, points: [[t, q], ...]}] for a dam's breach hydrographs (current runs first)."""
    rr = runs_module()
    if not os.path.exists(runs_db()):
        return []
    db = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(runs_db()), uri=True)
    try:
        out = []
        for r in rr.match_runs(db, dam)[:6]:
            pts = db.execute("SELECT time_hr, flow_cfs FROM hydrograph WHERE run_id=? AND series='breach' "
                             "ORDER BY time_hr", (r[0],)).fetchall()
            if pts:
                out.append({"label": "[%d] %s %s" % (r[0], r[4] or "", (r[5] or "")[:10]), "points": pts})
        return out
    finally:
        db.close()


def newest_report(since):
    """The newest Vor report written after `since`, or None."""
    d = os.path.join(vor_home(), "reports")
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md")]
    except OSError:
        return None
    files = [f for f in files if os.path.getmtime(f) >= since - 1]
    return max(files, key=os.path.getmtime) if files else None


# ---------------------------------------------------------------------------- 1.2.0: the Local AI app
# Everything below runs as the user, writes only under ~/local-ai and Vor's folder, and needs no
# package beyond the standard library (no sudo, no pip).

APP_PORT = int(os.environ.get("AI_UI_PORT") or 8767)      # the app's usual port; any free one when taken
IDLE_SECONDS = float(os.environ.get("AI_UI_IDLE_SECONDS") or 600)   # the app stops this long after its
#                                 last window closed (never while a job runs)
JOB_SECONDS = 12 * 3600         # a job (index, download, update) is stopped after this long
LOCK_SECONDS = 30               # a start lock older than this was left by a copy that died
UPLOAD_MAX = {"library": 500 << 20, "update": 200 << 20}
LIBRARY_EXT = (".pdf", ".md", ".txt")
SKIP_DIRS = {"__MACOSX", ".git", "_ocr_tmp", "node_modules"}      # as vor.py's walk


def local_ai(*parts):
    """~/local-ai, or the sandbox's (LOCAL_AI_HOME, written by install-local-ai-linux.sh --prefix)."""
    return os.path.join(os.path.expanduser(os.environ.get("LOCAL_AI_HOME") or os.path.join(HOME, "local-ai")), *parts)


def state_file():
    return local_ai("ai-ui.json")


def jobs_dir():
    return local_ai("logs", "ui-jobs")


def updates_dir():
    return local_ai("updates")


def popen_kw(detach=False):
    """No console window for a child on Windows; its own process group, so Stop reaches what it starts."""
    if os.name == "nt":
        flags = 0x00000200                                   # CREATE_NEW_PROCESS_GROUP
        flags |= 0x00000008 if detach else 0x08000000        # DETACHED_PROCESS / CREATE_NO_WINDOW
        return {"creationflags": flags}
    return {"start_new_session": True}


def spawn(argv, **kw):
    """Start a program that outlives this request (Ollama, the app's server, a browser window). It is
    never waited for, so its Popen is marked finished: Python would otherwise warn when it is collected."""
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True, **kw)  # nosec B603 - callers pass fixed lists
    p.returncode = 0
    return p


def vor_db():
    """The index vor.py reads: VOR_DB, else vor.db, else the pre-rename research.db beside it."""
    if os.environ.get("VOR_DB"):
        return os.environ["VOR_DB"]
    new, old = os.path.join(vor_home(), "vor.db"), os.path.join(vor_home(), "research.db")
    return old if (not os.path.exists(new) and os.path.exists(old)) else new


def tool_version(path):
    """The VERSION a script states near its top, or ''."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(20000)
    except OSError:
        return ""
    m = re.search(r'^VERSION\s*=\s*["\']([\d.]+)["\']', head, re.M)
    return m.group(1) if m else ""


def library_files():
    """Document files in Vor's library, by vor.py's own rule (what `vor ingest` would read)."""
    lib = os.path.join(vor_home(), "library")
    out = []
    for root, dirs, files in os.walk(lib):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        out += [os.path.join(root, f) for f in sorted(files)
                if not f.startswith(".") and f.lower().endswith(LIBRARY_EXT)]
    return out


def index_counts():
    """(documents, passages) in Vor's index, or None when there is none (or it cannot be read)."""
    p = vor_db()
    if not os.path.isfile(p):
        return None
    try:
        db = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(p), uri=True)
        try:
            return (db.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        finally:
            db.close()
    except sqlite3.Error:
        return None


def library_docs(limit=3000):
    """The indexed documents, for the Library tab: title, year, number, pages, file."""
    p = vor_db()
    if not os.path.isfile(p):
        return []
    try:
        db = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(p), uri=True)
        try:
            rows = db.execute("SELECT title, authors, year, org, number, pages, path FROM docs "
                              "ORDER BY lower(coalesce(nullif(title, ''), path)) LIMIT ?", (limit,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []
    return [{"title": r[0] or os.path.basename(r[6] or ""), "authors": r[1] or "", "year": r[2] or "",
             "org": r[3] or "", "number": r[4] or "", "pages": r[5] or 0, "path": r[6] or "",
             "pdf": bool(r[6]) and r[6].lower().endswith(".pdf") and os.path.isfile(r[6])} for r in rows]


def ollama_base():
    url = os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    if not url.startswith("http"):
        url = "http://" + url
    return url.rstrip("/")


def ollama_version():
    """Ollama's version when its server answers, else None."""
    try:
        with urllib.request.urlopen(ollama_base() + "/api/version", timeout=2) as r:
            return json.loads(r.read().decode("utf-8") or "{}").get("version") or "?"
    except (OSError, ValueError):
        return None


def ollama_binary():
    """(argv to start Ollama's server, or to open its app) on this computer, or None."""
    mac_bundled = local_ai("bin", "Ollama.app", "Contents", "Resources", "ollama")
    if sys.platform == "darwin" and os.path.isfile(mac_bundled):
        return [mac_bundled, "serve"]
    if os.name == "nt":
        for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama"), local_ai("ollama")):
            if os.path.isfile(os.path.join(d, "ollama.exe")):
                return [os.path.join(d, "ollama.exe"), "serve"]
    for p in (local_ai("ollama", "bin", "ollama"), local_ai("bin", "ollama"),
              os.path.join(HOME, ".local", "bin", "ollama")):
        if os.name != "nt" and os.path.isfile(p) and os.access(p, os.X_OK):
            return [p, "serve"]
    found = shutil.which("ollama")
    if found:
        return [found, "serve"]
    if sys.platform == "darwin" and os.path.isdir("/Applications/Ollama.app"):
        return ["/usr/bin/open", "-a", "Ollama"]
    return None


def start_ollama(wait=30):
    """Start Ollama's server in the background (as heim-start does) and wait until it answers."""
    if ollama_version():
        return {"ok": True, "text": "Ollama is already running."}
    argv = ollama_binary()
    if not argv:
        return {"ok": False, "text": "Ollama was not found on this computer. Run the installer again (Install update)."}
    env = dict(os.environ, OLLAMA_FLASH_ATTENTION=os.environ.get("OLLAMA_FLASH_ATTENTION", "1"),
               OLLAMA_KV_CACHE_TYPE=os.environ.get("OLLAMA_KV_CACHE_TYPE", "q8_0"))
    env.setdefault("OLLAMA_MODELS", local_ai("models"))
    os.makedirs(local_ai("logs"), exist_ok=True)
    with open(local_ai("logs", "ollama-serve.log"), "ab") as log:
        spawn(argv, stdout=log, stderr=subprocess.STDOUT, env=env, **popen_kw(detach=True))
    end = time.time() + wait
    while time.time() < end:
        v = ollama_version()
        if v:
            return {"ok": True, "text": "Ollama %s is running." % v}
        time.sleep(0.5)
    return {"ok": False, "text": "Ollama did not answer within %d s. Its log: %s"
            % (wait, local_ai("logs", "ollama-serve.log"))}


def status():
    """What the banner and the Health tab show: is everything able to answer, and what to press if not."""
    vc = vor_command()
    out = {"version": VERSION, "ollama": ollama_version(), "problems": [],
           "vor": None, "heim": {"tools": tool_version(tool("rag_query.py")) or "installed"}}
    if not out["ollama"]:
        out["problems"].append({"level": "PROBLEM", "fix": "start-ollama", "label": "Start Ollama",
                                "text": "Ollama is not running, so neither assistant can answer."})
    if vc:
        files = library_files()
        counts = index_counts()
        docs, passages = counts or (0, 0)
        out["vor"] = {"version": tool_version(vc[1]), "home": vor_home(), "files": len(files), "documents": docs,
                      "passages": passages, "index": vor_db() if counts is not None else ""}
        if files and not passages:
            out["problems"].append({"level": "PROBLEM", "fix": "vor-ingest", "label": "Index the library",
                                    "text": "Vor's index is empty: the %d file(s) in its library have not been indexed, "
                                            "so every question gets no passage." % len(files)})
        elif not files:
            out["problems"].append({"level": "WATCH", "fix": "goto-library", "label": "Get documents",
                                    "text": "Vor's library is empty: it has nothing to quote yet."})
    return out


# -------------------------------------------------------------------------------- catalog (Library tab)

def vor_tool_file(name):
    """A file that ships beside vor.py (fetch_asdso.py, reference_sources.json), or None."""
    vc = vor_command()
    cands = [os.path.join(os.path.dirname(vc[1]), name)] if vc else []
    cands.append(os.path.join(HERE, "..", "..", "vor", name))            # the repository layout
    return next((os.path.abspath(c) for c in cands if os.path.isfile(c)), None)


def catalog_groups():
    """[{id, about, total, have, manual}] for the download catalog, counting what is already here."""
    path = vor_tool_file("reference_sources.json")
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            cat = json.load(fh)
    except (OSError, ValueError):
        return []
    about = {}
    for m in re.finditer(r"Group '(\w+)' = (.*?)(?= Group '\w+' =|$)", cat.get("about", ""), re.S):
        about[m.group(1)] = re.split(r"\.\s", m.group(2).strip() + " ", maxsplit=1)[0].strip().rstrip(".")   # its first sentence
    out_dir = os.path.join(vor_home(), "library", "references")
    try:
        with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh).get("files", {})
    except (OSError, ValueError):
        man = {}
    groups = []
    for g, entries in (cat.get("groups") or {}).items():
        live = [e for e in entries if not e.get("skip")]
        manual = [e for e in live if e.get("kind") == "manual"]
        auto = [e for e in live if e.get("kind") != "manual"]
        have = 0
        for e in auto:
            if e.get("kind") == "index":
                d = os.path.join(out_dir, g, e["id"])
                have += bool(os.path.isdir(d) and any(f.lower().endswith(LIBRARY_EXT) for f in os.listdir(d)))
                continue
            f = os.path.join(out_dir, g, e["id"] + (".md" if e.get("kind") == "html" else ".pdf"))
            have += bool(os.path.isfile(f) and man.get(e["id"], {}).get("status") == "ok")
        groups.append({"id": g, "about": about.get(g, ""), "total": len(auto), "have": have, "manual": len(manual)})
    return groups


# -------------------------------------------------------------------------------------------- jobs

class Job(object):
    """A long command (index, download, OCR, test, update) that runs on its own, apart from the page:
    its output goes to a log file the page reads as it grows, so closing or reloading the window loses
    nothing and the job carries on. One at a time: two would write to the same index."""

    def __init__(self, title, steps):
        self.id = secrets.token_hex(6)
        self.title, self.steps = title, steps                # steps: [(label, argv, keep_going)]
        self.status, self.code, self.stopped = "running", None, False
        self.started, self.ended, self.proc = time.time(), None, None
        os.makedirs(jobs_dir(), exist_ok=True)
        self.log = os.path.join(jobs_dir(), "%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), self.id))

    def summary(self):
        return {"id": self.id, "title": self.title, "status": self.status, "code": self.code,
                "started": self.started, "ended": self.ended, "log": self.log}

    def run(self):
        code = 0
        try:
            code = self._run_steps()
        except Exception as e:  # noqa: BLE001 - a job always ends with a status the page can show
            code = code or 1
            try:
                with open(self.log, "ab") as out:
                    out.write(("\n[the job stopped: %s]\n" % e).encode("utf-8", "replace"))
            except OSError:
                pass
        finally:
            self.code, self.ended = code, time.time()
            self.status = "stopped" if self.stopped else ("failed" if code else "done")
            prune_job_logs()

    def _run_steps(self):
        base = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1", AI_UI_JOB="1")
        code = 0
        with open(self.log, "ab", buffering=0) as out:
            out.write(("%s\n" % self.title).encode("utf-8"))
            for step in self.steps:
                label, argv, keep_going = step[:3]
                env = dict(base, **(step[3] if len(step) > 3 else {}))
                if self.stopped:
                    break
                out.write(("\n== %s\n" % label).encode("utf-8"))
                try:
                    self.proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                 env=env, **popen_kw())  # nosec B603 - fixed argument lists
                except OSError as e:
                    out.write(("could not run %s: %s\n" % (argv[0], e)).encode("utf-8"))
                    code = 127
                    break
                timer = threading.Timer(JOB_SECONDS, self.stop)
                timer.start()
                try:
                    rc = self.proc.wait()
                finally:
                    timer.cancel()
                if rc:
                    out.write(("[%s stopped with exit code %d]\n" % (label, rc)).encode("utf-8"))
                    code = code or rc
                    if not keep_going:
                        break
        return code

    def stop(self):
        self.stopped = True
        p = self.proc
        if p and p.poll() is None:
            try:
                if os.name == "nt":
                    # the whole tree: an installer or a download runs programs of its own
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=0x08000000, check=False)  # nosec B603 B607
                else:
                    os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def read(self, start):
        """(text, next offset) of the log from byte `start`, never cutting a character in two."""
        try:
            with open(self.log, "rb") as fh:
                fh.seek(max(0, start))
                data = fh.read(1 << 18)
        except OSError:
            return "", start
        cut = len(data)
        while cut > 0:
            try:
                text = data[:cut].decode("utf-8")
                break
            except UnicodeDecodeError as e:
                if e.start >= cut - 4:
                    cut = e.start
                else:
                    text = data[:cut].decode("utf-8", "replace")
                    break
        else:
            text = ""
        return text, start + cut


def prune_job_logs(keep=30):
    try:
        logs = sorted(f for f in os.listdir(jobs_dir()) if f.endswith(".log"))
    except OSError:
        return
    for f in logs[:-keep]:
        try:
            os.remove(os.path.join(jobs_dir(), f))
        except OSError:
            pass


JOBS = {}
JOBS_LOCK = threading.Lock()


def running_job():
    with JOBS_LOCK:
        return next((j for j in JOBS.values() if j.status == "running"), None)


def latest_job():
    with JOBS_LOCK:
        return max(JOBS.values(), key=lambda j: j.started) if JOBS else None


def start_job(title, steps):
    """The new job, or (None, the running one) when a job is already running."""
    with JOBS_LOCK:
        busy = next((j for j in JOBS.values() if j.status == "running"), None)
        if busy:
            return None, busy
        job = Job(title, steps)
        JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return job, None


NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def installer_argv(folder):
    """The installer of an unpacked update, for this computer, or None."""
    root = os.path.join(folder, "damit_ai")
    if sys.platform == "darwin":
        p = os.path.join(root, "Install-Mac.command")
        return ["/bin/zsh", p] if os.path.isfile(p) else None
    if os.name == "nt":
        p = os.path.join(root, "install-local-ai-windows.ps1")
        # -NonInteractive is PowerShell's own switch: after -File it would go to the script instead
        return (["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", p]
                if os.path.isfile(p) else None)
    p = os.path.join(root, "install-local-ai-linux.sh")
    return ["bash", p] if os.path.isfile(p) else None


def conda_env(exe=None):
    """CONDA_EXE and PATH for an update's installer. The icon starts the app without a terminal's setup,
    so `conda` is often not on PATH; the installers look for CONDA_EXE first. Found from this Python:
    <conda>/envs/<name>/bin/python (Windows <conda>\\envs\\<name>\\python.exe), or <conda>/bin/python."""
    exe = os.path.abspath(exe or sys.executable)
    d = os.path.dirname(exe)
    env_dir = d if os.name == "nt" else os.path.dirname(d)
    roots = [os.path.dirname(os.path.dirname(env_dir))] if os.path.basename(os.path.dirname(env_dir)) == "envs" else []
    roots.append(env_dir)
    for root in roots:
        cands = ((os.path.join(root, "Scripts", "conda.exe"), os.path.join(root, "condabin", "conda.bat"))
                 if os.name == "nt" else (os.path.join(root, "bin", "conda"), os.path.join(root, "condabin", "conda")))
        for c in cands:
            if os.path.isfile(c):
                return {"CONDA_EXE": c, "PATH": os.path.dirname(c) + os.pathsep + os.environ.get("PATH", "")}
    return {}


def job_plan(action, body):
    """(title, steps) for a job the page may start; ValueError with the reason for anything else.
    Every command is a fixed argument list built here; the page sends only a word and checked values."""
    py, vc = sys.executable, vor_command()
    vor_actions = ("vor-ingest", "vor-tables", "vor-ocr", "vor-ocr-all", "fetch")
    if action in vor_actions and not vc:
        raise ValueError("Vor is not installed on this computer.")
    if action == "vor-ingest":
        return "Index Vor's library (new and changed files)", [("vor ingest", vc + ["ingest"], False)]
    if action == "vor-tables":
        return "Read the tables in Vor's PDFs", [("vor tables", vc + ["tables"], False)]
    if action == "vor-ocr":
        return "OCR Vor's scanned PDFs", [("vor ocr", vc + ["ocr"], False)]
    if action == "vor-ocr-all":
        return "OCR every scanned page in Vor's PDFs", [("vor ocr --min-fraction 0", vc + ["ocr", "--min-fraction", "0"], False)]
    if action == "heim-compact":
        return "Compact Heim's index", [("heim-index --compact", [py, tool("rag_index.py"), "--compact"], False)]
    if action == "heim-refresh":
        # the doctor prints the folders quoted ('...'), several when a collection has several roots
        name = (body.get("name") or "").strip()
        given = body.get("paths") if isinstance(body.get("paths"), list) else [body.get("path")]
        folders = [os.path.expanduser(p.strip().strip("'\"").strip()) for p in given[:20] if isinstance(p, str)]
        if not NAME_RE.match(name) or not folders or not all(f and os.path.isdir(f) for f in folders):
            raise ValueError("That needs a collection name and folders that exist.")
        return ("Re-index Heim's '%s' collection" % name,
                [("heim-index -c %s %s" % (name, " ".join("'%s'" % f for f in folders)),
                  [py, tool("rag_index.py"), "-c", name] + folders, False)])
    if action == "fetch":
        known = {g["id"] for g in catalog_groups()}
        groups = [g for g in (body.get("groups") or []) if isinstance(g, str) and g in known]
        fetch = vor_tool_file("fetch_asdso.py")
        if not groups:
            raise ValueError("Tick at least one group.")
        if not fetch:
            raise ValueError("fetch_asdso.py is not installed here yet. Install the latest update first.")
        return ("Download %s and index them" % ", ".join(groups),
                [("download: %s" % ", ".join(groups), [vc[0], fetch, "--catalog", ",".join(groups)], True),
                 ("vor ingest", vc + ["ingest"], False)])
    if action == "score":
        which = body.get("which") or "both"
        if which not in ("both", "vor", "heim"):
            raise ValueError("Pick Vor, Heim or both.")
        argv = [py, tool("ai_score.py")] + ([] if which == "both" else ["--" + which])
        return "Answer test (%s)" % {"both": "Heim and Vor"}.get(which, which.capitalize()), [("ai-score", argv, False)]
    if action == "update":
        folder = os.path.realpath(body.get("folder") or "")
        if not folder.startswith(os.path.realpath(updates_dir()) + os.sep) or not os.path.isdir(folder):
            raise ValueError("That is not an update this page unpacked.")
        argv = installer_argv(folder)
        if not argv:
            raise ValueError("That update has no installer for this computer.")
        return "Install the update in %s" % os.path.basename(folder), [("installer", argv, False, conda_env())]
    raise ValueError("Unknown action.")


# ------------------------------------------------------------------------------------------ uploads

def safe_name(name, exts):
    """A plain file name (no folders), with one of `exts`, or None."""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^\w .()+,-]", "_", base)[:150]
    if not base or base.startswith(".") or not base.lower().endswith(exts):
        return None
    return base


def free_path(folder, name):
    stem, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 2
    while os.path.exists(p):
        p, n = os.path.join(folder, "%s (%d)%s" % (stem, n, ext)), n + 1
    return p


def receive(rfile, length, dest):
    """Copy `length` bytes of the request into dest (through a .part file)."""
    part = dest + ".part"
    left = length
    with open(part, "wb") as fh:
        while left > 0:
            buf = rfile.read(min(left, 1 << 20))
            if not buf:
                break
            fh.write(buf)
            left -= len(buf)
    if left:
        os.remove(part)
        raise ValueError("the upload stopped part way")
    os.replace(part, dest)


def unpack_update(zpath):
    """Check a downloaded dam-local-ai zip and unpack it under ~/local-ai/updates/. Returns what the
    page shows before Install: the folder, the versions in it and the ones installed now."""
    import zipfile
    if not zipfile.is_zipfile(zpath):
        raise ValueError("That is not a zip file.")
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        if not names or len(names) > 20000 or sum(i.file_size for i in z.infolist()) > (1 << 30):
            raise ValueError("That zip is not a Local AI update (empty or too big).")
        for n in names:
            parts = n.replace("\\", "/").split("/")
            if parts[0] != "damit_ai" or ".." in parts or n.startswith("/") or ":" in parts[0]:
                raise ValueError("That zip is not a Local AI update: everything in it must be inside damit_ai/.")
        folder = os.path.splitext(zpath)[0]
        if os.path.exists(folder):
            shutil.rmtree(folder)
        z.extractall(folder)
    if not installer_argv(folder):
        raise ValueError("That zip has no installer for this computer.")
    vc = vor_command()
    root = os.path.join(folder, "damit_ai")
    return {"folder": folder, "zip": os.path.basename(zpath),
            "new": {"vor": tool_version(os.path.join(root, "vor", "vor.py")),
                    "ai": tool_version(os.path.join(root, "heim", "tools", "ai_ui.py"))},
            "now": {"vor": tool_version(vc[1]) if vc else "", "ai": VERSION}}


def open_folder(which):
    """Open one of the assistants' own folders in Finder / Explorer / the file manager."""
    paths = {"library": os.path.join(vor_home(), "library"), "reports": os.path.join(vor_home(), "reports"),
             "scores": score_reports(), "logs": local_ai("logs")}
    p = paths.get(which)
    if not p:
        raise ValueError("unknown folder")
    os.makedirs(p, exist_ok=True)
    if os.name == "nt":
        os.startfile(p)  # nosec B606 - one of the fixed folders above
    else:
        spawn(["/usr/bin/open" if sys.platform == "darwin" else "xdg-open", p],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_kw(detach=True))
    return p


def score_reports():
    """Where ai-score keeps its history (HEIM_REPORTS, as ai_score.py)."""
    return os.path.expanduser(os.environ.get("HEIM_REPORTS") or local_ai("reports"))


def score_history():
    p = os.path.join(score_reports(), "SCORE-HISTORY.md")
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-ui/" + VERSION
    # 1.2.0: HTTP/1.1, or a browser shows the chunked stream's length lines ("7", "8f", ...) in the
    # output: chunked transfer is not part of HTTP/1.0. One request per connection (Connection: close),
    # so a body a refusal did not read can never be taken for the next request.
    protocol_version = "HTTP/1.1"
    key = ""
    port = 0
    seen = 0.0                  # time.monotonic() of the last request that carried the key (the idle clock;
    #                             monotonic, so a computer waking from sleep does not count as idle time)

    def log_message(self, fmt, *args):      # quiet: the terminal shows only the address
        pass

    # ------------------------------------------------------------------ guards
    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    def _key_ok(self, query):
        got = self.headers.get("X-Key") or (query.get("k") or [""])[0]
        ok = bool(got) and bool(self.key) and secrets.compare_digest(got, self.key)
        if ok:
            Handler.seen = time.monotonic()
        return ok

    def _send(self, code, body, ctype="text/plain; charset=utf-8", headers=()):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.close_connection = True
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _stream(self, who, argv, after=None):
        """Run argv and send its output as it is written (chunked)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Answered-By", who)
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        def chunk(text):
            b = text.encode("utf-8")
            if b:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(b), b))
                self.wfile.flush()
        started = time.time()
        try:
            env = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1")
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}      # no console window on Windows
            with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  env=env, **kw) as p:  # nosec B603 - fixed argument list, no shell
                timer = threading.Timer(RUN_SECONDS, p.kill)
                timer.start()
                try:
                    for line in iter(p.stdout.readline, b""):
                        chunk(line.decode("utf-8", "replace"))
                    p.wait()
                finally:
                    timer.cancel()
            if p.returncode:
                chunk("\n[exit code %d]\n" % p.returncode)
            if after:
                extra = after(started)
                if extra:
                    chunk(extra)
        except OSError as e:
            chunk("could not run %s: %s\n" % (who, e))
        except (BrokenPipeError, ConnectionResetError):
            return
        self.wfile.write(b"0\r\n\r\n")

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._host_ok():
            return self._send(403, "wrong host")
        if u.path == "/":
            # the page holds no secret: it takes the key from its own address (#k=... from the app, ?k=...
            # from the address `ai` prints), keeps it for this window, and sends it with every request
            return self._send(200, PAGE.replace("__VERSION__", VERSION), "text/html; charset=utf-8")
        if u.path == "/api/hello":
            # proof that this server holds the key, without the key being sent: HMAC(key, the caller's nonce)
            nonce = (q.get("n") or [""])[0]
            if not (16 <= len(nonce) <= 128) or not self.key:
                return self._send(400, "bad nonce")
            return self._json({"app": "ai-ui", "proof": hello_proof(self.key, nonce)})
        if not self._key_ok(q):
            return self._send(403, "missing key")
        if u.path == "/api/ping":
            return self._json({"app": "ai-ui", "version": VERSION, "pid": os.getpid(), "busy": bool(running_job())})
        if u.path == "/pdf":
            path = (q.get("path") or [""])[0]
            if not allowed_pdf(path):
                return self._send(403, "only PDFs from Vor's library or Heim's indexed folders are served")
            with open(os.path.realpath(path), "rb") as f:
                return self._send(200, f.read(), "application/pdf")
        if u.path == "/api/hydrograph":
            try:
                return self._json(hydrograph_points((q.get("dam") or [""])[0]))
            except Exception as e:  # noqa: BLE001 - shown on the page
                return self._json({"error": str(e)}, 500)
        if u.path == "/api/report":
            p = (q.get("path") or [""])[0]
            real = os.path.realpath(p)
            if not (real.startswith(os.path.realpath(os.path.join(vor_home(), "reports")) + os.sep)
                    and real.endswith(".md") and os.path.isfile(real)):
                return self._send(403, "not a Vor report")
            with open(real, encoding="utf-8", errors="replace") as f:
                return self._send(200, f.read())
        if u.path == "/api/status":
            return self._json(status())
        if u.path == "/api/library":
            st = status()
            return self._json({"vor": st["vor"], "docs": library_docs(), "groups": catalog_groups()})
        if u.path == "/api/scores":
            return self._send(200, score_history())
        if u.path == "/api/job":
            with JOBS_LOCK:
                job = JOBS.get((q.get("id") or [""])[0])
            if not job:
                return self._json({"error": "no such job"}, 404)
            try:
                start = int((q.get("from") or ["0"])[0])
            except ValueError:
                start = 0
            text, nxt = job.read(start)
            return self._json(dict(job.summary(), text=text, next=nxt))
        if u.path == "/api/jobs":
            job = latest_job()
            return self._json({"job": job.summary() if job else None})
        return self._send(404, "not found")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if not self._host_ok() or not self._key_ok({}):
            return self._send(403, "forbidden")
        if u.path == "/api/upload":
            return self._upload(q)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
        except ValueError:
            return self._send(400, "bad request")
        if not isinstance(body, dict):
            return self._send(400, "bad request")
        if u.path == "/api/ask":
            q = (body.get("q") or "").strip()
            if not q:
                return self._send(400, "empty question")
            who, argv = route(q, body.get("target") or "auto")
            if argv is None:
                return self._send(200, "%s is not installed on this machine.\n" % who)
            after = None
            if who == "Vor":
                def after(started):
                    rep = newest_report(started)
                    return ("\n[report] %s\n" % rep) if rep else ""
            return self._stream(who, argv, after)
        if u.path == "/api/run":
            argv = action_argv(body.get("action") or "", body)
            if argv is None:
                return self._send(400, "that needs a dam (or a path that exists)")
            return self._stream(body.get("action"), argv)
        if u.path == "/api/job":
            try:
                title, steps = job_plan(body.get("action") or "", body)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            job, busy = start_job(title, steps)
            if busy:
                return self._json({"error": "Wait for '%s' to finish first (or stop it)." % busy.title,
                                   "job": busy.summary()}, 409)
            return self._json(job.summary())
        if u.path == "/api/job/stop":
            with JOBS_LOCK:
                job = JOBS.get(body.get("id") or "")
            if not job:
                return self._json({"error": "no such job"}, 404)
            job.stop()
            return self._json(job.summary())
        if u.path == "/api/start-ollama":
            return self._json(start_ollama())
        if u.path == "/api/open":
            try:
                return self._json({"opened": open_folder(body.get("which") or "")})
            except (ValueError, OSError) as e:
                return self._json({"error": str(e)}, 400)
        if u.path == "/api/quit":
            # the icon asks an older copy to make way after an update; never while a job runs
            busy = running_job()
            if busy:
                return self._json({"error": "'%s' is still running." % busy.title}, 409)
            self._json({"quitting": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        return self._send(404, "not found")

    def _upload(self, q):
        """A file sent from the page: a document for Vor's library, or a downloaded update zip."""
        kind = (q.get("kind") or [""])[0]
        if kind not in UPLOAD_MAX:
            return self._json({"error": "unknown upload"}, 400)
        try:
            n = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            n = -1
        if n < 0:
            return self._json({"error": "no file"}, 411)
        if n > UPLOAD_MAX[kind]:
            return self._json({"error": "That file is bigger than %d MB." % (UPLOAD_MAX[kind] >> 20)}, 413)
        exts = LIBRARY_EXT if kind == "library" else (".zip",)
        name = safe_name((q.get("name") or [""])[0], exts)
        if not name:
            return self._json({"error": "Only %s files." % " / ".join(e[1:].upper() for e in exts)}, 400)
        if kind == "library":
            if not vor_command():
                return self._json({"error": "Vor is not installed on this computer."}, 400)
            folder = os.path.join(vor_home(), "library", "added")
        else:
            folder = os.path.join(updates_dir(), time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(folder, exist_ok=True)
        dest = free_path(folder, name)
        try:
            receive(self.rfile, n, dest)
            if kind == "library":
                return self._json({"saved": dest})
            return self._json(unpack_update(dest))
        except (ValueError, OSError) as e:
            return self._json({"error": str(e)}, 400)


# ------------------------------------------------------------------------------- the app's window

class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets two programs share a port with SO_REUSEADDR, so a second copy would not notice the first
    allow_reuse_address = os.name != "nt"


def hello_proof(key, nonce):
    return hmac.new(key.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def read_state():
    try:
        with open(state_file(), encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) and st.get("port") and st.get("key") else None
    except (OSError, ValueError):
        return None


def write_state(port, key):
    os.makedirs(local_ai(), exist_ok=True)
    tmp = state_file() + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"port": port, "key": key, "pid": os.getpid(), "version": VERSION}, fh)
    os.replace(tmp, state_file())


def clear_state():
    st = read_state()
    if st and st.get("pid") == os.getpid():
        try:
            os.remove(state_file())
        except OSError:
            pass


def call(st, path, body=None, timeout=3):
    """A request to a running app server (the one in the state file)."""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (int(st["port"]), path),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Key": st["key"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def alive(st):
    """The running app's /api/ping ({version, busy, ...}), or None. The key in the state file goes only to a
    server that first proves it holds that key: a program that took the port after the app stopped gets
    nothing from us."""
    if not st:
        return None
    try:
        nonce = secrets.token_hex(16)
        url = "http://127.0.0.1:%d/api/hello?n=%s" % (int(st["port"]), nonce)
        with urllib.request.urlopen(url, timeout=3) as r:
            hello = json.loads(r.read().decode("utf-8") or "{}")
        if not hmac.compare_digest(str(hello.get("proof") or ""), hello_proof(str(st["key"]), nonce)):
            return None
        ping = call(st, "/api/ping")
        return ping if ping.get("app") == "ai-ui" else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def browsers():
    """App-window browsers on this computer, best first: (argv prefix that takes --app=URL)."""
    if sys.platform == "darwin":
        out = []
        for name in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            for d in ("/Applications", os.path.join(HOME, "Applications")):
                if os.path.isdir(os.path.join(d, name + ".app")):
                    out.append(["/usr/bin/open", "-na", os.path.join(d, name + ".app"), "--args"])
                    break
        return out
    if os.name == "nt":
        out = []
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            for rel in (("Microsoft", "Edge", "Application", "msedge.exe"),
                        ("Google", "Chrome", "Application", "chrome.exe")):
                p = os.path.join(base, *rel)
                if base and os.path.isfile(p):
                    out.append([p])
        return out
    return [[p] for p in (shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium",
                                                       "chromium-browser", "microsoft-edge", "brave-browser")) if p]


def open_window(url):
    """The page in a window of its own (Chrome / Edge / Brave app mode: no tabs or address bar), else
    in the default browser. Nothing is installed for it."""
    for prefix in browsers():
        try:
            spawn(prefix + ["--app=" + url, "--new-window"], stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, **popen_kw(detach=True))
            return "app window"
        except OSError:
            continue
    webbrowser.open(url)
    return "browser"


def server_python():
    """pythonw on Windows (no console window for the background server), else this python."""
    if os.name == "nt":
        w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(w):
            return w
    return sys.executable


def open_page_file(st):
    """A small page only this user can read that sends the window on to the app with the key in the
    address's #fragment (which never leaves the browser). Its file:// address is what goes on the
    browser's command line, so the key never does."""
    path = local_ai("ai-ui-open.html")
    url = "http://127.0.0.1:%d/#k=%s" % (int(st["port"]), urllib.parse.quote(str(st["key"]), safe=""))
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write('<!doctype html><meta charset="utf-8"><title>Local AI</title>'
                 '<script>location.replace(%s)</script>'
                 '<p style="font:15px sans-serif">Opening Local AI... <a href="%s">open it</a></p>\n'
                 % (json.dumps(url), url))
    os.replace(tmp, path)
    return pathlib.Path(path).resolve().as_uri()


def start_lock(wait):
    """Hold ~/local-ai/ai-ui.lock while one icon press checks for, starts and waits for the server, so
    two quick presses start one copy. True when held; False when another press held it all along."""
    lock = local_ai("ai-ui.lock")
    end = time.monotonic() + wait
    while True:
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_SECONDS:
                    os.remove(lock)                 # left by a press that died
                    continue
            except OSError:
                continue
            if time.monotonic() > end:
                return False
            time.sleep(0.2)


def start_server(wait):
    """Start the app's server in the background; its state, or None when it did not answer in time."""
    with open(local_ai("logs", "ai-ui.log"), "ab") as log:
        spawn([server_python(), os.path.abspath(__file__), "--serve-app"], stdout=log,
              stderr=subprocess.STDOUT, **popen_kw(detach=True))
    end = time.monotonic() + wait
    while time.monotonic() < end:
        st = read_state()
        if alive(st):
            return st
        time.sleep(0.25)
    return None


def app_open(wait=20):
    """What the Local AI icon runs: open a window on the running app, starting it first when needed.
    One copy runs at a time; it stops by itself a while after its last window closes. After an update an
    older copy that is idle is asked to stop, so the window shows the new version."""
    os.makedirs(local_ai("logs"), exist_ok=True)
    held = start_lock(wait + 10)
    try:
        st = read_state()
        ping = alive(st)
        if ping and ping.get("version") != VERSION and not ping.get("busy"):
            try:
                call(st, "/api/quit", {})
            except (OSError, ValueError):
                pass
            end = time.monotonic() + 10
            while time.monotonic() < end and alive(st):
                time.sleep(0.25)
            ping = None
        if not ping:
            st = start_server(wait)
            if not st:
                print("Local AI did not start; see %s" % local_ai("logs", "ai-ui.log"), file=sys.stderr)
                return 1
    finally:
        if held:
            try:
                os.remove(local_ai("ai-ui.lock"))
            except OSError:
                pass
    open_window(open_page_file(st))
    return 0


def watchdog(httpd):
    """The app stops IDLE_SECONDS after its last window went quiet, unless a job is running."""
    while True:
        time.sleep(min(15.0, IDLE_SECONDS / 4.0))
        if time.monotonic() - Handler.seen > IDLE_SECONDS and not running_job():
            httpd.shutdown()
            return


def serve(port=0, open_browser=True, app=False):
    Handler.key = secrets.token_urlsafe(18)
    Handler.seen = time.monotonic()
    try:
        httpd = Server(("127.0.0.1", APP_PORT if (app and not port) else port), Handler)
    except OSError:
        httpd = Server(("127.0.0.1", 0), Handler)
    Handler.port = httpd.server_address[1]
    if app:
        write_state(Handler.port, Handler.key)
        threading.Thread(target=watchdog, args=(httpd,), daemon=True).start()
        print("Local AI %s on 127.0.0.1:%d (pid %d)" % (VERSION, Handler.port, os.getpid()), flush=True)
    else:
        url = "http://127.0.0.1:%d/?k=%s" % (Handler.port, Handler.key)
        print("Heim and Vor: %s\n(this computer only; Ctrl+C stops it)" % url, flush=True)
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        job = running_job()
        if job:                                 # Ctrl+C: a job's programs do not carry on unseen
            job.stop()
        httpd.server_close()
        if app:
            clear_state()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai", description="One local page for Heim and Vor (127.0.0.1 only).")
    ap.add_argument("--port", type=int, default=0, help="port (default: any free one)")
    ap.add_argument("--no-browser", action="store_true", help="print the address instead of opening it")
    ap.add_argument("--app", action="store_true",
                    help="what the Local AI icon runs: open a window on the running app, starting it if needed")
    ap.add_argument("--serve-app", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=VERSION)
    a = ap.parse_args(argv)
    if a.app:
        return app_open()
    serve(a.port, not a.no_browser, app=a.serve_app)
    return 0


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local AI</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--accent:#2f5d8a;--ok:#2e7d4f;--watch:#a86b00;--bad:#b3261e;--code:#f1f0ec;--soft:#eef3f8}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a3a29b;--line:#34332f;--accent:#8db4dd;--ok:#6cc391;--watch:#e0a84a;--bad:#ef7a72;--code:#262624;--soft:#1f2a35}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:12px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:var(--bg);z-index:2}
header h1{font-size:18px;margin:0}header small{color:var(--muted)}
nav{display:flex;gap:4px;flex-wrap:wrap}nav button{background:none;border:1px solid transparent;border-radius:6px;padding:6px 12px;color:var(--ink);cursor:pointer;font:inherit}
nav button.on{border-color:var(--line);background:var(--panel)}
main{max-width:1040px;margin:0 auto;padding:16px}section{display:none}section.on{display:block}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
.card h2{font-size:16px;margin:0 0 6px}.card p{margin:4px 0 8px;color:var(--muted)}
textarea,input,select{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px}
input[type=checkbox]{width:auto;margin:0}
textarea{min-height:70px;resize:vertical}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.row>*{flex:1 1 160px}.row button,.row label{flex:0 0 auto}
button.go,button.fix{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:8px 16px;cursor:pointer;font:inherit}
button.fix{padding:2px 10px;font-size:13px;margin:0 2px}
button.plain{background:none;border:1px solid var(--line);border-radius:6px;padding:7px 14px;color:var(--ink);cursor:pointer;font:inherit}
button:disabled{opacity:.5;cursor:default}
@media (prefers-color-scheme:dark){button.go,button.fix{color:#111}}
pre{white-space:pre-wrap;word-break:break-word;background:var(--code);border-radius:8px;padding:12px;margin:0;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;min-height:40px;max-height:480px;overflow:auto}
.who{color:var(--muted);font-size:13px;margin:6px 0}a{color:var(--accent)}
.ok{color:var(--ok)}.watch{color:var(--watch)}.bad{color:var(--bad)}.muted{color:var(--muted)}
pre:empty{display:none}svg{width:100%;height:280px}svg text{fill:var(--muted);font-size:11px}
#banner,#offline{max-width:1040px;margin:12px auto 0;padding:0 16px}#banner:empty,#offline:empty{display:none}
.alert{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;border-radius:10px;padding:10px 14px;margin-bottom:8px;border:1px solid var(--line);background:var(--panel)}
.alert.PROBLEM{border-color:var(--bad)}.alert.WATCH{border-color:var(--watch)}
#job{max-width:1040px;margin:12px auto 0;padding:0 16px;display:none}
#job .card{border-color:var(--accent);background:var(--soft)}
#jobhead{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#jobhead b{flex:1 1 auto}
#joblast{font:13px ui-monospace,Menlo,Consolas,monospace;color:var(--muted);margin:6px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#jobout{display:none;max-height:300px}#job.open #jobout{display:block}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}td.n{text-align:right;white-space:nowrap}
#drop{border:2px dashed var(--line);border-radius:10px;padding:22px;text-align:center;color:var(--muted);cursor:pointer}
#drop.over{border-color:var(--accent);color:var(--accent)}
.stat{display:inline-block;margin-right:18px}.stat b{font-size:20px;display:block;color:var(--ink)}
.md h1,.md h2,.md h3{font-size:15px;margin:14px 0 6px}.md p{margin:4px 0}
</style></head><body>
<header><h1>Local AI</h1><small>Heim and Vor · on this computer only · ai_ui __VERSION__</small>
<nav><button data-t="ask" class="on">Ask</button><button data-t="library">Library</button><button data-t="runs">Runs</button><button data-t="add">Add</button><button data-t="score">Check answers</button><button data-t="health">Health &amp; update</button></nav></header>
<div id="offline"></div><div id="banner"></div>
<div id="job"><div class="card"><div id="jobhead"><b id="jobtitle"></b><span id="jobstate" class="muted"></span>
<button class="plain" id="jobmore">Show details</button><button class="plain" id="jobstop">Stop</button><button class="plain" id="jobhide">Hide</button></div>
<div id="joblast"></div><pre id="jobout"></pre></div></div>
<main>
<section id="ask" class="on"><div class="card">
<textarea id="q" placeholder="Ask in plain words, e.g.  what breach width does Froehlich 2008 give?  ·  how deep is the water at County Road 26 for 2801?  ·  what does REFINE_NEAR do?"></textarea>
<div class="row"><select id="target"><option value="auto">Pick for me</option><option value="vor">Publications (Vor): standards and papers, every quote checked</option><option value="heim">This software (Heim): tools, settings, errors, code</option><option value="runs">My run results: exact numbers from runs I have read in</option></select><button class="go" id="askgo">Ask</button></div>
</div><div class="who" id="who"></div><pre id="answer"></pre></section>

<section id="library">
<div class="card"><h2>Vor's library</h2><div id="libstats" class="muted">Reading the library...</div>
<div class="row"><button class="go" data-job="vor-ingest">Index new and changed files</button><button class="plain" data-open="library">Open the library folder</button><span></span></div></div>
<div class="card"><h2>Add your own documents</h2><p>PDFs, .md or .txt. They are copied into the library (folder "added") and indexed.</p>
<div id="drop">Drop files here, or click to choose them<input type="file" id="files" multiple accept=".pdf,.md,.txt" style="display:none"></div>
<div id="dropout" class="who"></div></div>
<div class="card"><h2>Get more documents</h2><p>Public dam-safety publications from the download catalog. Tick the groups you want: they are downloaded into the library and indexed. Files you already have are kept, not downloaded again.</p>
<table><thead><tr><th></th><th>Group</th><th>What is in it</th><th class="n">You have</th></tr></thead><tbody id="groups"></tbody></table>
<div class="row"><button class="go" id="fetchgo">Download the ticked groups and index them</button><span></span></div></div>
<div class="card"><h2>What is indexed</h2><input id="docfilter" placeholder="filter by title, number, year or organisation">
<table><thead><tr><th>Title</th><th>Number</th><th>Year</th><th class="n">Pages</th></tr></thead><tbody id="docs"></tbody></table><div id="docmore" class="who"></div></div>
</section>

<section id="runs"><div class="card">
<div class="row"><input id="dam" placeholder="dam: DWR-2801, 2801 or part of the name"><input id="place" placeholder="place (for 'at'): an address, road, structure id or lat,lon"></div>
<div class="row"><button class="go" data-a="list">List runs</button><button class="go" data-a="show">Show</button><button class="go" data-a="compare">Compare</button><button class="go" data-a="at">At place</button><button class="go" data-a="hydrograph">Hydrograph</button></div>
</div><svg id="chart" style="display:none"></svg><pre id="runsout"></pre></section>

<section id="add"><div class="card">
<input id="path" placeholder="a file or folder path (drag it into Terminal to copy its path, then paste here)">
<div class="row"><select id="to"><option value="heim">Heim: a run folder (read into the run results) or a document about the software</option><option value="vor">Publications library (Vor): a PDF</option></select><button class="go" id="addgo">Add</button></div>
</div><pre id="addout"></pre></section>

<section id="score">
<div class="card"><h2>Check the answers</h2><p>Asks each assistant its fixed test questions and scores the answers against the right ones, so you can see whether a change helped. It needs Ollama and takes several minutes.</p>
<div class="row"><button class="go" data-score="vor">Test Vor</button><button class="go" data-score="heim">Test Heim</button><button class="go" data-score="both">Test both</button><button class="plain" data-open="scores">Open the reports folder</button><span></span></div></div>
<div class="card"><h2>Score history</h2><div id="scores" class="md muted">No scores yet.</div></div>
</section>

<section id="health">
<div class="card"><h2>Health</h2><p>Checks both assistants: Ollama, the models, the indexes and the folders. When a line says what to run, the button next to it runs it.</p>
<div class="row"><button class="go" id="docgo">Check everything</button><button class="plain" id="ollamago">Start Ollama</button><button class="plain" data-open="logs">Open the logs folder</button><span></span></div>
<div id="ollamaout" class="who"></div></div>
<pre id="docout"></pre>
<div class="card" style="margin-top:14px"><h2>Install an update</h2><p>Choose the dam-local-ai zip you downloaded (for example dam-local-ai-mac-2026-11-24.zip). It is checked, unpacked into your local-ai folder and its installer runs. Your library, indexes, models and results are kept.</p>
<div class="row"><input type="file" id="upzip" accept=".zip"><span></span></div><div id="upinfo" class="who"></div>
<div class="row"><button class="go" id="upgo" disabled>Install this update</button><span></span></div></div>
</section>
</main>
<script>
// The key comes in this window's address (#k=... from the Local AI icon, ?k=... from the address `ai`
// printed), is kept for this window only, and is taken out of the address bar.
const KEY=(()=>{const m=location.hash.match(/[#&]k=([^&]+)/)||location.search.match(/[?&]k=([^&]+)/);let k="";
  if(m){k=decodeURIComponent(m[1]);try{sessionStorage.setItem("ai_k",k)}catch(e){}history.replaceState(null,"","/")}
  else{try{k=sessionStorage.getItem("ai_k")||""}catch(e){}}return k})();
function offline(why){$("offline").innerHTML='<div class="alert PROBLEM"><span><b class="bad">'+esc(why)+'</b></span></div>'}
function online(){$("offline").innerHTML=""}
const STOPPED="Local AI has stopped: open it again from its icon (or run ai in a terminal).";
const $=id=>document.getElementById(id);
function show(t){document.querySelectorAll("nav button,section").forEach(x=>x.classList.remove("on"));document.querySelector('nav button[data-t="'+t+'"]').classList.add("on");$(t).classList.add("on");
  if(t==="library")loadLibrary();if(t==="score")loadScores();if(t==="health"&&!$("docout").textContent)$("docgo").click()}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>show(b.dataset.t));
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
async function api(url,body){const o={headers:{"X-Key":KEY}};if(body!==undefined){o.method="POST";o.headers["Content-Type"]="application/json";o.body=JSON.stringify(body)}
  let r;try{r=await fetch(url+(body===undefined?(url.includes("?")?"&":"?")+"k="+KEY:""),o)}catch(e){offline(STOPPED);return {error:STOPPED,offline:true}}
  if(r.status===403){offline(STOPPED);return {error:STOPPED,offline:true}}
  let d={};try{d=await r.json()}catch(e){}if(!r.ok&&!d.error)d.error="HTTP "+r.status;return d}
function linkify(t){
  let h=esc(t);
  h=h.replace(/file:\/\/([^\s)#"]+\.pdf)(#page=(\d+))?/gi,(m,p,_,n)=>'<a target="_blank" href="/pdf?k='+KEY+'&path='+encodeURIComponent(decodeURIComponent(p))+(n?'#page='+n:'')+'">'+esc(decodeURIComponent(p).split('/').pop())+(n?' p.'+n:'')+'</a>');
  h=h.replace(/\[report\] (\S+\.md)/g,(m,p)=>'<a href="#" data-report="'+esc(p)+'">open the full report</a>');
  h=h.replace(/\b(PROBLEM)\b/g,'<span class="bad">$1</span>').replace(/\b(WATCH)\b/g,'<span class="watch">$1</span>').replace(/^(\s*)(ok|OK)\b/gm,'$1<span class="ok">$2</span>');
  return h}
// What a doctor line says to run becomes a button that runs it (only the commands listed here). A
// command quoted in `backticks` is part of a sentence, not something to run, and gets no button.
function fixify(h){
  const b=(fix,label,extra)=>'<button class="fix" data-fix="'+fix+'"'+(extra||"")+'>'+label+'</button>';
  const said=(s,off,len)=>s[off-1]!=="`"&&s[off+len]!=="`";
  // the folders come quoted ('...'), several when a collection has several; older doctors printed one bare
  h=h.replace(/heim-index -c ([A-Za-z0-9_.-]+) ((?:'[^'\n]+'[ \t]*)+|(?!&lt;)[^'\n]+?)[ \t]*$/gm,(m,n,p)=>{
    const ps=p.includes("'")?[...p.matchAll(/'([^'\n]+)'/g)].map(x=>x[1]):[p.trim()];
    return m+' '+b("heim-refresh","Re-index "+n,' data-name="'+n+'" data-paths="'+JSON.stringify(ps).replace(/"/g,"&quot;")+'"')});
  h=h.replace(/vor ocr((?: --[\w-]+(?: \d+)?)*)(?!\w)/g,(m,o,off,s)=>!said(s,off,m.length)?m:o===""?m+' '+b("vor-ocr","OCR"):o===" --min-fraction 0"?m+' '+b("vor-ocr-all","OCR them"):m);
  h=h.replace(/vor ingest((?: --[\w-]+)*)(?!\w)/g,(m,o,off,s)=>o===""&&said(s,off,m.length)?m+' '+b("vor-ingest","Index"):m);
  h=h.replace(/vor tables(?!\w)/g,(m,off,s)=>said(s,off,m.length)?m+' '+b("vor-tables","Read tables"):m);
  h=h.replace(/heim-index --compact/g,m=>m+' '+b("heim-compact","Compact"));
  h=h.replace(/heim-start|ollama serve/g,m=>m+' '+b("start-ollama","Start Ollama"));
  return h}
async function stream(url,body,out,who,fix){
  out.textContent="";let text="";let r;
  try{r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-Key":KEY},body:JSON.stringify(body)})}catch(e){offline(STOPPED);out.textContent=STOPPED;return}
  if(r.status===403){offline(STOPPED);out.textContent=STOPPED;return}
  if(who)who.textContent=r.headers.get("X-Answered-By")?("Answered by "+r.headers.get("X-Answered-By")):"";
  const rd=r.body.getReader(),dec=new TextDecoder();
  for(;;){const {value,done}=await rd.read();if(done)break;text+=dec.decode(value,{stream:true});out.innerHTML=fix?fixify(linkify(text)):linkify(text);out.scrollTop=out.scrollHeight}
  out.querySelectorAll("a[data-report]").forEach(a=>a.onclick=async e=>{e.preventDefault();const t=await (await fetch("/api/report?k="+KEY+"&path="+encodeURIComponent(a.dataset.report))).text();
    out.innerHTML=linkify(t.replace(/\]\((file:[^)]+)\)/g," $1"))});
}
// ---- jobs: long commands that carry on when the window closes
let JOB=null,POS=0,TEXT="",TIMER=null,PENDING=false;
async function startJob(body){const d=await api("/api/job",body);
  if(d.error){if(d.job){watch(d.job.id)}if(!d.offline)alert(d.error);return}watch(d.id)}
function watch(id){if(JOB!==id){JOB=id;POS=0;TEXT="";$("jobout").textContent=""}$("job").style.display="block";clearTimeout(TIMER);poll()}
async function poll(){
  const d=await api("/api/job?id="+JOB+"&from="+POS);if(d.error){if(!d.offline)TIMER=setTimeout(poll,5000);return}
  POS=d.next;TEXT=(TEXT+d.text).slice(-200000);$("jobtitle").textContent=d.title;
  const mins=Math.max(0,Math.round(((d.ended||Date.now()/1000)-d.started)/60));
  $("jobstate").innerHTML=d.status==="running"?"working, "+mins+" min":d.status==="done"?'<span class="ok">done</span> after '+mins+" min":'<span class="bad">'+d.status+"</span>"+(d.code?" (exit code "+d.code+")":"");
  const lines=TEXT.trim().split("\n");$("joblast").textContent=lines[lines.length-1]||"";
  $("jobout").innerHTML=linkify(TEXT);$("jobout").scrollTop=$("jobout").scrollHeight;$("jobstop").style.display=d.status==="running"?"":"none";
  if(d.status==="running"){TIMER=setTimeout(poll,1200)}else{refreshAll();if(PENDING){PENDING=false;startJob({action:"vor-ingest"})}if(d.title.startsWith("Install the update"))$("upinfo").innerHTML=d.status==="done"?'<span class="ok">Updated.</span> Close this window and open Local AI again to use the new version.':'<span class="bad">The installer stopped.</span> Open the details above for what it said.'}}
$("jobmore").onclick=()=>{$("job").classList.toggle("open");$("jobmore").textContent=$("job").classList.contains("open")?"Hide details":"Show details"};
$("jobhide").onclick=()=>{$("job").style.display="none"};
$("jobstop").onclick=async()=>{if(JOB&&confirm("Stop this job? What it finished is kept."))await api("/api/job/stop",{id:JOB})};
document.addEventListener("click",e=>{const t=e.target;
  if(t.dataset.fix){e.preventDefault();if(t.dataset.fix==="start-ollama")startOllama();else if(t.dataset.fix==="goto-library")show("library");else startJob({action:t.dataset.fix,name:t.dataset.name,paths:t.dataset.paths?JSON.parse(t.dataset.paths):undefined})}
  if(t.dataset.job)startJob({action:t.dataset.job});
  if(t.dataset.score)startJob({action:"score",which:t.dataset.score});
  if(t.dataset.open)api("/api/open",{which:t.dataset.open}).then(d=>{if(d.error)alert(d.error)})});
// ---- status banner
async function refreshStatus(){const s=await api("/api/status");if(s.offline)return s;
  $("banner").innerHTML=(s.problems||[]).map(p=>'<div class="alert '+p.level+'"><span><b class="'+(p.level==="PROBLEM"?"bad":"watch")+'">'+(p.level==="PROBLEM"?"Needs a fix":"Worth a look")+':</b> '+esc(p.text)+'</span><button class="fix" data-fix="'+p.fix+'">'+esc(p.label)+'</button></div>').join("");
  return s}
async function startOllama(){$("ollamaout").textContent="Starting Ollama...";const d=await api("/api/start-ollama",{});$("ollamaout").innerHTML=d.ok?'<span class="ok">'+esc(d.text)+'</span>':'<span class="bad">'+esc(d.text)+'</span>';refreshStatus();alertIfOff(d)}
function alertIfOff(d){if(!d.ok&&!$("health").classList.contains("on"))alert(d.text)}
function refreshAll(){refreshStatus();if($("library").classList.contains("on"))loadLibrary();if($("score").classList.contains("on"))loadScores()}
// ---- library
let DOCS=[];
async function loadLibrary(){const d=await api("/api/library");if(d.offline)return;
  if(!d.vor){$("libstats").textContent="Vor is not installed on this computer.";return}
  const v=d.vor;$("libstats").innerHTML='<span class="stat"><b>'+v.documents+'</b>documents indexed</span><span class="stat"><b>'+v.passages.toLocaleString()+'</b>passages</span><span class="stat"><b>'+v.files+'</b>files in the folder</span><div class="who">'+esc(v.home)+' · Vor '+esc(v.version)+'</div>';
  $("groups").innerHTML=(d.groups||[]).map(g=>'<tr><td><input type="checkbox" value="'+esc(g.id)+'"></td><td><b>'+esc(g.id)+'</b></td><td>'+esc(g.about)+(g.manual?' <span class="muted">('+g.manual+' to get by hand: see READING-LIST)</span>':'')+'</td><td class="n">'+g.have+' of '+g.total+'</td></tr>').join("")||'<tr><td colspan="4" class="muted">The download catalog is not installed here yet: install the latest update.</td></tr>';
  DOCS=d.docs||[];drawDocs()}
function drawDocs(){const f=$("docfilter").value.toLowerCase(),rows=DOCS.filter(d=>!f||(d.title+" "+d.number+" "+d.year+" "+d.org+" "+d.authors).toLowerCase().includes(f));
  $("docs").innerHTML=rows.slice(0,400).map(d=>'<tr><td>'+(d.pdf?'<a target="_blank" href="/pdf?k='+KEY+'&path='+encodeURIComponent(d.path)+'">'+esc(d.title)+'</a>':esc(d.title))+(d.org?' <span class="muted">· '+esc(d.org)+'</span>':'')+'</td><td>'+esc(d.number)+'</td><td>'+esc(d.year)+'</td><td class="n">'+d.pages+'</td></tr>').join("");
  $("docmore").textContent=rows.length>400?("Showing 400 of "+rows.length+": filter to find the rest."):(rows.length+" document(s)")}
$("docfilter").oninput=drawDocs;
$("fetchgo").onclick=()=>{const g=[...document.querySelectorAll("#groups input:checked")].map(x=>x.value);if(!g.length){alert("Tick at least one group.");return}startJob({action:"fetch",groups:g})};
async function upload(kind,file){const r=await fetch("/api/upload?kind="+kind+"&name="+encodeURIComponent(file.name),{method:"POST",headers:{"X-Key":KEY,"Content-Type":"application/octet-stream"},body:file});
  let d={};try{d=await r.json()}catch(e){d={error:"HTTP "+r.status}}return d}
async function addFiles(list){const files=[...list];if(!files.length)return;let ok=0,bad=[];
  for(let i=0;i<files.length;i++){$("dropout").textContent="Copying "+(i+1)+" of "+files.length+": "+files[i].name;const d=await upload("library",files[i]);if(d.error)bad.push(files[i].name+": "+d.error);else ok++}
  $("dropout").innerHTML=ok+" file(s) copied into the library."+(bad.length?' <span class="bad">'+esc(bad.join("; "))+'</span>':"");if(!ok)return;
  // a job already running (another drop, a download): index these when it ends
  const d=await api("/api/job",{action:"vor-ingest"});if(d.error&&d.job){PENDING=true;watch(d.job.id);$("dropout").innerHTML+=" They are indexed when '"+esc(d.job.title)+"' ends."}else if(d.error){if(!d.offline)alert(d.error)}else watch(d.id)}
const drop=$("drop");drop.onclick=()=>$("files").click();$("files").onchange=e=>addFiles(e.target.files);
drop.ondragover=e=>{e.preventDefault();drop.classList.add("over")};drop.ondragleave=()=>drop.classList.remove("over");
drop.ondrop=e=>{e.preventDefault();drop.classList.remove("over");addFiles(e.dataTransfer.files)};
// ---- scores
function md(t){const out=[];let tab=null;
  for(const line of t.split("\n")){
    if(/^\s*\|/.test(line)){const cells=line.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim());if(cells.every(c=>/^:?-+:?$/.test(c)))continue;
      if(!tab){tab=[];out.push(tab)}tab.push(cells);continue}
    tab=null;if(/^#+\s/.test(line))out.push("<h3>"+esc(line.replace(/^#+\s/,""))+"</h3>");else if(line.trim())out.push("<p>"+esc(line)+"</p>")}
  return out.map(x=>Array.isArray(x)?"<table>"+x.map((r,i)=>"<tr>"+r.map(c=>i?"<td>"+esc(c)+"</td>":"<th>"+esc(c)+"</th>").join("")+"</tr>").join("")+"</table>":x).join("")}
async function loadScores(){let t="";try{const r=await fetch("/api/scores?k="+KEY);if(r.status===403){offline(STOPPED);return}t=await r.text()}catch(e){offline(STOPPED);return}$("scores").innerHTML=t.trim()?md(t):"No scores yet: press Test Vor or Test both.";$("scores").classList.toggle("muted",!t.trim())}
// ---- health and update
$("docgo").onclick=()=>stream("/api/run",{action:"doctor"},$("docout"),null,true);
$("ollamago").onclick=startOllama;
let UPDATE=null;
$("upzip").onchange=async e=>{const f=e.target.files[0];if(!f)return;UPDATE=null;$("upgo").disabled=true;$("upinfo").textContent="Checking "+f.name+"...";
  const d=await upload("update",f);if(d.error){$("upinfo").innerHTML='<span class="bad">'+esc(d.error)+'</span>';return}
  UPDATE=d.folder;$("upinfo").innerHTML="Ready: "+esc(d.zip)+". Vor "+esc(d.now.vor||"not installed")+" &rarr; <b>"+esc(d.new.vor||"?")+"</b>, this page "+esc(d.now.ai)+" &rarr; <b>"+esc(d.new.ai||"?")+"</b>.";$("upgo").disabled=false};
$("upgo").onclick=()=>{if(UPDATE&&confirm("Install this update now? It takes a few minutes; your library, indexes and models are kept."))startJob({action:"update",folder:UPDATE})};
// ---- ask, runs, add (as before)
$("askgo").onclick=()=>stream("/api/ask",{q:$("q").value,target:$("target").value},$("answer"),$("who"));
$("q").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey))$("askgo").click()});
document.querySelectorAll("[data-a]").forEach(b=>b.onclick=async()=>{
  const a=b.dataset.a,dam=$("dam").value,svg=$("chart");svg.style.display="none";
  stream("/api/run",{action:a,dam:dam,place:$("place").value},$("runsout"));
  if(a==="hydrograph"&&dam){const d=await (await fetch("/api/hydrograph?k="+KEY+"&dam="+encodeURIComponent(dam))).json();if(Array.isArray(d)&&d.length)draw(svg,d)}});
function draw(svg,series){
  const W=900,H=280,L=60,B=30,all=series.flatMap(s=>s.points),tx=Math.max(...all.map(p=>p[0]))||1,qx=Math.max(...all.map(p=>p[1]))||1;
  const X=t=>L+(W-L-10)*t/tx,Y=q=>H-B-(H-B-10)*q/qx,cols=["var(--accent)","var(--watch)","var(--ok)","var(--bad)","var(--muted)","var(--ink)"];
  let g='<line x1="'+L+'" y1="'+(H-B)+'" x2="'+W+'" y2="'+(H-B)+'" stroke="var(--line)"/><line x1="'+L+'" y1="10" x2="'+L+'" y2="'+(H-B)+'" stroke="var(--line)"/>';
  g+='<text x="'+L+'" y="'+(H-8)+'">0 h</text><text x="'+(W-60)+'" y="'+(H-8)+'">'+tx.toFixed(1)+' h</text><text x="4" y="16">'+Math.round(qx).toLocaleString()+' cfs</text>';
  series.forEach((s,i)=>{g+='<polyline fill="none" stroke-width="2" stroke="'+cols[i%6]+'" points="'+s.points.map(p=>X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)).join(" ")+'"/>';
    g+='<text x="'+(L+10)+'" y="'+(24+14*i)+'" style="fill:'+cols[i%6]+'">'+esc(s.label)+'</text>'});
  svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.innerHTML=g;svg.style.display="block"}
$("addgo").onclick=()=>stream("/api/run",{action:"add",path:$("path").value,to:$("to").value},$("addout"));
// ---- start: the banner, a job already running (from before this window opened), and a heartbeat
if(!KEY)offline("Open Local AI from its icon, or the address that ai printed in the terminal (it carries the key).");
else{refreshStatus();api("/api/jobs").then(d=>{if(d.job&&d.job.status==="running")watch(d.job.id)})}
setInterval(()=>{if(KEY)fetch("/api/ping?k="+KEY).then(r=>{if(r.ok)online();else offline(STOPPED)}).catch(()=>offline(STOPPED))},30000);
</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
