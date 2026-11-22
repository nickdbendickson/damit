#!/usr/bin/env python3
# rag_query.py v2.6 — query the RAG store, streaming output (stdlib only; numpy if present)
#
#   rag_query.py "question"            one question, answered from the indexed documents
#   rag_query.py -c standards "..."    from one collection
#   rag_query.py --chat                a conversation: every question is looked up first
#   rag_query.py runs ...              the run results database (run_results.py: heim runs)
#
# v2.6: search by meaning AND by exact words, fused by rank (as Vor does). A name such as
#   ndbreach.rundam, STABILITY_RETRY_PCT or a function name is found by its word even where
#   prose about the same topic is closer in meaning. Vectors stored as bytes (rag_index 2.9)
#   load in a fraction of a second; text vectors from older indexes still load, slowly, until
#   `heim-index --compact` converts them. With no word index (an older index, or a SQLite
#   without FTS5) the search is by meaning alone, as before.
# v2.5: dam-breach run results. `heim runs add FOLDER` reads runs into ~/local-ai/runs.db
#   (run_results.py) and `heim runs ...` is passed to it. A question that names a dam in that
#   database and asks for a result (depth, velocity, arrival, peak flow, a structure, ...) is
#   answered from its tables, not from passages: a passage search can hand the model the
#   neighbour's row or a rounded number, a SELECT cannot. `heim add <run folder>` and a run
#   folder dragged into heim-chat go to the run database too.
# v2.4: `heim doctor`, `heim add FILE ...` and `heim chat` do what `heim-doctor`, `heim-add`
#   and `heim-chat` do. Vor takes its commands as words (`vor doctor`), Heim took them only
#   as separate hyphenated commands, so `heim doctor` put the one word "doctor" to the model
#   as a question and came back with an answer instead of the check.
# v2.3: --chat (the `heim-chat` command). heim-chat used to be `ollama run heim`: the bare
#   model, which never read a document, so the knowledge pack and anything added with
#   heim-add were invisible to it. Now each question is looked up in the index like a one-shot
#   query, a follow-up is searched together with the question before it, and a file dragged
#   into the window is indexed (rag_index --add) and readable on the next question. With
#   nothing indexed it says so before every answer: an empty index is not an error, and that
#   has cost a wrong answer more than once.
#
# v2.2 fixes (vs v2.1):
#   - nomic-embed-text query prefix (search_query:) to match the v2.4 index.
#   - Hidden per-collection stages excluded from "all".
#   - num_ctx sent per request, sized to the prompt, so Ollama never trims the
#     front of the prompt (the instructions) without saying so.
#   - qwen3 "thinking" is streamed separately and kept out of the answer.
import os, sys, re, json, sqlite3, urllib.request, urllib.error, math, argparse, shlex
from array import array

DB = os.path.expanduser(os.environ.get("HEIM_DB", "~/local-ai/knowledge.db"))
BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = "nomic-embed-text"
QUERY_PREFIX = "search_query: "
CHAT_MODEL = os.environ.get("HEIM_MODEL", "heim")
NUM_CTX = int(os.environ.get("HEIM_NUM_CTX", "16384"))
TOP_K = 10
POOL = 60                 # candidates taken from each of the two searches before fusing
RRF_K = 60                # reciprocal-rank fusion constant (as Vor)
FTS = "chunks_fts"
STOP = set("""a an and are as at be by can could did do does for from has have how if in into is it its
of on or should than that the their there these this those to was were what when where which who why
will with would about between during under over per using used use based any all also more most not
you your heim does doesn tell show explain""".split())
try:
    import numpy as np
except ImportError:
    np = None


def post(url, payload, timeout=900):
    """POST to Ollama. When nothing answers (connection refused), start it once and try again."""
    def once():
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    try:
        return once()
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError:
        if not ensure_ollama(BASE):
            raise
        return once()


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


