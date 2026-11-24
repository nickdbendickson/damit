#!/usr/bin/env python3
"""ai_ui.py 1.2.0 - one local page for both assistants (the `ai` command).

    ai                 open the page in your browser (http://127.0.0.1:<port>/, this computer only)
    ai --port 8765     a fixed port
    ai --no-browser    print the one-time link instead of opening it

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

Safety: the server binds 127.0.0.1, answers only requests whose Host is that address, and every
request must carry a random key in the X-Key header (other web pages in your browser cannot run
commands through it). Commands are fixed argument lists, never a shell. A PDF is served only from
Vor's library or Heim's index folders. Stdlib only. Ctrl+C stops it.

1.2.0 (security audit 2026-11-24): the key is never in an address. 127.0.0.1 is shared by every account
on the computer, and the browser is started with the address on its command line, which other local
users can list (ps, /proc/<pid>/cmdline) for as long as that browser runs. 1.1.0 put the key there
(/?k=<key>), so another account could read it and use the page as you (add your files to the library
and read them back through /pdf). Now `ai` opens /launch?c=<one-time code>. The server swaps a valid
code, once, for the page with the key in its body (the HTTP response to your browser's own loopback
connection); the page keeps the key in sessionStorage (this tab and this port only) and sends it only
in the X-Key header. The code is random, single-use, expires after LAUNCH_CODE_TTL_S and is compared in
constant time, so what stays visible on the command line is dead once the page has loaded. A key in
the query string (?k=) is no longer accepted. PDFs open through fetch + a blob: address. Residual risk
(the same as DamIT Desk's): a local user who uses the code before your browser does gets the page; your
browser then shows "already used", the terminal warns, and restarting `ai` makes a new key and code.
Same scheme as DamIT Desk (damit_crest/desktop/damit_desktop/__main__.py, LAUNCH_PATH).
"""
import argparse
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess  # nosec B404 - runs the assistants' own tools with fixed argument lists
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
RUN_SECONDS = 3600
LAUNCH_PATH = "/launch"
LAUNCH_CODE_TTL_S = 120.0          # --no-browser: LAUNCH_CODE_TTL_PRINTED_S (the link is copied by hand)
LAUNCH_CODE_TTL_PRINTED_S = 600.0
_launch_lock = threading.Lock()
_launch = {"code": None, "expires": 0.0, "used": False}


def issue_launch_code(ttl=LAUNCH_CODE_TTL_S):
    """A fresh one-time launch code (replaces any earlier one)."""
    code = secrets.token_urlsafe(32)
    with _launch_lock:
        _launch.update(code=code, expires=time.monotonic() + ttl, used=False)
    return code


