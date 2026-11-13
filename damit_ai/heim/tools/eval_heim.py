#!/usr/bin/env python3
# eval_heim.py v1.1 - score Heim's code-triage answers against questions with known answers.
# The Heim counterpart of vor/eval_vor.py.
#
#   python3 eval_heim.py                        # the 'heim' persona, all questions
#   python3 eval_heim.py --model qwen3:14b      # any Ollama model (run once per model)
#   python3 eval_heim.py --only solver-choices,crest-burn
#   python3 eval_heim.py --list                 # questions + whether their source is indexed
#   python3 eval_heim.py -c all                 # search every collection, not just heim_knowledge
#   python3 eval_heim.py --no-context           # the persona alone, no retrieval: what `heim-chat` answers
#
# Each question (eval/questions.json) names the source file (regex), and the facts (regexes)
# that must be in the answer. A question passes when
#   1. grounded: at least one retrieved context hit comes from a path matching "doc", and
#   2. facts:    every "facts" regex appears in the answer, and
#   3. clean:    no "forbid" regex (if any) appears in the answer, and no "forbid_unless_negated" regex appears in a
#                sentence that does not negate it ("there is no --no-refine" is fine, "use --no-refine" is not).
# With --no-context nothing is retrieved and the question goes to the persona as it is (the `heim-chat` path), so
# step 1 is skipped: this is what the 11 Nov 2026 test asked when the 8B model reversed the sunny-day rule and invented
# tool names. v1.1 adds --no-context and forbid_unless_negated.
# Questions whose source is not indexed are skipped (reported as SKIP), so the score reflects
# only what Heim could actually have grounded. The eval uses the same retrieval + prompt as
# `heim` (rag_query.py), so it measures the real pipeline. Nothing is sent off the machine.
#
# Writes ~/local-ai/reports/eval_heim_<model>_<date>.md (and .json) with the score, time per
# question, and every answer, so two models can be compared side by side.
import os, re, sys, json, time, argparse
from datetime import datetime

NEGATION = re.compile(r"(?i)\b(no|not|never|none|nor|without|isn't|aren't|doesn't|don't|do not|does not|"
                      r"is not|are not|cannot|can't|invented|invent|hallucinat\w*|wrong|nonexistent|non-existent)\b")
SENTENCE = re.compile(r"[^.!?\n]+")


def forbidden_hits(ans, q):
    """The forbid / forbid_unless_negated regexes of question q that the answer breaks."""
    bad = [f for f in q.get("forbid", []) if re.search(f, ans, re.I)]
    for f in q.get("forbid_unless_negated", []):
        for s in SENTENCE.findall(ans or ""):
            # the forbidden name itself is cut out first: "--no-refine" must not count as its own negation
            if re.search(f, s, re.I) and not NEGATION.search(re.sub(f, " ", s, flags=re.I)):
                bad.append(f)
                break
    return bad


def score(ans, q):
    """(ok, missing facts, forbidden hits) for one answer."""
    miss = [f for f in q.get("facts", []) if not re.search(f, ans or "", re.I)]
    bad = forbidden_hits(ans or "", q)
    return (not miss and not bad), miss, bad

HERE = os.path.dirname(os.path.abspath(__file__))
# eval/ sits beside the knowledge pack (heim/eval); tools live in heim/tools. Look in both layouts.
QCANDS = [os.path.join(HERE, "eval", "questions.json"),
          os.path.join(HERE, "..", "eval", "questions.json")]
REPORTS = os.path.expanduser(os.environ.get("HEIM_REPORTS", "~/local-ai/reports"))


