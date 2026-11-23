#!/usr/bin/env python3
# vor.py v1.4.9 — local research assistant for dam-safety, dam-design and
# flood-hazard publications. Runs on your Mac against Ollama; nothing leaves the machine.
#
# This is a RESEARCH ASSISTANT. Every statement it writes must be checked against
# the cited page of the source document before it is used for any dam-safety decision.
# It is kept apart from `heim` (the code-triage model): own Ollama model (vor),
# own embedding model, own database (~/Vor/vor.db).
#
#   vor ingest [PATH ...]      add PDFs / .md / .txt (default: ~/Vor/library,
#                                      the drop folder). Unchanged files are skipped.
#                                      --prune drops documents whose file is gone.
#   vor add PATH [PATH ...]    copy the files into ~/Vor/library/added and index them. In
#                                      Terminal, type `vor add ` and drag the files in.
#   vor list                   documents, pages, chunks, pages with no text layer
#   vor meta DOC --title T --authors A --year Y --org O --number N
#                                      fix a document's citation (DOC = id or part of file name)
#   vor bib FILE.bib           take titles/authors/years from a Zotero/BibTeX export
#   vor search QUESTION        retrieval only (no model): best passages with page numbers
#   vor ask QUESTION           quick cited answer (one retrieval pass)
#   vor research QUESTION      deep research: plan sub-questions -> retrieve -> extract
#                                      verbatim evidence -> check every quote against the page
#                                      -> cited report in ~/Vor/reports/
#   vor chat                   ask follow-up questions in a loop. Drag a file or folder into
#                                      the window to add it without leaving the chat.
#
#   search / ask / research / chat also take:
#     --doc KEY        only read this publication. KEY is the id from `vor list`,
#                      or part of its file name, title or report number; punctuation does
#                      not matter, so --doc P-946 finds the file named "... P946.pdf".
#                      Several keys, comma separated, are read together. Naming the
#                      publication in the QUESTION instead hurts: "FEMA" is just another
#                      search word and matches every FEMA document.
#     --per-doc N      passages allowed from any one publication (default 3; with --doc
#                      the cap is lifted unless you set it, so a long guideline can give
#                      up all -k passages).
#   vor tables                 add the PDFs' tables as their own passages (documents indexed
#                                      before 1.4.0; new ones get them at ingest). Needs PyMuPDF.
#   vor ocr                    OCR the scanned PDFs (needs ocrmypdf) and re-ingest them
#   vor remove DOC             drop a document from the index (file is not touched)
#   vor doctor                 check Ollama, the two models and the database
#
# Settings (environment; the installer writes them to ~/.zshrc):
#   VOR_HOME     ~/Vor   (library/, reports/, vor.db)
#   VOR_MODEL    vor    (Ollama persona made by the installer)
#   VOR_EMBED    qwen3-embedding:0.6b
#   VOR_NUM_CTX  context window the persona was built with
#   VOR_THINK    1 = let the model reason before writing the report (slower)
#   OLLAMA_URL           http://127.0.0.1:11434
#
# 1.0.1: reads library.csv in every sub-folder of the library (fetch_asdso.py writes one per folder).
# 1.4.9 (2026-11-23): the model is told which passages come from the publication the question names. On the
#   2026-11-23 real-model test Vor read the right pages (WSP 2339 Table 1 p.10, Pierce et al. p.35) but each
#   passage was labelled only "Arcement (1989) Guide for Selecting..." or "FEMA (2010) Predicting Peak...", so
#   the model decided they were not "WSP 2339" or "Pierce, Thornton and Abt" and returned no finding in 4 s
#   (7 of 11 failures). Each passage of a named publication now says so, with the question's own words, and
#   a report number the title leaves out is shown beside it. Table values are quoted as whole rows.
#   Only a plain naming is labelled (not 'P-94' in 'P-946', a year, 'p 10', or words that fit two documents);
#   with --doc too. The quote check reads a row's dot leaders as a space and sees numbers written '.018';
#   a finding's source is read from 'S1' before any other number.
# 1.4.8 (2026-11-23): `vor ocr` tries once more when ocrmypdf fails on a PDF (often JPEG 2000 images
#   it cannot decode: "JPXDecode ... could not be decoded", exit 4, as on FEMA P-946 and HMR 55A). PyMuPDF
#   draws each scanned page as a plain image, ocrmypdf reads those, and the copy is the original with
#   those pages put back in place; pages that had a text layer are kept as they were.
# 1.4.7 (2026-11-23): the same, when the original is not in the library at all (only its OCR copy came
#   across to ~/Vor): an entry whose file is gone and whose OCR copy is indexed is dropped by `vor ingest`.
# 1.4.6 (2026-11-23): a scanned original that an older version indexed under ~/DamResearch (before the
#   library was renamed ~/Vor) is dropped by `vor ingest` when its OCR copy is the document. It matched no
#   path, so it stayed "no longer has a file" in `vor doctor` and "file gone" in `vor tables` for good.
# 1.4.5 (2026-11-23): `vor` on its own (or `vor help`) prints the short command list, and `vor WORDS` is
#   `vor ask WORDS` (a first word that is not a command is a question). A new install with nothing in the
#   library and no index is a WATCH in `vor doctor`, not a PROBLEM: nothing is missing yet. A PROBLEM is
#   still a library that has files but no index, or a second, fuller library elsewhere.
# 1.4.4 (2026-11-22): the Pierce question named its paper as 'Pierce, Thornton and Abt (2010)' and the equation
#   page (p.35) was never read. Searched inside that paper it ranked 8th, behind the cover (on p.1 and again on
#   p.2), two contents pages and pages that merely cite 'Pierce (2008)'. Now a question that names authors and a
#   year reads that document first (the year must match; the names must be its authors, or, when it has no
#   author metadata, all on its first three pages, or 'X et al.' written there as an author; one all-capitals
#   agency may be its organisation if that picks out one or two documents); inside a named document the
#   search leaves out the words that named it, also loose in the planner's search terms (a citation that
#   named nothing stays); the named documents share 4 passages (two papers: two each); and every search
#   skips a passage repeating one already taken and puts contents pages last (dot-leader entries whose page
#   numbers run in order, or under a contents heading; a numbered data sheet is not one).
# 1.4.3 (2026-11-22, the 1.4.2 call records): the D15F question's model call read all 8 passages (3,444
#   prompt tokens) and replied exactly '{"findings": [], "not_covered": []}', with the answer page among them.
#   An empty list of findings is now asked once more, passages in reverse order and a nudge to read each
#   one; every quote it then offers is still checked against its page. (Its 0.8 s was most likely Ollama
#   reusing an identical earlier prompt from its cache, so the 1.4.2 'too fast to have read them' note is dropped.)
# 1.4.2 (from the second real-model test, 2026-11-22): three questions (filter-d15f, filter-band,
#   pierce-length) came back in 1-2 s with "8 passages read, the model drew no quote" although the right
#   pages were among them; the cause is not known yet. What 1.4.2 changes: passages are fitted to the
#   window in tokens (digits and table bars are a token each; tables were counted at 3.2 characters a
#   token and could overfill it), a passage over PASSAGE_MAX is cut instead of ending the reading, only
#   passages the model was handed count as read, and every model call prints its passages, our token
#   count, Ollama's prompt_eval_count, seconds and done_reason (the eval keeps them). Table passages cannot
#   grow past PASSAGE_MAX: all-empty columns are dropped, a mostly empty grid is not kept, a long row is
#   cut. `vor tables --check` lists over-long passages already indexed; `vor tables --redo` re-reads them.
# 1.4.1 (from the first real-model test, 2026-11-22): a question that names a report ('FEMA 333',
#   'P-946', 'TD-39') reads that report's passages first; four FEMA 333 questions had never read FEMA 333,
#   because other FEMA manuals repeat its definitions. And a cited sentence whose quote holds the opposite
#   term ('high hazard' with the low-hazard definition) is called out under Checks: the quote checker
#   passed it, because the quote was on its page.
# 1.4.0: tables are read as tables. A table on a PDF page became running text, so a row's numbers lost
#   their column headings (a Manning n table read "0.025 0.030 0.033 ..."). With PyMuPDF, ingest now also
#   stores each table it finds as its own passage: its caption and the table in Markdown, header kept on
#   every piece. `vor tables` adds them to documents indexed before 1.4.0 without re-reading the rest.
# 1.3.3: Ollama is started in the background when it is not running (ensure_ollama, the same
#   function as Heim's), instead of failing with "cannot reach Ollama" until heim-start had run.
# 1.3.2: `vor ocr`, `vor ingest` and `vor doctor` no longer send you round in a circle. `vor ocr`
#   said "No scanned PDFs to OCR" when every scanned document was under its default share
#   (30 % of the pages), and the other two answered that with "Run: vor ocr"; now all three
#   say how many documents are under it and how to take them, and `vor ocr --list` shows them
#   without running anything. The doctor sent you to `vor ingest` for a file that is an exact
#   copy of an indexed one, or too large to index, both of which ingest skips. It gives the
#   whole path of a document whose file is gone, and `vor list --missing` lists them.
# 1.3.1: `vor ocr` followed by `vor ingest` no longer puts the scanned original back in the
#   index beside its searchable copy. library/_ocr/ocr_sources.json records which original each
#   copy stands in for. A stopped `vor ocr` keeps what it finished and loses nothing, a document
#   ocrmypdf could not do stays indexed as it was, and two originals with one file name get two
#   copies. Before this the original was dropped from the index before its copy was in it.
# 1.3.0: an answer is never empty. A reply with no text in it (a reasoning model spending its
#   whole allowance before the first word of the answer) is asked for once more with reasoning
#   off and more room; if that is empty too, the answer is the checked findings themselves,
#   each with its quote and page, and the report says which of the three it was and why.
# 1.2.0: `vor add`, and `vor chat` takes a dragged file: the line Terminal pastes is a path, which
#        used to be sent to the model as a question. A chat that is running keeps its vectors in
#        memory, so before this a document ingested from another tab was invisible to it until
#        the chat was restarted, and nothing said so.
#
# Stdlib only; numpy makes search fast, PyMuPDF gives printed page labels. PDF text
# backends in order: PyMuPDF -> pdftotext -> pypdf.
import os, sys, re, json, time, math, hashlib, sqlite3, argparse, subprocess, difflib, shutil, shlex
import urllib.request, urllib.error, unicodedata
from array import array
from datetime import datetime, timedelta

VERSION = "1.4.9"


def _home():
    """Where the library and its index live: the folder that HOLDS THE INDEX.

    The tool was called damresearch until 2026-11-13 and kept everything in ~/DamResearch
    (research.db). setup-vor.zsh moves that to ~/Vor (vor.db). Until it has run, both names
    can exist: fetch_asdso.py or download-library.zsh run first would create ~/Vor to hold
    the downloads, and a rule of "use ~/Vor if it is there" then opens a new, empty index
    beside the real one. Nothing errors: `vor ask` simply finds no passages. So the index
    decides, not the folder. fetch_asdso.py carries the same rule (vor_home), and
    tests/test_home.py holds the two to the same answer.
    """
    if os.environ.get("VOR_HOME"):
        return os.path.expanduser(os.environ["VOR_HOME"])
    new = os.path.expanduser("~/Vor")
    old = os.path.expanduser("~/DamResearch")
    # DAMRESEARCH_HOME: the old installers exported it, so a library kept somewhere else is
    # still named by it in a shell whose rc file has not been rewritten yet.
    legacy = os.path.expanduser(os.environ.get("DAMRESEARCH_HOME") or old)
    for d in (new, legacy, old):
        if any(os.path.isfile(os.path.join(d, f)) for f in ("vor.db", "research.db")):
            return d
    if not os.path.isdir(new) and os.path.isdir(old):
        return old
    return new


HOME = _home()
LIBRARY = os.path.join(HOME, "library")
REPORTS = os.path.join(HOME, "reports")


def _db_path():
    """vor.db, or the pre-rename research.db beside it when vor.db does not exist yet."""
    if os.environ.get("VOR_DB"):
        return os.environ["VOR_DB"]
    new = os.path.join(HOME, "vor.db")
    old = os.path.join(HOME, "research.db")
    if not os.path.exists(new) and os.path.exists(old):
        return old
    return new


DB_PATH = _db_path()
BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CHAT_MODEL = os.environ.get("VOR_MODEL", "vor")
EMBED_MODEL = os.environ.get("VOR_EMBED", "qwen3-embedding:0.6b")
NUM_CTX = int(os.environ.get("VOR_NUM_CTX", "16384"))
THINK = os.environ.get("VOR_THINK", "0") == "1"
CHARS_PER_TOKEN = 3.2
CHUNK_TARGET = 1100
CHUNK_MAX = 1600
CHUNK_OVERLAP = 200
PASSAGE_MAX = 4 * CHUNK_MAX  # 1.4.2: most characters of one passage handed to the model
MIN_PAGE_CHARS = 40
EMBED_BATCH = 16
MAX_FILE_BYTES = 300 * 1024 * 1024
OCR_MIN_FRACTION = 0.3      # `vor ocr` takes a PDF when at least this share of its pages is scanned
DOCTOR_HASH_LIMIT = 200     # the doctor reads this many unindexed files at most to look for copies
TEXT_EXT = (".md", ".txt")
DOC_EXT = (".pdf",) + TEXT_EXT
SKIP_DIRS = {"__MACOSX", ".git", "_ocr_tmp", "node_modules"}
# The one line of character either AI gets. It greets; it never answers, so it cannot change
# what the model asserts. Everything that shapes an answer is in prompts/manner.txt.
VOICE = "Vor - literature assistant. Every sentence traces to a page, or it says it cannot."
BANNER = ("RESEARCH ASSISTANT OUTPUT - NOT ENGINEERING JUDGEMENT. Every statement must be "
          "checked against the cited page of the source before use in any dam-safety decision.")

try:
    import numpy as np
except ImportError:
    np = None


def start_hint():
    """How to start Ollama on this computer (heim-start exists only on a Mac install; the Linux installer
    unpacks Ollama into ~/local-ai/ollama/bin, which is not on PATH)."""
    if sys.platform == "darwin":
        return "run heim-start in a Terminal tab of its own, or open the Ollama app"
    if os.name == "nt":
        return "open Ollama from the Start menu, or run  ollama serve  in another window"
    own = os.path.join(os.path.expanduser("~"), "local-ai", "ollama", "bin", "ollama")
    if os.path.isfile(own):
        return "run  %s serve  in another terminal window" % own
    return "run  ollama serve  in another terminal window"


def die(msg, code=1):
    print("vor: " + msg, file=sys.stderr)
    sys.exit(code)



def damit_banner(subtitle=""):
    """DaMiT wordmark for the terminal (brand kit colours); plain text when piped or NO_COLOR is set."""
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return "DaMiT" + ("  " + subtitle if subtitle else "")
    c = lambda rgb, s: "\x1b[1;38;2;%d;%d;%dm%s\x1b[0m" % (rgb + (s,))
    teal, cream, amber = (48, 196, 200), (250, 250, 240), (244, 158, 24)
    word = c(teal, "D") + c(cream, "a") + c(teal, "M") + c(amber, "iT")
    return word + ("  \x1b[2m" + subtitle + "\x1b[0m" if subtitle else "") + "\n \x1b[38;2;31;188;188m~\x1b[0m"

def say(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------------- Ollama

def _post(path, payload, timeout=3600, _retry=True):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("Ollama %s -> HTTP %d: %s" % (path, e.code, body)) from None
    except urllib.error.URLError as e:
        if _retry and ensure_ollama(BASE, log=say):      # 1.3.3: start it instead of failing
            return _post(path, payload, timeout, _retry=False)
        raise RuntimeError("cannot reach Ollama at %s (%s). To start it, %s."
                           % (BASE, e.reason, start_hint())) from None


_OLLAMA_CHECKED = []


def ensure_ollama(base, log=print):
    """Start Ollama in the background when it is not answering at `base` (a local address only), and wait
    up to 30 s for it. Returns True when it answers. Before this, every assistant failed with "connection
    refused" until `heim-start` had been run in a tab of its own. HEIM_NO_AUTOSTART=1 turns it off.
    The same function is in rag_query.py, run_results.py and vor.py (a test keeps them identical)."""
    import shutil, subprocess, time, urllib.parse  # nosec B404 - starts the local Ollama server only
    if _OLLAMA_CHECKED:
        return _OLLAMA_CHECKED[0]

    def up():
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False
    if up():
        _OLLAMA_CHECKED.append(True)
        return True
    host = urllib.parse.urlparse(base).hostname or ""
    if os.environ.get("HEIM_NO_AUTOSTART") == "1" or host not in ("127.0.0.1", "localhost", "::1"):
        return False
    home = os.path.expanduser("~")
    exe = next((p for p in (os.path.join(home, "local-ai", "bin", "Ollama.app", "Contents", "Resources", "ollama"),
                            shutil.which("ollama"), "/Applications/Ollama.app/Contents/Resources/ollama",
                            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"))
                if p and os.path.isfile(p)), None)
    if not exe:
        log("Ollama is not running and no ollama program was found to start. Start it (heim-start or the Ollama app).")
        return False
    logf = os.path.join(home, "local-ai", "ollama-serve.log")
    os.makedirs(os.path.dirname(logf), exist_ok=True)
    env = dict(os.environ, OLLAMA_FLASH_ATTENTION=os.environ.get("OLLAMA_FLASH_ATTENTION", "1"),
               OLLAMA_KV_CACHE_TYPE=os.environ.get("OLLAMA_KV_CACHE_TYPE", "q8_0"))
    log("Ollama was not running: starting it in the background (log: %s) ..." % logf)
    with open(logf, "ab") as out:
        kw = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}   # detached
        subprocess.Popen([exe, "serve"], stdout=out, stderr=out, stdin=subprocess.DEVNULL, env=env, **kw)  # nosec B603
    for _ in range(60):
        if up():
            _OLLAMA_CHECKED.append(True)
            return True
        time.sleep(0.5)
    log("Ollama did not answer within 30 s; see %s" % logf)
    return False


def _get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read())


def is_qwen_embed(model):
    return "qwen3-embedding" in model


def doc_prefix(model):
    return "search_document: " if "nomic" in model else ""


def query_text(model, q):
    if is_qwen_embed(model):
        return ("Instruct: Given a question about dam safety, dam design or flood hazards, "
                "retrieve passages from technical publications that answer it\nQuery: " + q)
    if "nomic" in model:
        return "search_query: " + q
    if "mxbai" in model:
        return "Represent this sentence for searching relevant passages: " + q
    return q


def embed(texts, model):
    out = _post("/api/embed", {"model": model, "input": texts, "truncate": True})
    vecs = out.get("embeddings") or []
    if len(vecs) != len(texts):
        raise RuntimeError("embed returned %d vectors for %d texts" % (len(vecs), len(texts)))
    res = []
    for v in vecs:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        res.append([x / n for x in v])
    return res


_think_ok = [True]
_format_ok = [True]

