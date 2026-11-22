#!/usr/bin/env python3
"""ai_doctor.py 1.0.0 - both local assistants' checks in one go (the `ai-doctor` command).

    ai-doctor              Heim's doctor, then Vor's, then one summary line for each
    ai-doctor --library    without Ollama (the indexes and folders only)

Before this there were two doctors with two command shapes (`heim-doctor`, `vor doctor`) and two
places to look. This runs both as they are (nothing is re-implemented, so the two cannot drift
from it), shows their output, and ends with a line per assistant: OK, WATCH (something to look
at) or PROBLEM (it answers from less than you think). Exit code 1 when either has a PROBLEM.
An assistant that is not installed is said to be so, not counted as a problem.
"""
import argparse
import os
import re
import subprocess  # nosec B404 - runs the two doctors that ship beside this file
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def vor_command():
    """[python, vor.py] for Vor, or None when Vor is not installed."""
    tool = os.environ.get("VOR_TOOL") or os.path.join(os.path.expanduser("~"), "local-ai", "vor", "vor.py")
    if not os.path.isfile(tool):
        return None
    d = os.path.dirname(tool)
    py = os.environ.get("VOR_PYTHON") or next(
        (p for p in (os.path.join(d, "python"), os.path.join(d, "python.exe")) if os.path.isfile(p)), sys.executable)
    return [py, tool]


def run(name, cmd):
    """(exit code, output) of one doctor, its output echoed as it is."""
    print("=" * 70)
    print(name)
    print("=" * 70, flush=True)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # nosec B603 - fixed local tools
    except (OSError, subprocess.TimeoutExpired) as e:
        print("  could not run: %s" % e)
        return 2, ""
    out = (p.stdout or "") + (p.stderr or "")
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return p.returncode, out


def verdict(code, out):
    """OK / WATCH / PROBLEM from a doctor's exit code and its lines."""
    if code not in (0, None) or re.search(r"\bPROBLEM", out):
        return "PROBLEM"
    if re.search(r"\bWATCH\b|MISSING|NOT reachable", out):
        return "WATCH"
    return "OK"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai-doctor", description="Check Heim and Vor in one go.")
    ap.add_argument("--library", action="store_true", help="indexes and folders only: no Ollama needed")
    a = ap.parse_args(argv)
    lines, worst = [], 0
    heim = os.path.join(HERE, "rag_index.py")
    if os.path.isfile(heim):
        code, out = run("Heim", [sys.executable, heim, "--doctor"] + (["--library"] if a.library else []))
        v = verdict(code, out)
    else:
        v = "not installed"
    lines.append(("Heim", v))
    vc = vor_command()
    if vc:
        code, out = run("Vor", vc + ["doctor"] + (["--library"] if a.library else []))
        v = verdict(code, out)
    else:
        v = "not installed"
    lines.append(("Vor", v))
    print("=" * 70)
    for name, v in lines:
        print("  %-5s %s" % (name, {"OK": "OK", "WATCH": "WATCH: something to look at, above",
                                     "PROBLEM": "PROBLEM: it answers from less than you think; the fix is above"}.get(v, v)))
        worst = max(worst, {"PROBLEM": 2, "WATCH": 1}.get(v, 0))
    return 1 if worst == 2 else 0


if __name__ == "__main__":
    sys.exit(main())