class Store(object):
    """The indexed passages of one collection (or all), held in memory. A chat asks many
    questions, and parsing every stored vector again for each one takes seconds on a full
    index; the file's size and time say when it has changed and must be read again."""

    def __init__(self, coll):
        self.coll = coll
        self.rows, self.M, self.stamp = [], None, None
        self.pos, self.fts, self.text_vectors = {}, False, 0
        self.load()

    def _stamp(self):
        """(mtime, size, SQLite file change counter). The counter (header bytes 24-27) goes up on every
        committed write; mtime and size alone missed a small insert made within one file-system time
        tick (the new row fit in an existing page, so the size stayed the same)."""
        try:
            st = os.stat(DB)
        except OSError:
            return None
        counter = None
        try:
            with open(DB, "rb") as f:
                head = f.read(28)
            if len(head) == 28 and head.startswith(b"SQLite format 3\x00"):
                counter = int.from_bytes(head[24:28], "big")
        except OSError:
            pass
        return (st.st_mtime_ns, st.st_size, counter)

    def load(self):
        self.stamp = self._stamp()
        self.rows, self.M, self.pos, self.fts = [], None, {}, False
        if self.stamp is None:
            return
        db = sqlite3.connect(DB)
        try:
            if self.coll == "all":
                rows = db.execute("SELECT collection,path,idx,txt,vec,id FROM chunks "
                                  "WHERE collection NOT LIKE '\\_\\_%' ESCAPE '\\'").fetchall()
            else:
                rows = db.execute("SELECT collection,path,idx,txt,vec,id FROM chunks WHERE collection=?",
                                  (self.coll,)).fetchall()
            self.fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (FTS,)).fetchone())
        except sqlite3.OperationalError:      # a file that is not an index yet
            rows = []
        finally:
            db.close()
        self.rows = [r[:4] for r in rows]
        self.pos = dict((r[5], i) for i, r in enumerate(rows))
        self.text_vectors = sum(1 for r in rows if not isinstance(r[4], bytes))
        if np is not None and rows:
            if not self.text_vectors:
                self.M = np.frombuffer(b"".join(r[4] for r in rows), dtype=np.float32).reshape(len(rows), -1)
            else:
                self.M = np.array([unpack_vec(r[4]) for r in rows], dtype=np.float32)
            self.norms = np.linalg.norm(self.M, axis=1)
        else:
            self.vecs = [unpack_vec(r[4]) for r in rows]

    def changed(self):
        return self._stamp() != self.stamp

    def collections(self):
        out = {}
        for r in self.rows:
            out[r[0]] = out.get(r[0], 0) + 1
        return out

    def _sims(self, qv):
        if self.M is not None:
            v = np.array(qv, dtype=np.float32)
            return ((self.M @ v) / (self.norms * np.linalg.norm(v) + 1e-9)).tolist()
        nb = math.sqrt(sum(y * y for y in qv))

        def cos(a):
            d = sum(x * y for x, y in zip(a, qv))
            na = math.sqrt(sum(x * x for x in a))
            return d / (na * nb) if na and nb else 0.0
        return [cos(a) for a in self.vecs]

    def search(self, queries, top_k):
        """Best passages for any of the queries (a follow-up is searched on its own and
        together with the question before it). Two lists are fused by rank: the passages
        closest in meaning (each keeps its better score over the queries) and, when the index
        has its word index, the passages that contain the question's exact words. The score
        shown is the meaning score, so a passage found by its words alone shows a low one."""
        if not self.rows:
            return []
        qvs = post(BASE + "/api/embed", {"model": EMBED_MODEL,
                                         "input": [QUERY_PREFIX + q for q in queries]})["embeddings"]
        best = None
        for qv in qvs:
            sims = self._sims(qv)
            best = sims if best is None else [max(a, b) for a, b in zip(best, sims)]
        by_meaning = sorted(range(len(best)), key=lambda i: -best[i])[:max(POOL, top_k)]
        by_words = self.lexical(queries, max(POOL, top_k))
        fused = {}
        for lst in (by_meaning, by_words):
            for rank, i in enumerate(lst):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        order = sorted(fused, key=lambda i: (-fused[i], -best[i]))[:top_k]
        return [(float(best[i]),) + tuple(self.rows[i]) for i in order]

    def lexical(self, queries, n):
        """Row positions of the passages holding the queries' words, best first (BM25), or []
        when the index has no word index."""
        if not self.fts:
            return []
        words = []
        for q in queries:
            for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:[.\-][A-Za-z0-9_]+)*|\d+(?:\.\d+)?", q):
                if len(t) >= 3 and t.lower() not in STOP and t not in words:
                    words.append(t)
        if not words:
            return []
        expr = " OR ".join('"%s"' % w.replace('"', "") for w in words)
        if self.coll == "all":
            where, args = "c.collection NOT LIKE '\\_\\_%' ESCAPE '\\'", [expr, n]
        else:
            where, args = "c.collection = ?", [expr, self.coll, n]
        db = sqlite3.connect(DB)
        try:
            got = db.execute("SELECT f.rowid FROM %s f JOIN chunks c ON c.id = f.rowid WHERE %s MATCH ? AND %s "
                             "ORDER BY bm25(%s) LIMIT ?" % (FTS, FTS, where, FTS), args).fetchall()
        except sqlite3.Error:
            return []
        finally:
            db.close()
        return [self.pos[r[0]] for r in got if r[0] in self.pos]