# How the most recent chat() reply ended: done_reason ("stop", "length", ...), tokens written
# (eval_count) and how many characters of them were reasoning rather than answer. 1.3.0: a
# reply can come back EMPTY with nothing wrong at the HTTP level - a reasoning model spends its
# whole num_predict allowance in message.thinking and writes no content - and before this
# nothing recorded which of those happened.
LAST_REPLY = {"done_reason": "", "eval_count": 0, "thinking_chars": 0, "content_chars": 0, "prompt_tokens": 0,
              "seconds": 0.0}


def _note_reply(done_reason, eval_count, thinking_chars, content_chars, prompt_tokens=0, seconds=0.0):
    LAST_REPLY.update(done_reason=str(done_reason or ""), eval_count=int(eval_count or 0),
                      thinking_chars=int(thinking_chars or 0), content_chars=int(content_chars or 0),
                      prompt_tokens=int(prompt_tokens or 0), seconds=float(seconds or 0.0))


def strip_think(text):
    """Remove a model's inline reasoning from a reply. Closed <think>..</think> blocks go; an
    opening tag that is never closed means the reply ran out while still reasoning, so
    everything after it goes; a lone closing tag means the renderer dropped the opening one,
    so everything before it goes."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def empty_reply_reason():
    """Why the last reply had no answer in it, in words a report can carry."""
    r = LAST_REPLY
    if r["done_reason"] == "length":
        if r["thinking_chars"]:
            return ("it reached its length limit (%d tokens) while still reasoning, before writing "
                    "an answer" % r["eval_count"])
        return "it reached its length limit (%d tokens) without writing an answer" % r["eval_count"]
    if r["thinking_chars"]:
        return "it reasoned (%d characters) and then stopped without writing an answer" % r["thinking_chars"]
    if r["eval_count"]:
        return "it stopped after %d token(s) with no text (done_reason: %s)" % (
            r["eval_count"], r["done_reason"] or "not given")
    return "the reply was empty (done_reason: %s)" % (r["done_reason"] or "not given")


def chat(messages, schema=None, think=False, stream_to=None, num_predict=None, temperature=0.2):
    """One /api/chat call. schema = JSON schema (structured output). Returns the answer text.
    stream_to = a file object to echo the answer into while it is written."""
    opts = {"num_ctx": NUM_CTX, "temperature": temperature}
    if num_predict:
        opts["num_predict"] = num_predict
    p = {"model": CHAT_MODEL, "messages": messages, "options": opts, "stream": stream_to is not None}
    if schema is not None and _format_ok[0]:
        p["format"] = schema
    elif schema is not None:
        # 1.0.4: no structured output (older Ollama, or a model whose renderer has none, e.g.
        # qwen3.6 on Ollama 0.40: HTTP 501 "structured output is unavailable"): ask for the
        # same JSON in words; parse_json takes it out of the reply.
        msgs = [dict(m) for m in messages]
        msgs[-1]["content"] = (msgs[-1]["content"] + "\n\nReply with ONE JSON object only, no "
                               "other text, matching this JSON schema:\n" + json.dumps(schema))
        p["messages"] = msgs
    if _think_ok[0]:
        p["think"] = bool(think)
    try:
        if stream_to is None:
            out = _post("/api/chat", p)
            msg = out.get("message") or {}
            content = (msg.get("content") or "").strip()
            _note_reply(out.get("done_reason"), out.get("eval_count"), len(msg.get("thinking") or ""),
                        len(content), out.get("prompt_eval_count"), (out.get("total_duration") or 0) / 1e9)
            return content
        return _stream(p, stream_to)
    except RuntimeError as e:
        s = str(e)
        if "HTTP 400" in s and "think" in s.lower() and _think_ok[0]:
            _think_ok[0] = False          # older Ollama, or a model without a thinking switch
            return chat(messages, schema, False, stream_to, num_predict, temperature)
        if (schema is not None and _format_ok[0]
                and (("HTTP 400" in s and "format" in s.lower())
                     or ("HTTP 501" in s and "structured output" in s.lower()))):
            _format_ok[0] = False         # no JSON-schema output here: ask for JSON in words
            return chat(messages, schema, think, stream_to, num_predict, temperature)
        raise


def _stream(p, out):
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(p).encode(),
                                 headers={"Content-Type": "application/json"})
    buf, thinking_shown, thinking_chars, done_reason, eval_count = [], False, 0, "", 0
    prompt_tokens, seconds = 0, 0.0
    try:
        r = urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as e:
        raise RuntimeError("Ollama /api/chat -> HTTP %d: %s"
                           % (e.code, e.read().decode("utf-8", "replace")[:400])) from None
    except urllib.error.URLError as e:
        raise RuntimeError("cannot reach Ollama at %s (%s)" % (BASE, e.reason)) from None
    with r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            try:
                ch = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ch.get("error"):
                raise RuntimeError(ch["error"])
            msg = ch.get("message") or {}
            thinking_chars += len(msg.get("thinking") or "")
            if msg.get("thinking") and not thinking_shown:
                out.write("(thinking...)\n")
                out.flush()
                thinking_shown = True
            piece = msg.get("content") or ""
            if piece:
                buf.append(piece)
                out.write(piece)
                out.flush()
            if ch.get("done"):
                done_reason, eval_count = ch.get("done_reason") or "", ch.get("eval_count") or 0
                prompt_tokens, seconds = ch.get("prompt_eval_count") or 0, (ch.get("total_duration") or 0) / 1e9
                break
    out.write("\n")
    text = "".join(buf).strip()
    _note_reply(done_reason, eval_count, thinking_chars, len(text), prompt_tokens, seconds)
    return text


def parse_json(text):
    """Structured output is JSON already; older Ollama / models may wrap it in prose or fences."""
    text = strip_think(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


# --------------------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS docs(
  id INTEGER PRIMARY KEY, sha1 TEXT UNIQUE, path TEXT, title TEXT, authors TEXT, year TEXT,
  org TEXT, number TEXT, pages INTEGER, notext TEXT, backend TEXT, added TEXT, meta_src TEXT);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, doc_id INTEGER, page INTEGER, label TEXT, idx INTEGER, txt TEXT, vec BLOB);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
"""


class _Conn(sqlite3.Connection):
    fts = False


def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(DB_PATH, factory=_Conn)
    db.executescript(SCHEMA)
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                   "txt, title, content='', tokenize='porter unicode61')")
        fts = True
    except sqlite3.OperationalError:
        fts = False                     # SQLite without FTS5: vector search only
    db.fts = fts
    return db


def meta_get(db, k, default=None):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))


def check_embed_model(db):
    used = meta_get(db, "embed_model")
    if used and used != EMBED_MODEL:
        die("this library was indexed with %s but VOR_EMBED is %s. Either set it back, "
            "or rebuild: rm %s && vor ingest" % (used, EMBED_MODEL, DB_PATH))


def delete_doc(db, doc_id):
    if db.fts:
        for cid, txt, title in db.execute(
                "SELECT c.id, c.txt, d.title FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE c.doc_id=?",
                (doc_id,)).fetchall():
            db.execute("INSERT INTO chunks_fts(chunks_fts, rowid, txt, title) VALUES('delete',?,?,?)",
                       (cid, txt, title or ""))
    db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM docs WHERE id=?", (doc_id,))


def find_doc(db, key):
    if str(key).isdigit():
        r = db.execute("SELECT id FROM docs WHERE id=?", (int(key),)).fetchone()
        if r:
            return r[0]
    rows = db.execute("SELECT id, path FROM docs WHERE path LIKE ?", ("%" + key + "%",)).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if not rows:
        die("no document matches %r (see: vor list)" % key)
    die("%r matches %d documents; use the id from `vor list`:\n  " % (key, len(rows))
        + "\n  ".join("%d  %s" % r for r in rows[:20]))