def main():
    ap = argparse.ArgumentParser(description="Score Heim answers against known answers.")
    ap.add_argument("--model", help="Ollama model to test (default: heim, or $HEIM_MODEL)")
    ap.add_argument("--questions")
    ap.add_argument("--only", help="comma list of question ids")
    ap.add_argument("-c", "--collection", help="override the collection to search")
    ap.add_argument("-k", "--top-k", type=int, default=10, help="passages retrieved per question")
    ap.add_argument("--list", action="store_true", help="list questions and whether their source is indexed")
    ap.add_argument("--no-context", action="store_true",
                    help="no retrieval: ask the persona the bare question, as `heim-chat` does")
    a = ap.parse_args()
    if a.model:
        os.environ["HEIM_MODEL"] = a.model          # read by rag_query at import
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "tools"))  # when run from heim/ root
    try:
        import rag_query as rq
    except ImportError:
        sys.exit("rag_query.py not found next to eval_heim.py — keep them together (heim/tools).")

    qfile = a.questions
    if not qfile:
        qfile = next((q for q in QCANDS if os.path.exists(q)), QCANDS[0])
    spec = json.load(open(qfile, encoding="utf-8"))
    coll = a.collection or spec.get("collection", "heim_knowledge")
    qs = spec["questions"]
    if a.only:
        want = set(x.strip() for x in a.only.split(","))
        qs = [q for q in qs if q["id"] in want]

    def grounded_paths(q):
        """retrieve and return the hits whose path matches q['doc']."""
        hits = rq.retrieve(q["q"], coll, a.top_k)
        pat = re.compile(q["doc"], re.I)
        return hits, [h for h in hits if pat.search(str(h[2]))]

    if a.list:
        for q in qs:
            try:
                _, g = grounded_paths(q)
                tag = "indexed" if g else "MISSING"
                where = os.path.basename(str(g[0][2])) if g else q["doc"]
            except SystemExit as e:
                tag, where = "NO-INDEX", str(e)
            print("%-28s %-9s %s" % (q["id"], tag, where))
        return

    model = rq.CHAT_MODEL
    if a.no_context:
        coll = "(none: --no-context)"
    print("Testing model %s on %d question(s), collection '%s'.\n" % (model, len(qs), coll))
    rows = []
    npass = nfail = nskip = 0
    for q in qs:
        t0 = time.time()
        if a.no_context:
            g, prompt = [], q["q"]
        else:
            try:
                hits, g = grounded_paths(q)
            except SystemExit as e:
                print("  SKIP %-24s (%s)" % (q["id"], e)); nskip += 1
                rows.append({"id": q["id"], "result": "skip", "why": str(e)}); continue
            if not g:
                print("  SKIP %-24s (source not indexed: %s)" % (q["id"], q["doc"])); nskip += 1
                rows.append({"id": q["id"], "result": "skip", "why": "source not indexed"}); continue
            ctx = "\n\n".join("--- [%s] %s (chunk %d) ---\n%s" % (c, p, i, t) for _, c, p, i, t in hits)
            prompt = ("Answer using ONLY the context below. Cite each fact with the collection "
                      "and file path shown in its bracket header. If insufficient, say so plainly.\n\n"
                      "=== CONTEXT ===\n" + ctx + "\n=== QUESTION ===\n" + q["q"])
        try:
            out = rq.post(rq.BASE + "/api/chat", rq.chat_payload(prompt, False, think=False))
            ans = (out.get("message") or {}).get("content") or ""
        except Exception as e:
            ans = "[error: %s]" % e
        dt = time.time() - t0
        ok, miss, bad = score(ans, q)
        print("  %-4s %-24s %5.1fs%s%s" % ("PASS" if ok else "FAIL", q["id"], dt,
              ("  missing: " + ", ".join(miss)) if miss else "",
              ("  forbidden: " + ", ".join(bad)) if bad else ""))
        if ok: npass += 1
        else: nfail += 1
        rows.append({"id": q["id"], "result": "pass" if ok else "fail", "seconds": round(dt, 1),
                     "missing": miss, "forbidden": bad, "answer": ans,
                     "grounded_in": [os.path.basename(str(h[2])) for h in g]})

    scored = npass + nfail
    print("\n%d/%d passed  (%d skipped, source not indexed)" % (npass, scored, nskip))
    os.makedirs(REPORTS, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model) + ("_nocontext" if a.no_context else "")
    base = os.path.join(REPORTS, "eval_heim_%s_%s" % (safe, stamp))
    json.dump({"model": model, "collection": coll, "passed": npass, "scored": scored,
               "skipped": nskip, "rows": rows}, open(base + ".json", "w"), indent=2)
    with open(base + ".md", "w") as f:
        f.write("# Heim eval - %s (%s)\n\n%d/%d passed, %d skipped.\n\n" % (model, stamp, npass, scored, nskip))
        for r in rows:
            f.write("## %s - %s\n\n" % (r["id"], r["result"].upper()))
            if r.get("missing"): f.write("- missing: `%s`\n" % "`, `".join(r["missing"]))
            if r.get("forbidden"): f.write("- forbidden hit: `%s`\n" % "`, `".join(r["forbidden"]))
            if r.get("grounded_in"): f.write("- grounded in: %s\n" % ", ".join(r["grounded_in"]))
            if r.get("answer"): f.write("\n%s\n\n" % r["answer"])
            if r.get("why"): f.write("- %s\n\n" % r["why"])
    print("report: %s.md" % base)
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