def unpack_vec(v):
    """A stored vector: float32 bytes (rag_index 2.9) or JSON text (before)."""
    if isinstance(v, bytes):
        a = array("f")
        a.frombytes(v)
        return a.tolist()
    return json.loads(v)


def retrieve(q, coll, top_k):
    if not os.path.exists(DB):
        sys.exit("No index at %s — run rag_index.py first." % DB)
    store = Store(coll)
    if not store.rows:
        h = (" Collection '%s' empty — index it: rag_index.py -c %s <folder>" % (coll, coll)) if coll != "all" else ""
        sys.exit("Index is empty.%s" % h)
    slow_note(store)
    return store.search([q], top_k)


def slow_note(store):
    if store.text_vectors:
        print("(%d passages are stored in the old, slow format. One-time fix, nothing re-embedded: "
              "heim-index --compact)" % store.text_vectors)


def chat_payload(prompt, stream, think=True):
    est_tokens = len(prompt) // 3 + 4096          # prompt + room for thinking and answer
    p = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": prompt}],
         "stream": stream, "options": {"num_ctx": max(NUM_CTX, min(est_tokens, 40960))}}
    if think:
        p["think"] = True
    return p


def stream_answer(prompt, think=True):
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(chat_payload(prompt, True, think)).encode(),
                                 headers={"Content-Type": "application/json"})
    buf = []
    thinking_shown = False
    try:
        r = urllib.request.urlopen(req, timeout=1800)
    except urllib.error.HTTPError as e:
        if think and e.code == 400:      # older Ollama without the "think" field
            return stream_answer(prompt, think=False)
        raise
    with r:
        while True:
            line = r.readline()
            if not line:
                break
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
            if msg.get("thinking") and not thinking_shown:
                sys.stdout.write("(thinking…)\n")
                sys.stdout.flush()
                thinking_shown = True
            piece = msg.get("content") or ""
            if piece:
                buf.append(piece)
                sys.stdout.write(piece)
                sys.stdout.flush()
            if ch.get("done"):
                break
    sys.stdout.write("\n")
    return "".join(buf)


INSTRUCTION = ("Answer using ONLY the context below. Cite each fact with the collection "
               "and file path shown in its bracket header. If insufficient, say so plainly.")
NO_DOCS = ("NO DOCUMENTS ARE INDEXED%s, so nothing below is looked up or cited: it is the model's "
           "built-in rules only.\nIndex the knowledge pack:  heim-index -c heim_knowledge <folder>   "
           "(the installer does this; `heim-index --list-collections` shows what is there)")


def build_prompt(q, hits, earlier=None):
    ctx = "\n\n".join("--- [%s] %s (chunk %d) ---\n%s" % (c, p, i, t) for _, c, p, i, t in hits)
    parts = [INSTRUCTION, ""]
    if earlier:
        parts += ["=== EARLIER IN THIS CONVERSATION (for what the question refers to; not a source) ===",
                  "Question: " + earlier[0], "Answer: " + earlier[1][:1200], ""]
    parts += ["=== CONTEXT ===", ctx, "=== QUESTION ===", q]
    return "\n".join(parts)


def answer(prompt):
    """Stream the answer; fall back to one non-streamed call. Returns the text ('' if none)."""
    try:
        ans = stream_answer(prompt)
    except KeyboardInterrupt:
        print("\n[interrupted]")
        return None
    except Exception as e:
        print("[stream failed (%s) — non-streaming fallback]" % e)
        out = post(BASE + "/api/chat", chat_payload(prompt, False, think=False))
        ans = (out.get("message") or {}).get("content") or ""
        print(ans)
    if not ans.strip():
        print("[empty response — check `ollama ps` and the server log]")
    return ans


def dropped_paths(line):
    """The paths in a line Terminal pasted when a file was dragged in, or [] when the line is
    a question. Every word must be an existing path that has a separator or starts with ~, so
    a question that happens to name a file in the current folder is still a question."""
    try:
        parts = shlex.split(line)
    except ValueError:
        return []
    out = []
    for p in parts:
        full = os.path.expanduser(p)
        if not (os.sep in p or p.startswith("~")) or not os.path.exists(full):
            return []
        out.append(full)
    return out


