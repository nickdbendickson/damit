#!/usr/bin/env python3
"""lumo_watch.py 1.0.0 - Lumo as a DamIT run watcher.

How it fits together (the point of this tool):

  * CODE owns the verdict. run_digest.py reads the Runner's files and sets OK / WATCH / PROBLEM from its flags
    alone, in well under a second. The review is complete without any AI. Nothing here waits on Lumo, and
    Lumo can never change or gate the verdict.
  * LUMO only explains. A short prompt (about 500-1,000 tokens: the 20-40 line digest + the flag titles) goes to
    a SMALL model (qwen3:4b by default; phi4-mini is the alternative) with a pinned system prompt of Nick's
    rules and the real algorithm names. Ollama /api/chat, think:false, num_ctx about 4k, stream:true. Every
    streamed piece is written to disk at once, so a slow CPU box or a cut connection still leaves the partial text.
  * EVENT-DRIVEN. Hooks fire at the end of each pass, on a stall, before Hazard and at the run end, so even a
    45 s run is reviewed. When several events arrive together only the newest is sent to Lumo (one inference
    at a time); every event still gets its deterministic digest.

Commands:
  lumo_watch.py digest RUN_DIR            the digest (text, or --json), no AI
  lumo_watch.py event NAME RUN_DIR        one hook: pass_end | stall | before_hazard | after_hazard | run_end
  lumo_watch.py watch RUN_DIR             poll a run folder and fire the hooks as they happen
  lumo_watch.py explain DIGEST_JSON       the Lumo explanation of a saved digest (what `event` starts in the background)
  lumo_watch.py prompt DIGEST_JSON        show the exact prompt and its size (no model call)
  lumo_watch.py system [--write FILE]     the pinned system prompt

Models (env or flags):  LUMO_WATCH_MODEL (default qwen3:4b; 'small' = qwen3:4b, 'phi' = phi4-mini, or any tag)
  LUMO_WATCH_NUM_CTX (4096; kept between 4096 and 6144)   LUMO_WATCH_NUM_PREDICT (450)
  LUMO_WATCH_URL (http://127.0.0.1:11434)   LUMO_WATCH_WAIT_S (5: how long `event` waits for Lumo before returning)
  LUMO_WATCH_FIRST_TOKEN_S (600) and LUMO_WATCH_IDLE_S (180): how long to wait for the FIRST piece (CPU prompt
  evaluation is slow) and between pieces. They only stop the wait; the partial text is kept.
Interactive Q&A is a different model (LUMO_CHAT_MODEL, the `lumo` persona, 30B on a big Mac) and is not touched.

Nothing is written into the run folder: output goes to --out (default ~/local-ai/watch/<dam>_<run>/).
"""
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import run_digest as RD  # noqa: E402

VERSION = "1.0.0"

MODEL_ALIASES = {"small": "qwen3:4b", "phi": "phi4-mini", "qwen4b": "qwen3:4b", "default": "qwen3:4b"}
DEFAULT_MODEL = "qwen3:4b"
CTX_MIN, CTX_MAX = 4096, 6144
EVENTS = ("pass_end", "stall", "before_hazard", "after_hazard", "run_end")

# ----------------------------------------------------------------------------- the pinned system prompt
# One source of truth: this string. prompts/watcher_system.md is a mirror written by `system --write` and kept
# in step by a test. Every id and parameter below is checked against ALGORITHM-HELP-DAMIT.md (a test).
SYSTEM_PROMPT = """You are Lumo, the run watcher for the DamIT dam-breach suite (North Dakota dams). Code has already checked the run and set the verdict; you only explain the flags in plain words. You never change the verdict and you do not decide anything.

Rules you must not contradict (Nick's standing rules):
- Sunny day: the reservoir starts at the top of dam, which is the DWR max pool. There is NO inflow and NO outlet or spillway flow (outlets empty). The only water is the breach.
- DWR elevations are NAVD88 only (NGVD29 + VERTCON). An elevation of 0-300 ft is a local datum, not NAVD88.
- The breach inflow goes in at the lowest ground in the downstream toe band: 5 m out to H x (downstream slope + 1), 3:1 when the slope is not known, never more than 150 m from the dam line. H is the inventory height.
- Early passes may leak through an edge while the domain grows; the FINAL pass must not.
- Peak depth and peak velocity are maxima over wet cells (depth of 0.1 ft or more).
- North Dakota counts the TM-11 judgment zone as Medium. Roads with unknown class or AADT are not scored by DamIT Hazard.
- BNSF KO subdivision = 15 trains per day (the DamSafety value) for the rail check.
- Crest minus streambed should equal the inventory height; a mismatch moves the breach size and the toe band.

The real tools (no others exist): damit_screen:handoff, damit_run:rundam, damit:classify (also damit_lite:classify). damit_run:rundam parameters include CELL, MAX_RUNS, DURATION_HR, DURATION_MAX_HR, GRID_REFINE, TIER, METHOD, DS_SLOPE, TOP_FT, BOTTOM_FT, HEIGHT_FT, LISFLOOD_EXE, FORCE_ANUGA, DEM, DEM_Z, DAMS_FOLDER, OUTPUT_FOLDER. damit:classify takes RAIL_TRAINS_LOOKUP. To turn the automatic 10 m refine off use --GRID_REFINE=0. Never invent a tool, switch or number: if something is not in the digest, say UNSURE.

Answer in at most 6 short bullets: for each WATCH or PROBLEM flag say what it means for this run and what to check. Use only the numbers in the digest. Finish with the line "Verdict: <the verdict you were given>"."""


