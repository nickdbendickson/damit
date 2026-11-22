#!/usr/bin/env python3
"""ai_score.py 1.0.0 - both assistants' answer tests in one go, with a dated score history (`ai-score`).

    ai-score                      run Heim's test, then Vor's, add both to the history, show it
    ai-score --heim | --vor       one of the two
    ai-score --model qwen3:14b    test another Ollama model (passed to both tests)
    ai-score --only a,b           only these question ids (passed to both tests)
    ai-score --history            show the history without running anything
    ai-score --add REPORT.json    add a report that eval_heim.py / eval_vor.py already wrote

Before this the two tests were two commands with two report folders, and nothing kept the scores
side by side, so "did that change help?" meant digging out old reports by hand. This runs the two
tests as they are (nothing is re-implemented), reads the JSON report each one writes, and appends one
line per test to ~/local-ai/reports/score-history.jsonl. SCORE-HISTORY.md next to it is rewritten
each time: a table per assistant and model, and which questions changed between the last two runs.

The history never leaves the machine. Exit code 1 when a test could not run.
"""
import argparse
import json
import os
import re
import subprocess  # nosec B404 - runs the two eval scripts that ship beside this file
import sys
from datetime import datetime

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.expanduser(os.environ.get("HEIM_REPORTS", "~/local-ai/reports"))
HISTORY = os.path.join(REPORTS, "score-history.jsonl")
SUMMARY = os.path.join(REPORTS, "SCORE-HISTORY.md")
REPORT_LINE = re.compile(r"^Report:\s*(.+?)\.md\s*$", re.M | re.I)   # both tests end with this line


def heim_eval():
    """Path of eval_heim.py: beside this file once installed, or in tools/ in the repository."""
    p = os.path.join(HERE, "eval_heim.py")
    return p if os.path.isfile(p) else None


def vor_eval():
    """[python, eval_vor.py] for Vor's test, or None when Vor is not installed."""
    cands = []
    if os.environ.get("VOR_TOOL"):
        cands.append(os.path.dirname(os.environ["VOR_TOOL"]))
    cands += [os.path.join(os.path.expanduser("~"), "local-ai", "vor"),
              os.path.join(HERE, "..", "..", "vor")]          # the repository layout
    for d in cands:
        tool = os.path.join(d, "eval_vor.py")
        if os.path.isfile(tool):
            py = os.environ.get("VOR_PYTHON") or next(
                (p for p in (os.path.join(d, "python"), os.path.join(d, "python.exe")) if os.path.isfile(p)),
                sys.executable)
            return [py, os.path.abspath(tool)]
    return None


def run_eval(name, cmd):
    """Runs one test with its output shown as it comes; returns (exit code, report .json path or None)."""
    print("=" * 70)
    print("%s answer test" % name)
    print("=" * 70, flush=True)
    out = []
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,  # nosec B603
                              env=dict(os.environ, PYTHONUNBUFFERED="1")) as p:
            for line in p.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                out.append(line)
            code = p.wait()
    except OSError as e:
        print("  could not run: %s" % e)
        return 2, None
    m = list(REPORT_LINE.finditer("".join(out)))
    path = (m[-1].group(1) + ".json") if m else None
    return code, (path if path and os.path.isfile(path) else None)


def entry_from_report(path, assistant=None):
    """One history line from a report .json written by eval_heim.py or eval_vor.py."""
    with open(path, encoding="utf-8") as f:
        r = json.load(f)
    if "rows" in r:                                      # eval_heim.py
        assistant = assistant or "heim"
        statuses = {x["id"]: x.get("result", "?") for x in r.get("rows", [])}
        skipped = r.get("skipped", 0)
    else:                                                # eval_vor.py
        assistant = assistant or "vor"
        statuses = {x["id"]: x.get("status", "?") for x in r.get("results", [])}
        skipped = sum(1 for s in statuses.values() if s == "skip")
        statuses = {k: v for k, v in statuses.items() if v != "skip"}
    when = r.get("when") or datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
    return {"when": when, "assistant": assistant, "model": r.get("model", "?"),
            "passed": int(r.get("passed", 0)), "scored": int(r.get("scored", 0)), "skipped": int(skipped),
            "minutes": r.get("minutes"), "results": statuses, "report": os.path.abspath(path)}


def load_history(path=None):
    path = path or HISTORY
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        pass
    return rows


