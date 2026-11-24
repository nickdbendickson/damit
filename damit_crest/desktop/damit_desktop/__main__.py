"""Open the DamIT Desk desk in a desktop window.

Serves the bundled web desk (damit_desktop/web/, built by `npm run build:desktop`) on 127.0.0.1 and shows it in a pywebview
window. Exports go through a native Save dialog (`window.pywebview.api.save_file`, and `save_file_b64` for the view
PDF / PNG), because blob downloads do nothing
inside a webview. If pywebview cannot start, the desk opens in the system browser, where downloads work as usual.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hmac
import json
import os
import secrets
import shutil
import sys
import threading
import time
import uuid
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from damit_desktop import WEB_DIR_NAME
from damit_desktop import browser_io
from damit_desktop import classify_receptors
from damit_desktop import defaults
from damit_desktop import localdem
from damit_desktop import nid
from damit_desktop import profile as desk_profile
from damit_desktop import qgis_run
from damit_desktop.qgis_run import (
    WorkFolderError,
    handoff_config,
    resolve_work,
    run_classify,
    run_data,
    run_finder,
    run_folder,
    run_layers,
    run_model,
    run_pmp,
    run_screening,
)

#: Fixed local port, so the desk's saved records (browser localStorage is per origin) survive a restart. It differs from
#: Crest's 47231 so both apps can run side by side.
#: If it is taken, a random port is used for that session.
PREFERRED_PORT = 47241


class PortBusyError(OSError):
    """The fixed port asked for (DAMIT_PORT or "port" in the settings file) is in use."""


def configured_port(settings_file: Path | None = None, env: dict | None = None) -> int | None:
    """The fixed port the user asked for: DAMIT_PORT, else "port" in damit-desk-settings.json; None = the default
    (PREFERRED_PORT, or a random port when it is busy). A value that is not 1024-65535 is ignored with a message."""
    env = os.environ if env is None else env
    raw = (env.get("DAMIT_PORT") or "").strip()
    where = "DAMIT_PORT"
    if not raw and settings_file is not None:
        try:
            data = json.loads(Path(settings_file).read_text(encoding="utf-8"))
            raw = str(data.get("port") or "").strip() if isinstance(data, dict) else ""
            where = f"\"port\" in {Path(settings_file).name}"
        except (OSError, ValueError):
            raw = ""
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        port = -1
    if not 1024 <= port <= 65535:
        print(f"DamIT Desk: {where} = {raw!r} is not a port from 1024 to 65535; using the default.", flush=True)
        return None
    return port

TITLE = "DamIT Desk"

# Official DaMiT wordmark (docs/img/damit-wordmark-light.png), copied next to this package as icon.png
# so python run.py and the packaged app can find it without Node or a Vite-hashed asset name.
_ICON_NAME = "icon.png"


def logo_path() -> Path | None:
    """The DaMiT wordmark for the native window / packaged-app icon, or None if it is not on disk."""
    here = Path(__file__).resolve().parent
    candidates = [here / _ICON_NAME]
    # A source checkout also has the original at the repo root.
    try:
        repo_logo = here.parents[2] / "docs" / "img" / "damit-wordmark-light.png"
        candidates.append(repo_logo)
    except IndexError:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        candidates.extend(
            [
                root / "damit_desktop" / _ICON_NAME,
                root / _ICON_NAME,
                root / "docs" / "img" / "damit-wordmark-light.png",
            ]
        )
    for path in candidates:
        if path.is_file():
            return path
    return None



#: Injected into the desk after every page load (evaluate_js runs outside the page CSP, and webview_csp.py keeps it
#: from using eval, so script-src 'self' does not block it). It keeps the window on its own 127.0.0.1 origin: a click
#: on an off-origin http(s) link, or a window.open to one, is cancelled and handed to the OS browser via
#: window.pywebview.api.open_external. Same-origin links and non-web schemes (blob:, data:, about:, mailto:) are left
#: to the page, so nothing legitimate changes.
NAV_GUARD_JS = r"""
(function () {
  if (window.__damitNavGuard) return;
  window.__damitNavGuard = true;
  var ORIGIN = window.location.origin;
  function external(url) {
    try {
      var u = new URL(url, window.location.href);
      if (u.protocol !== "http:" && u.protocol !== "https:") return null;
      return u.origin === ORIGIN ? null : u.href;
    } catch (e) { return null; }
  }
  document.addEventListener("click", function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (!a) return;
    var href = external(a.getAttribute("href"));
    if (!href) return;
    ev.preventDefault();
    ev.stopPropagation();
    try { window.pywebview.api.open_external(href); } catch (e) {}
  }, true);
  var nativeOpen = window.open;
  window.open = function (url) {
    var href = url ? external(String(url)) : null;
    if (href) { try { window.pywebview.api.open_external(href); } catch (e) {} return null; }
    return nativeOpen.apply(window, arguments);
  };
})();
"""

#: Random per-launch secret. main() opens the desk at index.html#damit-token=<token>: a URL fragment is never sent
#: over HTTP, so no request to this server - from another local process or another OS user on a shared host - can
#: obtain it (security audit 2026-11-18: it used to be written into <meta name="damit-token"> of the served page).
#: The page keeps it in sessionStorage (src/lib/crest/desktop-server.ts); every /api/ call must send it back in the
#: X-DamIT-Token header. It is never written into the page markup and no endpoint returns it. A custom header also forces a CORS preflight, which this server never
#: answers, so other web origins cannot reach the API from a browser.
TOKEN_HEADER = "X-DamIT-Token"
API_TOKEN = secrets.token_urlsafe(32)

#: Browser fallback (no pywebview window): the OS starts the browser with the address on its command line, which other
#: local users can list (ps, /proc/<pid>/cmdline, Task Manager) for as long as that browser runs. So the fallback never
#: puts API_TOKEN there. It opens /launch?code=<one-time code> instead; the server swaps a valid code, once, for a
#: 303 redirect to index.html#damit-token=<token>, carried only in the HTTP response to the browser's own loopback
#: connection. The code is random, single-use, expires after LAUNCH_CODE_TTL_S and is compared in constant time, so
#: what stays visible on the command line is dead once the page has loaded. Residual risk (no fix without a channel the
#: other user cannot read): a local user who reads the code and uses it before the browser does gets the token; the
#: browser then gets the "already used" page, the terminal shows a warning, and restarting the desk makes a new token.
#: Same scheme as Crest (crest-desktop/crest/__main__.py).
LAUNCH_PATH = "/launch"
LAUNCH_CODE_TTL_S = 120.0
_launch_lock = threading.Lock()
_launch: dict = {"code": None, "expires": 0.0, "used": False}


def issue_launch_code(ttl: float = LAUNCH_CODE_TTL_S) -> str:
    """A fresh one-time launch code (replaces any earlier one)."""
    code = secrets.token_urlsafe(32)
    with _launch_lock:
        _launch.update(code=code, expires=time.monotonic() + ttl, used=False)
    return code


def consume_launch_code(code: str) -> str:
    """'ok' (and the code is spent), 'used', 'expired' or 'invalid'. Constant-time compare; one success per code."""
    with _launch_lock:
        current = _launch["code"]
        if not current or not code or not hmac.compare_digest(code.encode(), current.encode()):
            return "invalid"
        if _launch["used"]:
            return "used"
        if time.monotonic() > _launch["expires"]:
            _launch.update(used=True)
            return "expired"
        _launch.update(used=True)
        return "ok"
_LOCAL_HOSTS = ("127.0.0.1", "localhost")

#: damit-desk-settings.json (last Save folder, the chosen local DEM; read from damit-crest-settings.json before the
#: rename). Set by main(); tests set it directly.
SETTINGS_FILE: Path | None = None

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_cancels: dict[str, threading.Event] = {}

#: Keep this many jobs so the desk can still poll a just-finished run; evict the oldest finished ones past it.
#: Without a cap, finished jobs (each holding its whole log) accumulate for the life of the process.
MAX_JOBS = 40


def _evict_finished_locked() -> None:
    """Drop the oldest finished jobs once over MAX_JOBS. Running jobs are never evicted. Call under _jobs_lock.

    _jobs is insertion-ordered, so the finished ids come out oldest-first and the newest finished jobs are kept.
    """
    if len(_jobs) <= MAX_JOBS:
        return
    finished = [jid for jid, job in _jobs.items() if job.get("done")]
    for jid in finished[: len(_jobs) - MAX_JOBS]:
        _jobs.pop(jid, None)
        _cancels.pop(jid, None)


def _job_log(job: dict, line: str) -> None:
    with _jobs_lock:
        job["log"] += ("" if job["log"].endswith("\n") or not job["log"] else "\n") + str(line) + "\n"


def start_job(
    kind: str,
    dam: dict,
    analysis: dict,
    work: str | None,
    model: str = "lisflood",
    files=None,
    source: str = "pack",
    timeout: float | None = None,
    receptors: dict | None = None,
    profile: str = "us",
) -> dict:
    """Write the dam folder, fetch layers, or call the plugins on a background thread. Returns immediately.

    profile: the page's desk profile; the job runs under it (profile.profile_scope), so "nd" hands off to the DWR
    DamSafety plugins and "us" (the default) to the DamIT plugins.

    cancel_job(id) stops any job that runs qgis_process or the CLI (screening, model, classify, Download layers,
    Atlas 14, Find fills) and what it started; timeout (seconds) limits the screening chain (else
    DAMIT_SCREENING_TIMEOUT_S, else none). The plugin buttons have their own limits (qgis_run.plugin_timeout)."""
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "done": False, "ok": False, "log": "", "folder": "", "work": "", "cancelled": False}
    cancel = threading.Event()
    with _jobs_lock:
        _jobs[job_id] = job
        _cancels[job_id] = cancel
        _evict_finished_locked()

    def work_job():
        with desk_profile.profile_scope(profile):
            _work_job()

    def _work_job():
        try:
            log = lambda line: _job_log(job, line)
            if kind == "check":
                result = qgis_run.run_check(log, cancel=cancel)
            elif kind == "layers":
                result = run_layers(dam or {}, work, source, log)
            elif kind == "folder":
                result = run_folder(dam or {}, analysis or {}, work, log, files)
            elif kind == "model":
                result = run_model(dam or {}, analysis or {}, work, log, model, files, source, cancel=cancel)
            elif kind == "classify":
                result = run_classify(dam or {}, analysis or {}, work, log, files, cancel=cancel, receptors=receptors)
            elif kind == "data":
                result = run_data(dam or {}, analysis or {}, work, log, files, cancel=cancel)
            elif kind == "pmp":
                result = run_pmp(dam or {}, analysis or {}, work, log, files, cancel=cancel)
            elif kind == "finder":
                result = run_finder(dam or {}, analysis or {}, work, log, files, cancel=cancel)
            else:
                result = run_screening(dam or {}, analysis or {}, work, log, files, timeout=timeout, cancel=cancel,
                                       receptors=receptors)
            with _jobs_lock:
                job["ok"] = bool(result.get("ok"))
                job["cancelled"] = bool(result.get("cancelled"))
                if result.get("missingAlgorithm"):
                    job["missingAlgorithm"] = str(result["missingAlgorithm"])
                if result.get("chainIds"):
                    job["chainIds"] = list(result["chainIds"])
                if result.get("chainResult"):
                    job["chainResult"] = list(result["chainResult"])
                if result.get("check"):
                    job["check"] = list(result["check"])
                if isinstance(result.get("classification"), dict):
                    # damit:classify's class for the chosen jurisdiction; the Report step stores and leads with it.
                    job["classification"] = dict(result["classification"])
                for flag in ("noReceptors", "noDepth", "incomplete", "timedOut", "partial"):
                    if result.get(flag):
                        job[flag] = True
                if result.get("warning"):
                    job["warning"] = str(result["warning"])
                job["folder"] = result.get("folder") or ""
                job["work"] = result.get("work") or ""
        except Exception as exc:
            _job_log(job, f"DamIT Desk stopped: {exc}")
        finally:
            with _jobs_lock:
                job["done"] = True
                _cancels.pop(job_id, None)

    threading.Thread(target=work_job, daemon=True).start()
    return {"id": job_id}


def cancel_job(job_id: str) -> dict:
    """Ask a running job to stop. Layers and folder jobs run no external program and finish on their own."""
    with _jobs_lock:
        found = _jobs.get(job_id)
        event = _cancels.get(job_id)
        if not found:
            return {"error": "no job"}
        if found["done"] or event is None:
            return {"id": job_id, "done": True}
        event.set()
    _job_log(found, "Cancel requested. Stopping qgis_process…")
    return {"id": job_id, "cancelling": True}


def job_snapshot(job_id: str) -> dict | None:
    with _jobs_lock:
        found = _jobs.get(job_id)
        return dict(found) if found else None


def web_dir() -> Path:
    """The bundled web desk: next to this file, or inside the PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "damit_desktop" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / WEB_DIR_NAME