def system_prompt():
    return SYSTEM_PROMPT


def resolve_model(name=None):
    name = (name or os.environ.get("LUMO_WATCH_MODEL") or DEFAULT_MODEL).strip()
    return MODEL_ALIASES.get(name.lower(), name)


def clamp_ctx(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = CTX_MIN
    return max(CTX_MIN, min(CTX_MAX, n))


def settings(model=None, num_ctx=None, num_predict=None):
    env = os.environ.get
    return {
        "model": resolve_model(model),
        "num_ctx": clamp_ctx(num_ctx or env("LUMO_WATCH_NUM_CTX") or CTX_MIN),
        "num_predict": int(num_predict or env("LUMO_WATCH_NUM_PREDICT") or 450),
        "url": env("LUMO_WATCH_URL", "http://127.0.0.1:11434"),
        "first_token_s": float(env("LUMO_WATCH_FIRST_TOKEN_S", "600")),
        "idle_s": float(env("LUMO_WATCH_IDLE_S", "180")),
        "wait_s": float(env("LUMO_WATCH_WAIT_S", "5")),
    }


# ----------------------------------------------------------------------------- the short user prompt
def est_tokens(text):
    """A cheap token estimate (about 3.5 characters per token for English + numbers)."""
    return int(len(text) / 3.5) + 1


def flag_lines(digest, include_info=False):
    out = []
    for f in sorted(digest["flags"], key=lambda x: -RD._RANK.get(x["severity"], 0)):
        if f["severity"] == RD.INFO and not include_info:
            continue
        out.append("%s | %s | %s | %s" % (f["severity"], f["id"], f["where"], f["title"]))
    return out


def build_user_prompt(digest, event=None, max_tokens=1000):
    """The user message: the event, the verdict code already set, the digest text and the flag list.
    Trimmed to max_tokens (system prompt not counted) by dropping the per-pass table, then the details."""
    verdict = digest["verdict"]
    flags = flag_lines(digest)
    head = "EVENT: %s\nVERDICT (set by code, do not change): %s\n" % (event or digest.get("phase"), verdict)
    task = "\nExplain the WATCH/PROBLEM flags. End with: Verdict: %s" % verdict
    lines = digest["text"].splitlines()

    def make(ls, fls):
        return head + "\nDIGEST\n" + "\n".join(ls) + "\n\nFLAGS (severity | id | where | title)\n" + (
            "\n".join(fls) if fls else "none") + task

    text = make(lines, flags)
    if est_tokens(text) > max_tokens:       # 1: drop the pass table rows
        lines = [l for l in lines if not re.match(r"^\s+\d+ \|", l)]
        text = make(lines, flags)
    if est_tokens(text) > max_tokens:       # 2: the digest's own flag bullets repeat the FLAGS list
        lines = [l for l in lines if not l.startswith("- ")]
        text = make(lines, flags)
    while est_tokens(text) > max_tokens and len(flags) > 3:     # 3: the shortest list that still has the top flags
        flags = flags[:-1]
        text = make(lines, flags)
    return text


def build_messages(digest, event=None, max_tokens=1000):
    return [{"role": "system", "content": system_prompt()},
            {"role": "user", "content": build_user_prompt(digest, event, max_tokens)}]


# ----------------------------------------------------------------------------- Ollama: /api/chat, streamed
def chat_payload(messages, cfg, think=False):
    """The /api/chat request: think:false (a Qwen3 model otherwise spends the whole budget thinking and /no_think
    on /api/generate does not stop it), stream:true, a 4-6k context, a short reply."""
    p = {"model": cfg["model"], "messages": messages, "stream": True,
         "options": {"num_ctx": cfg["num_ctx"], "num_predict": cfg["num_predict"], "temperature": 0.2, "top_p": 0.9},
         "keep_alive": "30m"}
    if think is not None:
        p["think"] = bool(think)
    return p


def _write_status(path, st):
    if not path:
        return
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, path)