def squash(s):
    """Lower-case, punctuation removed: 'FEMA P-946' and 'P946.pdf' both become ...p946."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def find_docs(db, key):
    """Document ids a --doc filter names, as (ids, labels).

    KEY is an id, or part of a file name, title or report number. Punctuation is ignored,
    so --doc P-946 matches a file called "... P946.pdf". Comma-separated keys are read
    together. Unlike find_doc this allows several matches on purpose: the point is to scope
    a question to one publication, or to a family of them.
    """
    rows = db.execute("SELECT id, title, path, number FROM docs").fetchall()
    ids, labels = [], []
    for part in [p.strip() for p in str(key).split(",") if p.strip()]:
        if part.isdigit():
            hit = [r for r in rows if r[0] == int(part)]
        else:
            if len(squash(part)) < 2:
                die("--doc %r is too short to match on; use the id from `vor list`" % part)
            low = part.lower()
            hit = [r for r in rows if low in (r[2] or "").lower() or low in (r[1] or "").lower()
                   or low in (r[3] or "").lower()]
            if not hit:                                   # 'P-946' against a file named P946
                sq = squash(part)
                hit = [r for r in rows if sq in squash(r[2]) or sq in squash(r[1]) or sq in squash(r[3])]
        if not hit:
            die("--doc %r matches no document (see: vor list)" % part)
        for r in hit:
            if r[0] not in ids:
                ids.append(r[0])
                labels.append("%d  %s" % (r[0], (r[1] or r[2])[:80]))
    return ids, labels


_NAMED = re.compile(r"\b(FEMA|P|TD|WSP|EM|EP|ER|ETL|HDS|HEC|NEH|TR|DS|AH|REG|Bulletin|Circular)[\s_-]*"
                    r"(\d+(?:[.-]\d+)*)", re.I)


_PAGE_NO = r"(?:[A-Z]-\d+|\d+(?:[-–]\d+)?|[ivxlc]+)\b"
_LEADER = re.compile(r"(?:\.\s?){6,}\s*" + _PAGE_NO + r"(?![.,]\d)", re.I)     # not '1,240' or '1.3'
_CONTENTS_HEAD = re.compile(r"^\W*(?:(?:[ivxlc]+|\d+)\W+)?(?:table\s+of\s+)?contents\b|\bcontents\s+(?:\(continued\)|page)\b"
                            r"|\b(?:table\s+of\s+contents|list\s+of\s+(?:figures|tables|plates|illustrations|appendices))\b",
                            re.I)
_CONTENTS_ENTRY = re.compile(r"^\s*(?:(?:figure|fig\.|table|chapter|section|appendix|plate|part)\s+[\dA-Z]"
                             r"|\d+(?:[.-]\d+)*\.?\s+[A-Za-z]|[IVX]+\.\s+[A-Za-z])", re.I)


def is_contents(txt):
    """A table-of-contents or list-of-figures passage: three or more dot-leader entries ending in a page number
    ('Figure 10 Comparison ........ 31', '1.1 Purpose ........ 1-1'), under a contents heading (a passage that
    starts 'Contents', or 'Table of Contents' / 'List of Figures' anywhere) or, with page numbers that never
    go down, numbered entries ('Figure 10', '3.2 Breach', '1. Introduction', 'Chapter 4') or nothing but short
    entries (the later pieces of a long contents page). Stored passages have no line breaks (chunk_page joins
    them), so this counts entries, not lines. A data sheet ('1. Crest width, feet ........ 30', 'Reservoir
    contents, acre-feet ........ 5000') is not a contents page: its numbers do not run in order."""
    t = txt or ""
    pages = [m.group(0) for m in _LEADER.finditer(t)]
    if len(pages) < 3:
        return False
    if _CONTENTS_HEAD.search(t):
        return True
    if not _ascending(pages):          # a contents page's numbers run 1, 3, 7 ...; a data sheet's 230, 110, 30
        return False
    entries = [e for e in _LEADER.split(t) if e.strip()]
    if sum(1 for e in entries if _CONTENTS_ENTRY.search(e)) >= 3:
        return True
    # the later pieces of a long unnumbered contents page: almost nothing but short worded entries
    worded = [e for e in entries if len(e) <= 100 and len(re.findall(r"[A-Za-z]", e)) >= 3]
    return len(pages) >= 5 and sum(len(e) for e in worded) >= 0.7 * sum(len(e) for e in entries)


def _ascending(leaders):
    """Page numbers after the dot leaders never go down ('1-1', '1-4', '2-1' as chapter, page; roman skipped)."""
    keys = []
    for ld in leaders:
        n = re.search(_PAGE_NO + r"\s*$", ld, re.I).group(0).strip()
        if re.fullmatch(r"[ivxlc]+", n, re.I):
            continue
        keys.append(tuple(int(x) if x.isdigit() else 10 ** 6 + ord(x.upper())      # 'A-1' after page 79
                          for x in re.findall(r"\d+|[A-Za-z]", n)))
    return all(a <= b for a, b in zip(keys, keys[1:]))


def text_key(doc_id, txt):
    """What makes two passages the same: the same document and the same words (the whole text, so pieces of
    one table, which share caption and header, stay apart)."""
    return (doc_id, hashlib.sha1(squash(txt).encode()).hexdigest()) if squash(txt) else None


# A name: a word not starting lower case, of any letters (accents, Polish, Turkish ...), apostrophe or hyphen.
_SURNAME = r"(?![a-z\u00df-\u00f6\u00f8-\u00ff])[^\W\d_](?:[^\W\d_]|['\-])*"
_YEAR = r"(?:19|20)\d\d[a-z]?"
_YEARS = r"%s(?:\s*,\s*(?:%s|[a-z]\b))*(?:\s*,\s*pp?\.\s*\d+(?:\s*[-–]\s*\d+)?)?" % (_YEAR, _YEAR)
_NAMES = r"%s(?:\s*,\s*%s)*(?:\s*,?\s+(?:and|&)\s+%s)?(?:\s+et\s+al\.?)?(?:'s)?" % (_SURNAME, _SURNAME, _SURNAME)
_AUTHOR_YEAR = re.compile(r"(?<![^\W\d_])(%s)\s*\(\s*(%s)\s*\)" % (_NAMES, _YEARS))
_YEAR_PAREN = re.compile(r"\(\s*(?:%s)\s*\)" % _YEARS)
_CITE_PART = re.compile(r"^\s*(?:(?i:e\.g\.|i\.e\.|see\s+also|see|cf\.|after|from)\s*,?\s*)?(%s)\s*,?\s+(%s)\s*$"
                        % (_NAMES, _YEARS))     # no re.I: it would let a name start lower case
NOT_SURNAMES = set("""however also in on at for from the a an and or but what which when where why how does did do is are
was were according see under per by with dam dams safety program programs report reports table figure equation
section chapter appendix bureau guidelines guideline manual technical federal state national association
department agency board committee center institute university survey service corps engineers reclamation
usbr usace fema nrcs usgs asdso ferc hec tr td similarly briefly thus then now so next likewise finally additionally
specifically here there conversely alternatively meanwhile previously later earlier originally notably interestingly
overall again still instead otherwise accordingly consequently therefore hence moreover furthermore nevertheless
nonetheless first second third lastly today historically traditionally recently generally typically""".split())
ORG_MAX_DOCS = 2       # 'ASDSO (2015)' names a document only when it picks out one or two


def _plain(question):
    """Curly apostrophes (macOS smart quotes) as straight ones, so "Froehlich’s (2008)" reads as a citation."""
    return (question or "").replace("’", "'").replace("‘", "'")


def _citations(question):
    """(matched text, names text, [years], at sentence start) for every author-year citation: 'Pierce et al.
    (2010)', "Froehlich's (1995a, b)", 'Froehlich (2008, p. 35)', and in parentheses '(Froehlich, 2008)',
    '(Pierce et al. 2010)', '(e.g., Froehlich, 2008; Wahl, 2004)'."""
    q = _plain(question)
    out = []
    for y in _YEAR_PAREN.finditer(q):          # look back at most 200 characters from each '(year)'
        lo = max(0, y.start() - 200)
        m = None
        for m in _AUTHOR_YEAR.finditer(q, lo, y.end()):
            pass
        if m is None or m.end() != y.end():
            continue
        if m.start() == lo and lo > 0 and re.match(r"[^\W\d_]", q[lo - 1]):
            continue                          # the look-back cut a word in two
        out.append((m.group(0), m.group(1), [x[:4] for x in re.findall(_YEAR, m.group(2))],
                    re.search(r"(?:^|[.?!:;]\s)\s*$", q[:m.start()]) is not None))
    for g in re.finditer(r"\(([^()]{4,300})\)", q):
        for part in g.group(1).split(";"):
            m = _CITE_PART.match(part)
            if m:
                out.append((part.strip(), m.group(1), [y[:4] for y in re.findall(_YEAR, m.group(2))], False))
    return out


def _cited_names(group):
    """Surnames in an 'A, B and C' citation: capitalised words, without possessives."""
    names = [re.sub(r"'s$", "", n) for n in re.findall(_SURNAME, group)]
    return [n for n in names if n[:1].isupper()]


def _has(name, text):
    return re.search(r"(?<![^\W\d_])%s(?![^\W\d_])" % re.escape(name), text or "", re.I) is not None


def _as_author(name, text):
    """The name written as an author on a cover: after initials ('M. W. Pierce', 'MICHAEL W. PIERCE') or
    before them ('Pierce, M.'), in any case."""
    n = re.escape(name)
    return re.search(r"(?<![^\W\d_])[A-Z]\.\s*(?:[A-Z]\.\s*)*(?i:%s)(?![^\W\d_])|(?<![^\W\d_])(?i:%s),\s*[A-Z]\."
                     % (n, n), text or "") is not None


_PERSON = re.compile(r"[A-Z][a-z]+,\s*[A-Z]\.|[A-Z]\.\s*[A-Z][a-z]+|[A-Z][a-z]+\s+(?:[A-Z]\.\s*)*[A-Z][a-z]+"
                     r"|[A-Z][a-z]+\s+[A-Z]\.")
_NOT_PERSON = re.compile(r"\b(?:department|bureau|corps|agency|university|engineers?|reclamation|user|customer|"
                         r"administrator|administration|service|survey|office|commission|institute|association|"
                         r"council|district|county|state|states|inc|llc|company|authority|laboratory|division|"
                         r"management|federal|national|security|interior|army|owner|author|unknown|default)\b", re.I)


def _names_people(authors):
    """An author field that names people ('Wahl, T. L.', 'Tony Wahl'), not an agency or PDF junk ('Federal
    Emergency Management Agency', 'U.S. Army Corps of Engineers', 'Microsoft Office User')."""
    return _PERSON.search(authors) is not None and _NOT_PERSON.search(authors) is None


def _docs_for(db, names, etal, years):
    """Documents of one of the years whose authors are these names. Every name must be in the authors field.
    The PDF's own author field is often empty or junk ('Administrator', 'FEMA', a login), or holds only the
    first author (Pierce et al. (2010) is filed under FEMA with none), so unless it names other people, the
    first three pages count too: two or more names all there, or one with 'et al.' written there as an
    author ('M. W. Pierce'). A single all-capitals name ('USSD', 'ICOLD') may instead be the document's
    organisation (or the whole of a non-person author field), if that picks out no more than ORG_MAX_DOCS
    documents."""
    rows = db.execute("SELECT id, title, path, authors, org FROM docs WHERE substr(trim(CAST(year AS TEXT)), 1, 4) IN (%s)"
                      % ",".join("?" * len(years)), years).fetchall()
    hits, org_hits = [], []
    agency = len(names) == 1 and names[0].isupper() and len(names[0]) >= 3
    for did, title, path, authors, org in rows:
        a = (authors or "").strip()
        ok = bool(a) and all(_has(n, a) for n in names)
        if ok and agency and not _names_people(a):      # 'FEMA (2013)' and an author field 'FEMA': as organisation
            org_hits.append((did, title, path))
            continue
        others = bool(a) and _names_people(a) and not any(_has(n, a) for n in names)
        if not ok and not others and (len(names) >= 2 or etal):
            front = " ".join(t for (t,) in db.execute(
                "SELECT txt FROM chunks WHERE doc_id = ? AND page <= 3", (did,)).fetchall())
            ok = all(_has(n, front) for n in names) if len(names) >= 2 else _as_author(names[0], front)
        if ok:
            hits.append((did, title, path))
        elif agency and _has(names[0], org):
            org_hits.append((did, title, path))
    if not hits and len(org_hits) <= ORG_MAX_DOCS:
        hits = org_hits
    return hits


def _author_year_docs(db, question):
    """1.4.4: documents the question names by author and year ('Pierce, Thornton and Abt (2010)'), as
    (id, label, matched text). Words that are not names ('However', 'Dam') are left out. A citation that
    opens a sentence as 'Word, Name (year)' is tried without its first word when it matches nothing (common
    openers such as 'Similarly' are on the list); co-authors are never dropped. An agency on the NOT_SURNAMES
    list ('USBR (1982)') is matched against the organisation."""
    out = []
    for text, group, years, opens in _citations(question):
        if not years:
            continue
        raw = _cited_names(group)
        etal = re.search(r"\bet\s+al\b", group) is not None
        names = [n for n in raw if n.lower() not in NOT_SURNAMES]
        orgs = [n for n in raw if n.lower() in NOT_SURNAMES and n.isupper() and len(n) >= 3]   # 'USBR (1982)'
        if not names and len(orgs) == 1:
            names = orgs
        if not names:
            continue
        found = _docs_for(db, names, etal, years)
        if (not found and opens and len(names) == 2 and not etal and names[0] == raw[0]
                and re.fullmatch(r"\s*%s\s*,\s*%s(?:'s)?\s*" % (re.escape(names[0]), re.escape(names[1])), group)):
            found = _docs_for(db, names[1:], etal, years)         # as in: Plainly, Froehlich (2008)
        for did, title, path in found:
            out.append((did, "%d  %s" % (did, (title or path)[:80]), text))
    return out


def strip_naming(question, spans=None):
    """The question without the words that name a document ('FEMA 333', 'Pierce, Thornton and Abt (2010)'). They
    pick the document; inside it they only match its cover and reference pages, which outranked the page with
    the answer. With spans (named_docs' third value, for THIS question) only the words that did pick a
    document go: a citation of a paper not in the library ('MacDonald and Langridge-Monopolis (1984)') stays
    as search words. Returns the question unchanged when too little would be left."""
    q = _plain(question)
    if spans is None:
        spans = [c[0] for c in _citations(q)] + [m.group(0) for m in _NAMED.finditer(q)]
    for sp in sorted(set(spans), key=len, reverse=True):
        q = re.sub(re.escape(sp), " ", q, flags=re.I)
    # the same names and years left loose, as in the planner's search terms ('Pierce Thornton Abt 2010')
    words = set()
    for sp in spans:
        if _AUTHOR_YEAR.search(sp) or _CITE_PART.match(sp):
            words.update(n for n in _cited_names(sp) if len(n) >= 3 and n.lower() not in NOT_SURNAMES)
            words.update(re.findall(r"(?:19|20)\d\d", sp))
    for w in sorted(words, key=len, reverse=True):
        q = re.sub(r"(?<![^\W_])%s(?:'s)?(?:[a-z]\b)?(?![^\W_])" % re.escape(w), " ", q, flags=re.I)
    if words:
        q = re.sub(r"\bet\s+al\b\.?", " ", q)
    q = re.sub(r"\(\s*[;,]?\s*\)", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    left = [t for t in re.findall(r"[A-Za-z]{3,}", q) if t.lower() not in STOP]
    return q if len(left) >= 2 else question


def named_docs(db, question, spans=False, by_doc=False):
    """Documents the question names by report number ('FEMA 333', 'P-946', 'TD-39', 'WSP 2339') or by author
    and year ('Pierce, Thornton and Abt (2010)'), as (ids, labels), or (ids, labels, matched texts) with
    spans=True. The 2026-11-22 real-model test asked four FEMA 333 questions and FEMA 333 was never among
    the passages read: other FEMA manuals repeat its definitions and outranked it. A number match needs the
    prefix and number together ('p946' in 'FEMA P946.pdf'), or, for a number of 3+ digits, the number on its
    own as a whole number plus the prefix anywhere ('FEMA ... 333_04.pdf').
    1.4.9: by_doc=True returns {id: [the question's words that named it]}, only where those words name that one
    document plainly (see _plainly_named); the model is then told the passage is from the named publication."""
    q = _plain(question)
    want = [(m.group(0), m.group(1), m.group(2)) for m in _NAMED.finditer(q)]
    ids, labels, used = [], [], []
    strong = {}                                     # the question's words -> documents they name plainly
    if want or _citations(q):
        rows = db.execute("SELECT id, title, path, number, org FROM docs").fetchall() if want else []
        for text, pfx, num in want:
            tight = squash(pfx + num)
            for r in rows:
                raw = " ".join(x or "" for x in (os.path.basename(r[2] or ""), r[1], r[3], r[4]))
                sq = squash(raw)
                ok = tight in sq
                if not ok and len(re.sub(r"\D", "", num)) >= 3:
                    ok = bool(re.search(r"(?<![\d.])%s(?![\d])" % re.escape(num), raw)) and squash(pfx) in sq
                if ok:
                    used.append(text)
                    if _plainly_named(text, pfx, num, raw):
                        strong.setdefault(text, set()).add(r[0])
                    if r[0] not in ids:
                        ids.append(r[0])
                        labels.append("%d  %s" % (r[0], (r[1] or r[2])[:80]))
        for did, label, text in _author_year_docs(db, q):
            used.append(text)
            strong.setdefault(text, set()).add(did)
            if did not in ids:
                ids.append(did)
                labels.append(label)
    if by_doc:
        words = {}
        for text, docs in strong.items():
            if len(docs) == 1:                      # words that fit two documents name neither of them plainly
                words.setdefault(next(iter(docs)), []).append(text)
        return {d: words[d] for d in ids[:6] if d in words}
    if spans:
        return ids[:6], labels[:6], used
    return ids[:6], labels[:6]


def _plainly_named(text, pfx, num, raw):
    """1.4.9: does 'FEMA P-946' / 'WSP 2339' in the question name this document plainly, and not by a loose match
    (named_docs' own test only reorders the reading)? The independent review of 1.4.9 found loose matches that
    would have been labelled as the named publication: 'P-94' in 'P-946', 'HDS-5' in 'HDS-51', 'Bulletin 17'
    (B) in 'Bulletin 17C', 'p 10' (a page) in 'P-1025', 'FEMA 2013' (a year) in two FEMA documents.
    The number must stand on its own in the file name, title or number (no digit or letter after it), and
    neither a year nor a one-letter prefix written apart from its number counts."""
    if re.fullmatch(r"(?:19|20)\d\d", num):
        return False
    if len(pfx) == 1 and (pfx.islower() or re.search(r"\s", text)):
        return False
    numpat = r"[._\s-]?".join(re.escape(g) for g in re.split(r"[.-]", num))
    if re.search(r"(?<![A-Za-z0-9])%s[\s_.-]*%s(?![0-9A-Za-z])" % (re.escape(pfx), numpat), raw, re.I):
        return True
    return (len(re.sub(r"\D", "", num)) >= 3 and squash(pfx) in squash(raw)
            and re.search(r"(?<![A-Za-z0-9.])%s(?![0-9A-Za-z])" % numpat, raw) is not None)


def merge_hits(first, rest, k):
    """first (the named documents' passages), then rest, without repeats, k in all."""
    out, seen = [], set()
    for h in list(first) + list(rest):
        key = text_key(getattr(h, "doc_id", None), getattr(h, "txt", "") or "")
        if h.cid in seen or (key and key in seen):
            continue
        seen.add(h.cid)
        if key:
            seen.add(key)
        out.append(h)
        if len(out) >= k:
            break
    return out


_OPPOSITES = (("high", "low", "significant"), ("upstream", "downstream"), ("minimum", "maximum"),
              ("increase", "decrease"), ("above", "below"))


def opposite_terms(text, ev):
    """Cited sentences whose quotes hold the opposite term and not the sentence's own: 'High hazard
    potential dams are those where failure results in no probable loss of human life [F1]' when F1 is
    the LOW hazard definition. The quote checker passes that (the quote is on its page); this does not.
    Returns one line per suspect sentence."""
    fmap = {f["F"]: f for f in ev.findings}
    flags = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        cited = [fmap[int(n)] for n in re.findall(r"F(\d+)", sent) if int(n) in fmap]
        if not cited:
            continue
        bare = re.sub(r"\[F[^\]]*\]", "", sent).lower()
        quotes = " ".join(f["quote"] for f in cited).lower()
        for group in _OPPOSITES:
            said = [w for w in group if re.search(r"\b%s\b" % w, bare)]
            if len(said) != 1:
                continue
            w = said[0]
            other = [o for o in group if o != w and re.search(r"\b%s\b" % o, quotes)]
            if other and not re.search(r"\b%s\b" % w, quotes):
                flags.append("a sentence says '%s' but its quote(s) %s say '%s' instead: %s" % (
                    w, ", ".join("F%d" % f["F"] for f in cited), other[0], textwrap_short(bare.strip(), 90)))
                break
    return flags


def scope_note(labels):
    """One line naming what --doc scoped the search to, so a silent over-match is visible."""
    if not labels:
        return ""
    if len(labels) <= 6:
        return "Scoped to %d document(s):\n  %s" % (len(labels), "\n  ".join(labels))
    return "Scoped to %d documents: %s, ... (%d more)" % (
        len(labels), "; ".join(l.split("  ", 1)[-1][:40] for l in labels[:3]), len(labels) - 3)


# --------------------------------------------------------------------------- text extraction

def clean(t):
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("­", "")                                  # soft hyphen
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)                       # embank-\nment
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_pdf(path):
    """[(page_no, label, text)], backend, pdf_meta"""
    try:
        import pymupdf as pm
    except ImportError:
        try:
            import fitz as pm
        except ImportError:
            pm = None
    if pm is not None:
        try:
            d = pm.open(path)
            pages = []
            for i, pg in enumerate(d):
                try:
                    label = pg.get_label() or ""
                except Exception:
                    label = ""
                pages.append((i + 1, label, pg.get_text("text") or ""))
            md = dict(d.metadata or {})
            d.close()
            return pages, "pymupdf", md
        except Exception as e:
            say("    PyMuPDF failed on this file (%s); trying pdftotext" % e)
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True)
        if r.returncode == 0:
            parts = r.stdout.decode("utf-8", "replace").split("\f")
            if parts and not parts[-1].strip():
                parts = parts[:-1]
            md = {}
            info = subprocess.run(["pdfinfo", path], capture_output=True)
            for line in info.stdout.decode("utf-8", "replace").splitlines():
                k, _, v = line.partition(":")
                if k.strip() in ("Title", "Author", "CreationDate"):
                    md[{"Title": "title", "Author": "author", "CreationDate": "creationDate"}[k.strip()]] = v.strip()
            return [(i + 1, "", t) for i, t in enumerate(parts)], "pdftotext", md
    try:
        import pypdf
        rd = pypdf.PdfReader(path)
        pages = []
        for i, pg in enumerate(rd.pages):
            try:
                label = rd.page_labels[i]
            except Exception:
                label = ""
            pages.append((i + 1, label, pg.extract_text() or ""))
        md = {}
        if rd.metadata:
            md = {"title": rd.metadata.get("/Title") or "", "author": rd.metadata.get("/Author") or "",
                  "creationDate": rd.metadata.get("/CreationDate") or ""}
        return pages, "pypdf", md
    except ImportError:
        raise RuntimeError("no PDF reader: install PyMuPDF (pip install pymupdf) or poppler (pdftotext)")


TABLE_IDX = 1000            # chunk idx of a page's first table passage (text passages count from 0)
TABLE_MIN_NUMBER_LINES = 6  # a page is searched for tables only with this many lines of numbers (the finder
                            # takes about 0.7 s a page; USGS WSP 2339: 13 of 44 pages searched, every n table found)


def table_markdown(rows):
    """A table (list of rows of cells, the first row the header) as Markdown, or '' when it is not a table
    worth keeping (fewer than 2 rows or 2 columns, or almost empty)."""
    rows = [[re.sub(r"\s+", " ", str(c or "")).strip().replace("|", "/") for c in r] for r in rows or []]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    keep = [j for j in range(n) if any(r[j] for r in rows)]          # 1.4.2: no all-empty columns
    rows = [[r[j] for j in keep] for r in rows]
    n = len(keep)
    filled = sum(1 for r in rows for c in r if c)
    if n < 2 or filled < 4 or filled < 0.2 * n * len(rows):          # 1.4.2: a mostly empty grid
        return ""
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def table_chunks(caption, md):
    """Passages for one table: the caption and the header on every piece, rows never split."""
    lines = [ln if len(ln) <= CHUNK_MAX else ln[:CHUNK_MAX - 2] + " …" for ln in md.split("\n")]   # 1.4.2
    head, body = lines[:2], lines[2:]
    lead = ("Table: %s\n" % caption) if caption else "Table:\n"
    out, cur = [], []
    for ln in body:
        if cur and len(lead) + sum(len(x) + 1 for x in head + cur + [ln]) > CHUNK_MAX:
            out.append(lead + "\n".join(head + cur))
            cur = []
        cur.append(ln)
    if cur:
        out.append(lead + "\n".join(head + cur))
    return out


_NUMBER_LINE = re.compile(r"[\s\d.,\-\u2013%()<>=+/]*\d[\s\d.,\-\u2013%()<>=+/]*")


def table_candidate(text):
    """Worth running the (slow) table finder on: enough lines that are only numbers (a table whose cells are
    read one per line), or a few lines holding three numbers or more (a table read row by row)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    only = sum(1 for ln in lines if _NUMBER_LINE.fullmatch(ln))
    rows = sum(1 for ln in lines if len(re.findall(r"\d+(?:\.\d+)?", ln)) >= 3)
    return only >= TABLE_MIN_NUMBER_LINES or rows >= 3


def _cell_words(words, bbox, pm):
    """The page's words whose centre falls in bbox, in reading order (block, line, word)."""
    r = pm.Rect(bbox)
    ws = [w for w in words if r.contains(pm.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))]
    ws.sort(key=lambda w: (w[5], w[6], w[7]))
    return " ".join(w[4] for w in ws)


