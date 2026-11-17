#!/usr/bin/env python3
"""DamIT <-> DamSafety engine parity gate.

DamIT's flood engine, breach equations and Finder are ports of the DamSafety plugins
(nickdbendickson/DWR_Plugins). A fix made there has to be made here too, or the two suites give
different answers for the same dam. Twice already it was not: the 2026-11-09 partial-breach width
fix (M15) and the LISFLOOD-FP wall-clock limit (audit P2) sat in DamSafety for days while DamIT's
copy of the same files stayed as ported.

This gate compares every ported file with its DamSafety original. A pair is in one of three states:

  identical   the two files are byte-identical;
  accepted    they differ, and the difference is exactly the one recorded in
              damit_runner/PARITY.json (DamIT's own names, imports and wording);
  DRIFT       they differ in some other way: DamSafety changed and DamIT did not follow, or
              DamIT's copy was edited. The gate fails and names the file and the commits to read.

The recorded difference is a SHA-256 of the changed lines only (no line numbers), so a change made
identically on both sides leaves it untouched. After porting a DamSafety change, or after a
deliberate DamIT-only edit, re-record with --update and commit PARITY.json with the change.

    python3 scripts/check_engine_parity.py --dwr /path/to/DWR_Plugins            # exit 1 on drift
    python3 scripts/check_engine_parity.py --dwr /path/to/DWR_Plugins --update   # re-record

CI (.github/workflows/engine_parity.yml) runs it two ways: on a pull request against the DamSafety
commit PARITY.json was recorded at (so an edit to a ported file has to be acknowledged), and every
day against DamSafety's main (so a DamSafety change that was not ported shows up within a day).

Pure Python, no QGIS.
"""
import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = os.path.join(ROOT, "damit_runner", "PARITY.json")
SOURCE_REPO = "nickdbendickson/DWR_Plugins"

# (DamIT folder, DamSafety folder, recurse): every .py of the DamIT folder with a file of the same
# relative path in the DamSafety folder is a pair.
FOLDERS = (
    ("damit_runner/core", "DamSafety_Runner/core", False),
    ("damit_finder", "DamSafety_Finder", True),
)
# single files that moved or were renamed in the port
FILES = (
    ("damit_runner/flood/breach.py", "DamSafety_Runner/core/breach.py"),
    ("damit_runner/algorithms/engine.py", "DamSafety_Runner/algorithms.py"),
    ("damit_runner/compat/nodata_sample.py", "DamSafety_Core/damsuite/nodata_sample.py"),
)
# DamSafety folders whose NEW modules must be looked at: a module there that DamIT has neither
# ported nor listed under "not_ported" in PARITY.json is drift (a ported file may import it).
WATCHED = ("DamSafety_Runner/core",)


def pairs(root=ROOT, dwr=None):
    """[(damit relative path, DamSafety relative path)] for every ported file present on both sides."""
    out = []
    for mine, theirs, recurse in FOLDERS:
        base = os.path.join(root, mine)
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__") if recurse else []
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), base).replace(os.sep, "/")
                if dwr is None or os.path.isfile(os.path.join(dwr, theirs, rel)):
                    out.append(("{}/{}".format(mine, rel), "{}/{}".format(theirs, rel)))
    out += [p for p in FILES if dwr is None or os.path.isfile(os.path.join(dwr, p[1]))]
    return out


def changed_lines(a_text, b_text):
    """The lines that differ, as '-<line>' / '+<line>' in file order, without positions."""
    a, b = a_text.splitlines(), b_text.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out += ["-" + ln for ln in a[i1:i2]]
        out += ["+" + ln for ln in b[j1:j2]]
    return out


