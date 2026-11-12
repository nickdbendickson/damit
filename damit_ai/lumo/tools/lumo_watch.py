#!/usr/bin/env python3
"""lumo_watch.py 1.3.3 - Lumo as a DamIT run watcher.

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

  * NEVER SLOWS THE ENGINE. A CPU-only box shares its cores between LISFLOOD-FP and the model (an explanation during a
    pass made the Runner about 7x slower in a live test; a "quiet gap between passes" gate in 1.2.0 still started Lumo
    2 s after pass 6 of DWR-2824, because the Runner works in Python between passes with no LISFLOOD process and no log
    growing). So by default Lumo explains only after the Runner's WHOLE pipeline has finished (run_progress.json
    "complete", run_report.json, or run_setup.json finished / failed) and no LISFLOOD process is running; a pass hook
    only queues until then (only the newest event is kept), and Ollama is capped to a few threads. A Runner that died
    mid-run (nothing written to the run folder for LUMO_WATCH_STALE_S, no LISFLOOD process) counts as over, so the queue
    cannot wait forever. The digest and its COMPLETE flag list are written at once either way.
  * EVERY FLAG IS LISTED. The complete flag list is written by code at the top of lumo_<event>.md; Lumo's comments go
    under it, one bullet per flag, and any flag Lumo skipped is named in a footer.

Models (env or flags):  LUMO_WATCH_MODEL (default qwen3:4b; 'small' = qwen3:4b, 'phi' = phi4-mini, or any tag)
  LUMO_WATCH_NUM_CTX (4096; kept between 4096 and 6144)   LUMO_WATCH_NUM_PREDICT (600)
  LUMO_WATCH_URL (http://127.0.0.1:11434)   LUMO_WATCH_WAIT_S (5: how long `event` waits for Lumo before returning)
  LUMO_WATCH_FIRST_TOKEN_S (600) and LUMO_WATCH_IDLE_S (180): how long to wait for the FIRST piece (CPU prompt
  evaluation is slow) and between pieces. They only stop the wait; the partial text is kept.
  LUMO_WATCH_EXPLAIN (idle | end | always | never; default idle): when Lumo may use the CPU.
      idle   = (default) the Runner's whole pipeline has finished and no lisflood process runs; pass hooks only queue
      end    = the same gate (kept so existing settings still work)
      always = whenever an event fires (old behaviour, slows the run)    never = no model
  LUMO_WATCH_STALE_S (900): a run folder nothing has written to for this long, with no lisflood process, counts as stopped
  LUMO_WATCH_PASS_RECEPTOR_EVERY (2): a pass_end hook samples the receptors (structure layer) only on every Nth pass (2, 4, 6 ...), and
      always at run_end (final raster) and when the run is already over; 1 = every pass, 0 = never mid-run. The layer is read and
      reprojected once per `watch` process and sampled with numpy (no per-feature GDAL call), but a pass hook still shares the CPU
      with the next LISFLOOD pass (DWR-2801, 88,734 structures: the 1.3.0 hooks made the Runner 493 s instead of 348 s).
  LUMO_WATCH_RECORD_GRACE_S (120): a pass_end hook waits for the Runner to write the finished pass into run_progress.json (its
      georeference), up to this many seconds after LISFLOOD-FP's log finishes. Every digest then carries receptors or an explicit
      checks.receptors_skipped reason (1.3.2).
  LUMO_WATCH_MIN_FREE_MB (1024): a mid-run pass hook does not read a pass grid that would leave less than this much RAM free.
  LUMO_WATCH_KEEP_ALIVE (2m): how long Ollama keeps the model in memory after an explain (was a fixed 30m, 1.3.2).
  LUMO_WATCH_PASS_NICE (19): `watch` lowers its own priority to this nice level (POSIX) so the pass hooks yield to the Runner.
  LUMO_WATCH_IDLE_GAP_S (20): no longer decides anything (1.3.0); still accepted so an old setting does not break
  LUMO_WATCH_QUEUE_WAIT_S (300): after the run ends, how long `watch` keeps waiting for a busy engine before it leaves the
      explanation queued (it prints the `explain` command to run later)
  LUMO_WATCH_NUM_THREAD (2; 0 = Ollama's own default): num_thread for the model, so it cannot take every core
  LUMO_WATCH_NICE (10): nice level of the explain process (POSIX). It does not nice the Ollama server; num_thread does.
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

VERSION = "1.3.3"

MODEL_ALIASES = {"small": "qwen3:4b", "phi": "phi4-mini", "qwen4b": "qwen3:4b", "default": "qwen3:4b"}
DEFAULT_MODEL = "qwen3:4b"
CTX_MIN, CTX_MAX = 4096, 6144
EVENTS = ("pass_end", "stall", "before_hazard", "after_hazard", "run_end")
EXPLAIN_MODES = ("idle", "end", "always", "never")

# ----------------------------------------------------------------------------- the pinned system prompt
# One source of truth: this string. prompts/watcher_system.md is a mirror written by `system --write` and kept
# in step by a test. Every id and parameter below is checked against ALGORITHM-HELP-DAMIT.md (a test).
SYSTEM_PROMPT = """You are Lumo, the run watcher for the DamIT dam-breach suite (North Dakota dams). Code has already checked the run, set the verdict and listed every flag; you only explain the flags in plain words. You never change the verdict and you do not decide anything.