def _table_rows(t, words=None, pm=None):
    """A PyMuPDF table's rows. Each cell is rebuilt from the page's words when they are given: that keeps
    the spaces between words and numbers like .017 whole (to_markdown() can drop the spaces, extract() can
    put a decimal point after its digits). to_markdown() and then extract() are the fallbacks."""
    if words and pm is not None and getattr(t, "rows", None):
        try:
            rows = [[_cell_words(words, c, pm) if c else "" for c in r.cells] for r in t.rows]
            if any(any(c for c in r) for r in rows):
                return rows
        except Exception:
            pass
    try:
        md = t.to_markdown()
    except Exception:
        md = ""
    rows = []
    for ln in (md or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("|") or re.match(r"^\|(\s*:?-+:?\s*\|)+$", ln):
            continue
        rows.append([c.replace("<br>", " ").strip() for c in ln.strip("|").split("|")])
    return rows or t.extract()


_CAPTION = re.compile(r"^\s*table\s+[0-9A-Z]+[.:\s-]", re.I)


def _table_caption(words, bbox, pm):
    """The caption above a table: the nearest line within 150 pt that starts 'Table N' (plus a bracketed
    note line right after it), else the last line within 60 pt."""
    x0, y0, x1, _ = bbox
    lines = {}
    for w in words:
        if w[3] <= y0 + 1 and w[1] >= y0 - 150:
            lines.setdefault((w[5], w[6]), []).append(w)
    ordered = []
    for k in sorted(lines):
        ws = sorted(lines[k], key=lambda w: w[7])
        ordered.append((min(w[1] for w in ws), " ".join(w[4] for w in ws)))
    for n in range(len(ordered) - 1, -1, -1):
        if _CAPTION.match(ordered[n][1]):
            cap = ordered[n][1]
            if n + 1 < len(ordered) and ordered[n + 1][1].lstrip().startswith("["):
                cap += " " + ordered[n + 1][1]
            return cap.strip()[:200]
    near = [t for y, t in sorted(ordered) if y >= y0 - 60]
    return (near[-1].strip() if near else "")[:200]


def extract_pdf_tables(path, pages_text=None):
    """{page_no: [table passage, ...]} found by PyMuPDF's table finder; {} without PyMuPDF or on error.
    Only pages that look like they hold a table are searched (the finder is slow and most pages hold none)."""
    try:
        import pymupdf as pm
    except ImportError:
        try:
            import fitz as pm
        except ImportError:
            return {}
    out = {}
    try:
        d = pm.open(path)
    except Exception:
        return {}
    try:
        for i, pg in enumerate(d):
            text = pages_text.get(i + 1) if pages_text else None
            if text is None:
                text = pg.get_text("text") or ""
            if not table_candidate(text) or not hasattr(pg, "find_tables"):
                continue
            try:
                found = pg.find_tables()
            except Exception:
                continue
            try:
                words = pg.get_text("words") or []
            except Exception:
                words = []
            for t in getattr(found, "tables", []) or []:
                try:
                    md = table_markdown(_table_rows(t, words, pm))
                except Exception:
                    md = ""
                if not md:
                    continue
                try:
                    cap = _table_caption(words, t.bbox, pm)
                except Exception:
                    cap = ""
                out.setdefault(i + 1, []).extend(table_chunks(cap, md))
    finally:
        d.close()
    return out


def extract_text_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        t = f.read()
    # Split long notes at headings so a citation points at a section, not a whole file.
    parts = re.split(r"\n(?=#{1,3} )", t) if path.endswith(".md") else [t]
    pages, acc = [], ""
    for p in parts:
        if len(acc) + len(p) > 6000 and acc:
            pages.append(acc)
            acc = ""
        acc += ("\n" if acc else "") + p
    if acc:
        pages.append(acc)
    return [(i + 1, "sec %d" % (i + 1), x) for i, x in enumerate(pages)], "text", {}


BAD_TITLE = re.compile(r"^(microsoft word|untitled|document\d*|\S+\.(docx?|pdf|indd|tmp))", re.I)


def guess_meta(path, pages, md):
    title = (md.get("title") or "").strip()
    src = "pdf-metadata"
    if not title or len(title) < 6 or BAD_TITLE.match(title):
        title, src = "", "first-page"
        for _, _, t in pages[:2]:
            for line in clean(t).splitlines():
                s = line.strip()
                if 12 <= len(s) <= 180 and sum(c.isalpha() for c in s) > 0.6 * len(s):
                    title = s
                    break
            if title:
                break
    if not title:
        title, src = os.path.splitext(os.path.basename(path))[0].replace("_", " "), "file-name"
    authors = (md.get("author") or "").strip()
    year = ""
    m = re.search(r"(19|20)\d\d", md.get("creationDate") or "")
    first = clean(pages[0][2])[:3000] if pages else ""
    m2 = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", first)
    if m2:
        year = m2.group(1)
    elif m:
        year = m.group(0)
    return {"title": title[:300], "authors": authors[:300], "year": year, "meta_src": src}


def chunk_page(text):
    """Chunks never cross a page, so every citation points at one page."""
    text = clean(text)
    if len(text) < MIN_PAGE_CHARS:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9][^\n]{0,80}\n)", text) if p.strip()]
    pieces = []
    for p in paras:
        p = p.replace("\n", " ")
        while len(p) > CHUNK_MAX:
            cut = p.rfind(". ", 0, CHUNK_TARGET + 200)
            cut = cut + 1 if cut > CHUNK_TARGET // 2 else CHUNK_TARGET
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 1 > CHUNK_TARGET:
            chunks.append(cur)
            tail = cur[-CHUNK_OVERLAP:]
            k = tail.find(". ")
            cur = (tail[k + 2:] if k >= 0 else "") + " " + p
            cur = cur.strip()
        else:
            cur = (cur + " " + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- OCR copies
# `vor ocr` writes a searchable copy of a scanned PDF to library/_ocr, and the copy is what is
# indexed. The original stays in the library, so something has to remember that it has been
# replaced: otherwise the next ingest sees a file that is not in the index and adds it again,
# and the document is in the library twice, once with its unreadable pages.
# library/_ocr/ocr_sources.json is that record: {sha1 of the original: {"copy": the file name
# in _ocr, "from": where the original is, inside the library}}. It is keyed by content, so an
# original that changes is a new document; and it sits beside the copies, not in the index, so
# it is still there after an index is deleted and rebuilt.

def ocr_dir():
    return os.path.join(LIBRARY, "_ocr")


def scan_split(rows, min_fraction=OCR_MIN_FRACTION):
    """The documents with pages that have no text layer, sorted by what `vor ocr` does with
    them. rows are (id, path, pages, notext); each list holds (id, path, pages, scanned pages).

    take   a PDF with at least min_fraction of its pages scanned: `vor ocr` does it
    below  a PDF under that share: left alone unless --min-fraction is lowered
    gone   its file is no longer there, so nothing can be run on it
    other  not a PDF (ocrmypdf reads only PDFs)

    A copy OCR already made is in none of them: a page OCR could make nothing of stays that
    way. One function for `vor ocr`, `vor ingest` and the doctor, because before 1.3.2 they
    disagreed: with every scanned document under the default share, `vor ocr` said there was
    nothing to OCR and the other two said to run it."""
    take, below, gone, other = [], [], [], []
    for i, p, n, nt in rows:
        k = len([x for x in (nt or "").split(",") if x])
        if not k or in_ocr_dir(p):
            continue
        row = (i, p, n or 0, k)
        if not os.path.exists(p):
            gone.append(row)
        elif not p.lower().endswith(".pdf"):
            other.append(row)
        elif k >= max(1, (n or 1) * min_fraction):
            take.append(row)
        else:
            below.append(row)
    return take, below, gone, other


def _share(fraction):
    return "%g %%" % (fraction * 100)


def ocr_advice(take, below, gone, other, installed=True):
    """What to run for the documents scan_split sorted, at the default share. One sentence."""
    if not (take or below):
        return ("Nothing to run: %s." % " and ".join(
            w for w, on in (("their files are gone", gone), ("they are not PDFs", other)) if on))
    first = "" if installed else "OCR is not installed: re-run the installer with --ocr, then: "
    if take and below:
        return first + ("Run: vor ocr (takes the %d with at least %s of their pages scanned), or "
                        "vor ocr --min-fraction 0 for all %d. vor ocr --list shows them first."
                        % (len(take), _share(OCR_MIN_FRACTION), len(take) + len(below)))
    if take:
        return first + "Run: vor ocr"
    return first + ("Each has under %s of its pages scanned, which a plain `vor ocr` leaves alone. "
                    "See them: vor ocr --min-fraction 0 --list. Take them: vor ocr --min-fraction 0"
                    % _share(OCR_MIN_FRACTION))


def _show_path(path):
    """A path as the doctor prints it: inside the library, relative to it; else with ~."""
    p, lib = os.path.abspath(path), os.path.abspath(LIBRARY) + os.sep
    if p.startswith(lib):
        return p[len(lib):]
    home = os.path.expanduser("~") + os.sep
    return "~" + os.sep + p[len(home):] if p.startswith(home) else p


def in_ocr_dir(path):
    return os.path.abspath(path).startswith(os.path.abspath(ocr_dir()) + os.sep)


def _lib_rel(path):
    path, lib = os.path.abspath(path), os.path.abspath(LIBRARY)
    return os.path.relpath(path, lib) if path.startswith(lib + os.sep) else path


def ocr_map_load():
    try:
        with open(os.path.join(ocr_dir(), "ocr_sources.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(m, dict):
        return {}
    return {h: v for h, v in m.items() if isinstance(v, dict) and v.get("copy")}


def ocr_map_save(m):
    os.makedirs(ocr_dir(), exist_ok=True)
    path = os.path.join(ocr_dir(), "ocr_sources.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def ocr_adopt(m, library_files):
    """Copies written before the record existed (vor 1.3.0 and earlier): <name>.ocr.pdf is taken
    to stand in for <name>.pdf when exactly one PDF in the library has that name. True when the
    record gained an entry."""
    d = ocr_dir()
    if not os.path.isdir(d):
        return False
    owned = {v["copy"] for v in m.values()}
    loose = [f for f in sorted(os.listdir(d)) if f.lower().endswith(".ocr.pdf") and f not in owned]
    if not loose:
        return False
    by_stem = {}
    for f in library_files:
        if f.lower().endswith(".pdf") and not in_ocr_dir(f):
            by_stem.setdefault(os.path.splitext(os.path.basename(f))[0], []).append(f)
    gained = False
    for name in loose:
        from_ = by_stem.get(name[:-len(".ocr.pdf")], [])
        if len(from_) != 1:
            continue
        try:
            h = sha1_of(from_[0])
        except OSError:
            continue
        if h not in m:
            m[h] = {"copy": name, "from": _lib_rel(from_[0])}
            gained = True
    return gained


def ocr_copy_name(m, path, h):
    """The file name in _ocr for this original: its own name, unless another original has it."""
    if h in m:
        return m[h]["copy"]
    stem = os.path.splitext(os.path.basename(path))[0]
    name = stem + ".ocr.pdf"
    if name in {v["copy"] for v in m.values()} or os.path.exists(os.path.join(ocr_dir(), name)):
        name = "%s-%s.ocr.pdf" % (stem, h[:8])
    return name


def ocr_replaced_paths():
    """The originals the record says a copy stands in for. No hashing: the doctor's view."""
    out = set()
    for v in ocr_map_load().values():
        src = v.get("from") or ""
        if src and os.path.exists(os.path.join(ocr_dir(), v["copy"])):
            out.add(os.path.normpath(src if os.path.isabs(src) else os.path.join(LIBRARY, src)))
    return out


# --------------------------------------------------------------------------- ingest

def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def walk(paths):
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isfile(p):
            if p.lower().endswith(DOC_EXT):
                yield p
            continue
        if not os.path.isdir(p):
            say("  not found: %s" % p)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(files):
                if f.startswith(("._", ".")) or not f.lower().endswith(DOC_EXT):
                    continue
                yield os.path.join(root, f)


def load_sidecar(paths):
    """library.csv next to the files: file,title,authors,year,org,number (any subset of columns)."""
    import csv
    out = {}
    files = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if not os.path.isdir(p):
            continue
        # every library.csv under the folder (fetch_asdso.py writes one per sub-folder)
        for root, dirs, fs in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            if "library.csv" in fs:
                files.append(os.path.join(root, "library.csv"))
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("file") or "").strip()
                if name:
                    out[os.path.basename(name)] = {k: (v or "").strip() for k, v in row.items() if k != "file"}
    return out


def cmd_ingest(a):
    db = connect()
    check_embed_model(db)
    paths = a.paths or [LIBRARY]
    os.makedirs(LIBRARY, exist_ok=True)
    side = load_sidecar(paths)
    files = list(walk(paths))
    say("Scanning %d file(s) under %s" % (len(files), ", ".join(paths)))
    known = {r[0]: (r[1], r[2]) for r in db.execute("SELECT sha1, id, path FROM docs")}
    by_path = {r[1]: (r[0], r[2]) for r in db.execute("SELECT id, path, sha1 FROM docs")}
    # 1.3.1: which originals an OCR copy stands in for (see "OCR copies" above)
    omap = ocr_map_load()
    if ocr_adopt(omap, files if paths == [LIBRARY] else list(walk([LIBRARY]))):
        ocr_map_save(omap)
    copy_from = {v.get("from"): h for h, v in omap.items()}
    walked = set(files)
    added = skipped = failed = notext = replaced = 0
    t0 = time.time()
    for n, path in enumerate(files, 1):
        try:
            if not os.path.exists(path):          # an out-of-date OCR copy removed a moment ago
                continue
            if os.path.getsize(path) > MAX_FILE_BYTES:
                say("  [%d/%d] SKIP (over %d MB): %s" % (n, len(files), MAX_FILE_BYTES >> 20, path))
                skipped += 1
                continue
            h = sha1_of(path)
            if not in_ocr_dir(path):
                copy = os.path.join(ocr_dir(), omap[h]["copy"]) if h in omap else ""
                if copy and os.path.exists(copy) and (copy in by_path or copy in walked):
                    # its searchable copy is the document; an original that an earlier version
                    # indexed a second time comes back out
                    if path in by_path:
                        delete_doc(db, by_path.pop(path)[0])
                        db.commit()
                        known.pop(h, None)
                    elif h in known and known[h][0] is not None and not os.path.exists(known[h][1]):
                        # 1.4.6: the same original indexed under a path that is gone (the library
                        # was ~/DamResearch before 2026-11-13): no path matches it, so drop it by
                        # its content, or it stays "no longer has a file" for good
                        old_id, old_path = known.pop(h)
                        delete_doc(db, old_id)
                        by_path.pop(old_path, None)
                        db.commit()
                    replaced += 1
                    continue
                was = copy_from.get(_lib_rel(path))
                if was and was != h and was in omap:
                    # the file changed since its copy was made: the copy is of the older text
                    stale = os.path.join(ocr_dir(), omap.pop(was)["copy"])
                    if stale in by_path:
                        known.pop(by_path[stale][1], None)
                        delete_doc(db, by_path.pop(stale)[0])
                        db.commit()
                    if os.path.exists(stale):
                        os.remove(stale)
                    ocr_map_save(omap)
                    say("  %s was made from an older version of %s: removed. Run `vor ocr` again if "
                        "the new one has scanned pages." % (os.path.basename(stale), os.path.basename(path)))
            if h in known:
                did, old = known[h]
                if old != path and not os.path.exists(old):
                    db.execute("UPDATE docs SET path=? WHERE id=?", (path, did))   # file was moved
                    db.commit()
                skipped += 1
                continue
            if path in by_path and by_path[path][1] != h:
                say("  [%d/%d] changed, re-indexing: %s" % (n, len(files), os.path.basename(path)))
                delete_doc(db, by_path[path][0])
                db.commit()
            ok = ingest_one(db, path, h, side.get(os.path.basename(path)), n, len(files))
            known[h] = (None, path)
            if ok:
                added += 1
            else:
                notext += 1
        except KeyboardInterrupt:
            say("\nStopped. Finished documents are saved; run ingest again to continue.")
            break
        except RuntimeError as e:
            if "cannot reach Ollama" in str(e):
                db.close()
                die(str(e))
            say("  [%d/%d] FAILED %s: %s" % (n, len(files), os.path.basename(path), e))
            failed += 1
    # 1.4.7: an original whose file is gone (not in the library at all, only its OCR copy is) never
    # comes up in the walk above. When its searchable copy is indexed, the copy is the document: the
    # original's entry goes, or it stays "no longer has a file" for good.
    indexed = {r[0] for r in db.execute("SELECT path FROM docs")}
    for did, dpath, dh in db.execute("SELECT id, path, sha1 FROM docs").fetchall():
        rec = omap.get(dh)
        if rec and not os.path.exists(dpath) and os.path.join(ocr_dir(), rec["copy"]) in indexed:
            delete_doc(db, did)
            replaced += 1
    db.commit()
    if a.prune:
        roots = [os.path.abspath(os.path.expanduser(p)) for p in paths]
        gone = [(i, p) for i, p in db.execute("SELECT id, path FROM docs")
                if any(p.startswith(r) for r in roots) and not os.path.exists(p)]
        for i, p in gone:
            delete_doc(db, i)
            say("  pruned (file gone): %s" % p)
        db.commit()
    nd, nc = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0], db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    say("Done in %.0f s: %d added, %d with no text, %d unchanged/skipped, %d failed. Library: %d documents, %d passages."
        % (time.time() - t0, added, notext, skipped, failed, nd, nc))
    if replaced:
        say("%d scanned original(s) left out: the searchable copy in library/_ocr is indexed instead." % replaced)
    split = scan_split(db.execute("SELECT id, path, pages, notext FROM docs WHERE notext!='' AND notext IS NOT NULL"))
    scanned = sum(len(x) for x in split)
    if scanned:
        say("%d document(s) have pages with no text layer (scanned). %s"
            % (scanned, ocr_advice(*split, installed=bool(ocr_exe()))))
    db.close()


def dropped_paths(line):
    """The existing files/folders a line names, when it names nothing else.

    Dragging a file into a terminal pastes its path: spaces backslash-escaped in Terminal
    and iTerm, the whole path quoted in some others, several files space-separated. A token
    must look like a path (a separator or a leading ~) AND exist, so an ordinary question is
    never mistaken for a drop, even one whose only word matches a file in the current folder."""
    try:
        parts = shlex.split(line)
    except ValueError:                  # an unbalanced quote: a question, not a path
        return []
    out = []
    for p in parts:
        full = os.path.abspath(os.path.expanduser(p))
        if not (os.sep in p or p.startswith("~")) or not os.path.exists(full):
            return []
        out.append(full)
    return out


def add_paths(paths):
    """Copy files into LIBRARY/added and index them; returns (documents, passages) added.

    Both numbers, because a scanned PDF adds a document and no passages: it is in the
    library and nothing can be asked of it until `vor ocr` has run.

    Copied, not indexed where they lie: a dragged file usually sits in Downloads or on the
    Desktop, and the library should not lose its source when that copy is tidied away. A
    file already inside the library, and a whole folder, are indexed in place."""
    db = connect()
    have = {r[0]: r[1] for r in db.execute("SELECT sha1, path FROM docs")}
    count = "SELECT (SELECT COUNT(*) FROM docs), (SELECT COUNT(*) FROM chunks)"
    before = db.execute(count).fetchone()
    lib = os.path.join(os.path.abspath(LIBRARY), "")
    dest_dir = os.path.join(LIBRARY, "added")
    targets = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            say("  folder, indexed where it is: %s" % p)
            targets.append(p)
            continue
        if not os.path.isfile(p):
            say("  not found: %s" % p)
            continue
        if not p.lower().endswith(DOC_EXT):
            say("  not added (%s files are what the library reads): %s"
                % (" ".join(DOC_EXT), os.path.basename(p)))
            continue
        if p.startswith(lib):
            targets.append(p)
            continue
        h = sha1_of(p)
        if h in have:
            say("  already in the library: %s  (as %s)" % (os.path.basename(p), have[h]))
            continue
        os.makedirs(dest_dir, exist_ok=True)
        dst = os.path.join(dest_dir, os.path.basename(p))
        if os.path.exists(dst) and sha1_of(dst) != h:      # same name, different file
            stem, ext = os.path.splitext(os.path.basename(p))
            dst = os.path.join(dest_dir, "%s-%s%s" % (stem, h[:8], ext))
        if not os.path.exists(dst):
            shutil.copy2(p, dst)
        targets.append(dst)
    db.close()
    if not targets:
        return 0, 0
    cmd_ingest(argparse.Namespace(paths=targets, prune=False))
    db = connect()
    after = db.execute(count).fetchone()
    db.close()
    return after[0] - before[0], after[1] - before[1]


def cmd_add(a):
    add_paths(a.paths)


def ingest_one(db, path, h, side, n, total):
    name = os.path.basename(path)
    if path.lower().endswith(".pdf"):
        pages, backend, md = extract_pdf(path)
    else:
        pages, backend, md = extract_text_file(path)
    meta = guess_meta(path, pages, md)
    if side:
        for k in ("title", "authors", "year", "org", "number"):
            # a library.csv with an empty authors column means "cite the organisation", so it
            # replaces whatever the PDF's own Author field says (often a typist's login)
            if side.get(k) or (k == "authors" and k in side):
                meta[k] = side[k]
        meta["meta_src"] = "library.csv"
    notext = [str(p) for p, _, t in pages if len(clean(t)) < MIN_PAGE_CHARS] if backend != "text" else []
    items = []
    for p, label, t in pages:
        for i, c in enumerate(chunk_page(t)):
            items.append((p, label, i, c))
    if backend == "pymupdf":
        labels = {p: label for p, label, _ in pages}
        tables = extract_pdf_tables(path, {p: t for p, _, t in pages})
        for p in sorted(tables):
            for k, c in enumerate(tables[p]):
                items.append((p, labels.get(p, ""), TABLE_IDX + k, c))
        backend = "pymupdf+tables"
    if not items:
        say("  [%d/%d] NO TEXT (scanned? run `vor ocr`): %s" % (n, total, name))
        db.execute("INSERT INTO docs(sha1,path,title,authors,year,org,number,pages,notext,backend,added,meta_src)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (h, path, meta["title"], meta.get("authors", ""), meta.get("year", ""), meta.get("org", ""),
                    meta.get("number", ""), len(pages), ",".join(notext), backend,
                    datetime.now().isoformat(timespec="seconds"), meta["meta_src"]))
        db.commit()
        return False
    vecs = []
    pre = doc_prefix(EMBED_MODEL)
    for b in range(0, len(items), EMBED_BATCH):
        batch = items[b:b + EMBED_BATCH]
        vecs += embed([pre + "%s (p.%s)\n%s" % (meta["title"], lab or p, c) for p, lab, _, c in batch], EMBED_MODEL)
    dim = len(vecs[0])
    old = meta_get(db, "embed_dim")
    if old and int(old) != dim:
        raise RuntimeError("embedding size %d differs from the library's %s" % (dim, old))
    cur = db.cursor()
    cur.execute("BEGIN")
    cur.execute("INSERT INTO docs(sha1,path,title,authors,year,org,number,pages,notext,backend,added,meta_src)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (h, path, meta["title"], meta.get("authors", ""), meta.get("year", ""), meta.get("org", ""),
                 meta.get("number", ""), len(pages), ",".join(notext), backend,
                 datetime.now().isoformat(timespec="seconds"), meta["meta_src"]))
    did = cur.lastrowid
    for (p, lab, i, c), v in zip(items, vecs):
        cur.execute("INSERT INTO chunks(doc_id,page,label,idx,txt,vec) VALUES(?,?,?,?,?,?)",
                    (did, p, lab, i, c, array("f", v).tobytes()))
        if db.fts:
            cur.execute("INSERT INTO chunks_fts(rowid, txt, title) VALUES(?,?,?)", (cur.lastrowid, c, meta["title"]))
    meta_set(db, "embed_model", EMBED_MODEL)
    meta_set(db, "embed_dim", dim)
    db.commit()
    say("  [%d/%d] %s  (%d pages, %d passages%s, %s)" % (
        n, total, name, len(pages), len(items),
        ", %d page(s) without text" % len(notext) if notext else "", backend))
    return True