def diff_sha(a_text, b_text):
    """'' when the texts are identical, else the SHA-256 of their changed lines."""
    if a_text == b_text:
        return ""
    return hashlib.sha256("\n".join(changed_lines(a_text, b_text)).encode("utf-8")).hexdigest()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _commit(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def unported(dwr, root=ROOT):
    """DamSafety modules of the watched folders that DamIT does not have."""
    out = []
    mapping = {theirs: mine for mine, theirs, _ in FOLDERS}
    for theirs in WATCHED:
        mine = mapping[theirs]
        for f in sorted(os.listdir(os.path.join(dwr, theirs))):
            if f.endswith(".py") and not os.path.isfile(os.path.join(root, mine, f)):
                out.append("{}/{}".format(theirs, f))
    return out


def measure(dwr, root=ROOT):
    """{damit path: {'from': DamSafety path, 'diff': sha or ''}} as the two checkouts stand."""
    out = {}
    for mine, theirs in pairs(root, dwr):
        out[mine] = {"from": theirs, "diff": diff_sha(_read(os.path.join(dwr, theirs)),
                                                      _read(os.path.join(root, mine)))}
    return out


def load_record(path=RECORD):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(dwr, record, root=ROOT):
    """(problems, counts). problems: one line per drifted pair or unlisted DamSafety module."""
    now = measure(dwr, root)
    rec = record.get("pairs") or {}
    problems = []
    counts = {"identical": 0, "accepted": 0, "drift": 0}
    since = record.get("synced_to") or "the recorded commit"
    for mine, cur in sorted(now.items()):
        want = rec.get(mine)
        if want is None:
            counts["drift"] += 1
            problems.append("{}: not in PARITY.json (a new ported file; record it with --update)".format(mine))
        elif cur["diff"] == want.get("diff", ""):
            counts["identical" if not cur["diff"] else "accepted"] += 1
        else:
            counts["drift"] += 1
            problems.append(
                "{mine}: differs from {theirs} in a way that is not recorded. If DamSafety changed, port it: "
                "`git -C <DWR_Plugins> diff {since}..HEAD -- {theirs}`. If DamIT's copy was edited on purpose, "
                "re-record with --update.".format(mine=mine, theirs=cur["from"], since=since[:12]))
    for mine in sorted(set(rec) - set(now)):
        counts["drift"] += 1
        problems.append("{}: recorded in PARITY.json but the file, or its DamSafety original {}, is gone".format(
            mine, rec[mine].get("from")))
    listed = set(record.get("not_ported") or [])
    for mod in unported(dwr, root):
        if mod not in listed:
            counts["drift"] += 1
            problems.append("{}: a DamSafety module DamIT has not ported. Port it, or list it under 'not_ported' "
                            "in PARITY.json if DamIT does not need it.".format(mod))
    return problems, counts


def update(dwr, root=ROOT, path=RECORD, keep_not_ported=None):
    """Re-record PARITY.json from the two checkouts as they stand."""
    try:
        old = load_record(path)
    except (OSError, ValueError):
        old = {}
    not_ported = sorted(set(unported(dwr, root)) if keep_not_ported is None else set(keep_not_ported))
    rec = {
        "schema": "damit.engine_parity", "schema_version": 1,
        "about": "Recorded differences between DamIT's ported files and their DamSafety originals. Written by "
                 "scripts/check_engine_parity.py --update; do not edit the hashes by hand.",
        "source": SOURCE_REPO,
        "synced_to": _commit(dwr) or old.get("synced_to", ""),
        "not_ported": not_ported,
        "pairs": measure(dwr, root),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dwr", required=True, help="a checkout of " + SOURCE_REPO)
    ap.add_argument("--update", action="store_true", help="re-record PARITY.json instead of checking")
    ap.add_argument("--print-synced-to", action="store_true", help="print the recorded DamSafety commit and exit")
    a = ap.parse_args(argv)
    if a.print_synced_to:
        print(load_record().get("synced_to", ""))
        return 0
    if not os.path.isdir(os.path.join(a.dwr, "DamSafety_Runner", "core")):
        print("{} is not a DWR_Plugins checkout (no DamSafety_Runner/core)".format(a.dwr), file=sys.stderr)
        return 2
    if a.update:
        rec = update(a.dwr)
        same = sum(1 for p in rec["pairs"].values() if not p["diff"])
        print("PARITY.json recorded at DamSafety {}: {} pairs ({} identical, {} with an accepted difference), "
              "{} DamSafety modules not ported".format(rec["synced_to"][:12] or "?", len(rec["pairs"]), same,
                                                       len(rec["pairs"]) - same, len(rec["not_ported"])))
        return 0
    problems, counts = check(a.dwr, load_record())
    print("Engine parity with DamSafety {}: {} identical, {} accepted differences, {} drifted".format(
        (_commit(a.dwr) or "?")[:12], counts["identical"], counts["accepted"], counts["drift"]))
    for p in problems:
        print("DRIFT " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