Rules you must not contradict (Nick's standing rules):
- Sunny day: the reservoir starts at the top of dam, which is the DWR max pool. There is NO inflow and NO outlet or spillway flow (outlets empty). The only water is the breach.
- DWR elevations are NAVD88 only (NGVD29 + VERTCON). An elevation of 0-300 ft is a local datum, not NAVD88.
- The breach inflow goes in at the lowest ground in the downstream toe band: 5 m out to H x (downstream slope + 1), 3:1 when the slope is not known, never more than 150 m from the dam line. H is the inventory height.
- "Edge" flags (EDGE_OUTFLOW_EARLY, EDGE_OUTFLOW_FINAL, EDGE_INFLOW) are about the edge of the MODEL DOMAIN, the border of the computation grid. They are never about the breach or the dam. Early-pass outflow through the model domain edge is EXPECTED while the domain grows. It is not dam leakage, says nothing about the dam being weak, and does not change the breach; only a leaking FINAL pass is a concern.
- Peak depth and peak velocity are maxima over wet cells (depth of 0.1 ft or more).
- North Dakota counts the TM-11 judgment zone as Medium. Roads with unknown class or AADT are not scored by DamIT Hazard.
- BNSF KO subdivision = 15 trains per day (the DamSafety value) for the rail check.
- Crest minus streambed should equal the inventory height; a mismatch moves the breach size and the toe band.

The real tools (no others exist): damit_screen:handoff, damit_run:rundam, damit:classify (also damit_lite:classify). damit_run:rundam parameters include CELL, MAX_RUNS, DURATION_HR, DURATION_MAX_HR, GRID_REFINE, TIER, METHOD, DS_SLOPE, TOP_FT, BOTTOM_FT, HEIGHT_FT, LISFLOOD_EXE, FORCE_ANUGA, DEM, DEM_Z, DAMS_FOLDER, OUTPUT_FOLDER. damit:classify takes RAIL_TRAINS_LOOKUP. To turn the automatic 10 m refine off use --GRID_REFINE=0. Never invent a tool, switch, number or flag id: the only flag ids are the ones in the FLAGS list. If something is not in the digest, say UNSURE.

Write ONE short bullet (at most 30 words) for EVERY flag in the FLAGS list, whatever its severity (PROBLEM, WATCH and INFO), in the same order, each starting with its flag id, then what it means for this run and what to check. An INFO flag is a note, not a concern: say what it tells the engineer (for example that a record or a check was not available) and what, if anything, to do; it still gets its own bullet. Do not stop early and do not merge or skip flags. Use only the numbers in the digest. Finish with the line "Verdict: <the verdict you were given>"."""


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


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def settings(model=None, num_ctx=None, num_predict=None):
    env = os.environ.get
    return {
        "model": resolve_model(model),
        "num_ctx": clamp_ctx(num_ctx or env("LUMO_WATCH_NUM_CTX") or CTX_MIN),
        "num_predict": int(num_predict or env("LUMO_WATCH_NUM_PREDICT") or 600),
        "num_thread": max(0, _int(env("LUMO_WATCH_NUM_THREAD"), 2)),
        "explain": (env("LUMO_WATCH_EXPLAIN") or "idle").strip().lower() if (
            (env("LUMO_WATCH_EXPLAIN") or "idle").strip().lower() in EXPLAIN_MODES) else "idle",
        "idle_gap_s": max(0.0, _float(env("LUMO_WATCH_IDLE_GAP_S"), 20.0)),     # 1.3.0: accepted, no longer used
        "stale_s": max(0.0, _float(env("LUMO_WATCH_STALE_S"), RD.THRESHOLDS["stall_s"])),
        "pass_receptor_every": max(0, _int(env("LUMO_WATCH_PASS_RECEPTOR_EVERY"), 2)),
        "keep_alive": (env("LUMO_WATCH_KEEP_ALIVE") or "2m").strip(),
        "pass_nice": max(0, _int(env("LUMO_WATCH_PASS_NICE"), 19)),
        "record_grace_s": max(0.0, _float(env("LUMO_WATCH_RECORD_GRACE_S"), RECORD_GRACE_S)),
        "queue_wait_s": max(0.0, _float(env("LUMO_WATCH_QUEUE_WAIT_S"), 300.0)),
        "nice": max(0, _int(env("LUMO_WATCH_NICE"), 10)),
        "url": env("LUMO_WATCH_URL", "http://127.0.0.1:11434"),
        "first_token_s": float(env("LUMO_WATCH_FIRST_TOKEN_S", "600")),
        "idle_s": float(env("LUMO_WATCH_IDLE_S", "180")),
        "wait_s": float(env("LUMO_WATCH_WAIT_S", "5")),
    }


# ----------------------------------------------------------------------------- the short user prompt
def est_tokens(text):
    """A cheap token estimate (about 3.5 characters per token for English + numbers)."""
    return int(len(text) / 3.5) + 1


def flag_hint(f, n=None):
    """The receptor ids a flag carries (first 10 and a count), so the commentary can name them (e.g. 104270538)."""
    return RD.flag_ids_text(f, n)


def flag_lines(digest, include_info=True, title_chars=None, hints=True, hint_n=None):
    """EVERY flag, one line each, PROBLEM first and INFO notes last (include_info=False leaves the INFO notes out). Nothing
    is dropped: since 1.2.0 the INFO flags are in the prompt too, so Lumo is asked for a bullet on them."""
    out = []
    for f in sorted(digest["flags"], key=RD.flag_sort_key):
        if f["severity"] == RD.INFO and not include_info:
            continue
        title = f["title"] if not title_chars else f["title"][:title_chars]
        hint = flag_hint(f, hint_n) if hints else ""
        out.append("%s | %s | %s | %s%s" % (f["severity"], f["id"], f["where"], title, (" | " + hint) if hint else ""))
    return out


def build_user_prompt(digest, event=None, max_tokens=1000):
    """The user message: the event, the verdict code already set, the digest text and the flag list.
    Trimmed to max_tokens (system prompt not counted) by dropping the per-pass table, the digest's flag bullets and
    then shortening the titles. EVERY flag (INFO too) stays in the list: Lumo is asked for one bullet each."""
    verdict = digest["verdict"]
    nflags = len(digest["flags"])
    head = "EVENT: %s\nVERDICT (set by code, do not change): %s\n" % (event or digest.get("phase"), verdict)
    task = "\nWrite one bullet for each of the %d flag(s) above, in order, each starting with its flag id. End with: Verdict: %s" % (
        nflags, verdict)
    lines = digest["text"].splitlines()

    def make(ls, fls):
        return head + "\nDIGEST\n" + "\n".join(ls) + "\n\nFLAGS (severity | id | where | title)\n" + (
            "\n".join(fls) if fls else "none") + task

    text = make(lines, flag_lines(digest))
    if est_tokens(text) > max_tokens:       # 1: drop the pass table rows
        lines = [l for l in lines if not re.match(r"^\s+\d+ \|", l)]
        text = make(lines, flag_lines(digest))
    if est_tokens(text) > max_tokens:       # 2: the digest's own flag bullets repeat the FLAGS list
        lines = [l for l in lines if not l.startswith("- ")]
        text = make(lines, flag_lines(digest))
    for chars in (140, 100, 70):            # 3: shorter titles, then fewer id hints; never fewer flags
        if est_tokens(text) <= max_tokens:
            break
        text = make(lines, flag_lines(digest, title_chars=chars, hints=True, hint_n=10 if chars > 100 else 3))
    return text


def build_messages(digest, event=None, max_tokens=1000):
    return [{"role": "system", "content": system_prompt()},
            {"role": "user", "content": build_user_prompt(digest, event, max_tokens)}]


# ----------------------------------------------------------------------------- Ollama: /api/chat, streamed
def chat_payload(messages, cfg, think=False):
    """The /api/chat request: think:false (a Qwen3 model otherwise spends the whole budget thinking and /no_think
    on /api/generate does not stop it), stream:true, a 4-6k context, a short reply, a capped thread count."""
    p = {"model": cfg["model"], "messages": messages, "stream": True,
         "options": {"num_ctx": cfg["num_ctx"], "num_predict": cfg["num_predict"], "temperature": 0.2, "top_p": 0.9},
         "keep_alive": cfg.get("keep_alive") or "2m"}
    if cfg.get("num_thread"):                   # cap the CPU threads so the model cannot take every core from LISFLOOD
        p["options"]["num_thread"] = int(cfg["num_thread"])
    if think is not None:
        p["think"] = bool(think)
    return p


# Every field Ollama puts on the final streamed object (durations are nanoseconds).
OLLAMA_FIELDS = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
                 "eval_duration", "done_reason")


def timing_summary(st):
    """Seconds and tokens/s derived from Ollama's own counters (no estimate): load, prompt evaluation, generation."""
    out = {}
    for k, name in (("load_duration", "load_s"), ("prompt_eval_duration", "prompt_eval_s"), ("eval_duration", "eval_s"),
                    ("total_duration", "total_s")):
        if st.get(k) is not None:
            out[name] = round(st[k] / 1e9, 3)
    if st.get("prompt_eval_count") and st.get("prompt_eval_duration"):
        out["prompt_tok_per_s"] = round(st["prompt_eval_count"] / (st["prompt_eval_duration"] / 1e9), 2)
    if st.get("eval_count") and st.get("eval_duration"):
        out["eval_tok_per_s"] = round(st["eval_count"] / (st["eval_duration"] / 1e9), 2)
    return out


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
    status = done | partial | timeout | unavailable | error, text, chars, pieces, elapsed_s, eval counts when Ollama sent them.
    A model without thinking support answers 400 to think:false; that case is retried once without the field."""
    t0 = time.time()
    st = {"status": "starting", "model": payload.get("model"), "chars": 0, "pieces": 0, "started": t0,
          "think": payload.get("think"), "elapsed_s": 0.0, "error": None, "thinking_chars": 0,
          "thinking_despite_think_false": False, "first_piece_s": None,
          # first_byte_wait_s: MEASURED seconds from the request to the first streamed line (None until it arrives; on a
          # timeout, the seconds actually waited). first_token_cap_s: the configured limit (LUMO_WATCH_FIRST_TOKEN_S).
          "first_byte_wait_s": None, "first_token_cap_s": first_token_s}
    think_out = [None]                           # <out>.thinking.txt, opened only if thinking tokens arrive
    u = urlparse(url)
    text_parts = []
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out = open(out_path, "w", encoding="utf-8")
    if header:
        out.write(header)
        out.flush()
    _write_status(status_path, st)
    last_status = [t0]
    conns = []

    def fin(status, err=None):
        if st["first_byte_wait_s"] is None and status in ("timeout", "partial", "error"):
            st["first_byte_wait_s"] = round(time.time() - t0, 2)        # nothing streamed: the wait that ran out
        st.update(status=status, error=err, elapsed_s=round(time.time() - t0, 2), text="".join(text_parts))
        try:
            out.flush()
            out.close()
        except OSError:
            pass
        if think_out[0] is not None:
            try:
                think_out[0].close()
            except OSError:
                pass
        for c in conns:                          # no socket is left to the garbage collector (ResourceWarning)
            try:
                c.close()
            except OSError:
                pass
        _write_status(status_path, {k: v for k, v in st.items() if k != "text"})
        return st

    def request(body):
        conn = (connect or (lambda h, p, t: http.client.HTTPConnection(h, p, timeout=t)))(
            u.hostname, u.port or 80, first_token_s if first_token_s and first_token_s > 0 else None)
        conns.append(conn)
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
                if first and not text_parts:
                    return fin("timeout", "Ollama sent nothing for %.0f s (it may be busy with another job, or loading the "
                               "model): this is a wait that ran out, not a partial answer. The digest stands; raise "
                               "LUMO_WATCH_FIRST_TOKEN_S (0 = wait without limit) or ask again later (%s)" % (first_token_s, e))
                return fin("partial" if text_parts else "error", "no data for %.0f s (%s); partial text kept" % (
                    first_token_s if first else idle_s, e))
            if not line:
                break
            if first:
                first = False
                st["first_byte_wait_s"] = round(time.time() - t0, 2)
                try:
                    conn.sock.settimeout(idle_s if idle_s and idle_s > 0 else None)
                except (AttributeError, OSError):
                    pass
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            if obj.get("error"):
                return fin("error", str(obj["error"])[:300])
            msg = obj.get("message") or {}
            think_piece = msg.get("thinking") or ""
            if think_piece:                      # think:false should stop these; when they come anyway, keep and flag them
                if think_out[0] is None:
                    think_out[0] = open(out_path + ".thinking.txt", "w", encoding="utf-8")
                think_out[0].write(think_piece)
                think_out[0].flush()
                st["thinking_chars"] += len(think_piece)
                st["thinking_despite_think_false"] = payload.get("think") is False
            piece = msg.get("content") or ""
            if piece:
                if st["first_piece_s"] is None:
                    st["first_piece_s"] = round(time.time() - t0, 2)
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
                for k in OLLAMA_FIELDS:
                    if k in obj:
                        st[k] = obj[k]
                st.update(timing_summary(st))
                if st["thinking_despite_think_false"]:
                    st["error"] = ("thinking tokens arrived although think:false was sent (%d chars, kept in %s); the "
                                   "answer text is unaffected" % (st["thinking_chars"], os.path.basename(out_path) + ".thinking.txt"))
                return fin("done", st["error"])
        return fin("partial" if text_parts else "error", "the stream ended before 'done'")
    except TimeoutError as e:                   # no reply headers yet: Ollama is queued behind another job or loading the model
        if text_parts:
            return fin("partial", "no data for %.0f s (%s); partial text kept" % (idle_s, e))
        return fin("timeout", "Ollama sent nothing for %.0f s (it may be busy with another job, or loading the model): "
                   "this is a wait that ran out, not a partial answer. The digest stands; raise LUMO_WATCH_FIRST_TOKEN_S "
                   "(0 = wait without limit) or ask again later (%s)" % (first_token_s, e))
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


def _unique(ids):
    """The ids in order, each once (a digest is already one flag per id; this keeps a hand-built one honest too)."""
    out = []
    for i in ids:
        if i not in out:
            out.append(i)
    return out


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
        if "more flag(s)" in digest["text"]:        # the 40-line summary cut some bullets: the file still lists every flag
            f.write("\n" + (digest.get("flags_text") or RD.render_flag_list(digest)) + "\n")
    with open(os.path.join(out_dir, "latest_verdict.json"), "w", encoding="utf-8") as f:
        json.dump({"event": event, "pass": pass_no, "verdict": digest["verdict"],
                   "flags": _unique(x["id"] for x in digest["flags"] if x["severity"] != RD.INFO),
                   "info_flags": _unique(x["id"] for x in digest["flags"] if x["severity"] == RD.INFO),
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
        with open(p, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def flag_coverage(text, digest):
    """(covered, missing): which flag ids, of every severity (INFO too, since 1.2.0), the commentary mentions (by id, or
    id with spaces)."""
    low = (text or "").lower()
    ids = []
    for f in sorted(digest["flags"], key=RD.flag_sort_key):
        if f["id"] not in ids:
            ids.append(f["id"])
    hit = [i for i in ids if i.lower() in low or i.lower().replace("_", " ") in low]
    return hit, [i for i in ids if i not in hit]


def invented_ids(text):
    """FLAG-LIKE ids (UPPER_CASE_WITH_UNDERSCORE) in Lumo's text that are neither one of the digest's flag ids nor a
    parameter / tool name from the pinned prompt (a small model once invented WITHIN_BREACH)."""
    known = set(RD.KNOWN_FLAG_IDS) | set(re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", SYSTEM_PROMPT))
    known |= {"LUMO_WATCH_MODEL", "NO_RUN_FILES"}
    found = []
    for m in re.finditer(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", text or ""):
        if m.group(0) not in known and m.group(0) not in found:
            found.append(m.group(0))
    return found


def explain_header(digest, cfg, tag):
    """Written by code before the first model token: the complete flag list, then the heading Lumo's text goes under."""
    flags_text = digest.get("flags_text") or RD.render_flag_list(digest)
    return ("<!-- Lumo (%s) comments on the code's verdict %s for %s; it does not set or change it. The flag list below "
            "is written by code and is complete. -->\n%s\n\n## Lumo's comments (model %s, one bullet per flag)\n" % (
                cfg["model"], digest["verdict"], tag, flags_text, cfg["model"]))


def explain(digest_path, cfg=None, out_path=None, connect=None, max_tokens=1000):
    """Ask Lumo to comment on a saved digest. Writes lumo_<tag>.md (the complete flag list, written by code, then
    Lumo's streamed bullets) and lumo_<tag>.status.json next to it. Never raises, never alters the digest or verdict."""
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
    header = explain_header(digest, cfg, tag)
    lock = os.path.join(d, "lumo.busy")
    with open(lock, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    try:
        st = stream_chat(payload, cfg["url"], out_path, status_path, cfg["first_token_s"], cfg["idle_s"],
                         connect=connect, header=header)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    covered, missing = flag_coverage(st.get("text"), digest)
    bogus = invented_ids(st.get("text"))
    if missing or bogus:                         # say so, deterministically (the list above has every real flag)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write("\n\n---\n")
            if missing:
                titles = {x["id"]: x for x in digest["flags"]}
                f.write("Not commented on by Lumo (%s): %s. They are in the complete flag list above.\n" % (
                    st.get("status"), ", ".join("%s%s" % (i, " (INFO: %s)" % titles[i]["title"] if titles[i]["severity"] == RD.INFO
                                                          else "") for i in missing)))
            if bogus:
                f.write("Lumo named ids that are not flags of this run: %s. Ignore them; the list above is the truth.\n" % (
                    ", ".join(bogus)))
    st.update(prompt_tokens_est=est_tokens(msgs[0]["content"] + msgs[1]["content"]), flags_total=len(covered) + len(missing),
              flags_covered=covered, flags_missing=missing, invented_ids=bogus, num_thread=cfg.get("num_thread"), num_ctx=cfg["num_ctx"],
              explain_mode=cfg.get("explain"))
    _write_status(status_path, {k: v for k, v in st.items() if k != "text"})
    return st


def _explain_env(cfg):
    return dict(os.environ, LUMO_WATCH_MODEL=cfg["model"], LUMO_WATCH_NUM_CTX=str(cfg["num_ctx"]),
                LUMO_WATCH_URL=cfg["url"], LUMO_WATCH_NUM_THREAD=str(cfg.get("num_thread", 2)),
                LUMO_WATCH_NUM_PREDICT=str(cfg["num_predict"]), LUMO_WATCH_FIRST_TOKEN_S=str(cfg["first_token_s"]),
                LUMO_WATCH_IDLE_S=str(cfg["idle_s"]))


_CHILDREN = []          # explain processes this watcher started; kept so they are reaped, never "still running" on gc


def reap_children(wait_s=0.0):
    """Collect finished explain processes (poll). Returns how many are still running after waiting up to wait_s."""
    t0 = time.time()
    while True:
        _CHILDREN[:] = [c for c in _CHILDREN if getattr(c, "poll", lambda: 0)() is None]
        if not _CHILDREN or time.time() - t0 >= wait_s:
            return len(_CHILDREN)
        time.sleep(0.05)


def spawn_explain(digest_path, cfg):
    """Start the explanation in a detached, niced process: the watcher never waits on it. Returns the Popen."""
    cmd = [sys.executable, os.path.abspath(__file__), "explain", digest_path]
    kw = {}
    if os.name != "nt":
        kw["start_new_session"] = True
        n = int(cfg.get("nice") or 0)
        if n > 0:
            kw["preexec_fn"] = lambda: os.nice(n)
    with open(digest_path[:-5] + ".lumo.log", "w", encoding="utf-8") as log:       # the child keeps its own copy
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=_explain_env(cfg), **kw)
    _CHILDREN.append(proc)
    return proc


def _read_status(status_path):
    try:
        with open(status_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def wait_for_lumo(status_path, wait_s):
    """Wait up to wait_s for the explanation to finish; then give up WITHOUT killing it (it keeps streaming to disk)."""
    t0 = time.time()
    while time.time() - t0 < wait_s:
        st = _read_status(status_path)
        if st and st.get("status") in ("done", "partial", "unavailable", "error", "timeout"):
            return st
        time.sleep(0.2)
    return _read_status(status_path) or {"status": "pending"}


# ----------------------------------------------------------------------------- when may Lumo use the CPU?
def _lisflood_process_running():
    """True when a lisflood process is alive on this machine (any run: they share the CPU). None when it cannot be
    told (then only the run folder's files decide)."""
    if os.environ.get("LUMO_WATCH_PROC_SCAN", "1") == "0":
        return None
    try:
        if os.path.isdir("/proc/self"):                              # Linux
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    try:
                        with open("/proc/%s/comm" % pid, encoding="utf-8", errors="replace") as f:
                            if f.read().strip().lower().startswith("lisflood"):
                                return True
                    except OSError:
                        continue
            return False
        if os.name == "nt":
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout
        else:                                                         # macOS / BSD
            out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=10).stdout
        return any(os.path.basename(l.strip()).lower().startswith("lisflood") for l in out.splitlines())
    except (OSError, subprocess.SubprocessError):
        return None


def _last_activity(run_dir):
    """Newest mtime of anything the Runner writes in a run folder (top-level files, the progress note, every pass's log and
    .mass), or None."""
    latest = None
    spots = []
    try:
        for e in os.scandir(run_dir):
            spots.append(e.path)
    except OSError:
        return None
    for pd in RD._pass_dirs(run_dir):
        spots += [os.path.join(pd, "lisflood.log"), os.path.join(pd, "results", "run.mass"), pd]
    for p in spots:
        try:
            t = os.path.getmtime(p)
        except OSError:
            continue
        latest = t if latest is None or t > latest else latest
    return latest


def engine_state(run_dir, cfg=None, now=None, proc=None):
    """May the CPU go to Lumo? {idle: bool, reason, finished, complete}. Pure file inspection plus a process look
    (proc=True/False/None overrides the look, for tests). Idle means: no lisflood process AND the Runner's whole pipeline is
    over (run_digest.run_complete: run_progress.json complete, run_report.json, run_setup.json finished / failed), or the
    Runner has stopped without finishing (nothing written to the run folder for cfg stale_s, default 900 s, and no lisflood
    process). A quiet gap between passes is NOT idle (1.3.0): the Runner works in Python between passes (domain growth,
    reading results) with no LISFLOOD process and no pass log growing; a gate that started Lumo there made pass 7 of DWR-2824
    take 71 s instead of 26 s."""
    cfg = cfg or settings()
    now = now if now is not None else time.time()
    setup = RD._load_json(os.path.join(run_dir, "run_setup.json")) or {}
    done, how = RD.run_complete(run_dir, setup)
    running = _lisflood_process_running() if proc is None else proc
    st = {"idle": False, "reason": "", "finished": done, "complete": done}
    if running:
        st["reason"] = "a lisflood process is running"
        return st
    if done:
        st.update(idle=True, reason="the Runner has finished the run (%s)" % how)
        return st
    stale = cfg.get("stale_s", RD.THRESHOLDS["stall_s"])
    last = _last_activity(run_dir)
    if stale and last is not None and now - last >= stale:
        st.update(idle=True, reason="the Runner has stopped: nothing written to the run folder for %.0f s and no lisflood "
                  "process (the run did not finish)" % (now - last), abandoned=True)
        return st
    pdirs = RD._pass_dirs(run_dir)
    if pdirs and RD._log_finished(pdirs[-1]) is False:
        st["reason"] = "pass %s is still running" % RD._pass_number(pdirs[-1])
    elif pdirs:
        st["reason"] = "the Runner is still working: pass %s has ended but the run has not finished" % RD._pass_number(pdirs[-1])
    else:
        st["reason"] = "the Runner has not finished the run"
    return st


def explain_gate(run_dir, cfg, now=None, proc=None):
    """(may_start, reason) for the configured LUMO_WATCH_EXPLAIN mode."""
    mode = cfg.get("explain", "idle")
    if mode == "never":
        return False, "LUMO_WATCH_EXPLAIN=never"
    if mode == "always":
        return True, "LUMO_WATCH_EXPLAIN=always"
    st = engine_state(run_dir, cfg, now, proc)
    return st["idle"], st["reason"]


def start_explain(jp, out_dir, event, pass_no, cfg, spawn=None):
    """Spawn one explanation and wait a few seconds for it. Returns the Lumo status dict."""
    tag = event_tag(event, pass_no)
    sp = os.path.join(out_dir, "lumo_%s.status.json" % tag)
    for stale in (sp, sp + ".part"):
        try:
            os.remove(stale)
        except OSError:
            pass
    reap_children()
    (spawn or spawn_explain)(jp, cfg)
    st = wait_for_lumo(sp, cfg["wait_s"]) if cfg["wait_s"] > 0 else {"status": "started"}
    reap_children()
    return st


# ----------------------------------------------------------------------------- hooks
DAM_RECORD_KEYS = ("dam_id", "nid_id", "name", "height_ft", "top_of_dam_elev_ft", "storage_acft", "surface_area_ac",
                   "stated_datum")


def flat_dam_record(digest):
    """A FLAT dam record (top-level dam_id / nid_id) for damit:classify's DAM_JSON, built from what the digest found
    (the dam folder's dam.json, else the run's own record, the hand-off or the folder name). The dam folder's own
    dam.json nests its values under "fields", which Hazard does not read; this file is written beside the digest, never
    into the dam or run folder. None when no dam id could be found."""
    dam = (digest.get("checks") or {}).get("dam") or {}
    if not dam.get("dam_id"):
        return None
    rec = {"dam_id": dam["dam_id"], "nid_id": dam["dam_id"], "name": dam.get("name"), "height_ft": dam.get("height_ft"),
           "top_of_dam_elev_ft": dam.get("top_ft"), "stated_datum": dam.get("stated_datum"),
           "_written_by": "lumo_watch %s (not the dam record: a flat copy for damit:classify DAM_JSON)" % VERSION,
           "_dam_id_source": dam.get("dam_id_source")}
    return {k: v for k, v in rec.items() if v is not None}


def write_flat_dam_record(out_dir, digest):
    rec = flat_dam_record(digest)
    if not rec:
        return None
    path = os.path.join(out_dir, "dam_record_hazard.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return path


def pass_receptors_due(run_dir, pass_no, cfg=None):
    """Should this pass_end hook sample the receptors? Every cfg pass_receptor_every-th pass (default 2), and always when the run is
    already over (a replayed hook costs the Runner nothing). 0 = never mid-run. The final raster is sampled at run_end either way."""
    cfg = cfg or settings()
    every = cfg.get("pass_receptor_every", 2)
    if pass_no is None or every == 1:
        return True
    if RD.run_complete(run_dir)[0]:
        return True
    return every > 0 and pass_no % every == 0


def run_event(run_dir, event, out_dir=None, pass_no=None, lumo=True, cfg=None, spawn=None, probe=None, **digest_kw):
    """One hook. Returns {digest, digest_path, verdict, lumo: status or None}. The verdict is final when this
    returns; Lumo's text, if any, lands in lumo_<event>.md later. lumo.status is "queued" when LISFLOOD is busy and
    the configured mode (LUMO_WATCH_EXPLAIN) says to wait: `watch` starts it when the run has finished; a one-shot
    `event` leaves the digest and the complete flag list and says how to ask for the explanation later."""
    if event not in EVENTS:
        raise ValueError("event must be one of %s" % ", ".join(EVENTS))
    cfg = cfg or settings()
    phase = event
    if event == "pass_end" and "sample_receptors" not in digest_kw:
        digest_kw["sample_receptors"] = pass_receptors_due(run_dir, pass_no, cfg)
    d = RD.build_digest(run_dir, phase=phase, upto_pass=pass_no if event in ("pass_end", "stall") else None, **digest_kw)
    out_dir = out_dir or default_out_dir(run_dir, d)
    if _inside(out_dir, run_dir):
        raise ValueError("refusing to write into the run folder")
    jp = write_digest(out_dir, d, event, pass_no)
    res = {"digest": d, "digest_path": jp, "verdict": d["verdict"], "lumo": None, "out_dir": out_dir,
           "pass_no": pass_no, "hazard_dam_record": write_flat_dam_record(out_dir, d)}
    if lumo and cfg.get("explain") == "never":
        pass                                         # LUMO_WATCH_EXPLAIN=never: no model call at all ("not asked")
    elif lumo:
        if lumo_busy(out_dir):
            res["lumo"] = {"status": "skipped", "error": "a Lumo explanation is still running"}
        else:
            ok, why = (probe or explain_gate)(run_dir, cfg)
            if not ok:
                res["lumo"] = {"status": "queued", "error": "not started: " + why,
                               "later": "python lumo_watch.py explain %s" % jp}
            else:
                res["lumo"] = start_explain(jp, out_dir, event, pass_no, cfg, spawn)
    return res


class EventDetector(object):
    """Turns what appeared in a run folder into hook events. Pure file inspection (no model, no process).

    state (a dict, kept by the caller / saved as JSON): passes_done, stall_fired, run_end, before_hazard, after_hazard."""

    def __init__(self, stall_s=None, record_grace_s=None):
        self.stall_s = stall_s if stall_s is not None else RD.THRESHOLDS["stall_s"]
        # (1.3.2) how long a finished pass waits for the Runner to record it in run_progress.json before the hook fires anyway
        self.record_grace_s = RECORD_GRACE_S if record_grace_s is None else float(record_grace_s)

    def scan(self, run_dir, state, now=None):
        now = now if now is not None else time.time()
        ev = []
        done = state.setdefault("passes_done", [])
        fired = state.setdefault("stall_fired", [])
        setup = RD._load_json(os.path.join(run_dir, "run_setup.json")) or {}
        finished = os.path.exists(os.path.join(run_dir, "run_report.json")) or (
            setup.get("status") == "finished" and setup.get("model_launched"))
        pdirs = RD._pass_dirs(run_dir)
        progress = RD.load_progress(run_dir)
        running = bool(progress) and not finished and not RD.run_complete(run_dir, setup, None, progress)[0]
        for i, pd in enumerate(pdirs):
            n = RD._pass_number(pd)
            if RD._log_finished(pd) and n not in done:
                if running and not RD.progress_pass(progress, pd).get("bounds"):
                    # LISFLOOD-FP has finished the pass but the Runner is still reading its results and has not written the
                    # pass into run_progress.json, which holds the georeference the hook needs. DWR-2801 (1.3.1): the hook
                    # fired in that gap on passes 4 to 6 and 8, found no grid, and sampled nothing. Wait for the entry (the
                    # grace is a cap for a Runner that never writes it); the next scan fires the hook.
                    lm = RD._log_mtime(pd)
                    if lm is None or now - lm < self.record_grace_s:
                        continue
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


RECORD_GRACE_S = 120.0


def own_rss_mb():
    """This process's resident and peak memory in MB from /proc/self/status, or (None, None) (1.3.2: the 2801 test could not say what
    the watcher held, `ps` named it `python`); every hook's log line carries it."""
    out = {}
    try:
        with open("/proc/self/status", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    out[line.split(":")[0]] = int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return out.get("VmRSS"), out.get("VmHWM")


def _log_line(msg):
    print(msg, flush=True)                       # a pipe or a file gets each line now, not when the process exits


def watch(run_dir, out_dir=None, poll_s=2.0, until="before_hazard", lumo=True, cfg=None, max_wait_s=None, once=False,
          stall_s=None, log=_log_line, spawn=None, probe=None, sleep=time.sleep, **digest_kw):
    """Poll the run folder; fire the hooks. Returns the list of results. Stops after `until` fires (run_end |
    before_hazard | after_hazard), after max_wait_s, or after one scan with once=True. Every event gets its digest
    at once. Lumo is queued: only the NEWEST event waits, and it starts when the Runner has finished the run and LISFLOOD is idle (LUMO_WATCH_EXPLAIN:
    idle | end | always | never), so the model never competes with the engine for the CPU. A 45 s run therefore
    finishes at full speed and is explained as soon as it is done."""
    cfg = cfg or settings()
    det, state, results = EventDetector(stall_s, cfg.get("record_grace_s")), {}, []
    pending = None                              # (result, event) waiting for an idle engine
    t0 = time.time()

    def try_start(force=False):
        nonlocal pending
        if pending is None or lumo_busy(pending[0]["out_dir"]):
            return
        r, e = pending
        ok, why = (probe or explain_gate)(run_dir, cfg)
        if not ok and not force:
            return
        r["lumo"] = start_explain(r["digest_path"], r["out_dir"], e["event"], e["pass"], cfg, spawn)
        log("[%s] Lumo explains %s%s (%s)" % (time.strftime("%H:%M:%S"), e["event"],
                                             " pass %s" % e["pass"] if e["pass"] else "", r["lumo"].get("status")))
        pending = None

    while True:
        evs = det.scan(run_dir, state)
        for e in evs:
            r = run_event(run_dir, e["event"], out_dir, e["pass"], lumo=False, cfg=cfg, spawn=spawn,
                          stall_s=stall_s, **digest_kw)
            r["event"] = e["event"]
            results.append(r)
            log("[%s] %s%s -> %s%s" % (time.strftime("%H:%M:%S"), e["event"], " (pass %s)" % e["pass"] if e["pass"] else "",
                                       r["verdict"], "; flags: " + ", ".join(
                                           sorted({f["id"] for f in r["digest"]["flags"] if f["severity"] != RD.INFO}))
                                       if r["digest"]["flags"] else "") + (
                "; receptors skipped: %s" % r["digest"]["checks"]["receptors_skipped"]
                if r["digest"].get("checks", {}).get("receptors_skipped") else "") + (
                " [watch RSS %.0f MB, peak %.0f MB]" % own_rss_mb() if own_rss_mb()[0] is not None else ""))
            if lumo and cfg.get("explain") != "never":
                if pending is not None:
                    pending[0]["lumo"] = {"status": "skipped", "error": "a newer event replaced it in the queue"}
                r["lumo"] = {"status": "queued", "error": "waiting for the Runner to finish the run"}
                pending = (r, e)
        if lumo:
            try_start()
        done = once or state.get(until) or (max_wait_s is not None and time.time() - t0 > max_wait_s)
        if done:
            if lumo and pending is not None and once:
                try_start()
            elif lumo and pending is not None and state.get("run_end"):
                # the run is over: give a busy engine (another LISFLOOD on this box) a while to go idle, then leave it queued
                t1 = time.time()
                while pending is not None and time.time() - t1 <= cfg.get("queue_wait_s", 300.0):
                    try_start()
                    if pending is not None:
                        sleep(poll_s)
                if pending is not None:
                    log("[%s] Lumo explanation still queued (LISFLOOD busy): python lumo_watch.py explain %s" % (
                        time.strftime("%H:%M:%S"), pending[0]["digest_path"]))
            return results
        sleep(poll_s)


# ----------------------------------------------------------------------------- CLI
def lower_priority(nice):
    """Raise this process's nice level to `nice` (POSIX; never lowers it, never fails). `watch` calls it so the pass hooks (digest
    reads, receptor sampling) yield the CPU to the Runner's LISFLOOD passes. The explain child process is niced separately."""
    if not nice or not hasattr(os, "nice"):
        return None
    try:
        cur = os.nice(0)
        return os.nice(nice - cur) if nice > cur else cur
    except OSError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lumo as a DamIT run watcher: the code sets the verdict, Lumo explains.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--explain", choices=EXPLAIN_MODES, help="when Lumo may use the CPU (default idle: only when "
                       "the whole run has finished; end = the same; always = any time; never)")
        p.add_argument("--explain-now", action="store_true", help="same as --explain always")
        p.add_argument("--num-thread", type=int, help="threads the model may use (default 2; 0 = Ollama's default)")
        p.add_argument("--idle-gap", type=float, help="no longer used (1.3.0: Lumo waits for the whole run to finish); accepted for old scripts")
        p.add_argument("--pass-receptor-every", type=int, help="sample the receptors at every Nth pass_end hook (default 2; 1 = every "
                       "pass; 0 = only at run_end); LUMO_WATCH_PASS_RECEPTOR_EVERY")
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
    p.add_argument("--num-thread", type=int, help="threads the model may use (default 2; 0 = Ollama's default)")
    p = sub.add_parser("prompt")
    p.add_argument("digest_json")
    p = sub.add_parser("system")
    p.add_argument("--write")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)      # piped output is line-buffered too
    except (AttributeError, ValueError, OSError):
        pass

    if a.cmd == "system":
        if a.write:
            with open(a.write, "w", encoding="utf-8") as f:
                f.write(system_prompt() + "\n")
        else:
            print(system_prompt())
        return 0
    if a.cmd == "explain":
        cfg = settings(a.model)
        if a.num_thread is not None:
            cfg["num_thread"] = max(0, a.num_thread)
        st = explain(a.digest_json, cfg)
        print(json.dumps({k: v for k, v in st.items() if k != "text"}, indent=1))
        return 0
    if a.cmd == "prompt":
        with open(a.digest_json, encoding="utf-8") as f:
            d = json.load(f)
        m = build_messages(d, d.get("event"))
        print(m[1]["content"])
        print("\n[system ~%d tokens + user ~%d tokens]" % (est_tokens(m[0]["content"]), est_tokens(m[1]["content"])))
        return 0

    cfg = settings(a.model)
    if a.lumo_wait is not None:
        cfg["wait_s"] = a.lumo_wait
    if a.explain_now:
        cfg["explain"] = "always"
    elif a.explain:
        cfg["explain"] = a.explain
    if a.num_thread is not None:
        cfg["num_thread"] = max(0, a.num_thread)
    if a.idle_gap is not None:
        cfg["idle_gap_s"] = max(0.0, a.idle_gap)
    if a.pass_receptor_every is not None:
        cfg["pass_receptor_every"] = max(0, a.pass_receptor_every)
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
        if (r["lumo"] or {}).get("status") == "queued":
            print("(%s) Ask later with: %s" % (r["lumo"]["error"], r["lumo"]["later"]))
        verdict = r["verdict"]
    elif a.cmd == "watch":
        lower_priority(cfg.get("pass_nice", 19))
        rs = watch(a.run_dir, a.out, a.poll, a.until, not a.no_lumo, cfg, a.max_wait, a.once, a.stall_s, **kw)
        order = {RD.OK: 0, RD.WATCH: 1, RD.PROBLEM: 2}
        verdict = max((r["verdict"] for r in rs), key=lambda v: order[v], default=RD.OK)
    return {RD.OK: 0, RD.WATCH: 1, RD.PROBLEM: 2}[verdict] if getattr(a, "exit_code", False) else 0


if __name__ == "__main__":
    sys.exit(main())