# --------------------------------------------------------------------------- retrieval

class Index:
    """Vectors held in memory once per process (chat keeps it warm)."""

    def __init__(self, db):
        self.db = db
        rows = db.execute("SELECT c.id, c.doc_id, c.vec FROM chunks c").fetchall()
        if not rows:
            die("the library is empty. Put PDFs in %s and run: vor ingest" % LIBRARY)
        self.ids = [r[0] for r in rows]
        self.doc_of = [r[1] for r in rows]
        self._sel_cache = {}
        if np is not None:
            self.M = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        else:
            self.M = [array("f", r[2]) for r in rows]

    def rows_for(self, keep):
        """Row positions belonging to the documents in `keep` (cached: chat reuses the Index)."""
        key = frozenset(keep)
        hit = self._sel_cache.get(key)
        if hit is None:
            sel = [i for i, d in enumerate(self.doc_of) if d in key]
            hit = np.asarray(sel, dtype=np.int64) if np is not None else sel
            self._sel_cache[key] = hit
        return hit

    def vector(self, q, n, keep=None):
        qv = embed([query_text(EMBED_MODEL, q)], EMBED_MODEL)[0]
        # With --doc the filter is applied BEFORE ranking, not after: a pool taken from the
        # whole library can easily hold no chunk of the document that was asked for.
        sel = self.rows_for(keep) if keep else None
        if np is not None:
            if sel is None:
                s = self.M @ np.asarray(qv, dtype=np.float32)
                top = np.argsort(-s)[:n]
                return [(self.ids[i], float(s[i])) for i in top]
            if len(sel) == 0:
                return []
            s = self.M[sel] @ np.asarray(qv, dtype=np.float32)
            return [(self.ids[sel[i]], float(s[i])) for i in np.argsort(-s)[:n]]
        rows = range(len(self.M)) if sel is None else sel
        sc = sorted(((sum(a * b for a, b in zip(self.M[i], qv)), i) for i in rows), reverse=True)[:n]
        return [(self.ids[i], s) for s, i in sc]

    def lexical(self, q, n, keep=None):
        if not self.db.fts:
            return []
        toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|\d+(?:\.\d+)?", q) if t.lower() not in STOP]
        if not toks:
            return []
        expr = " OR ".join('"%s"' % t.replace('"', "") for t in dict.fromkeys(toks))
        sql = "SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ?"
        args = [expr]
        if keep:
            ids = sorted(keep)
            sql += " AND rowid IN (SELECT id FROM chunks WHERE doc_id IN (%s))" % ",".join("?" * len(ids))
            args += ids
        sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
        args.append(n)
        try:
            return [(r[0], -r[1]) for r in self.db.execute(sql, args)]
        except sqlite3.OperationalError:
            return []

    def search(self, q, k=8, per_doc=3, pool=60, keep=None):
        """Hybrid: meaning (vectors) + exact words (BM25, catches 'Froehlich', 'MacDonald'), fused by rank.

        keep: document ids to read, or None for the whole library (see find_docs).
        per_doc: passages allowed from any one document; None lifts the cap, which is what
        a question scoped to a single long guideline needs.
        """
        if per_doc is None:
            per_doc = k
        fused = {}
        for lst in (self.vector(q, pool, keep), self.lexical(q, pool, keep)):
            for rank, (cid, _) in enumerate(lst):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
        order = sorted(fused, key=lambda c: -fused[c])
        hits, seen_doc, seen_txt, late = [], {}, set(), []
        for cid in order:
            row = self.db.execute(
                "SELECT c.id, c.doc_id, c.page, c.label, c.txt, d.title, d.path, d.authors, d.year, d.org, d.number "
                "FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE c.id=?", (cid,)).fetchone()
            if not row:
                continue
            # 1.4.4: a passage whose text repeats one already taken (a report's cover printed on p.1 and p.2)
            # is skipped, and a contents page (dot leaders) waits until nothing else is left: on the Pierce
            # (2010) question they held 4 of the 7 places ahead of the equation page.
            key = text_key(row[1], row[4])
            if key and key in seen_txt:
                continue
            if seen_doc.get(row[1], 0) >= per_doc:
                continue
            if is_contents(row[4]):
                late.append((row, fused[cid]))
                continue
            seen_txt.add(key)
            seen_doc[row[1]] = seen_doc.get(row[1], 0) + 1
            hits.append(Hit(row, fused[cid]))
            if len(hits) >= k:
                break
        for row, sc in late:
            if len(hits) >= k:
                break
            key = text_key(row[1], row[4])
            if (key and key in seen_txt) or seen_doc.get(row[1], 0) >= per_doc:
                continue
            seen_txt.add(key)
            seen_doc[row[1]] = seen_doc.get(row[1], 0) + 1
            hits.append(Hit(row, sc))
        return hits


STOP = set("""a an and are as at be by can could did do does for from has have how if in into is it its
of on or should than that the their there these this those to was were what when where which who why
will with would about between during under over per using used use based any all also more most
""".split())


class Hit:
    def __init__(self, row, score):
        (self.cid, self.doc_id, self.page, self.label, self.txt, self.title, self.path,
         self.authors, self.year, self.org, self.number) = row
        self.score = score

    @property
    def pg(self):
        if self.path.lower().endswith(".pdf"):
            if self.label and self.label != str(self.page):
                return "p.%s (PDF p.%d)" % (self.label, self.page)
            return "p.%d" % self.page
        return self.label or "sec %d" % self.page

    def short(self):
        who = (self.authors.split(",")[0].split(";")[0].strip() if self.authors else self.org) or ""
        t = self.title if len(self.title) <= 70 else self.title[:67] + "..."
        return "%s%s%s" % (who + " " if who else "", "(%s) " % self.year if self.year else "", t)

    def model_label(self, named=None):
        """1.4.9: the label the MODEL reads: short() plus a report number the title leaves out ('(WSP 2339)'),
        and, when the question named this publication, the question's own words for it. The model had
        refused passages of 'Arcement (1989) Guide for Selecting...' for a question about 'WSP 2339'."""
        lab = self.short()
        num = (self.number or "").strip()
        if num and squash(num) not in squash(lab):
            lab += " (%s)" % num
        lab += ", " + self.pg
        said = (named or {}).get(self.doc_id)
        if said:
            lab += " (from %s, the publication the question names)" % " / ".join("'%s'" % w.strip() for w in said)
        return lab

    def link(self):
        u = "file://" + urllib.request.pathname2url(self.path)
        return u + ("#page=%d" % self.page if self.path.lower().endswith(".pdf") else "")


def doc_scope(db, a):
    """Turn --doc / --per-doc into (document ids or None, per_doc or None, a line to print).

    Without --doc the per-document cap stays at 3, which keeps one chatty source from
    filling the window. With --doc the cap is lifted unless it was asked for: scoping to a
    145-page guideline and then reading 3 of its passages is the thing that sends you away
    empty-handed.
    """
    keep, labels = (find_docs(db, a.doc) if getattr(a, "doc", None) else ([], []))
    per_doc = getattr(a, "per_doc", None)
    if per_doc is None:
        per_doc = None if keep else 3
    return (keep or None), per_doc, scope_note(labels)


def cmd_search(a):
    db = connect()
    check_embed_model(db)
    idx = Index(db)
    q = " ".join(a.question)
    keep, per_doc, note = doc_scope(db, a)
    if note:
        say(note)
    hits = idx.search(q, k=a.k, per_doc=per_doc, keep=keep)
    if not hits:
        say("\nNo passage matched%s. %s" % (
            " in that document" if keep else "",
            "Try other words, or drop --doc." if keep else "Try other words."))
        return
    for n, h in enumerate(hits, 1):
        say("\n[%d] %s  %s   (score %.4f)\n    %s" % (n, h.short(), h.pg, h.score, h.path))
        say("    " + textwrap_short(h.txt, 420))


def textwrap_short(t, n):
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n - 3] + "..."


# --------------------------------------------------------------------------- quote checking

def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.translate({0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"', 0x2013: "-", 0x2014: "-",
                     0x2212: "-", 0x00d7: "x"})
    s = re.sub(r"(\w)- (\w)", r"\1\2", s)
    s = re.sub(r"[^\w%.,;:()/=+\-'\" ]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:")


_LEADERS = re.compile(r"(?: ?(?:_|\.(?!\d)) ?){3,}")


def _no_leaders(s):
    """1.4.9: a table row's dot leaders ('Concrete ....... _ 0.012-0.018') as one space, in the quote and the page
    alike, so a row quoted without them ('Concrete 0.012-0.018') still checks. Numbers keep their single points."""
    return re.sub(r"\s+", " ", _LEADERS.sub(" ", s)).strip(" .,;:")


def quote_check(quote, source_txt):
    """'exact', 'close' (>= 90% of the quote's characters found in order), or 'not found'."""
    q, t = _no_leaders(norm(quote)), _no_leaders(norm(source_txt))
    if len(q) < 12:
        return "too short"
    if q in t:
        return "exact"
    sm = difflib.SequenceMatcher(None, q, t, autojunk=False)
    m = sum(b.size for b in sm.get_matching_blocks() if b.size >= 4)
    # must also be one contiguous region of the page, not letters scattered across it
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 4]
    span = (blocks[-1].b + blocks[-1].size - blocks[0].b) if blocks else 0
    if m >= 0.9 * len(q) and span <= 1.3 * len(q):
        # a near match must not hide a changed number ("2 and 5 times" -> "3 and 7 times")
        region = t[blocks[0].b: blocks[-1].b + blocks[-1].size]
        if nums(q) != nums(region):
            return "numbers differ"
        return "close"
    return "not found"


NUM = re.compile(r"(?<![\w.])\.?\d+(?:[.,]\d+)*")


def nums(s):
    """The numbers in s, '.018' (a table's way of writing it) read as 0.018. 1.4.9: before, a number with no
    leading zero was not seen at all, so 'Sand .3 .018' passed as a close quote of a row reading '.3 .017'."""
    return ["0" + n if n.startswith(".") else n for n in NUM.findall(s)]


def numbers_outside(claim, quote, source_txt):
    """Numbers in the paraphrase that appear in neither the quote nor the page — likely invented."""
    allowed = set(nums(norm(quote))) | set(nums(norm(source_txt)))
    bad = [n for n in nums(norm(claim)) if n not in allowed and n.replace(",", "") not in allowed]
    return bad


# --------------------------------------------------------------------------- research pipeline

SYSTEM = """You are a research assistant for dam-safety engineers (dam safety, dam and spillway design,
breach parameters, inundation mapping, hydrology and flood hazards). You work ONLY from the numbered
source passages you are given, which come from the user's own library of publications.
Rules:
- Every factual statement must come from a given passage. Never use outside knowledge to fill a gap.
- Quotes must be copied character-for-character from the passage. Do not fix or reword them.
- Keep numbers, units, equations, coefficients and their applicability limits exactly as written.
- Say which kind of source a statement comes from when it matters: federal guidance/standard
  (FEMA, USBR, USACE, NRCS, FERC, state rules) versus a research paper or a case study.
- If passages disagree, report both sides; do not pick one silently.
- If the passages do not answer something, say so plainly. "The library does not cover this" is a
  good answer. Never guess.
- One publication goes by several names: its report number (WSP 2339, FEMA 333, TD-39), its authors
  and its agency. A passage label that says "the publication the question names" is from the document
  the question asks about, even when the label shows other authors, an agency or a long title."""

PLAN_SCHEMA = {"type": "object", "properties": {
    "subquestions": {"type": "array", "items": {"type": "string"}},
    "search_terms": {"type": "array", "items": {"type": "string"}}},
    "required": ["subquestions", "search_terms"]}

EXTRACT_SCHEMA = {"type": "object", "properties": {
    "findings": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"},
        "quote": {"type": "string"},
        "claim": {"type": "string"},
        "kind": {"type": "string", "enum": ["value", "equation", "method", "recommendation",
                                            "requirement", "finding", "definition", "limitation", "case"]}},
        "required": ["source", "quote", "claim", "kind"]}},
    "not_covered": {"type": "array", "items": {"type": "string"}}},
    "required": ["findings", "not_covered"]}


def plan(question, depth):
    if depth <= 1:
        return [question], []
    msg = ("Break this research question into at most %d focused sub-questions that together answer it, "
           "the way an engineer would search a library of dam-safety publications. Also give up to 8 exact "
           "search terms (method names, equation authors, agency document numbers, technical terms).\n\n"
           "Question: %s" % (depth - 1, question))
    out = parse_json(chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                          schema=PLAN_SCHEMA, num_predict=800)) or {}
    subs = [s.strip() for s in out.get("subquestions", []) if isinstance(s, str) and s.strip()][:depth - 1]
    terms = [s.strip() for s in out.get("search_terms", []) if isinstance(s, str) and s.strip()][:8]
    return [question] + [s for s in subs if s.lower() != question.lower()], terms


class Evidence:
    def __init__(self):
        self.sources = []        # Hit, index = S number - 1
        self.by_cid = {}
        self.findings = []       # dict(F, source, quote, claim, kind, check, numbers, sub)
        self.rejected = []
        self.not_covered = []
        self.answer_note = ""    # set when the model's own write-up could not be used
        self.answer_from = "model"   # "model" | "model, second attempt" | "findings"
        self.term_flags = []     # opposite_terms(): a sentence whose quote says the opposite
        self.cut = []            # 1.4.2: passages cut to PASSAGE_MAX (or the window) before the model read them
        self.cut_cids = set()
        self.calls = []          # 1.4.2: one dict per extract() model call (passages, tokens, seconds, ...)
        self.not_asked = 0       # 1.4.2: extract() calls where no passage fitted, so the model was not asked
        self.named = {}          # 1.4.9: document id -> the question's words that named it (model_label)

    def add_source(self, h):
        if h.cid not in self.by_cid:
            self.sources.append(h)
            self.by_cid[h.cid] = len(self.sources)
        return self.by_cid[h.cid]


def budget_chars(reserve_tokens):
    return max(4000, int((NUM_CTX - reserve_tokens) * CHARS_PER_TOKEN))


def est_tokens(text):
    """Tokens a passage costs, on the safe side. 1.4.2: prose runs about CHARS_PER_TOKEN characters a token,
    but Qwen reads every digit as its own token and a table's '|' and '---' cost one each, so a table
    passage counted at 3.2 characters a token could fill twice the room it was given."""
    text = text or ""
    d = sum(c.isdigit() for c in text)
    p = text.count("|")
    return int((len(text) - d - p) / CHARS_PER_TOKEN + d + p) + 1


EXTRACT_ASK = ("List every finding in these passages that helps answer the sub-question. For each: the source "
               "label (like S3), an exact quote copied from that passage (one or two sentences, under 300 "
               "characters), a one-sentence plain claim that says no more than the quote, and its kind. "
               "Skip passages that are not relevant. A value in a table is quoted as its whole row: the row's "
               "name and its numbers, as they appear in the passage. In not_covered, list parts of the "
               "sub-question that none of the passages answer.")


def _note_call(ev, blocks, msg, reply, out, retry=False):
    """1.4.2: one line and one record per model call (passages, our token count, Ollama's prompt_eval_count,
    seconds, done_reason, findings), so an empty answer can be traced."""
    call = {"passages": len(blocks), "est_tokens": est_tokens(SYSTEM + msg),
            "prompt_tokens": LAST_REPLY.get("prompt_tokens", 0), "seconds": round(LAST_REPLY.get("seconds", 0.0), 1),
            "done": LAST_REPLY.get("done_reason", ""), "reply_chars": len(reply or ""),
            "findings": len((out or {}).get("findings") or []) if isinstance(out, dict) else None}
    if retry:
        call["retry"] = True
    ev.calls.append(call)
    say("  (model read %d passage(s)%s: about %d tokens by our count, %s by Ollama's, %.1f s, done: %s; "
        "%s finding(s) offered)" % (call["passages"], " again" if retry else "", call["est_tokens"],
                                     call["prompt_tokens"] or "?", call["seconds"], call["done"] or "?",
                                     "?" if call["findings"] is None else call["findings"]))