def consume_launch_code(code):
    """'ok' (and the code is spent), 'used', 'expired' or 'invalid'. Constant-time compare; one success per code."""
    with _launch_lock:
        current = _launch["code"]
        if not current or not code or not hmac.compare_digest(code.encode(), current.encode()):
            return "invalid"
        if _launch["used"]:
            return "used"
        if time.monotonic() > _launch["expires"]:
            _launch["used"] = True
            return "expired"
        _launch["used"] = True
        return "ok"


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
    return os.path.expanduser(os.environ.get("VOR_HOME") or os.path.join(HOME, "Vor"))


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


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-ui/" + VERSION
    key = ""
    port = 0

    def log_message(self, fmt, *args):      # quiet: the terminal shows only the address
        pass

    # ------------------------------------------------------------------ guards
    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port)

    def _key_ok(self):
        """The key, in the X-Key header only (1.2.0: never from the address, see the module docstring)."""
        got = self.headers.get("X-Key") or ""
        return bool(got) and bool(self.key) and hmac.compare_digest(got.encode(), self.key.encode())

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _page(self, key):
        return PAGE.replace("__KEY__", key).replace("__VERSION__", VERSION)

    def _serve_launch(self, query):
        """Swap the one-time launch code for the page with the key in its body (never in an address)."""
        result = consume_launch_code((query.get("c") or [""])[0])
        if result == "ok":
            return self._send(200, self._page(self.key), "text/html; charset=utf-8")
        if result == "used":
            print("ai: WARNING - the one-time link was used more than once. If the page in your browser says so, "
                  "another program used it first: stop ai (Ctrl+C) and start it again.", flush=True)
        msg = {"used": "This link was already used. Use the Heim and Vor tab that is already open, or stop ai "
                       "(Ctrl+C in its terminal) and start it again for a new link.",
               "expired": "This link has expired. Stop ai (Ctrl+C in its terminal) and start it again."}.get(
            result, "This is not a valid link. Stop ai (Ctrl+C in its terminal) and start it again.")
        return self._send(410 if result in ("used", "expired") else 403, msg)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _stream(self, who, argv, after=None):
        """Run argv and send its output as it is written (chunked)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Answered-By", who)
        self.end_headers()

        def chunk(text):
            b = text.encode("utf-8")
            if b:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(b), b))
                self.wfile.flush()
        started = time.time()
        try:
            env = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1")
            with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  env=env) as p:  # nosec B603 - fixed argument list, no shell
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
        if u.path == LAUNCH_PATH:
            return self._serve_launch(q)
        if u.path == "/":
            # no key in this copy: a reload in the same tab takes it from sessionStorage (see PAGE)
            return self._send(200, self._page(""), "text/html; charset=utf-8")
        if not self._key_ok():
            return self._send(403, "missing key")
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
        return self._send(404, "not found")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._host_ok() or not self._key_ok():
            return self._send(403, "forbidden")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
        except ValueError:
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
        return self._send(404, "not found")


def launch_url(port, code):
    """The address `ai` opens or prints: a one-time launch code, never the key (see the module docstring)."""
    return "http://127.0.0.1:%d%s?c=%s" % (port, LAUNCH_PATH, code)


def serve(port=0, open_browser=True):
    Handler.key = secrets.token_urlsafe(32)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    Handler.port = httpd.server_address[1]
    code = issue_launch_code(LAUNCH_CODE_TTL_S if open_browser else LAUNCH_CODE_TTL_PRINTED_S)
    url = launch_url(Handler.port, code)
    print("Heim and Vor: %s\n(a one-time link: it works once, for %d minutes; this computer only; Ctrl+C stops it)"
          % (url, int((LAUNCH_CODE_TTL_S if open_browser else LAUNCH_CODE_TTL_PRINTED_S) // 60)), flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai", description="One local page for Heim and Vor (127.0.0.1 only).")
    ap.add_argument("--port", type=int, default=0, help="port (default: any free one)")
    ap.add_argument("--no-browser", action="store_true", help="print the one-time link instead of opening it")
    a = ap.parse_args(argv)
    serve(a.port, not a.no_browser)
    return 0


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heim and Vor</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--accent:#2f5d8a;--ok:#2e7d4f;--watch:#a86b00;--bad:#b3261e;--code:#f1f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a3a29b;--line:#34332f;--accent:#8db4dd;--ok:#6cc391;--watch:#e0a84a;--bad:#ef7a72;--code:#262624}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header small{color:var(--muted)}
nav{display:flex;gap:4px}nav button{background:none;border:1px solid transparent;border-radius:6px;padding:6px 12px;color:var(--ink);cursor:pointer;font:inherit}
nav button.on{border-color:var(--line);background:var(--panel)}
main{max-width:1000px;margin:0 auto;padding:16px}section{display:none}section.on{display:block}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}
textarea,input,select{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px}
textarea{min-height:70px;resize:vertical}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.row>*{flex:1 1 160px}.row button{flex:0 0 auto}
button.go{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:8px 16px;cursor:pointer;font:inherit}
@media (prefers-color-scheme:dark){button.go{color:#111}}
pre{white-space:pre-wrap;word-break:break-word;background:var(--code);border-radius:8px;padding:12px;margin:0;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;min-height:40px}
.who{color:var(--muted);font-size:13px;margin:6px 0}a{color:var(--accent)}
.ok{color:var(--ok)}.watch{color:var(--watch)}.bad{color:var(--bad)}
pre:empty{display:none}svg{width:100%;height:280px}svg text{fill:var(--muted);font-size:11px}
</style></head><body>
<header><h1>Heim and Vor</h1><small>runs on this computer only · ai_ui __VERSION__</small>
<nav><button data-t="ask" class="on">Ask</button><button data-t="runs">Runs</button><button data-t="add">Add</button><button data-t="health">Health</button></nav></header>
<main>
<section id="ask" class="on"><div class="card">
<textarea id="q" placeholder="Ask in plain words, e.g.  what breach width does Froehlich 2008 give?  ·  how deep is the water at County Road 26 for 2801?  ·  what does REFINE_NEAR do?"></textarea>
<div class="row"><select id="target"><option value="auto">Pick for me</option><option value="vor">Publications (Vor): standards and papers, every quote checked</option><option value="heim">This software (Heim): tools, settings, errors, code</option><option value="runs">My run results: exact numbers from runs I read in</option></select><button class="go" id="askgo">Ask</button></div>
</div><div class="who" id="who"></div><pre id="answer"></pre></section>
<section id="runs"><div class="card">
<div class="row"><input id="dam" placeholder="dam: DWR-2801, 2801 or part of the name"><input id="place" placeholder="place (for 'at'): an address, road, structure id or lat,lon"></div>
<div class="row"><button class="go" data-a="list">List runs</button><button class="go" data-a="show">Show</button><button class="go" data-a="compare">Compare</button><button class="go" data-a="at">At place</button><button class="go" data-a="hydrograph">Hydrograph</button></div>
</div><svg id="chart" style="display:none"></svg><pre id="runsout"></pre></section>
<section id="add"><div class="card">
<input id="path" placeholder="a file or folder path (drag it into Terminal to copy its path, then paste here)">
<div class="row"><select id="to"><option value="heim">Heim: a run folder (read into the run results) or a document about the software</option><option value="vor">Publications library (Vor): a PDF</option></select><button class="go" id="addgo">Add</button></div>
</div><pre id="addout"></pre></section>
<section id="health"><div class="card"><button class="go" id="docgo">Run ai-doctor</button></div><pre id="docout"></pre></section>
</main>
<div id="nokey" class="card" style="display:none">This tab has no key. Open the one-time link that <code>ai</code> printed, or stop <code>ai</code> (Ctrl+C) and start it again.</div>
<script>
// 1.2.0: the key comes only in the body of the one-time /launch page, is kept in sessionStorage (this tab, this
// port) and is sent only in the X-Key header. The address bar is set back to "/" so the code is not reused.
const KEY=(function(){const k="__KEY__";try{if(k){sessionStorage.setItem("ai-ui-key",k);history.replaceState(null,"","/");return k}return sessionStorage.getItem("ai-ui-key")||""}catch(e){return k}})();
if(!KEY)document.getElementById("nokey").style.display="block";
async function openPdf(path,page){
  const w=window.open("about:blank","_blank");
  try{const r=await fetch("/pdf?path="+encodeURIComponent(path),{headers:{"X-Key":KEY}});
    if(!r.ok)throw new Error(await r.text());
    const u=URL.createObjectURL(await r.blob());if(w)w.location=u+(page?"#page="+page:"");else location.href=u}
  catch(e){if(w)w.close();alert(String(e.message||e))}}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button,section").forEach(x=>x.classList.remove("on"));b.classList.add("on");document.getElementById(b.dataset.t).classList.add("on")});
function esc(s){return s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function linkify(t){
  let h=esc(t);
  h=h.replace(/file:\/\/([^\s)#"]+\.pdf)(#page=(\d+))?/gi,(m,p,_,n)=>'<a href="#" data-pdf="'+esc(decodeURIComponent(p))+'" data-page="'+(n||'')+'">'+esc(decodeURIComponent(p).split('/').pop())+(n?' p.'+n:'')+'</a>');
  h=h.replace(/\[report\] (\S+\.md)/g,(m,p)=>'<a href="#" data-report="'+esc(p)+'">open the full report</a>');
  h=h.replace(/\b(PROBLEM)\b/g,'<span class="bad">$1</span>').replace(/\b(WATCH)\b/g,'<span class="watch">$1</span>').replace(/^(\s*)(ok|OK)\b/gm,'$1<span class="ok">$2</span>');
  return h}
async function stream(url,body,out,who){
  out.textContent="";let text="";
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-Key":KEY},body:JSON.stringify(body)});
  if(who)who.textContent=r.headers.get("X-Answered-By")?("Answered by "+r.headers.get("X-Answered-By")):"";
  const rd=r.body.getReader(),dec=new TextDecoder();
  for(;;){const {value,done}=await rd.read();if(done)break;text+=dec.decode(value,{stream:true});out.innerHTML=linkify(text);out.scrollTop=out.scrollHeight}
  wire(out);
}
function wire(out){
  out.querySelectorAll("a[data-pdf]").forEach(a=>a.onclick=e=>{e.preventDefault();openPdf(a.dataset.pdf,a.dataset.page)});
  out.querySelectorAll("a[data-report]").forEach(a=>a.onclick=async e=>{e.preventDefault();const t=await (await fetch("/api/report?path="+encodeURIComponent(a.dataset.report),{headers:{"X-Key":KEY}})).text();
    out.innerHTML=linkify(t.replace(/\]\((file:[^)]+)\)/g," $1"));wire(out)});
}
document.getElementById("askgo").onclick=()=>stream("/api/ask",{q:document.getElementById("q").value,target:document.getElementById("target").value},document.getElementById("answer"),document.getElementById("who"));
document.getElementById("q").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey))document.getElementById("askgo").click()});
document.querySelectorAll("[data-a]").forEach(b=>b.onclick=async()=>{
  const a=b.dataset.a,dam=document.getElementById("dam").value,svg=document.getElementById("chart");svg.style.display="none";
  stream("/api/run",{action:a,dam:dam,place:document.getElementById("place").value},document.getElementById("runsout"));
  if(a==="hydrograph"&&dam){const d=await (await fetch("/api/hydrograph?dam="+encodeURIComponent(dam),{headers:{"X-Key":KEY}})).json();if(Array.isArray(d)&&d.length)draw(svg,d)}});
function draw(svg,series){
  const W=900,H=280,L=60,B=30,all=series.flatMap(s=>s.points),tx=Math.max(...all.map(p=>p[0]))||1,qx=Math.max(...all.map(p=>p[1]))||1;
  const X=t=>L+(W-L-10)*t/tx,Y=q=>H-B-(H-B-10)*q/qx,cols=["var(--accent)","var(--watch)","var(--ok)","var(--bad)","var(--muted)","var(--ink)"];
  let g='<line x1="'+L+'" y1="'+(H-B)+'" x2="'+W+'" y2="'+(H-B)+'" stroke="var(--line)"/><line x1="'+L+'" y1="10" x2="'+L+'" y2="'+(H-B)+'" stroke="var(--line)"/>';
  g+='<text x="'+L+'" y="'+(H-8)+'">0 h</text><text x="'+(W-60)+'" y="'+(H-8)+'">'+tx.toFixed(1)+' h</text><text x="4" y="16">'+Math.round(qx).toLocaleString()+' cfs</text>';
  series.forEach((s,i)=>{g+='<polyline fill="none" stroke-width="2" stroke="'+cols[i%6]+'" points="'+s.points.map(p=>X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)).join(" ")+'"/>';
    g+='<text x="'+(L+10)+'" y="'+(24+14*i)+'" style="fill:'+cols[i%6]+'">'+esc(s.label)+'</text>'});
  svg.setAttribute("viewBox","0 0 "+W+" "+H);svg.innerHTML=g;svg.style.display="block"}
document.getElementById("addgo").onclick=()=>stream("/api/run",{action:"add",path:document.getElementById("path").value,to:document.getElementById("to").value},document.getElementById("addout"));
document.getElementById("docgo").onclick=()=>stream("/api/run",{action:"doctor"},document.getElementById("docout"));
</script></body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