def add_dropped(paths):
    """Index dragged files with rag_index.add_files (the heim-add command). Returns the number
    of files indexed, or None when the indexer could not be used at all."""
    import importlib.util
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_index.py")
    if not os.path.isfile(src):
        print("rag_index.py is not next to this script, so nothing was added. Use: heim-add <file>")
        return None
    spec = importlib.util.spec_from_file_location("rag_index_for_chat", src)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod.add_files(paths)
    except SystemExit as e:                 # the indexer exits with its reason; keep the chat
        if e.code not in (0, None):
            print(e.code if isinstance(e.code, str) else "not added (reason above)")
        return None
    except Exception as e:                  # Ollama down, an unreadable file: say so and go on
        print("not added: %s" % e)
        return None


def chat(coll, top_k, ask=input):
    store = Store(coll)
    slow_note(store)
    print("Heim chat (%s): every question is looked up in the indexed documents first.\n"
          "Blank line or Ctrl+D quits. Drag a file into this window to add it." % CHAT_MODEL)
    cols = store.collections()
    if cols:
        print("Reading %d passages: %s" % (len(store.rows), ", ".join(
            "%s (%d)" % kv for kv in sorted(cols.items()))))
    else:
        print(NO_DOCS % ((" in collection '%s'" % coll) if coll != "all" else ""))
    earlier = None
    while True:
        try:
            q = ask("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            break
        if not q:
            break
        drop = dropped_paths(q)
        mod = runs_module() if drop else None
        if drop and mod is not None and all(mod.has_runs(p) for p in drop):
            try:
                n = mod.add(drop)
            except Exception as e:
                print("not added: %s" % e)
                n = 0
            if n:
                print("Ready: ask about it (name the dam, e.g. 'peak flow at DWR-2801').")
            continue
        if drop:
            n = add_dropped(drop)
            store.load()
            if n:
                print("Ready: ask about it.")
                if coll not in ("all", "added"):
                    print("(this chat reads only collection '%s'; a dragged file goes into 'added', "
                          "so start heim-chat without -c to read it)" % coll)
            continue
        if store.changed():                 # heim-add or heim-index ran in another window
            store.load()
        dams = run_question(q)
        if dams:
            ans = answer_from_runs(q, dams)
            if ans:
                earlier = (q, ans)
            continue
        try:
            hits = store.search([q] + ([earlier[0] + "\n" + q] if earlier else []), top_k)
        except Exception as e:
            print("could not look that up: %s\n(is Ollama running? heim-start)" % e)
            continue
        if hits:
            print("Looked up %d passages:" % len(hits))
            for s, c, p, i, _ in hits:
                print("  %.3f  [%s] %s (chunk %d)" % (s, c, p, i))
            prompt = build_prompt(q, hits, earlier)
        else:
            print(NO_DOCS % ((" in collection '%s'" % coll) if coll != "all" else ""))
            prompt = q if not earlier else ("Earlier question: %s\nEarlier answer: %s\n\nQuestion: %s"
                                            % (earlier[0], earlier[1][:1200], q))
        print("-" * 70)
        ans = answer(prompt)
        if ans is None:
            continue
        if ans.strip():
            earlier = (q, ans.strip())


HELP = """\
The commands you will use (the rest: heim --help, heim runs --help, vor --help):

  heim "question"            ask about the suite's code, tools and known behaviours (cited)
  heim chat                  a conversation; drag a file or a run folder in to add it
  heim runs add FOLDER       read finished runs, then:  heim runs show 2801 | at 2801 "Main St" |
                             compare 2801 | ask "how deep at County Road 26 for 2801?"
  vor ask "question"         an answer from your library of publications, every quote checked
  vor research "question"    a longer cited brief, saved in ~/Vor/reports
  ai-doctor                  is everything installed, indexed and reading what you think?
  ai                         all of the above on one page in your browser (this computer only)
  ai-score                   run both answer tests and keep a dated score history

Ollama is started for you when it is not running (heim-start still works).
More: heim add FILE, heim doctor, heim-digest / heim-watch (run watcher), damchain, heim-index.
"""


RUN_WORDS = ("depth", "deep", "velocity", "fast", "arrival", "arrive", "peak", "discharge", "flow", "cfs",
             "wse", "water surface", "elevation", "structure", "house", "home", "building", "address",
             "road", "rail", "bridge", "culvert", "flooded", "inundat", "breach", "hydrograph", "storage",
             "volume", "hazard class", "how long", "when does", "time to")
_RUNS = []


def runs_module():
    """run_results.py beside this file (None when it is not there: an older install)."""
    if _RUNS:
        return _RUNS[0]
    import importlib.util
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_results.py")
    mod = None
    if os.path.isfile(src):
        spec = importlib.util.spec_from_file_location("run_results_for_heim", src)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            mod = None
    _RUNS.append(mod)
    return mod


def run_question(q):
    """The dams of the run database a question names, when it also asks for a result; else []."""
    low = q.lower()
    if not any(w in low for w in RUN_WORDS):
        return []
    mod = runs_module()
    if mod is None:
        return []
    try:
        return mod.dams_named_in(q)
    except Exception:
        return []


def answer_from_runs(q, dams):
    print("Answered from the run results (%s), not from documents: the numbers are the database's."
          % ", ".join(dams))
    print("-" * 70)
    return runs_module().ask(q)


def command_word(argv):
    """`heim doctor`, `heim add FILE ...`, `heim chat`: the arguments to run instead, or None
    when argv is a question.

    Returns ("index", [...]) for rag_index.py beside this file, ("query", [...]) for this one.
    A question is never taken for a command: `doctor` counts only with nothing after it but
    flags, `chat` only alone, and `add` only when every word after it is a file or folder that
    exists (or there is none, which gets the usage line). "add a culvert to the run?" is a
    question; "doctor" on its own is not one."""
    if not argv or argv[0] not in ("doctor", "add", "chat", "runs", "help"):
        return None
    word, rest = argv[0], argv[1:]
    if word == "help" and not rest:
        print(HELP)
        sys.exit(0)
    if word == "runs":
        return ("runs", rest)
    if word == "doctor" and all(r.startswith("-") for r in rest):
        return ("index", ["--doctor"] + rest)
    if word == "chat" and not rest:
        return ("query", ["--chat"])
    if word == "add":
        if not rest:
            sys.exit("usage: heim add FILE ...   (a file dragged into the Terminal window gives its path)")
        if all(os.path.exists(os.path.expanduser(r)) for r in rest):
            mod = runs_module()
            if mod is not None and all(mod.has_runs(os.path.expanduser(r)) for r in rest):
                return ("runs", ["add"] + rest)      # run folders: numbers into the run database
            return ("index", ["--add"] + rest)
    return None


def main():
    word = command_word(sys.argv[1:])
    if word and word[0] in ("index", "runs"):
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "rag_index.py" if word[0] == "index" else "run_results.py")
        if not os.path.exists(tool):
            sys.exit("ERROR: %s is missing; re-run the Heim installer" % tool)
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, tool] + word[1])
    if word:
        sys.argv[1:] = word[1]
    ap = argparse.ArgumentParser(description="Ask Heim a question, answered from the indexed documents.",
                                 epilog="Also: heim doctor (is Heim reading what you think it is), "
                                        "heim add FILE ... (index a file), heim chat (a conversation), "
                                        "heim runs ... (dam-breach run results: heim runs --help).")
    ap.add_argument("-c", "--collection", default="all",
                    help="read one collection only (default: all of them)")
    ap.add_argument("-k", "--top-k", type=int, default=TOP_K, help="passages handed to the model per question")
    ap.add_argument("--chat", action="store_true",
                    help="a conversation: each question is looked up first, and a dragged file is indexed")
    ap.add_argument("question", nargs="*")
    args = ap.parse_args()
    if args.chat:
        if args.question:
            ap.error("--chat takes no question on the command line: type it at the ? prompt")
        chat(args.collection, args.top_k)
        return
    q = " ".join(args.question).strip()
    if not q:
        sys.exit("no question given")
    dams = run_question(q)
    if dams:
        answer_from_runs(q, dams)
        return
    hits = retrieve(q, args.collection, args.top_k)
    print("Top %d context hits:" % len(hits))
    for s, c, p, i, _ in hits:
        print("  %.3f  [%s] %s (chunk %d)" % (s, c, p, i))
    print("-" * 70)
    prompt = build_prompt(q, hits)
    print("Answer (%s, streaming — Ctrl+C aborts):" % CHAT_MODEL)
    print("-" * 70)
    if answer(prompt) is None:
        sys.exit(0)


if __name__ == "__main__":
    main()