def extract(ev, sub, hits):
    """Ask the model for verbatim evidence from these passages, then check every quote ourselves.

    1.4.2: the passages are fitted to the window in tokens, not characters, a passage longer than
    PASSAGE_MAX (or than the room left) is cut rather than ending the reading, and only the passages
    actually handed to the model are counted as read."""
    room = NUM_CTX - 2500 - est_tokens(SYSTEM + EXTRACT_ASK + sub) - 200
    blocks, used = [], 0
    for h in hits:
        txt = h.txt or ""
        head = "[S%d] %s\n" % (len(ev.sources) + 1, h.model_label(ev.named))     # label fixed below
        left = room - used - est_tokens(head)
        if left < 150:
            continue                       # no room for this one; a shorter one further down may fit
        keep = len(txt)
        if keep > PASSAGE_MAX:
            keep = PASSAGE_MAX
        while keep > 200 and est_tokens(txt[:keep]) > left:
            keep = int(keep * 0.8)
        if est_tokens(txt[:keep]) > left:
            continue
        s = ev.add_source(h)
        if keep < len(txt):
            if h.cid not in ev.cut_cids:
                ev.cut_cids.add(h.cid)
                ev.cut.append("%s, %s: %d of %d characters" % (h.short(), h.pg, keep, len(txt)))
            txt = txt[:keep] + "\n[passage cut here: %d of %d characters shown]" % (keep, len(txt))
        b = "[S%d] %s\n%s" % (s, h.model_label(ev.named), txt)
        blocks.append((s, b))
        used += est_tokens(b)
    if not blocks:
        say("  (no passage fitted in the model's window, so the model was not asked)")
        ev.not_asked += 1
        return
    msg = ("Sub-question: %s\n\nSource passages:\n\n%s\n\n%s"
           % (sub, "\n\n".join(b for _, b in blocks), EXTRACT_ASK))
    reply = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                 schema=EXTRACT_SCHEMA, num_predict=2500)
    out = parse_json(reply)
    _note_call(ev, blocks, msg, reply, out)
    if isinstance(out, dict) and not (out.get("findings") or []):
        # 1.4.3: the model said every passage was irrelevant. On 2026-11-22 it answered the D15F question
        # with exactly '{"findings": [], "not_covered": []}' although FilterManual p.114 (the answer) was
        # among the 8 passages; the same question with the same passages had passed earlier. Once more,
        # with the passages in reverse order (the first ones read were other manuals) and a nudge to read
        # each one. Nothing new is trusted: every quote still goes through quote_check against its page.
        say("  (the model offered no finding from %d passage(s); asking once more with them in reverse order)"
            % len(blocks))
        msg2 = ("Sub-question: %s\n\nSource passages:\n\n%s\n\n%s\n\nRead every passage to the end before "
                "deciding. If any sentence or table row states a value, criterion, definition, equation or "
                "rule that bears on the sub-question, quote it exactly. Return no findings only if no passage "
                "says anything about it." % (sub, "\n\n".join(b for _, b in reversed(blocks)), EXTRACT_ASK))
        reply2 = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg2}],
                      schema=EXTRACT_SCHEMA, num_predict=2500, temperature=0.5)
        out2 = parse_json(reply2)
        _note_call(ev, blocks, msg2, reply2, out2, retry=True)
        if isinstance(out2, dict) and (out2.get("findings") or []):
            out, reply = out2, reply2
    if out is None and not strip_think(reply):
        # 1.3.0: nothing came back at all. Once more with twice the room, because the usual
        # cause is the allowance being spent before the first character of the answer.
        why = empty_reply_reason()
        say("  (the model returned nothing for these passages: %s. Asking once more.)" % why)
        reply = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                     schema=EXTRACT_SCHEMA, num_predict=5000)
        out = parse_json(reply)
        if out is None and not strip_think(reply):
            ev.rejected.append({"sub": sub, "why": "model returned nothing for these passages, twice (%s; "
                                                    "then %s)" % (why, empty_reply_reason())})
            return
    if out is None:
        ev.rejected.append({"sub": sub, "why": "model reply was not valid JSON"})
        return
    allowed = {s for s, _ in blocks}
    for f in out.get("findings") or []:
        if not isinstance(f, dict):
            continue
        src = str(f.get("source", ""))
        m = re.search(r"\bS\s*(\d+)", src, re.I) or re.search(r"(\d+)", src)   # 1.4.9: 'S1' before the
        s = int(m.group(1)) if m else -1                                     # '2339' of 'WSP 2339 (S1)'
        quote, claim = str(f.get("quote", "")).strip().strip('"'), str(f.get("claim", "")).strip()
        if s not in allowed:
            ev.rejected.append({"sub": sub, "why": "cites S%s, which was not in its passages" % s,
                                "claim": claim, "quote": quote})
            continue
        h = ev.sources[s - 1]
        chk = quote_check(quote, h.txt)
        if chk != "exact" and chk != "close":
            ev.rejected.append({"sub": sub, "why": "quote %s on %s" % (chk, h.pg), "claim": claim,
                                "quote": quote, "S": s})
            continue
        if any(quote == g["quote"] and s == g["source"] for g in ev.findings):
            continue
        ev.findings.append({"F": len(ev.findings) + 1, "source": s, "quote": quote, "claim": claim,
                            "kind": f.get("kind", ""), "check": chk, "sub": sub,
                            "numbers": numbers_outside(claim, quote, h.txt)})
    for g in out.get("not_covered") or []:
        if isinstance(g, str) and g.strip() and g.strip().lower() not in {x.lower() for _, x in ev.not_covered}:
            ev.not_covered.append((sub, g.strip()))


def synthesize(question, ev, mode, out):
    lines = []
    for f in ev.findings:
        h = ev.sources[f["source"] - 1]
        lines.append('[F%d] (%s; %s) %s\n     quote: "%s"' % (
            f["F"], h.model_label(ev.named), f["kind"], f["claim"], f["quote"]))
    gaps = "\n".join("- %s" % g for _, g in ev.not_covered) or "- (none reported)"
    if mode == "ask":
        shape = ("Write a direct answer of one to four short paragraphs. Put the finding labels you rely on "
                 "after each sentence, like [F2] or [F2][F5]. End with one line starting 'Not covered:' if "
                 "part of the question is unanswered.")
    else:
        shape = ("Write a research brief in Markdown with these sections:\n"
                 "## Answer  (the short answer, 1-2 paragraphs)\n"
                 "## What the sources say  (grouped by theme; methods, equations and values exactly as quoted)\n"
                 "## Where sources differ  (or 'No disagreement found in these passages.')\n"
                 "## Gaps and uncertainty  (what the library does not answer; what an engineer should check)\n"
                 "Put the finding labels after every sentence that states a fact, like [F2] or [F2][F5].")
    msg = ("Question: %s\n\nVerified findings (each quote has been checked against its page):\n\n%s\n\n"
           "Parts the sources did not cover:\n%s\n\n%s\nUse ONLY these findings. Do not add facts, numbers or "
           "references that are not in them. If they do not answer the question, say so."
           % (question, "\n".join(lines) or "(no findings)", gaps, shape))
    reserve = 3000 if mode == "ask" else 5000
    if len(msg) > budget_chars(reserve):
        msg = msg[:budget_chars(reserve)] + "\n[findings list cut to fit the context window]"
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}]
    body = strip_think(chat(msgs, think=THINK, stream_to=out, num_predict=reserve))
    if body:
        return body
    # 1.3.0. On the first real run (2026-11-12, qwen3.6:27b) four of sixteen questions ended
    # here with one to four checked findings and an empty answer: the right page found, the
    # quote verified, and nothing written. The reply being empty is not an error to Ollama, so
    # the empty string went into the report as the answer.
    first = empty_reply_reason()
    say("The model wrote no answer: %s. Asking once more, with reasoning off and more room." % first)
    room = int(NUM_CTX - len(msg) / CHARS_PER_TOKEN - 600)
    again = [msgs[0], {"role": "user", "content": msg + "\n\nWrite the answer itself now, beginning "
                       "with its first sentence. Do not reason or plan first."}]
    body = strip_think(chat(again, think=False, stream_to=out,
                            num_predict=max(reserve, min(reserve * 2, room)), temperature=0.5))
    if body:
        ev.answer_from = "model, second attempt"
        ev.answer_note = ("the model wrote no answer at first (%s); this is its second attempt" % first)
        return body
    second = empty_reply_reason()
    ev.answer_from = "findings"
    ev.answer_note = ("the model wrote no answer twice (%s; then %s), so the answer above is the checked "
                      "findings themselves, not a written summary" % (first, second))
    body = findings_answer(ev)
    out.write(body + "\n")
    return body


def no_findings_answer(ev, keep):
    """What to say when no quote survived. 1.3.0: two different things used to get one sentence,
    "The library returned no passage that answers this question". On 2026-11-12 one model gave
    that for seven of sixteen questions whose right page was in the passages it had just been
    handed: the library was not empty, the model drew nothing from it. Saying the library has
    nothing sends the reader off to find a document they already own."""
    if not ev.sources:
        return ("That document returned no passage that answers this question, so there is nothing to "
                "cite. Try `vor search --doc ...` with different words, or drop --doc and search "
                "the whole library." if keep else
                "The library returned no passage that answers this question, so there is nothing to cite. "
                "Try `vor search` with different words, or add publications that cover it.")
    seen, pages = set(), []
    for h in ev.sources:
        key = (h.short(), h.pg)
        if key not in seen:
            seen.add(key)
            pages.append("- %s, %s" % key)
    quoted = [r for r in ev.rejected if r.get("quote")]
    other = [r for r in ev.rejected if not r.get("quote")]
    if quoted:
        drew = "the model offered %d quote(s), and none of them passed the check against its page" % len(quoted)
    elif other:
        drew = "the model's reply could not be used (%s)" % other[0].get("why", "no reason recorded")
    elif ev.not_asked and not ev.calls:
        drew = "none of them fitted in the model's window, so the model was not asked"
    else:
        drew = "the model drew no quote from them"
        if any(c.get("retry") for c in ev.calls):
            drew += ", twice (the second time with the passages in reverse order)"
    return ("There is nothing to cite: %d passage(s) were read and %s. That is not the same as the "
            "library having nothing. These are the passages the search ranked closest to the question, "
            "unchecked:\n\n%s\n\nOpen those pages, or ask again in different words%s."
            % (len(ev.sources), drew, "\n".join(pages[:8]),
               "" if keep else ", or name the publication with --doc"))


def findings_answer(ev):
    """An answer made only of what was verified: each finding's claim, its quote and its label.
    Used when the model writes nothing. Every line carries its [F] label, so it renders with
    page citations like any other answer, and nothing in it is the model's unchecked prose."""
    L = ["The model did not write an answer, so these are the checked findings as they stand. "
         "Each quote was found on the page cited."]
    L.append("")
    for f in ev.findings:
        claim = f["claim"].rstrip()
        if claim and claim[-1] not in ".!?":
            claim += "."
        L.append('- %s "%s" [F%d]' % (claim, f["quote"], f["F"]))
    if ev.not_covered:
        L.append("")
        L.append("Not covered: " + "; ".join(g for _, g in ev.not_covered))
    return "\n".join(L)


def render_citations(text, ev):
    """[F3] -> [n, p.12]; n numbers the references list in order of first use."""
    order, unknown = [], []

    def ref_no(doc_id):
        if doc_id not in order:
            order.append(doc_id)
        return order.index(doc_id) + 1

    fmap = {f["F"]: f for f in ev.findings}

    def sub(m):
        out = []
        for n in re.findall(r"\d+", m.group(0)):
            f = fmap.get(int(n))
            if not f:
                unknown.append(n)
                out.append("[F%s: NO SUCH FINDING]" % n)
                continue
            h = ev.sources[f["source"] - 1]
            c = "[%d, %s]" % (ref_no(h.doc_id), h.pg)
            if c not in out:
                out.append(c)
        return "".join(out)
    rendered = re.sub(r"\[F\d+(?:\]\s*\[F\d+)*\]|\[F\d+(?:\s*[,;]\s*F?\d+)+\]", sub, text)
    used_f = set(int(n) for n in re.findall(r"F(\d+)", text))
    return rendered, order, unknown, used_f


def uncited_sentences(text):
    bad = 0
    for para in text.split("\n"):
        p = para.strip()
        if not p or p.startswith("#") or p.lower().startswith(("not covered", "no disagreement")):
            continue
        for s in re.split(r"(?<=[.!?])\s+", p):
            if len(s) > 60 and "[F" not in s and not re.search(r"not (covered|answer)|does not|no (finding|source)", s, re.I):
                bad += 1
    return bad


def run_pipeline(question, mode, depth, k, out=sys.stdout, idx=None, save=True,
                 keep=None, per_doc=None, scope=""):
    db = connect()
    try:
        check_embed_model(db)
        return _run_pipeline(db, question, mode, depth, k, out, idx or Index(db), save, keep, per_doc, scope)
    finally:
        db.close()          # one connection per question was left open for the life of a chat


def _run_pipeline(db, question, mode, depth, k, out, idx, save, keep, per_doc, scope):
    if scope:
        say(scope)
    t0 = time.time()
    ev = Evidence()
    if mode == "research":
        say("Planning sub-questions...")
    subs, terms = plan(question, depth)
    if mode == "research":
        for s in subs[1:]:
            say("  - " + s)
        if terms:
            say("  search terms: " + "; ".join(terms))
    named, named_spans = [], []
    if not keep:
        named, named_labels, named_spans = named_docs(db, question, spans=True)
        if named:
            say("The question names: " + "; ".join(named_labels) + " (their passages are read first)")
    # 1.4.9: the passages of a publication the question names plainly say so (Hit.model_label); with --doc too,
    # for the documents kept (the 2026-11-23 failures read "Pierce, Thornton and Abt" on a "FEMA (2010)" label)
    ev.named = {d: w for d, w in named_docs(db, question, by_doc=True).items() if not keep or d in keep}
    log = []
    for i, s in enumerate(subs, 1):
        q = s + ((" " + " ".join(terms)) if (i == 1 and terms) else "")
        hits = idx.search(q, k=k, per_doc=per_doc if per_doc is not None else 3, keep=keep)
        if named:
            # 1.4.4: inside the named documents, search without the naming words, and read up to 4 passages
            # (the words that name a document are found again in each sub-question, which plan() rewords)
            sq = strip_naming(q, named_spans + named_docs(db, q, spans=True)[2])
            each = max(1, min(4, k) // len(named))            # two named papers: two places each
            first = []
            for d in named:
                first += idx.search(sq, k=each, per_doc=each, keep={d})
            hits = merge_hits(first[:min(4, k)], hits, k)
        log.append((s, hits))
        say("[%d/%d] reading %d passages for: %s" % (i, len(subs), len(hits), textwrap_short(s, 90)))
        extract(ev, s, hits)
    nf, nr = len(ev.findings), len(ev.rejected)
    say("Evidence: %d quote(s) checked against their pages, %d rejected (quote not on the page or wrong source)."
        % (nf, nr))
    say("-" * 72)
    if not ev.findings:
        body = no_findings_answer(ev, keep)
        out.write(body + "\n")
    else:
        body = synthesize(question, ev, mode, out)
    rendered, order, unknown, used_f = render_citations(body, ev)
    unc = uncited_sentences(body) if (ev.findings and ev.answer_from != "findings") else 0
    ev.term_flags = opposite_terms(body, ev) if ev.findings else []
    report = build_report(question, mode, subs, terms, log, ev, rendered, order, unknown, used_f, unc,
                          time.time() - t0, scope=scope)
    path = None
    if save:
        os.makedirs(REPORTS, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", question.lower())[:60].strip("-") or "question"
        path = os.path.join(REPORTS, "%s_%s_%s.md" % (datetime.now().strftime("%Y-%m-%d_%H%M"), mode, slug))
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
    say("-" * 72)
    say("With references:\n")
    say(rendered)
    say("\nReferences:")
    for n, did in enumerate(order, 1):
        h = next(s for s in ev.sources if s.doc_id == did)
        say("  [%d] %s" % (n, cite_line(h)))
    if unknown or unc or ev.answer_note or ev.term_flags or ev.cut or any(f["numbers"] for f in ev.findings if f["F"] in used_f):
        say("\nChecks: %s" % "; ".join(checks_summary(ev, unknown, used_f, unc)))
    if path:
        say("\nReport (evidence table, quotes, rejected items): %s" % path)
    say(BANNER)
    return path, rendered, ev


def cite_line(h):
    parts = []
    if h.authors:
        parts.append(h.authors)
    elif h.org:
        parts.append(h.org)
    if h.year:
        parts.append("(%s)" % h.year)
    parts.append(h.title + ".")
    if h.number:
        parts.append(h.number + ".")
    if h.org and h.authors:
        parts.append(h.org + ".")
    return " ".join(parts) + "  " + os.path.basename(h.path)


def checks_summary(ev, unknown, used_f, unc):
    c = []
    if unknown:
        c.append("%d citation(s) to findings that do not exist (marked NO SUCH FINDING)" % len(unknown))
    nums = [f for f in ev.findings if f["F"] in used_f and f["numbers"]]
    if nums:
        c.append("%d cited finding(s) state numbers that are not on the page: %s" % (
            len(nums), ", ".join("F%d (%s)" % (f["F"], ", ".join(f["numbers"])) for f in nums)))
    close = [f for f in ev.findings if f["F"] in used_f and f["check"] == "close"]
    if close:
        c.append("%d quote(s) match the page only closely (PDF text extraction or a small slip): %s"
                 % (len(close), ", ".join("F%d" % f["F"] for f in close)))
    if unc:
        c.append("%d long sentence(s) carry no citation - treat them as the model's own words" % unc)
    for t in getattr(ev, "term_flags", []):
        c.append("CHECK " + t)
    cut = getattr(ev, "cut", [])
    if cut:
        c.append("%d passage(s) were too long and only their start was read (%s)"
                 % (len(cut), "; ".join(cut[:3]) + ("; ..." if len(cut) > 3 else "")))
    if not c:
        c.append("all cited quotes found on their pages; no uncited sentences")
    if ev.answer_note:
        c.insert(0, ev.answer_note)
    return c


def md_cell(s):
    return " ".join(str(s).split()).replace("|", "\\|")


def build_report(question, mode, subs, terms, log, ev, rendered, order, unknown, used_f, unc, secs,
                 scope=""):
    L = ["# %s" % question, "",
         "> **%s**" % BANNER, "",
         "%s · model `%s` · embeddings `%s` · %s · %.0f s" % (
             "Deep research" if mode == "research" else "Quick answer", CHAT_MODEL, EMBED_MODEL,
             datetime.now().strftime("%Y-%m-%d %H:%M"), secs), ""]
    if scope:
        L += ["> " + scope.replace("\n", "  \n> "), ""]           # --doc: say what was read
    L += [rendered.strip(), "", "## References", ""]
    for n, did in enumerate(order, 1):
        hs = [s for s in ev.sources if s.doc_id == did]
        pages = sorted({s.pg for s in hs})
        L.append("%d. %s  \n   Pages used: %s · [open](%s)" % (n, cite_line(hs[0]), ", ".join(pages), hs[0].link()))
    L += ["", "## Automatic checks", ""] + ["- " + c for c in checks_summary(ev, unknown, used_f, unc)]
    L += ["", "## Evidence (every quote checked against its page)", "",
          "| F | Used | Claim | Quote | Source | Page | Check |", "|---|---|---|---|---|---|---|"]
    for f in ev.findings:
        h = ev.sources[f["source"] - 1]
        chk = f["check"] + ("; numbers not on page: " + ", ".join(f["numbers"]) if f["numbers"] else "")
        L.append("| F%d | %s | %s | \"%s\" | %s | %s | %s |" % (
            f["F"], "yes" if f["F"] in used_f else "", md_cell(f["claim"]), md_cell(f["quote"]),
            md_cell(h.short()), h.pg, chk))
    if ev.rejected:
        L += ["", "## Rejected by the checks (not used)", ""]
        seen = set()
        for r in ev.rejected:
            key = (r.get("why"), r.get("quote"))
            if key in seen:
                continue
            seen.add(key)
            L.append("- %s: %s%s" % (md_cell(r.get("why")), md_cell(r.get("claim", "")),
                                    (' — "%s"' % md_cell(r["quote"][:200])) if r.get("quote") else ""))
    if ev.not_covered:
        L += ["", "## Not covered by the passages read", ""] + ["- %s" % md_cell(g) for _, g in ev.not_covered]
    L += ["", "## Search log", ""]
    if terms:
        L.append("Search terms: " + "; ".join(terms))
    for s, hits in log:
        L.append("- **%s**" % md_cell(s))
        for h in hits:
            L.append("  - %s, %s (score %.4f)" % (md_cell(h.short()), h.pg, h.score))
    return "\n".join(L) + "\n"


def cmd_ask(a):
    keep, per_doc, note = doc_scope(connect(), a)
    run_pipeline(" ".join(a.question), "ask", 1, a.k, save=not a.no_save,
                 keep=keep, per_doc=per_doc, scope=note)


def cmd_vor(a):
    keep, per_doc, note = doc_scope(connect(), a)
    run_pipeline(" ".join(a.question), "research", a.depth, a.k,
                 keep=keep, per_doc=per_doc, scope=note)


def cmd_chat(a):
    db = connect()
    check_embed_model(db)
    idx = Index(db)
    keep, per_doc, note = doc_scope(db, a)
    say(damit_banner(VOICE))
    if note:
        say(note)
    say("vor chat — cited answers from your library (%s). Blank line or Ctrl+D quits.\n"
        "Prefix a question with '!' for deep research. Drag a file or folder into this window\n"
        "to add it to the library.\n%s" % (CHAT_MODEL, BANNER))
    last_q, last_a = None, None
    while True:
        try:
            q = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        drop = dropped_paths(q)
        if drop:
            try:
                ndocs, npass = add_paths(drop)
            except SystemExit:              # cmd_ingest dies when Ollama is down: keep the chat
                say("not indexed (reason above). Anything copied is in %s and the next "
                    "`vor ingest` picks it up." % os.path.join(LIBRARY, "added"))
                continue
            if npass:
                idx = Index(db)             # the vectors are held in memory: reload, or the new
                say("Ready: ask about it.") # document is invisible to this chat
                if keep:
                    say("(this chat was started with --doc, so answers still come only from that "
                        "selection; start `vor chat` without it to read the new document)")
            elif ndocs:
                say("Added, but it has no readable text, so there is nothing to ask it yet. "
                    "A scanned PDF needs `vor ocr` first.")
            continue
        deep = q.startswith("!")
        q = q.lstrip("!").strip()
        if last_q:
            # make a follow-up stand on its own so retrieval sees the whole question
            r = chat([{"role": "user", "content":
                       "Previous question: %s\nPrevious answer (start): %s\nFollow-up: %s\n\nRewrite the follow-up "
                       "as one standalone question. Reply with the question only." % (last_q, (last_a or "")[:800], q)}],
                     num_predict=200)
            r = strip_think(r)
            r = r.strip().strip('"').splitlines()[0] if r.strip() else q
            if r and r.lower() != q.lower():
                say("(searching for: %s)" % r)
                q = r
        try:
            _, ans, _ = run_pipeline(q, "research" if deep else "ask", a.depth if deep else 1, a.k,
                                     idx=idx, keep=keep, per_doc=per_doc)
        except RuntimeError as e:
            say("error: %s" % e)
            continue
        last_q, last_a = q, ans
    db.close()


# --------------------------------------------------------------------------- housekeeping

def cmd_list(a):
    db = connect()
    rows = db.execute("SELECT d.id, d.title, d.year, d.pages, d.notext, d.path, d.meta_src, "
                      "(SELECT COUNT(*) FROM chunks c WHERE c.doc_id=d.id) FROM docs d ORDER BY d.id").fetchall()
    if not rows:
        say("No documents yet. Put PDFs in %s and run: vor ingest" % LIBRARY)
        return
    missing = getattr(a, "missing", False)
    if missing:
        total = len(rows)
        rows = [r for r in rows if not os.path.exists(r[5])]
        if not rows:
            db.close()
            say("Every one of the %d indexed documents still has its file." % total)
            return
    for i, t, y, pages, notext, path, src, nc in rows:
        nt = [x for x in (notext or "").split(",") if x]
        flag = ""
        if nt:
            flag = "  NO TEXT on %d/%d pages%s" % (len(nt), pages, " (scanned - run ocr)" if len(nt) > pages / 2 else "")
        say("%4d  %s%s  [%d p, %d passages]%s%s\n      %s" % (
            i, t[:90], " (%s)" % y if y else "", pages or 0, nc, flag,
            "  title from %s" % src if src in ("first-page", "file-name") else "", path))
    if missing:
        db.close()
        say("\n%d of %d indexed documents no longer have a file at the path shown. They are still "
            "answered from. Put the file back and run `vor ingest` (a moved file is found by its "
            "content), or drop one with: vor remove ID" % (len(rows), total))
        return
    say("\n%d documents. Embeddings: %s. Fix a citation: vor meta ID --title ... --year ..."
        % (len(rows), meta_get(db, "embed_model", "?")))


def cmd_meta(a):
    db = connect()
    did = find_doc(db, a.doc)
    sets = {k: getattr(a, k) for k in ("title", "authors", "year", "org", "number") if getattr(a, k) is not None}
    if not sets:
        r = db.execute("SELECT title, authors, year, org, number, path FROM docs WHERE id=?", (did,)).fetchone()
        say("title:   %s\nauthors: %s\nyear:    %s\norg:     %s\nnumber:  %s\nfile:    %s" % r)
        return
    msg = ", ".join("%s=%s" % kv for kv in sets.items())
    if "title" in sets:
        set_title(db, did, sets.pop("title"))
    for k, v in sets.items():
        db.execute("UPDATE docs SET %s=?, meta_src='manual' WHERE id=?" % k, (v, did))
    db.execute("UPDATE docs SET meta_src='manual' WHERE id=?", (did,))
    db.commit()
    say("updated document %d: %s" % (did, msg))


def set_title(db, did, title):
    """Change a title and keep the keyword index (which also searches titles) in step."""
    old = db.execute("SELECT title FROM docs WHERE id=?", (did,)).fetchone()[0] or ""
    if db.fts and title != old:
        for cid, txt in db.execute("SELECT id, txt FROM chunks WHERE doc_id=?", (did,)).fetchall():
            db.execute("INSERT INTO chunks_fts(chunks_fts, rowid, txt, title) VALUES('delete',?,?,?)", (cid, txt, old))
            db.execute("INSERT INTO chunks_fts(rowid, txt, title) VALUES(?,?,?)", (cid, txt, title))
    db.execute("UPDATE docs SET title=? WHERE id=?", (title, did))


def parse_bib(text):
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]*),(.*?)\n\}", text, re.S):
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|\d+)", m.group(3)):
            v = fm.group(2).strip()
            if v[:1] in "{\"":
                v = v[1:-1]
            fields[fm.group(1).lower()] = re.sub(r"[{}]", "", " ".join(v.split()))
        entries.append(fields)
    return entries