def append_history(entry, path=None):
    path = path or HISTORY
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def changes(prev, cur):
    """(newly passing, newly failing) question ids between two runs of the same assistant and model."""
    a, b = prev.get("results", {}), cur.get("results", {})
    up = sorted(q for q, s in b.items() if s == "pass" and a.get(q) not in (None, "pass"))
    down = sorted(q for q, s in b.items() if s != "pass" and a.get(q) == "pass")
    return up, down


def pct(e):
    return (100.0 * e["passed"] / e["scored"]) if e.get("scored") else 0.0


def summary_lines(rows):
    """The history as Markdown: a table per assistant and model, newest last, and the last change."""
    groups = {}
    for e in rows:
        groups.setdefault((e.get("assistant", "?"), e.get("model", "?")), []).append(e)
    L = ["# Answer-test score history", "",
         "Written by ai-score %s on %s. One row per test run; a question's result is pass or fail, and skipped "
         "means its source was not indexed on this machine." % (VERSION, datetime.now().strftime("%Y-%m-%d %H:%M")), ""]
    if not groups:
        return L + ["No runs yet. Run `ai-score`.", ""]
    for (who, model), es in sorted(groups.items()):
        es = sorted(es, key=lambda e: e.get("when", ""))
        L += ["## %s, model %s" % (who.capitalize(), model), "",
              "| When | Passed | Score | Change | Skipped | Minutes |", "|---|---|---|---|---|---|"]
        prev = None
        for e in es:
            ch = "" if prev is None else "%+.0f pts" % (pct(e) - pct(prev))
            L.append("| %s | %d / %d | %.0f%% | %s | %d | %s |" % (
                e.get("when", "?").replace("T", " ")[:16], e["passed"], e["scored"], pct(e), ch or "first run",
                e.get("skipped", 0), "" if e.get("minutes") is None else e["minutes"]))
            prev = e
        if len(es) > 1:
            up, down = changes(es[-2], es[-1])
            L.append("")
            L.append("Since the run before: %s; %s." % (
                ("now passing " + ", ".join(up)) if up else "nothing newly passing",
                ("now failing " + ", ".join(down)) if down else "nothing newly failing"))
        L.append("")
    return L


def write_summary(rows, path=None):
    path = path or SUMMARY
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = "\n".join(summary_lines(rows)) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai-score", description="Run Heim's and Vor's answer tests and keep the scores.")
    ap.add_argument("--heim", action="store_true", help="Heim's test only")
    ap.add_argument("--vor", action="store_true", help="Vor's test only")
    ap.add_argument("--model", help="Ollama model to test (default: each assistant's own)")
    ap.add_argument("--only", help="comma list of question ids")
    ap.add_argument("--history", action="store_true", help="show the score history and stop")
    ap.add_argument("--add", nargs="+", metavar="REPORT.json", help="add reports already written to the history")
    a = ap.parse_args(argv)

    if a.history:
        sys.stdout.write(write_summary(load_history()))
        return 0
    bad = 0
    if a.add:
        for p in a.add:
            try:
                append_history(entry_from_report(p))
                print("added %s" % p)
            except (OSError, ValueError, KeyError) as e:
                print("could not add %s: %s" % (p, e))
                bad = 1
    else:
        extra = (["--model", a.model] if a.model else []) + (["--only", a.only] if a.only else [])
        both = not (a.heim or a.vor)
        if a.heim or both:
            h = heim_eval()
            if not h:
                print("Heim's test (eval_heim.py) is not installed beside this file.")
                bad = 1
            else:
                code, rep = run_eval("Heim", [sys.executable, h] + extra)
                if rep:
                    append_history(entry_from_report(rep, "heim"))
                else:
                    print("Heim's test wrote no report (exit code %s)." % code)
                    bad = 1
        if a.vor or both:
            v = vor_eval()
            if not v:
                print("Vor is not installed (no eval_vor.py found).")
                bad = 1 if a.vor else bad
            else:
                code, rep = run_eval("Vor", v + extra)
                if rep:
                    append_history(entry_from_report(rep, "vor"))
                else:
                    print("Vor's test wrote no report (exit code %s)." % code)
                    bad = 1
    print("=" * 70)
    sys.stdout.write(write_summary(load_history()))
    print("History: %s\nSummary: %s" % (HISTORY, SUMMARY))
    return bad


if __name__ == "__main__":
    sys.exit(main())