def stream_chat(payload, url, out_path, status_path=None, first_token_s=600.0, idle_s=180.0, deadline_s=None,
                connect=None, header=""):
    """POST to /api/chat with stream:true and append every piece to out_path the moment it arrives.

    There is NO total timeout that throws the answer away: first_token_s and idle_s only stop the WAIT, and
    whatever has streamed is already on disk. Returns the status dict (also written to status_path):
    status = done | partial | unavailable | error, text, chars, pieces, elapsed_s, eval counts when Ollama sent them.
    A model without thinking support answers 400 to think:false; that case is retried once without the field."""
    t0 = time.time()
    st = {"status": "starting", "model": payload.get("model"), "chars": 0, "pieces": 0, "started": t0,
          "think": payload.get("think"), "elapsed_s": 0.0, "error": None}
    u = urlparse(url)
    text_parts = []
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out = open(out_path, "w", encoding="utf-8")
    if header:
        out.write(header)
        out.flush()
    _write_status(status_path, st)
    last_status = [t0]

    def fin(status, err=None):
        st.update(status=status, error=err, elapsed_s=round(time.time() - t0, 2), text="".join(text_parts))
        try:
            out.flush()
            out.close()
        except OSError:
            pass
        _write_status(status_path, {k: v for k, v in st.items() if k != "text"})
        return st

    def request(body):
        conn = (connect or (lambda h, p, t: http.client.HTTPConnection(h, p, timeout=t)))(
            u.hostname, u.port or 80, first_token_s)
        conn.request("POST", "/api/chat", body=json.dumps(body).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        return conn, conn.getresponse()

    try:
        conn, resp = request(payload)
        if resp.status == 400 and payload.get("think") is not None:
            err_body = resp.read().decode("utf-8", "replace")
            if "think" in err_body.lower():
                conn.close()
                payload = {k: v for k, v in payload.items() if k != "think"}
                st["think"] = "omitted (model has no thinking switch)"
                conn, resp = request(payload)
            else:
                return fin("error", "HTTP 400: " + err_body[:300])
        if resp.status != 200:
            return fin("error", "HTTP %d: %s" % (resp.status, resp.read(300).decode("utf-8", "replace")))
        st["status"] = "streaming"
        first = True
        while True:
            if deadline_s is not None and time.time() - t0 > deadline_s:
                return fin("partial", "deadline of %.0f s reached; the partial text is kept" % deadline_s)
            try:
                line = resp.readline()
            except (OSError, http.client.HTTPException) as e:        # socket.timeout is an OSError
                return fin("partial" if text_parts else "error", "no data for %.0f s (%s); partial text kept" % (
                    first_token_s if first else idle_s, e))
            if not line:
                break
            if first:
                first = False
                try:
                    conn.sock.settimeout(idle_s)
                except (AttributeError, OSError):
                    pass
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if obj.get("error"):
                return fin("error", str(obj["error"])[:300])
            piece = (obj.get("message") or {}).get("content") or ""
            if piece:
                text_parts.append(piece)
                out.write(piece)
                out.flush()
                st["chars"] += len(piece)
                st["pieces"] += 1
                if time.time() - last_status[0] > 2.0:
                    last_status[0] = time.time()
                    st["elapsed_s"] = round(time.time() - t0, 2)
                    _write_status(status_path, st)
            if obj.get("done"):
                for k in ("prompt_eval_count", "eval_count", "total_duration", "eval_duration", "done_reason"):
                    if k in obj:
                        st[k] = obj[k]
                return fin("done")
        return fin("partial" if text_parts else "error", "the stream ended before 'done'")
    except (ConnectionRefusedError, ConnectionResetError) as e:
        return fin("unavailable", "Ollama is not reachable at %s (%s): the digest and verdict stand without Lumo" % (url, e))
    except OSError as e:
        return fin("partial" if text_parts else "unavailable", "%s: %s" % (type(e).__name__, e))
    except Exception as e:                      # noqa: BLE001 - never raise into the watcher
        return fin("partial" if text_parts else "error", "%s: %s" % (type(e).__name__, e))


# ----------------------------------------------------------------------------- output files and the single-flight lock
def default_out_dir(run_dir, digest=None):
    base = os.path.join(os.path.expanduser("~"), "local-ai", "watch")
    dam = (digest or {}).get("dam_id") or "run"
    name = os.path.basename(os.path.abspath(run_dir))
    return os.path.join(base, "%s_%s" % (dam, name))


def _inside(path, folder):
    a, b = os.path.abspath(path), os.path.abspath(folder)
    return a == b or a.startswith(b + os.sep)


def event_tag(event, pass_no=None):
    return "%s%s" % (event, "_p%s" % pass_no if pass_no is not None else "")


def write_digest(out_dir, digest, event, pass_no=None):
    os.makedirs(out_dir, exist_ok=True)
    tag = event_tag(event, pass_no)
    jp = os.path.join(out_dir, "digest_%s.json" % tag)
    tmp = jp + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(digest, event=event, pass_no=pass_no), f, indent=1, default=str)
    os.replace(tmp, jp)
    with open(os.path.join(out_dir, "digest_%s.txt" % tag), "w", encoding="utf-8") as f:
        f.write(digest["text"] + "\n")
    with open(os.path.join(out_dir, "latest_verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"event": event, "pass": pass_no, "verdict": digest["verdict"],
                   "flags": [x["id"] for x in digest["flags"] if x["severity"] != RD.INFO],
                   "written": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=1)
    return jp


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def lumo_busy(out_dir):
    p = os.path.join(out_dir, "lumo.busy")
    try:
        pid = int(open(p).read().strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def explain(digest_path, cfg=None, out_path=None, connect=None, max_tokens=1000):
    """Ask Lumo to explain a saved digest. Writes lumo_<tag>.md (streaming) and lumo_<tag>.status.json next to it.
    Never raises, never alters the digest or its verdict."""
    cfg = cfg or settings()
    with open(digest_path, encoding="utf-8") as f:
        digest = json.load(f)
    event, pass_no = digest.get("event"), digest.get("pass_no")
    tag = event_tag(event or digest.get("phase", "run"), pass_no)
    d = os.path.dirname(os.path.abspath(digest_path))
    out_path = out_path or os.path.join(d, "lumo_%s.md" % tag)
    status_path = out_path[:-3] + ".status.json" if out_path.endswith(".md") else out_path + ".status.json"
    msgs = build_messages(digest, event, max_tokens)
    payload = chat_payload(msgs, cfg, think=False)
    header = "<!-- Lumo (%s) explains the code's verdict %s for %s; it does not set or change it. -->\n" % (
        cfg["model"], digest["verdict"], tag)
    lock = os.path.join(d, "lumo.busy")
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    try:
        st = stream_chat(payload, cfg["url"], out_path, status_path, cfg["first_token_s"], cfg["idle_s"],
                         connect=connect, header=header)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    st["prompt_tokens_est"] = est_tokens(msgs[0]["content"] + msgs[1]["content"])
    return st


def spawn_explain(digest_path, cfg):
    """Start the explanation in a detached process: the watcher never waits on it. Returns the Popen."""
    env = dict(os.environ, LUMO_WATCH_MODEL=cfg["model"], LUMO_WATCH_NUM_CTX=str(cfg["num_ctx"]),
               LUMO_WATCH_URL=cfg["url"])
    cmd = [sys.executable, os.path.abspath(__file__), "explain", digest_path]
    kw = {"start_new_session": True} if os.name != "nt" else {}
    log = open(digest_path[:-5] + ".lumo.log", "w")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, **kw)


def wait_for_lumo(status_path, wait_s):
    """Wait up to wait_s for the explanation to finish; then give up WITHOUT killing it (it keeps streaming to disk)."""
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            st = json.load(open(status_path))
            if st.get("status") in ("done", "partial", "unavailable", "error"):
                return st
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    try:
        return json.load(open(status_path))
    except (OSError, ValueError):
        return {"status": "pending"}


# ----------------------------------------------------------------------------- hooks
def run_event(run_dir, event, out_dir=None, pass_no=None, lumo=True, cfg=None, spawn=None, **digest_kw):
    """One hook. Returns {digest, digest_path, verdict, lumo: status or None}. The verdict is final when this
    returns; Lumo's text, if any, lands in lumo_<event>.md later."""
    if event not in EVENTS:
        raise ValueError("event must be one of %s" % ", ".join(EVENTS))
    cfg = cfg or settings()
    phase = event
    d = RD.build_digest(run_dir, phase=phase, upto_pass=pass_no if event in ("pass_end", "stall") else None, **digest_kw)
    out_dir = out_dir or default_out_dir(run_dir, d)
    if _inside(out_dir, run_dir):
        raise ValueError("refusing to write into the run folder")
    jp = write_digest(out_dir, d, event, pass_no)
    res = {"digest": d, "digest_path": jp, "verdict": d["verdict"], "lumo": None, "out_dir": out_dir}
    if lumo:
        if lumo_busy(out_dir):
            res["lumo"] = {"status": "skipped", "error": "a Lumo explanation is still running"}
        else:
            tag = event_tag(event, pass_no)
            sp = os.path.join(out_dir, "lumo_%s.status.json" % tag)
            for stale in (sp, sp + ".part"):
                try:
                    os.remove(stale)
                except OSError:
                    pass
            (spawn or spawn_explain)(jp, cfg)
            res["lumo"] = wait_for_lumo(sp, cfg["wait_s"]) if cfg["wait_s"] > 0 else {"status": "started"}
    return res


class EventDetector(object):
    """Turns what appeared in a run folder into hook events. Pure file inspection (no model, no process).

    state (a dict, kept by the caller / saved as JSON): passes_done, stall_fired, run_end, before_hazard, after_hazard."""

    def __init__(self, stall_s=None):
        self.stall_s = stall_s if stall_s is not None else RD.THRESHOLDS["stall_s"]

    def scan(self, run_dir, state, now=None):
        now = now if now is not None else time.time()
        ev = []
        done = state.setdefault("passes_done", [])
        fired = state.setdefault("stall_fired", [])
        setup = RD._load_json(os.path.join(run_dir, "run_setup.json")) or {}
        finished = os.path.exists(os.path.join(run_dir, "run_report.json")) or (
            setup.get("status") == "finished" and setup.get("model_launched"))
        pdirs = RD._pass_dirs(run_dir)
        for i, pd in enumerate(pdirs):
            n = RD._pass_number(pd)
            if RD._log_finished(pd) and n not in done:
                done.append(n)
                ev.append({"event": "pass_end", "pass": n})
            elif RD._log_finished(pd) is False and not finished and i == len(pdirs) - 1 and n not in fired:
                mp = os.path.join(pd, "results", "run.mass")
                age = now - os.path.getmtime(mp) if os.path.exists(mp) else None
                if age is not None and age >= self.stall_s:
                    fired.append(n)
                    ev.append({"event": "stall", "pass": n})
        if finished and not state.get("run_end"):
            state["run_end"] = True
            ev.append({"event": "run_end", "pass": None})
        if state.get("run_end"):
            folder = RD._dam_folder(run_dir, setup)
            hz = RD.find_hazard_report(run_dir, setup, folder)
            if not state.get("before_hazard") and not hz:
                state["before_hazard"] = True
                ev.append({"event": "before_hazard", "pass": None})
            if hz and not state.get("after_hazard"):
                state["after_hazard"] = True
                ev.append({"event": "after_hazard", "pass": None})
        return ev


def watch(run_dir, out_dir=None, poll_s=2.0, until="before_hazard", lumo=True, cfg=None, max_wait_s=None, once=False,
          stall_s=None, log=print, spawn=None, **digest_kw):
    """Poll the run folder; fire the hooks. Returns the list of results. Stops after `until` fires (run_end |
    before_hazard | after_hazard), after max_wait_s, or after one scan with once=True. When one scan finds several
    events (a 45 s run), each gets its digest but only the last is sent to Lumo."""
    det, state, results = EventDetector(stall_s), {}, []
    t0 = time.time()
    while True:
        evs = det.scan(run_dir, state)
        for i, e in enumerate(evs):
            last = i == len(evs) - 1
            r = run_event(run_dir, e["event"], out_dir, e["pass"], lumo=lumo and last, cfg=cfg, spawn=spawn,
                          stall_s=stall_s, **digest_kw)
            r["event"] = e["event"]
            results.append(r)
            log("[%s] %s%s -> %s%s" % (time.strftime("%H:%M:%S"), e["event"], " (pass %s)" % e["pass"] if e["pass"] else "",
                                       r["verdict"], "; flags: " + ", ".join(
                                           sorted({f["id"] for f in r["digest"]["flags"] if f["severity"] != RD.INFO}))
                                       if r["digest"]["flags"] else ""))
        if once or state.get(until) or (max_wait_s is not None and time.time() - t0 > max_wait_s):
            return results
        time.sleep(poll_s)


# ----------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Lumo as a DamIT run watcher: the code sets the verdict, Lumo explains.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--out", help="where to write (never inside the run folder); default ~/local-ai/watch/<dam>_<run>/")
        p.add_argument("--dam-folder")
        p.add_argument("--structures")
        p.add_argument("--points")
        p.add_argument("--rail-lookup")
        p.add_argument("--no-lumo", action="store_true", help="digest only")
        p.add_argument("--model", help="small | phi | any Ollama tag (default %s)" % DEFAULT_MODEL)
        p.add_argument("--lumo-wait", type=float, help="seconds to wait for Lumo before returning (default 5)")
        p.add_argument("--exit-code", action="store_true", help="exit 0 OK, 1 WATCH, 2 PROBLEM (never from Lumo)")

    p = sub.add_parser("digest")
    p.add_argument("run_dir")
    p.add_argument("--json", action="store_true")
    common(p)
    p = sub.add_parser("event")
    p.add_argument("name", choices=EVENTS)
    p.add_argument("run_dir")
    p.add_argument("--pass", dest="pass_no", type=int)
    common(p)
    p = sub.add_parser("watch")
    p.add_argument("run_dir")
    p.add_argument("--poll", type=float, default=2.0)
    p.add_argument("--until", default="before_hazard", choices=("run_end", "before_hazard", "after_hazard"))
    p.add_argument("--max-wait", type=float, help="give up after this many seconds")
    p.add_argument("--once", action="store_true")
    p.add_argument("--stall-s", type=float)
    common(p)
    p = sub.add_parser("explain")
    p.add_argument("digest_json")
    p.add_argument("--model")
    p = sub.add_parser("prompt")
    p.add_argument("digest_json")
    p = sub.add_parser("system")
    p.add_argument("--write")
    a = ap.parse_args(argv)

    if a.cmd == "system":
        if a.write:
            with open(a.write, "w", encoding="utf-8") as f:
                f.write(system_prompt() + "\n")
        else:
            print(system_prompt())
        return 0
    if a.cmd == "explain":
        st = explain(a.digest_json, settings(a.model))
        print(json.dumps({k: v for k, v in st.items() if k != "text"}, indent=1))
        return 0
    if a.cmd == "prompt":
        d = json.load(open(a.digest_json))
        m = build_messages(d, d.get("event"))
        print(m[1]["content"])
        print("\n[system ~%d tokens + user ~%d tokens]" % (est_tokens(m[0]["content"]), est_tokens(m[1]["content"])))
        return 0

    cfg = settings(a.model)
    if a.lumo_wait is not None:
        cfg["wait_s"] = a.lumo_wait
    kw = dict(dam_folder=a.dam_folder, structures_path=a.structures, points_path=a.points, rail_lookup=a.rail_lookup)
    verdict = RD.OK
    if a.cmd == "digest":
        d = RD.build_digest(a.run_dir, "run_end", **kw)
        print(json.dumps(RD.machine_flags(d), indent=1, default=str) if a.json else d["text"])
        if a.out:
            if _inside(a.out, a.run_dir):
                print("refusing to write into the run folder", file=sys.stderr)
                return 2
            write_digest(a.out, d, "run_end")
        verdict = d["verdict"]
    elif a.cmd == "event":
        r = run_event(a.run_dir, a.name, a.out, a.pass_no, lumo=not a.no_lumo, cfg=cfg, **kw)
        print(r["digest"]["text"])
        print("\nLumo: %s" % (r["lumo"] or {}).get("status", "not asked"))
        verdict = r["verdict"]
    elif a.cmd == "watch":
        rs = watch(a.run_dir, a.out, a.poll, a.until, not a.no_lumo, cfg, a.max_wait, a.once, a.stall_s, **kw)
        order = {RD.OK: 0, RD.WATCH: 1, RD.PROBLEM: 2}
        verdict = max((r["verdict"] for r in rs), key=lambda v: order[v], default=RD.OK)
    return {RD.OK: 0, RD.WATCH: 1, RD.PROBLEM: 2}[verdict] if getattr(a, "exit_code", False) else 0


if __name__ == "__main__":
    sys.exit(main())