def cmd_bib(a):
    db = connect()
    with open(os.path.expanduser(a.bibfile), encoding="utf-8", errors="replace") as f:
        entries = parse_bib(f.read())
    docs = db.execute("SELECT id, path FROM docs").fetchall()
    by_name = {}
    for i, p in docs:
        by_name.setdefault(os.path.basename(p).lower(), []).append(i)
    hit = 0
    for e in entries:
        files = re.split(r";", e.get("file", ""))
        for fl in files:
            # Zotero: "Title:files/12/name.pdf:application/pdf" or a plain path
            parts = fl.split(":")
            cand = [x for x in parts if x.lower().endswith(".pdf")]
            for c in cand:
                for did in by_name.get(os.path.basename(c).lower(), []):
                    authors = "; ".join(x.strip() for x in e.get("author", "").split(" and ") if x.strip())
                    if e.get("title"):
                        set_title(db, did, e["title"])
                    db.execute("UPDATE docs SET authors=?, year=?, org=?, number=?, meta_src='bibtex' WHERE id=?",
                               (authors, e.get("year", ""),
                                e.get("institution") or e.get("publisher") or e.get("journal") or "",
                                e.get("number") or e.get("doi") or "", did))
                    hit += 1
    db.commit()
    say("%d BibTeX entries read, %d library documents updated." % (len(entries), hit))


def long_passages(db, limit=PASSAGE_MAX):
    """(doc id, file, page, characters) of every passage longer than `limit`, longest first."""
    return db.execute("SELECT c.doc_id, d.path, c.page, length(c.txt) FROM chunks c JOIN docs d ON d.id = c.doc_id "
                      "WHERE length(c.txt) > ? ORDER BY length(c.txt) DESC", (limit,)).fetchall()


def cmd_tables(a):
    """Add table passages to PDFs indexed before 1.4.0 (backend 'pymupdf'), embedding only the tables.
    1.4.2: --check lists passages longer than PASSAGE_MAX; --redo reads the tables of those documents again
    with the 1.4.2 limits (no all-empty columns, no mostly empty grids, no row longer than a passage)."""
    if getattr(a, "check", False):
        db = connect()
        try:
            rows = long_passages(db)
        finally:
            db.close()
        if not rows:
            say("No passage is longer than %d characters. Nothing to redo." % PASSAGE_MAX)
            return
        say("%d passage(s) longer than %d characters (Vor reads only their start):" % (len(rows), PASSAGE_MAX))
        for did, path, page, n in rows[:40]:
            say("  %8d  doc %d  p.%s  %s" % (n, did, page, os.path.basename(path)))
        say("Fix: vor tables --redo")
        return
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            import fitz  # noqa: F401
        except ImportError:
            die("`vor tables` needs PyMuPDF (the installer puts it in Vor's Python).")
    db = connect()
    try:
        _add_tables(db, redo=getattr(a, "redo", False))
    finally:
        db.close()


def _add_tables(db, redo=False):
    if redo:
        ids = sorted({r[0] for r in long_passages(db)})
        rows = [db.execute("SELECT id, path, title FROM docs WHERE id=?", (i,)).fetchone() for i in ids]
        rows = [r for r in rows if r and (r[1] or "").lower().endswith(".pdf")]
        if not rows:
            say("No PDF has a passage longer than %d characters. Nothing to redo." % PASSAGE_MAX)
            return
        say("Reading the tables of %d document(s) again (they hold passages longer than %d characters) ..."
            % (len(rows), PASSAGE_MAX))
    else:
        rows = db.execute("SELECT id, path, title FROM docs WHERE backend = 'pymupdf' ORDER BY id").fetchall()
        if not rows:
            say("Every PDF already has its tables (or none was read with PyMuPDF). Nothing to do.")
            return
        say("Looking for tables in %d document(s) indexed before Vor 1.4.0 (only pages with numbers are searched) ..."
            % len(rows))
    pre = doc_prefix(EMBED_MODEL)
    added = 0
    for n, (did, path, title) in enumerate(rows, 1):
        if not os.path.isfile(path):
            say("  [%d/%d] file gone, skipped: %s" % (n, len(rows), path))
            continue
        labels = dict(db.execute("SELECT page, label FROM chunks WHERE doc_id=? GROUP BY page", (did,)).fetchall())
        tables = extract_pdf_tables(path)
        items = [(p, labels.get(p, ""), TABLE_IDX + k, c) for p in sorted(tables) for k, c in enumerate(tables[p])]
        vecs = []
        for b in range(0, len(items), EMBED_BATCH):
            batch = items[b:b + EMBED_BATCH]
            vecs += embed([pre + "%s (p.%s)\n%s" % (title, lab or p, c) for p, lab, _, c in batch], EMBED_MODEL)
        cur = db.cursor()
        cur.execute("BEGIN")
        if db.fts:
            for cid, txt in db.execute("SELECT id, txt FROM chunks WHERE doc_id=? AND idx >= ?", (did, TABLE_IDX)).fetchall():
                cur.execute("INSERT INTO chunks_fts(chunks_fts, rowid, txt, title) VALUES('delete',?,?,?)",
                            (cid, txt, title or ""))
        cur.execute("DELETE FROM chunks WHERE doc_id=? AND idx >= ?", (did, TABLE_IDX))
        for (p, lab, i, c), v in zip(items, vecs):
            cur.execute("INSERT INTO chunks(doc_id,page,label,idx,txt,vec) VALUES(?,?,?,?,?,?)",
                        (did, p, lab, i, c, array("f", v).tobytes()))
            if db.fts:
                cur.execute("INSERT INTO chunks_fts(rowid, txt, title) VALUES(?,?,?)", (cur.lastrowid, c, title))
        cur.execute("UPDATE docs SET backend = 'pymupdf+tables' WHERE id=?", (did,))
        db.commit()
        added += len(items)
        say("  [%d/%d] %s: %d table passage(s)" % (n, len(rows), os.path.basename(path), len(items)))
    say("Added %d table passage(s). Searches see them now." % added)


def cmd_remove(a):
    db = connect()
    did = find_doc(db, a.doc)
    p = db.execute("SELECT path FROM docs WHERE id=?", (did,)).fetchone()[0]
    delete_doc(db, did)
    db.commit()
    say("removed from the index (file left in place): %s" % p)


def ocr_exe():
    """ocrmypdf, looking in this Python's env first: the launcher runs the env's python without
    activating the env, so its bin (ocrmypdf, tesseract, ghostscript) goes on PATH."""
    for envbin in (os.path.dirname(os.path.realpath(sys.executable)), os.path.dirname(sys.executable)):
        if envbin not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = envbin + os.pathsep + os.environ.get("PATH", "")
    return shutil.which("ocrmypdf")


REDRAW_DPI = 300


def _pymupdf():
    try:
        import pymupdf as pm
    except ImportError:
        import fitz as pm          # an older PyMuPDF; ImportError when there is none
    return pm


def redraw_scanned_pages(src, dst):
    """1.4.8: a PDF of the pages of src that have no text layer, each drawn as a plain greyscale
    image (REDRAW_DPI). ocrmypdf stops on some JPEG 2000 images ("JPXDecode ... could not be
    decoded", exit 4: FEMA P-946, HMR 55A); MuPDF usually draws them. Returns the 0-based
    page numbers that were drawn, in order ([] when there were none)."""
    pm = _pymupdf()
    try:
        pm.TOOLS.mupdf_display_errors(False)
    except Exception:  # noqa: BLE001 - an older PyMuPDF; only the console noise differs
        pass
    doc, out, drawn = pm.open(src), pm.open(), []
    try:
        for i, page in enumerate(doc):
            if len(clean(page.get_text("text") or "")) >= MIN_PAGE_CHARS:
                continue
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            try:
                pix = page.get_pixmap(dpi=REDRAW_DPI, colorspace=pm.csGRAY)
                new.insert_image(new.rect, pixmap=pix)
            except Exception:  # noqa: BLE001 - a page MuPDF cannot draw stays blank: OCR finds nothing
                pass
            drawn.append(i)
        if drawn:
            out.save(dst, garbage=3, deflate=True)
        return drawn
    finally:
        out.close()
        doc.close()


def merge_ocr_pages(src, ocrd, drawn, dst):
    """src with its pages `drawn` replaced, in order, by the pages of ocrd (the redrawn pages
    after OCR); every other page, with its own text layer, is taken from src as it is."""
    pm = _pymupdf()
    doc, got, out = pm.open(src), pm.open(ocrd), pm.open()
    try:
        if len(got) != len(drawn):
            raise RuntimeError("OCR gave %d page(s) for %d drawn" % (len(got), len(drawn)))
        at = {p: k for k, p in enumerate(drawn)}
        for i in range(len(doc)):
            if i in at:
                out.insert_pdf(got, from_page=at[i], to_page=at[i])
            else:
                out.insert_pdf(doc, from_page=i, to_page=i)
        try:
            out.set_metadata(dict(doc.metadata or {}))
            out.set_page_labels(doc.get_page_labels())    # printed page numbers, as cited
        except Exception:  # noqa: BLE001 - an older PyMuPDF: page numbers are cited by position
            pass
        out.save(dst, garbage=3, deflate=True)
    finally:
        out.close()
        got.close()
        doc.close()


def ocr_by_redraw(exe, src, dst, tmpdir, n):
    """ocrmypdf failed on src: OCR its scanned pages drawn as images, then put them back in
    place. True when dst was written."""
    redrawn = os.path.join(tmpdir, "redraw-%d.pdf" % n)
    ocrd = os.path.join(tmpdir, "redraw-%d.ocr.pdf" % n)
    try:
        drawn = redraw_scanned_pages(src, redrawn)
        if not drawn:
            return False
        say("  redrawing its %d scanned page(s) as images and trying again" % len(drawn))
        r = subprocess.run([exe, "--skip-text", "--output-type", "pdf", "-q", redrawn, ocrd])
        if r.returncode != 0 or not os.path.exists(ocrd):
            say("  ocrmypdf failed on the redrawn pages too (exit %d)" % r.returncode)
            return False
        merge_ocr_pages(src, ocrd, drawn, dst)
        return os.path.exists(dst)
    except ImportError:
        say("  (redrawing the pages needs PyMuPDF, which this Python does not have)")
        return False
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001 - any reader or writer failure: the original stays as it was
        say("  the pages could not be redrawn (%s)" % " ".join(str(e).split())[:200])
        return False
    finally:
        for f in (redrawn, ocrd):
            if os.path.exists(f):
                os.remove(f)