def check_bundle(root: Path | None = None) -> Path:
    root = root or web_dir()
    index = root / "index.html"
    if not index.is_file():
        raise SystemExit(
            f"DamIT Desk desktop: the web desk bundle is missing ({index}).\n"
            "Build it from the repo root with `npm ci && npm run build:desktop`."
        )
    return root


#: Sent when the bundle has no security-headers.json (an older bundle): scripts and data from this server only.
_FALLBACK_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; connect-src 'self' data: blob: https:; worker-src 'self' blob:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


def load_security_headers(root: Path) -> dict[str, str]:
    """The response headers the desktop build wrote beside the bundle (web/security-headers.json).

    The Content-Security-Policy there is built from src/lib/crest/csp.ts, the same source as DamIT.html's meta tag:
    scripts from this server only, and the named tile and lookup services. DAMIT_NO_CSP=1 drops the policy (not the
    other headers), for a webview that turns out to need something the policy does not allow.
    """
    try:
        loaded = json.loads((root / "security-headers.json").read_text(encoding="utf-8"))
        headers = {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        headers = {}
    if "Content-Security-Policy" not in headers:
        headers = dict(_FALLBACK_SECURITY_HEADERS)
    # A header value is one line: a newline in the file must not become a second header.
    headers = {k: v for k, v in headers.items() if "\n" not in k + v and "\r" not in k + v}
    if os.environ.get("DAMIT_NO_CSP") == "1":
        headers.pop("Content-Security-Policy", None)
    return headers


class _Handler(SimpleHTTPRequestHandler):
    #: Set per server by serve() from the bundle's security-headers.json.
    security_headers: dict[str, str] = dict(_FALLBACK_SECURITY_HEADERS)

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".html": "text/html; charset=utf-8",
    }

    # ---- request checks (see TOKEN_HEADER) -------------------------------------------------------------------
    def _port(self) -> int:
        return int(self.server.server_address[1])

    def _host_ok(self) -> bool:
        """Host must name this loopback server (blocks DNS rebinding)."""
        host = (self.headers.get("Host") or "").strip().lower()
        return host in {f"{h}:{self._port()}" for h in _LOCAL_HOSTS}

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.strip().lower() in {f"http://{h}:{self._port()}" for h in _LOCAL_HOSTS}

    def _token_ok(self) -> bool:
        return hmac.compare_digest((self.headers.get(TOKEN_HEADER) or "").encode(), API_TOKEN.encode())

    def _api_allowed(self, need_json: bool = False) -> bool:
        """Sends a 403/415 and returns False when the request is not from the desk itself."""
        if not (self._host_ok() and self._origin_ok() and self._token_ok()):
            self._send(403, b'{"error":"forbidden"}', "application/json")
            return False
        if need_json:
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                self._send(415, b'{"error":"content type must be application/json"}', "application/json")
                return False
        return True

    def _serve_index(self) -> None:
        index = Path(self.directory) / "index.html"
        html = index.read_text(encoding="utf-8")
        # The token is NOT injected into the page (see API_TOKEN): any local peer can GET / on the loopback port.
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_launch(self, query: dict) -> None:
        """Browser fallback: swap the one-time launch code for a redirect that carries the token in the fragment."""
        code = (query.get("code") or [""])[0]
        result = consume_launch_code(code)
        if result == "ok":
            self.send_response(303)
            self.send_header("Location", f"/index.html#damit-token={API_TOKEN}{profile_fragment()}")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if result == "used":
            print("DamIT Desk: WARNING - the browser launch link was used more than once. If the desk in your "
                  "browser says so, another program used it first: stop DamIT Desk (Ctrl+C) and start it again.",
                  flush=True)
        msg = {
            "used": "This DamIT Desk launch link was already used. Use the DamIT Desk tab that is already open, or "
                    "stop DamIT Desk (Ctrl+C in its terminal) and start it again for a new link.",
            "expired": "This DamIT Desk launch link has expired. Stop DamIT Desk (Ctrl+C in its terminal) and start "
                       "it again.",
        }.get(result, "This is not a valid DamIT Desk launch link. Stop DamIT Desk (Ctrl+C in its terminal) and "
                      "start it again.")
        self._send(410 if result in ("used", "expired") else 403, msg.encode("utf-8"), "text/plain; charset=utf-8")

    def do_GET(self):
        if not self._host_ok():
            self._send(403, b"forbidden", "text/plain")
            return
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._serve_index()
            return
        if parsed.path == LAUNCH_PATH:
            self._serve_launch(parse_qs(parsed.query))
            return
        if parsed.path.startswith("/api/") and not self._api_allowed():
            return
        if parsed.path == "/api/dem":
            self._send_dem(parse_qs(parsed.query))
            return
        if parsed.path == "/api/vertcon":
            self._send_vertcon(parse_qs(parsed.query))
            return
        if parsed.path == "/api/nid/state":
            self._send_nid(parse_qs(parsed.query))
            return
        if parsed.path in ("/api/fs/list", "/api/dem/choice", "/api/export_dir"):
            self._browser_get(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/api/handoff":
            # The algorithm ids the buttons will call (DamIT defaults or overrides), for the Report step to show.
            # Also the folder a blank Work folder field means, and a one-line notice when this run's settings came
            # over from the old DamIT Crest folder (2026-11-21: that copy was only printed in the terminal).
            with desk_profile.profile_scope((parse_qs(parsed.query).get("profile") or [""])[0]):
                info = handoff_config().as_json()
            info["work"] = str(qgis_run.default_work_dir())
            info["notices"] = list(STORAGE_NOTICES)
            self._send(200, json.dumps(info).encode(), "application/json")
            return
        if parsed.path == "/api/classify/receptors":
            # The real receptors damit:classify judged (its GeoPackage), with names and a point to zoom to.
            self._reply(lambda: classify_receptors.read_receptors(
                classify_receptors.gpkg_path((parse_qs(parsed.query).get("gpkg") or [""])[0])))
            return
        if parsed.path == "/api/handoff/autofill":
            # Paths for the hand-off form: the chosen DEM, the imported run's rasters found by name, a rail lookup CSV.
            q = parse_qs(parsed.query)
            names = [n for n in (q.get("names") or [""])[0].split(",") if n.strip()]
            self._reply(lambda: browser_io.autofill(SETTINGS_FILE, names))
            return
        if parsed.path == "/api/job":
            job_id = (parse_qs(parsed.query).get("id") or [""])[0]
            found = job_snapshot(job_id)
            if not found:
                self._send(404, b'{"error":"no job"}', "application/json")
                return
            self._send(200, json.dumps(found).encode(), "application/json")
            return
        super().do_GET()

    def _send_nid(self, query: dict) -> None:
        """One state's NID dams (nid.py): cached in the settings folder, downloaded once per state or on refresh."""
        state = (query.get("state") or [""])[0]
        refresh = (query.get("refresh") or [""])[0] in ("1", "true")
        try:
            bundle = nid.load_state(state, refresh=refresh)
        except nid.NidError as exc:
            code = 400 if "state code" in str(exc) else 502
            self._send(code, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        self._send(200, json.dumps(bundle, separators=(",", ":")).encode(), "application/json")

    def do_POST(self):
        parsed = urlparse(self.path)
        kinds = {
            "/api/screen": "screen",
            "/api/model": "model",
            "/api/folder": "folder",
            "/api/layers": "layers",
            "/api/classify": "classify",
            "/api/data": "data",
            "/api/pmp": "pmp",
            "/api/finder": "finder",
            "/api/check": "check",
        }
        kind = kinds.get(parsed.path)
        if not self._api_allowed():
            return
        if parsed.path == "/api/cancel":
            job_id = (parse_qs(parsed.query).get("id") or [""])[0]
            found = cancel_job(job_id)
            self._send(404 if found.get("error") else 200, json.dumps(found).encode(), "application/json")
            return
        if parsed.path in BROWSER_POST:
            if not self._api_allowed(need_json=True):
                return
            body = self._json_body(limit=MAX_SAVE_BODY if parsed.path == "/api/save" else 1_000_000)
            if body is not None:
                self._browser_post(parsed.path, body)
            return
        if kind is None:
            self._send(404, b"not found", "text/plain")
            return
        if not self._api_allowed(need_json=True):
            return
        # This handler reads a fixed Content-Length body; a chunked body would read as empty and start a job with
        # defaults instead of failing, so reject it explicitly. A malformed Content-Length is a 400, not a 500.
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self._send(400, b'{"error":"chunked request bodies are not supported"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send(400, b'{"error":"bad content length"}', "application/json")
            return
        if length < 0:
            self._send(400, b'{"error":"bad content length"}', "application/json")
            return
        if length > 20_000_000:
            self._send(413, b'{"error":"too large"}', "application/json")
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        if not isinstance(payload, dict):
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        dam = payload.get("dam") if isinstance(payload.get("dam"), dict) else {}
        if payload.get("dem"):
            dam = dict(dam)
            dam["demPath"] = payload.get("dem")
        # Classify: the model run's rasters (paths on this computer), for damit:classify's DEPTH / VELOCITY / DV / WSE /
        # NONBREACH / ARRIVAL.
        for key, field in (("depth", "depthRaster"), ("velocity", "velocityRaster"), ("dv", "dvRaster"),
                           ("wse", "wseRaster"), ("nonbreach", "nonbreachRaster"), ("arrival", "arrivalRaster"),
                           ("railLookup", "railTrainsLookup")):
            if isinstance(payload.get(key), str) and payload[key].strip():
                dam = dict(dam)
                dam[field] = payload[key].strip()
        model = str(payload.get("model") or "lisflood")
        source = str(payload.get("source") or "data").lower()
        if source == "pack":  # the Crest desk's name for the shared data folder
            source = "data"
        if source not in ("data", "download"):
            source = "data"
        files = payload.get("files") if isinstance(payload.get("files"), dict) else None
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        timeout = payload.get("timeout")
        timeout = timeout if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) else None
        try:
            work = resolve_work(payload.get("work"))
        except WorkFolderError as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        # Classify: the downstream receptor layers the desk built (classify-receptors.ts); receptors.py validates them.
        # Screen: the same payload when the desk sends one (else the record's mapped seeds), structures only.
        receptors = (payload.get("receptors") if kind in ("classify", "screen")
                     and isinstance(payload.get("receptors"), dict) else None)
        # The page's desk profile (Settings, or ?profile=nd): "nd" hands off to the DWR DamSafety plugins (profile.py).
        profile = desk_profile.normalize(payload.get("profile"))
        body = json.dumps(start_job(kind, dam, analysis, work, model, files, source, timeout, receptors, profile))
        self._send(200, body.encode(), "application/json")

    def _json_body(self, limit: int) -> dict | None:
        """The request's JSON object, or None after sending the 400 / 413."""
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self._send(400, b'{"error":"chunked request bodies are not supported"}', "application/json")
            return None
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._send(400, b'{"error":"bad content length"}', "application/json")
            return None
        if length > limit:
            self._send(413, b'{"error":"too large"}', "application/json")
            return None
        try:
            payload = json.loads((self.rfile.read(length) if length else b"{}").decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._send(400, b'{"error":"bad json"}', "application/json")
            return None
        return payload

    def _reply(self, fn) -> None:
        try:
            out = fn()
        except browser_io.BrowserIOError as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        except (OSError, ValueError) as exc:
            self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        self._send(200, json.dumps(out).encode(), "application/json")

    def _browser_get(self, path: str, query: dict) -> None:
        """Browser mode (browser_io.py): list a folder for the desk's file chooser, the chosen DEM, the exports folder."""
        if path == "/api/fs/list":
            mode = (query.get("mode") or ["dem"])[0]
            self._reply(lambda: browser_io.list_dir((query.get("dir") or [""])[0] or None, mode if mode in ("folder", "csv") else "dem",
                                                     SETTINGS_FILE))
        elif path == "/api/dem/choice":
            self._reply(lambda: browser_io.dem_state(SETTINGS_FILE))
        else:
            self._reply(lambda: {"dir": str(browser_io.export_dir(SETTINGS_FILE))})

    def _browser_post(self, path: str, body: dict) -> None:
        if path == "/api/dem/choose":
            self._reply(lambda: browser_io.choose_dem(SETTINGS_FILE, str(body.get("path") or "")))
        elif path == "/api/dem/clear":
            self._reply(lambda: browser_io.clear_dem(SETTINGS_FILE))
        elif path == "/api/export_dir":
            self._reply(lambda: {"dir": str(browser_io.set_export_dir(SETTINGS_FILE, str(body.get("path") or "")))})
        else:  # /api/save
            def save():
                if isinstance(body.get("b64"), str):
                    data = decode_b64(body["b64"])
                elif isinstance(body.get("text"), str):
                    data = body["text"].encode("utf-8")
                else:
                    raise browser_io.BrowserIOError("nothing to save")
                return {"saved": str(browser_io.save_export(SETTINGS_FILE, str(body.get("name") or ""), data))}

            self._reply(save)

    def _send_dem(self, query: dict) -> None:
        """Terrain from the local DEM chosen in the app (localdem.py); 409 when none is chosen."""
        src = localdem.read_dem_path(SETTINGS_FILE)
        if not src:
            self._send(409, b'{"error":"no local DEM chosen"}', "application/json")
            return
        try:
            bbox, width, height, cell = localdem.parse_request(query)
        except ValueError as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        try:
            body = localdem.read_window(src, bbox, width, height, cell)
        except Exception as exc:  # gdalwarp missing or failed: the desk shows the message
            self._send(502, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        self._send(200, body, "application/octet-stream")

    def _send_vertcon(self, query: dict) -> None:
        """NGVD29 → NAVD88 vertical offset for any CONUS point, via pyproj (ships with QGIS)."""
        try:
            lat = float((query.get("lat") or [""])[0])
            lon = float((query.get("lon") or [""])[0])
        except (ValueError, IndexError):
            self._send(400, b'{"error":"lat and lon required"}', "application/json")
            return
        try:
            from pyproj import Transformer
            # NGVD29 (EPSG:5102) → NAVD88 (EPSG:5103); the shift is NAVD88 - NGVD29
            t = Transformer.from_crs("EPSG:5102", "EPSG:5103", always_xy=True)
            _, _, shift_m = t.transform(lon, lat, 0.0)
            shift_ft = shift_m / 0.3048
            self._send(200, json.dumps({"shift_ft": round(shift_ft, 5), "shift_m": round(shift_m, 5),
                                        "source": "pyproj VERTCON (PROJ-data us_noaa_vertconc.tif)"}).encode(),
                       "application/json")
        except ImportError:
            self._send(501, json.dumps({"error": "pyproj not available; install QGIS or pyproj"}).encode(),
                       "application/json")
        except Exception as exc:
            self._send(502, json.dumps({"error": str(exc)}).encode(), "application/json")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Cache-Control: no-store is added for every response by the end_headers() override below,
        # so it is not repeated here (it was emitted twice per _send response).
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quiet
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        for name, value in self.security_headers.items():
            self.send_header(name, value)
        super().end_headers()


def serve(root: Path | None = None, port: int = PREFERRED_PORT, fixed: bool = False) -> ThreadingHTTPServer:
    """Serve the bundle on 127.0.0.1 in a daemon thread. Port 0 means any free port. fixed (a port the user set):
    a busy port is an error (PortBusyError) instead of a random port, so the saved records' address never changes."""
    root = check_bundle(root)
    bundle_handler = type("_BundleHandler", (_Handler,), {"security_headers": load_security_headers(root)})
    handler = partial(bundle_handler, directory=str(root))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as e:
        # Windows says WSAEACCES (10013) when the port is held with SO_EXCLUSIVEADDRUSE (or reserved): busy, too.
        busy = e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1), 10048) or (
            os.name == "nt" and getattr(e, "winerror", None) == 10013)
        if port == 0 or not busy:
            raise
        if fixed:
            raise PortBusyError(e.errno, f"DamIT Desk: port {port} (set with DAMIT_PORT or \"port\" in the settings "
                                         "file) is busy: close the program using it, or choose another port.") from e
        print(f"DamIT Desk: port {port} is busy (another DamIT Desk, or another program). Using a random port for this "
              "session: records saved in the browser are kept per address, so the ones from port "
              f"{port} are not shown until the desk runs on {port} again.", flush=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


#: The settings file in the storage folder (last Save folder, the chosen local DEM, the exports folder).
SETTINGS_NAME = "damit-desk-settings.json"
#: Its name before the rename to DamIT Desk (2026-11-20): still read when the new one is missing.
LEGACY_SETTINGS_NAME = "damit-crest-settings.json"
#: Written into the new folder when it was copied from the old DamIT Crest one: where from, and when.
MIGRATED_NOTE = "COPIED-FROM-DAMIT-CREST.txt"


#: One-line notices about this run's settings folder (a copy from the old DamIT Crest folder), for the Report step.
STORAGE_NOTICES: list[str] = []


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def storage_dir() -> Path:
    """Where the webview keeps localStorage (the desk's records) between runs, the settings and the NID cache."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "DamIT Desk"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DamIT Desk"
    return _data_home() / "damit-desk"


def legacy_storage_dir() -> Path:
    """The same folder under its DamIT Crest name, from before the rename (read, never changed or deleted)."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "DamIT Crest"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DamIT Crest"
    return _data_home() / "damit-crest"


def prepare_storage(log=print) -> tuple[Path, Path]:
    """(storage folder, settings file) for this run.

    First run after the rename: the old DamIT Crest folder is copied to the DamIT Desk one, so saved records, the
    chosen DEM and the NID cache carry over; the old folder is left exactly as it was. When the copy cannot be made the
    old folder is used as it is. Later runs: a settings file missing from the new folder is read from the old one."""
    store, legacy = storage_dir(), legacy_storage_dir()
    STORAGE_NOTICES.clear()

    def notice(line: str) -> None:
        STORAGE_NOTICES.append(line)
        log("DamIT Desk: " + line)

    if not store.exists() and legacy.is_dir():
        try:
            shutil.copytree(legacy, store, symlinks=True,
                            ignore=shutil.ignore_patterns("SingletonLock", "SingletonSocket", "SingletonCookie",
                                                          "*.lock", "lockfile"))
            notice(f"first start: copied the old DamIT Crest settings and records from {legacy} to {store}. "
                   "The old folder is left as it was; delete it yourself once you no longer need DamIT Crest.")
            try:
                (store / MIGRATED_NOTE).write_text(
                    f"Copied from {legacy} by DamIT Desk on {time.strftime('%Y-%m-%d %H:%M %Z')}.\n"
                    "The old folder was not changed.\n", encoding="utf-8")
            except OSError:
                pass
        except (OSError, shutil.Error) as exc:
            notice(f"could not copy the old DamIT Crest folder {legacy} to {store} ({exc}); using the old folder.")
            return legacy, _settings_in(legacy)
    store.mkdir(parents=True, exist_ok=True)
    settings = store / SETTINGS_NAME
    old = store / LEGACY_SETTINGS_NAME
    if not settings.exists():
        for source in (old, legacy / LEGACY_SETTINGS_NAME):
            if source.is_file():
                try:
                    shutil.copy2(source, settings)
                except OSError:
                    notice(f"reading the settings from the old file {source} (it could not be copied to {settings}).")
                    return store, source
                if source.parent != store:
                    notice(f"copied the old DamIT Crest settings file {source} to {settings}.")
                break
    return store, settings


def _settings_in(folder: Path) -> Path:
    new = folder / SETTINGS_NAME
    return new if new.is_file() or not (folder / LEGACY_SETTINGS_NAME).is_file() else folder / LEGACY_SETTINGS_NAME


def _save_dialog_type(webview_mod):
    file_dialog = getattr(webview_mod, "FileDialog", None)
    return file_dialog.SAVE if file_dialog is not None else webview_mod.SAVE_DIALOG


def _open_dialog_type(webview_mod):
    file_dialog = getattr(webview_mod, "FileDialog", None)
    return file_dialog.OPEN if file_dialog is not None else webview_mod.OPEN_DIALOG


def _file_types(name: str) -> tuple[str, ...]:
    ext = Path(name).suffix.lower().lstrip(".")
    labels = {"csv": "CSV", "json": "JSON", "par": "LISFLOOD parameters", "bci": "LISFLOOD boundary", "bdy": "LISFLOOD hydrograph", "geojson": "GeoJSON", "kml": "KML", "pdf": "PDF", "png": "PNG image"}
    if ext in labels:
        return (f"{labels[ext]} (*.{ext})", "All files (*.*)")
    return ("All files (*.*)",)


class Api:
    """Exposed to the page as window.pywebview.api (see src/lib/crest/save.ts)."""

    def __init__(self, settings_file: Path | None = None) -> None:
        # Underscored attributes are not exposed to JS by pywebview.
        self._window = None
        self._settings_file = settings_file  # remembers the last Save folder across sessions

    def _start_dir(self) -> str:
        """The folder of the last export if it still exists, else the home folder."""
        try:
            last = json.loads(self._settings_file.read_text(encoding="utf-8")).get("last_save_dir") if self._settings_file else None
        except (OSError, ValueError, AttributeError):
            last = None
        return last if isinstance(last, str) and Path(last).is_dir() else str(Path.home())

    def _remember_dir(self, folder: Path) -> None:
        if not self._settings_file:
            return
        try:
            data = json.loads(self._settings_file.read_text(encoding="utf-8")) if self._settings_file.is_file() else {}
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data["last_save_dir"] = str(folder)
        try:
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            self._settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # not worth failing an export over

    def get_dem(self) -> dict:
        """The local DEM the desk uses for terrain instead of 3DEP (None = 3DEP), and whether gdalwarp was found."""
        return {"path": localdem.read_dem_path(self._settings_file), "gdalwarp": localdem.find_gdalwarp()}

    def pick_dem(self) -> dict:
        """Choose the DEM file (e.g. ND_1m_EPSG26914.vrt) in an Open dialog and remember it."""
        import webview

        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return {"error": "no window"}
        current = localdem.read_dem_path(self._settings_file)
        start = str(Path(current).parent) if current else str(Path.home())
        types = ("DEM (*.vrt;*.tif;*.tiff;*.img)", "All files (*.*)")
        try:
            picked = window.create_file_dialog(_open_dialog_type(webview), directory=start, file_types=types)
        except Exception:  # some backends reject the file_types filter
            picked = window.create_file_dialog(_open_dialog_type(webview), directory=start)
        if not picked:
            return {"cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]
        if Path(path).suffix.lower() not in localdem.DEM_SUFFIXES:
            return {"error": f"Not a DEM file DamIT Desk reads ({', '.join(localdem.DEM_SUFFIXES)}): {path}"}
        if self._settings_file:
            localdem.write_dem_path(self._settings_file, path)
        return {"path": path, "gdalwarp": localdem.find_gdalwarp()}

    def clear_dem(self) -> dict:
        """Back to USGS 3DEP."""
        if self._settings_file:
            localdem.write_dem_path(self._settings_file, None)
        return {"path": None, "gdalwarp": localdem.find_gdalwarp()}

    def get_defaults(self) -> dict:
        """Your shared defaults file (defaults.py): its path and text, text None when you have none yet."""
        return defaults.read_user()

    def save_defaults(self, text: str) -> dict:
        """Write your shared defaults file, the one the DamIT plugins read too."""
        return defaults.write_user(text)

    def save_file(self, name: str, text: str) -> dict:
        import webview

        name = Path(str(name or "damit_export.txt")).name or "damit_export.txt"
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return {"error": "no window"}
        start = self._start_dir()
        try:
            picked = window.create_file_dialog(
                _save_dialog_type(webview), directory=start, save_filename=name, file_types=_file_types(name)
            )
        except Exception:  # some backends reject the file_types filter
            picked = window.create_file_dialog(_save_dialog_type(webview), directory=start, save_filename=name)
        if not picked:
            return {"cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]
        try:
            write_text(Path(path), text)
        except OSError as e:
            return {"error": str(e)}
        self._remember_dir(Path(path).resolve().parent)
        return {"saved": str(path)}

    def save_file_b64(self, name: str, b64: str) -> dict:
        """Binary exports (the view PDF / PNG): `b64` is the file as base64. Same Save dialog as save_file."""
        import webview

        try:
            data = decode_b64(b64)
        except ValueError as e:
            return {"error": str(e)}
        name = Path(str(name or "damit_export.bin")).name or "damit_export.bin"
        window = self._window or (webview.windows[0] if webview.windows else None)
        if window is None:
            return {"error": "no window"}
        start = self._start_dir()
        try:
            picked = window.create_file_dialog(
                _save_dialog_type(webview), directory=start, save_filename=name, file_types=_file_types(name)
            )
        except Exception:  # some backends reject the file_types filter
            picked = window.create_file_dialog(_save_dialog_type(webview), directory=start, save_filename=name)
        if not picked:
            return {"cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]
        try:
            write_bytes(Path(path), data)
        except OSError as e:
            return {"error": str(e)}
        self._remember_dir(Path(path).resolve().parent)
        return {"saved": str(path)}

    def open_external(self, url: str) -> dict:
        """Open an http/https link in the system browser. The desk window itself never leaves its own local origin:
        the page nav guard (NAV_GUARD_JS) routes every off-origin link here, so a link can never drive the app to
        another site. Any non-web scheme is refused rather than handed to the OS."""
        try:
            parsed = urlparse(str(url))
        except Exception:
            return {"error": "bad url"}
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"error": "only http/https links open in the browser"}
        webbrowser.open(url)
        return {"opened": url}


#: Largest binary export accepted from the page (a view PDF is a few MB).
MAX_BINARY_BYTES = 100 * 1024 * 1024
#: Largest /api/save request (base64 of MAX_BINARY_BYTES plus the JSON around it).
MAX_SAVE_BODY = MAX_BINARY_BYTES * 4 // 3 + 1_000_000
#: Browser-mode POSTs (browser_io.py).
BROWSER_POST = ("/api/dem/choose", "/api/dem/clear", "/api/save", "/api/export_dir")


def decode_b64(b64: str) -> bytes:
    """Strict base64 (a `data:...;base64,` prefix is allowed). Raises ValueError on anything else."""
    if not isinstance(b64, str):
        raise ValueError("the export was not sent as base64 text")
    text = b64.split(",", 1)[1] if b64.startswith("data:") and "," in b64 else b64
    text = "".join(text.split())
    if len(text) * 3 // 4 > MAX_BINARY_BYTES:
        raise ValueError("the export is too large")
    if text and not _canonical_b64(text):
        raise ValueError("the export was not valid base64")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the export was not valid base64") from None
    if not data:
        raise ValueError("the export is empty")
    return data


def _canonical_b64(text: str) -> bool:
    """True for canonical base64. Unpadded input is allowed; a stray '=' is not.

    b64decode(..., validate=True) still accepts 'QUJD=' (a pad on a complete
    group) and returns b'ABC'. That must not open a Save dialog.
    """
    pad = len(text) - len(text.rstrip("="))
    if pad > 2 or "=" in text[: len(text) - pad]:
        return False
    body = text[: len(text) - pad]
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" for c in body):
        return False
    rem = len(body) % 4
    if pad:
        return (rem == 2 and pad == 2) or (rem == 3 and pad == 1)
    return rem != 1


def write_bytes(path: Path, data: bytes) -> None:
    """Write a binary export as is; a partial file is not left behind if the write fails."""
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text(path: Path, text: str) -> None:
    """Write an export exactly as the desk produced it (UTF-8, no newline translation).

    Atomic: a crash mid-write never leaves a truncated export in place of a file the user may already have had."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(str(text))
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def profile_fragment() -> str:
    """"&profile=nd" (or "&profile=us") when DAMIT_DESK_PROFILE names a profile, else "". The suite installer's North
    Dakota launcher sets DAMIT_DESK_PROFILE=nd, so the desk opens in that profile (the page reads profile= from the
    address fragment, profile.ts; the token is taken out of the fragment and the rest is kept)."""
    chosen = desk_profile.normalize(os.environ.get("DAMIT_DESK_PROFILE"))
    return f"&profile={chosen}" if (os.environ.get("DAMIT_DESK_PROFILE") or "").strip() else ""


def desk_url(port: int) -> str:
    """The address the desk window opens: the API token rides in the fragment, which is never sent over HTTP."""
    return f"http://127.0.0.1:{port}/index.html#damit-token={API_TOKEN}{profile_fragment()}"


def launch_url(port: int, code: str) -> str:
    """The address the browser fallback opens: a one-time launch code, never the API token (see LAUNCH_PATH)."""
    return f"http://127.0.0.1:{port}{LAUNCH_PATH}?code={code}"


def main() -> None:
    global SETTINGS_FILE
    store, SETTINGS_FILE = prepare_storage(lambda line: print(line, flush=True))
    qgis_run.SETTINGS_DIR = store  # damit-handoff.json is read from here (docs/HANDOFF.md)
    qgis_run.DESK_SETTINGS_FILE = SETTINGS_FILE  # the DEM chosen in the desk goes to the plugins too
    nid.NID_DIR = store / "nid"  # the per-state NID cache (nid.py), outside the install and any repository
    fixed = configured_port(SETTINGS_FILE)
    try:
        server = serve(port=fixed or PREFERRED_PORT, fixed=fixed is not None)
    except PortBusyError as e:
        print(e.strerror, flush=True)
        sys.exit(2)
    # printed without the token: opening this plain address elsewhere shows the desk, but its /api/ calls are refused
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    open_url = desk_url(server.server_address[1])
    # install test 2026-11-18: the address is printed at start (flushed: the launcher's output may be a pipe), so the
    # port is visible whichever window opens. It carries no token: opened by hand it shows the desk, but every /api/
    # call is refused. Only the window (or the browser fallback's one-time launch link) gets the token.
    print(f"DamIT Desk: {url}", flush=True)
    try:
        import webview

        try:
            webview.settings["ALLOW_DOWNLOADS"] = True  # belt and braces; exports use the Save dialog bridge
            # A target=_blank / window.open link goes to the OS browser, never a new in-app window on another origin.
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        except Exception:
            pass
        # pywebview's JS API binder uses new Function / eval; rewrite it so the CSP can stay
        # script-src 'self' (no unsafe-eval). See webview_csp.py.
        from .webview_csp import install_pywebview_csp_patches
        install_pywebview_csp_patches(webview)
        api = Api(settings_file=SETTINGS_FILE)
        api._window = webview.create_window(TITLE, open_url, js_api=api, width=1280, height=860, min_size=(760, 560))
        # Re-arm the nav guard after every in-page load (the loaded event re-fires on each navigation).
        api._window.events.loaded += lambda *a: api._window.evaluate_js(NAV_GUARD_JS)
        start_kw: dict = {"private_mode": False, "storage_path": str(store)}
        icon = logo_path()
        if icon is not None:
            start_kw["icon"] = str(icon)
        webview.start(**start_kw)
    except Exception as e:  # no GUI backend: use the system browser (Linux on purpose; see browser_io.py)
        if not isinstance(e, ImportError):
            print(f"DamIT Desk: no native window ({e}).", flush=True)
        # The OS passes this address to the browser on its command line, which other local users may be able to
        # list, so it carries a one-time launch code that expires, not the token (see LAUNCH_PATH).
        link = launch_url(server.server_address[1], issue_launch_code())
        print("DamIT Desk is opening in your browser with a one-time launch link.", flush=True)
        print("Leave this terminal open while you use the desk; press Ctrl+C here to close it.", flush=True)
        if not webbrowser.open(link):
            # No browser could be started (e.g. over ssh). The terminal is the user's own; the link is single-use.
            print(f"DamIT Desk: no browser started. Open this one-time link within {int(LAUNCH_CODE_TTL_S)} s: "
                  f"{link}", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