def cmd_ocr(a):
    db = connect()
    rows = db.execute("SELECT id, path, pages, notext FROM docs WHERE notext!='' AND notext IS NOT NULL").fetchall()
    db.close()
    # 1.3.1: never a copy that OCR already made; a page it could make nothing of stays that way
    take, below, gone, other = scan_split(rows, a.min_fraction)
    share = _share(a.min_fraction)
    pages = lambda docs: sum(d[3] for d in docs)
    if getattr(a, "list", False):
        for mark, docs in (("ocr ", take), ("skip", below)):
            for i, p, n, k in sorted(docs, key=lambda d: -d[3] / float(d[2] or 1)):
                say("  %s  %4d of %4d pages scanned (%3.0f %%)  %s"
                    % (mark, k, n, 100.0 * k / (n or 1), _show_path(p)))
        say("%d document(s), %d scanned page(s) would be OCRed at --min-fraction %g; %d document(s), "
            "%d page(s) are under it and would be left. Nothing was run."
            % (len(take), pages(take), a.min_fraction, len(below), pages(below)))
        if gone:
            say("%d more have no file any more (vor list --missing)." % len(gone))
        return
    if not take:
        # 1.3.2: this said "No scanned PDFs to OCR" whatever the reason, while the doctor and
        # ingest counted the same documents and said "Run: vor ocr"
        if below:
            say("No PDF has at least %s of its pages scanned, so there is nothing to OCR at this setting. "
                "%d document(s) have a smaller share (%d scanned page(s) in all), often blank pages and "
                "full-page figures.\nSee them: vor ocr --min-fraction 0 --list\nTake them: vor ocr --min-fraction 0"
                % (share, len(below), pages(below)))
        elif gone:
            say("%d document(s) with scanned pages no longer have a file, so there is nothing to OCR "
                "(vor list --missing)." % len(gone))
        else:
            say("No scanned PDFs to OCR.")
        return
    exe = ocr_exe()
    if not exe:
        die("ocrmypdf is not installed. Re-run the installer with --ocr (adds ocrmypdf + tesseract to the "
            "ndvor env), then run this again.")
    if below:
        say("%d more document(s) have under %s of their pages scanned and are left alone "
            "(vor ocr --min-fraction 0 takes them too)." % (len(below), share))
    todo = [(i, p) for i, p, _, _ in take]
    outdir, tmpdir = ocr_dir(), os.path.join(LIBRARY, "_ocr_tmp")
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(tmpdir, exist_ok=True)
    omap = ocr_map_load()
    done, stopped = [], False
    for n, (i, p) in enumerate(todo, 1):
        h = sha1_of(p)
        name = ocr_copy_name(omap, p, h)
        tmp = os.path.join(tmpdir, name)        # written here first: a stopped run leaves no half copy
        say("OCR [%d/%d]: %s" % (n, len(todo), os.path.basename(p)))
        try:
            r = subprocess.run([exe, "--skip-text", "--output-type", "pdf", "-q", p, tmp])
        except KeyboardInterrupt:
            stopped = True
            break
        if r.returncode not in (0, 6) or not os.path.exists(tmp):     # 6 = already has text
            if os.path.exists(tmp):
                os.remove(tmp)
            redrawn = False
            if r.returncode not in (3, 6, 130):    # not: a missing tesseract/ghostscript, done, Ctrl+C
                say("  ocrmypdf failed (exit %d)" % r.returncode)
                try:
                    redrawn = ocr_by_redraw(exe, p, tmp, tmpdir, n)
                except KeyboardInterrupt:
                    stopped = True
                    break
            if not redrawn:
                say("  %s" % ("ocrmypdf found a text layer already and wrote nothing; left as is" if r.returncode == 6
                              else "left as is" if r.returncode not in (3, 130)
                              else "ocrmypdf failed (exit %d); left as is" % r.returncode))
                if os.path.exists(tmp):
                    os.remove(tmp)
                continue
            say("  done from the redrawn pages")
        os.replace(tmp, os.path.join(outdir, name))
        omap[h] = {"copy": name, "from": _lib_rel(p)}
        ocr_map_save(omap)
        done.append((i, p, os.path.join(outdir, name)))
    shutil.rmtree(tmpdir, ignore_errors=True)
    if stopped:
        say("\nStopped. %d of %d done; run `vor ocr` again for the rest." % (len(done), len(todo)))
    if not done:
        return
    say("Re-indexing the OCR copies...")
    cmd_ingest(argparse.Namespace(paths=[outdir], prune=False))
    # The copy takes the original's place only once the copy is in the index. Before 1.3.1 the
    # original was dropped first, so a run that stopped, or an Ollama that was not answering,
    # took every document done so far out of the library.
    db = connect()
    have = {r[0] for r in db.execute("SELECT path FROM docs")}
    for i, p, copy in done:
        if copy in have:
            delete_doc(db, i)
        else:
            say("  %s: its OCR copy is not indexed yet, so the original stays. Run: vor ingest" % os.path.basename(p))
    db.commit()
    db.close()


def home_reason():
    """Why HOME is the folder it is, in a few words (see _home)."""
    if os.environ.get("VOR_HOME"):
        return "VOR_HOME is set"
    if any(os.path.isfile(os.path.join(HOME, f)) for f in ("vor.db", "research.db")):
        return "it holds the index"
    return "the default; no index found anywhere yet"


def _index_counts(path):
    """(documents, passages) in an index file, or None when it cannot be read as one."""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(path), uri=True)
        try:
            return (db.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        finally:
            db.close()
    except sqlite3.Error:
        return None


def other_libraries():
    """Folders that look like a Vor library and are NOT the one in use: (folder, index counts
    or None, number of document files). Two libraries is how Vor has gone quiet before: the
    one being read was empty and the full one was a folder away."""
    here = os.path.realpath(HOME)
    seen, out = {here}, []
    cands = [os.path.expanduser("~/Vor"), os.path.expanduser("~/DamResearch")]
    if os.environ.get("DAMRESEARCH_HOME"):
        cands.append(os.path.expanduser(os.environ["DAMRESEARCH_HOME"]))
    parent = os.path.expanduser("~")
    try:
        cands += sorted(os.path.join(parent, d) for d in os.listdir(parent)
                        if d.startswith("Vor.before-rename-"))
    except OSError:
        pass
    for d in cands:
        real = os.path.realpath(d)
        if real in seen or not os.path.isdir(d):
            continue
        seen.add(real)
        counts = None
        for f in ("vor.db", "research.db"):
            if os.path.isfile(os.path.join(d, f)):
                counts = _index_counts(os.path.join(d, f)) or (0, 0)
                break
        nfiles = sum(1 for _ in walk([os.path.join(d, "library")])) if os.path.isdir(os.path.join(d, "library")) else 0
        if counts is not None or nfiles:
            out.append((d, counts, nfiles))
    return out


def library_checks():
    """The checks that need no model: is Vor reading the library you think it is, and is the
    index level with the files. Returns [(level, text)], level one of OK / WATCH / PROBLEM.
    Every PROBLEM here is a state in which Vor runs without error and answers from nothing."""
    out = []
    add = lambda level, text: out.append((level, text))
    add("OK", "library folder %s (%s)" % (HOME, home_reason()))
    on_disk = list(walk([LIBRARY])) if os.path.isdir(LIBRARY) else []
    if not os.path.exists(DB_PATH):
        nd = nc = 0
        # 1.4.5: a new install (no files, no index, no other library anywhere) is not a fault yet
        fresh = not on_disk and not other_libraries()
        add("WATCH" if fresh else "PROBLEM", "no index at %s%s" % (DB_PATH, (": %d document file(s) are waiting in "
            "the library. Run: vor ingest" % len(on_disk)) if on_disk else (
            ". The library is empty: put PDFs in %s and run: vor ingest  (or: vor add FILE ...)" % LIBRARY)))
        rows, used = [], None
    else:
        counts = _index_counts(DB_PATH)
        if counts is None:
            add("PROBLEM", "%s is not a readable index" % DB_PATH)
            return out
        nd, nc = counts
        db = connect()
        try:
            used = meta_get(db, "embed_model")
            rows = db.execute("SELECT path, notext, added, sha1, id, pages FROM docs").fetchall()
            fts = db.fts
            no_tables = db.execute("SELECT COUNT(*) FROM docs WHERE backend = 'pymupdf'").fetchone()[0]
        finally:
            db.close()
        if no_tables:
            add("WATCH", "%d PDF(s) were indexed before Vor 1.4.0 read tables as tables: a table row's numbers "
                         "are only in running text, without their column headings. Run: vor tables "
                         "(embeds only the tables)" % no_tables)
        if not nc:
            add("PROBLEM", "the index is empty (%d documents, 0 passages): every question will get "
                "'no passage'. %s" % (nd, ("%d file(s) are in the library. Run: vor ingest" % len(on_disk))
                                       if on_disk else "Put PDFs in %s and run: vor ingest" % LIBRARY))
        else:
            add("OK", "index: %d documents, %d passages" % (nd, nc))
        if used and used != EMBED_MODEL:
            add("PROBLEM", "indexed with %s but VOR_EMBED is %s: every search is refused until one is "
                           "set back or the index is rebuilt" % (used, EMBED_MODEL))
        if not fts:
            add("WATCH", "keyword search is off (this Python's SQLite has no FTS5): names like "
                         "'Froehlich' are found by meaning only")
    for d, counts, nfiles in other_libraries():
        what = ("an index with %d documents" % counts[0]) if counts is not None else "no index"
        text = ("a second library exists at %s (%s, %d document file(s)); Vor is reading %s"
                % (d, what, nfiles, HOME))
        fuller = (counts[0] if counts else 0) > nd or (nd == 0 and nfiles)
        add("PROBLEM" if fuller else "WATCH",
            text + (". It holds MORE than the one in use: run `zsh setup-vor.zsh` to bring it over, or set "
                    "VOR_HOME to it" if fuller else ". Nothing reads it; remove it once you are sure"))
    if rows:
        indexed = {os.path.normpath(r[0]) for r in rows}
        replaced = ocr_replaced_paths()        # a scanned original whose OCR copy is indexed instead
        unindexed = [f for f in on_disk if os.path.normpath(f) not in indexed and os.path.normpath(f) not in replaced]
        # 1.3.2: a file ingest will never add is not "run: vor ingest". Ingest goes by content, so
        # a second copy of an indexed file is skipped, and so is a file over the size limit.
        by_hash = {r[3]: r[0] for r in rows}
        new, copies, big = [], [], []
        for f in unindexed:
            try:
                if os.path.getsize(f) > MAX_FILE_BYTES:
                    big.append(f)
                    continue
                twin = by_hash.get(sha1_of(f)) if len(unindexed) <= DOCTOR_HASH_LIMIT else None
            except OSError:
                twin = None
            if twin and os.path.exists(twin):
                copies.append((f, twin))
            else:
                new.append(f)       # also a moved file: ingest finds it by content and re-points it
        if new:
            add("WATCH", "%d file(s) in the library are not in the index (first: %s). Run: vor ingest"
                % (len(new), os.path.relpath(new[0], LIBRARY)))
        if big:
            add("WATCH", "%d file(s) are over %d MB, which Vor does not index (first: %s). Split the PDF "
                "to have it read" % (len(big), MAX_FILE_BYTES >> 20, os.path.relpath(big[0], LIBRARY)))
        if copies:
            add("OK", "%d file(s) are exact copies of an indexed document, so ingest leaves them out "
                "(first: %s is the same file as %s)"
                % (len(copies), os.path.relpath(copies[0][0], LIBRARY), _show_path(copies[0][1])))
        gone = [r[0] for r in rows if not os.path.exists(r[0])]
        if gone:
            lib = os.path.abspath(LIBRARY) + os.sep
            outside = [g for g in gone if not os.path.abspath(g).startswith(lib)]
            drop = ("To drop them: vor ingest --prune" if not outside else
                    "%d of them %s indexed from outside the library, which `vor ingest --prune` does "
                    "not touch: drop one with vor remove ID"
                    % (len(outside), "was" if len(outside) == 1 else "were"))
            add("WATCH", "%d indexed document(s) no longer have a file (first: %s). They are still "
                "answered from. List them: vor list --missing. %s" % (len(gone), _show_path(gone[0]), drop))
        changed = []
        for path, _, added in (r[:3] for r in rows):
            try:
                when = datetime.fromisoformat((added or "")[:19])
                if os.path.exists(path) and datetime.fromtimestamp(os.path.getmtime(path)) > when + timedelta(seconds=2):
                    changed.append(path)
            except ValueError:
                continue
        if changed:
            add("WATCH", "%d file(s) changed after they were indexed (first: %s), so answers come from "
                "the older text. Run: vor ingest" % (len(changed), os.path.basename(changed[0])))
        no_text = [r for r in rows if (r[1] or "").strip()]
        scanned = [r for r in no_text if not in_ocr_dir(r[0])]
        if scanned:
            pages = sum(len(r[1].split(",")) for r in scanned)
            split = scan_split([(r[4], r[0], r[5], r[1]) for r in scanned])
            add("WATCH", "%d document(s) have %d page(s) with no text layer: Vor cannot read those pages. %s"
                % (len(scanned), pages, ocr_advice(*split, installed=bool(ocr_exe()))))
        after = [r for r in no_text if in_ocr_dir(r[0])]
        if after:
            add("OK", "%d page(s) in %d OCR copies still have no text (blank or unreadable pages; "
                      "there is nothing more to run)" % (sum(len(r[1].split(",")) for r in after), len(after)))
        if not (new or big or gone or changed):
            add("OK", "every file in the library is indexed, and none changed since")
    return out


def print_checks(checks):
    """Print [(level, text)] and return the number of PROBLEMs."""
    for level, text in checks:
        say("  %-8s %s" % ({"OK": "ok", "WATCH": "WATCH", "PROBLEM": "PROBLEM"}[level], text))
    return sum(1 for level, _ in checks if level == "PROBLEM")


def cmd_doctor(a):
    ok = True
    say(damit_banner("vor"))
    say("vor %s   home %s" % (VERSION, HOME))
    if getattr(a, "library_only", False):
        say("  (models not checked: --library)")
    else:
        try:
            v = _get("/api/version").get("version")
            say("  Ollama %s at %s" % (v, BASE))
            tags = {m["name"] for m in _get("/api/tags").get("models", [])}
            for m in (CHAT_MODEL, EMBED_MODEL):
                have = m in tags or (m + ":latest") in tags
                say("  model %-28s %s" % (m, "present" if have else "MISSING - re-run setup-vor.zsh"))
                ok &= have
            if ok:
                vec = embed([query_text(EMBED_MODEL, "spillway design flood")], EMBED_MODEL)[0]
                say("  embeddings work (%d dims)" % len(vec))
                r = strip_think(chat([{"role": "user", "content": "Reply with the single word: ready"}],
                                     num_predict=20))
                if r:
                    say("  chat model replies: %r" % r[:40])
                else:
                    # 1.3.0: an empty reply used to print as '' and count as working
                    say("  chat model replied with NOTHING to a one-word request: %s" % empty_reply_reason())
                    ok = False
        except Exception as e:
            say("  Ollama: NOT reachable (%s). To start it, %s." % (e, start_hint()))
            ok = False
    # 1.3.0: the library itself. These need no model, and each PROBLEM is a state in which Vor
    # runs without an error and answers from nothing.
    problems = print_checks(library_checks())
    say("  numpy %s" % ("yes" if np is not None else "no (slower search)"))
    try:
        import pymupdf  # noqa
        say("  PDF reader: PyMuPDF (printed page labels on)")
    except ImportError:
        say("  PDF reader: %s" % ("pdftotext" if shutil.which("pdftotext") else "pypdf/none"))
    say("  OCR: %s" % ("ocrmypdf" if ocr_exe() else "not installed (installer --ocr)"))
    if problems:
        say("\n%d PROBLEM(s) above: until fixed, Vor will run and answer from less than you think." % problems)
    sys.exit(0 if (ok and not problems) else 1)


def add_scope_args(s):
    """--doc / --per-doc, on every command that retrieves."""
    s.add_argument("--doc", metavar="KEY",
                   help="only read this publication: the id from `vor list`, or part of its "
                        "file name, title or report number (punctuation is ignored, so P-946 finds a "
                        "file named P946.pdf). Comma-separated for several. Naming the publication in "
                        "the question instead does not scope anything - 'FEMA' is just a search word "
                        "and matches every FEMA document.")
    s.add_argument("--per-doc", type=int, default=None, metavar="N",
                   help="passages allowed from any one publication (default 3; with --doc the cap is "
                        "lifted unless you set it)")


SHORT_HELP = """\
Vor answers from your library of dam-safety publications, and checks every quote against its page.

  vor "question"            (the same as vor ask) a short answer, every quote cited
  vor research "question"   a longer brief, saved in the reports folder
  vor chat                  a conversation; start a line with ! for a deep-research brief
  vor add FILE ...          copy publications into the library and index them (drag files in)
  vor ingest                index what is in the library folder
  vor list                  what is in the library
  vor doctor                is everything installed, indexed and level with its files?

All commands and options: vor --help
"""


def main():
    argv = sys.argv[1:]
    if not argv or argv == ["help"]:
        print(SHORT_HELP)      # 1.4.5: not argparse's "the following arguments are required: cmd"
        return
    ap = argparse.ArgumentParser(prog="vor",
                                 description="Local research assistant for dam-safety literature. " + BANNER)
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest", help="index PDFs/.md/.txt (default: the library drop folder)")
    s.add_argument("paths", nargs="*")
    s.add_argument("--prune", action="store_true", help="drop documents whose file is gone")
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("add", help="copy files into the library and index them (drag them in)")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("list", help="documents in the library")
    s.add_argument("--missing", action="store_true",
                   help="only the indexed documents whose file is no longer where it was")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("meta", help="show or fix a document's citation")
    s.add_argument("doc")
    for k in ("title", "authors", "year", "org", "number"):
        s.add_argument("--" + k)
    s.set_defaults(fn=cmd_meta)
    s = sub.add_parser("bib", help="take citations from a Zotero/BibTeX export")
    s.add_argument("bibfile")
    s.set_defaults(fn=cmd_bib)
    s = sub.add_parser("search", help="retrieval only: best passages with pages")
    s.add_argument("question", nargs="+")
    s.add_argument("-k", type=int, default=10)
    add_scope_args(s)
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("ask", help="quick cited answer")
    s.add_argument("question", nargs="+")
    s.add_argument("-k", type=int, default=10)
    s.add_argument("--no-save", action="store_true")
    add_scope_args(s)
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("research", help="deep research report with checked quotes")
    s.add_argument("question", nargs="+")
    s.add_argument("--depth", type=int, default=5, help="sub-questions incl. the original (default 5)")
    s.add_argument("-k", type=int, default=8, help="passages read per sub-question (default 8)")
    add_scope_args(s)
    s.set_defaults(fn=cmd_vor)
    s = sub.add_parser("chat", help="interactive; '!' prefix = deep research")
    s.add_argument("--depth", type=int, default=4)
    s.add_argument("-k", type=int, default=8)
    add_scope_args(s)
    s.set_defaults(fn=cmd_chat)
    s = sub.add_parser("tables", help="add the PDFs' tables as their own passages (documents indexed before 1.4.0)")
    s.add_argument("--check", action="store_true", help="list passages too long for Vor to read whole; changes nothing")
    s.add_argument("--redo", action="store_true", help="read the tables again of documents with a passage that is too long")
    s.set_defaults(fn=cmd_tables)
    s = sub.add_parser("ocr", help="OCR scanned PDFs (needs ocrmypdf) and re-index them")
    s.add_argument("--min-fraction", type=float, default=OCR_MIN_FRACTION,
                   help="OCR a PDF when at least this share of its pages has no text (default 0.3; "
                        "0 = every PDF with a scanned page)")
    s.add_argument("--list", action="store_true",
                   help="show what would be OCRed at this --min-fraction, and what would be left; runs nothing")
    s.set_defaults(fn=cmd_ocr)
    s = sub.add_parser("remove", help="drop a document from the index")
    s.add_argument("doc")
    s.set_defaults(fn=cmd_remove)
    s = sub.add_parser("doctor", help="check Ollama, the models, and that the library being read is "
                                      "the full one and level with its files")
    s.add_argument("--library", dest="library_only", action="store_true",
                   help="check the library and index only (no Ollama needed)")
    s.set_defaults(fn=cmd_doctor)
    if not argv[0].startswith("-") and argv[0] not in sub.choices:
        argv = ["ask"] + argv  # 1.4.5: `vor what breach width ...` is a question
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except RuntimeError as e:
        die(str(e))
    except KeyboardInterrupt:
        die("interrupted", 130)


if __name__ == "__main__":
    main()
