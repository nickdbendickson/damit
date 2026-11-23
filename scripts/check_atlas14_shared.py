#!/usr/bin/env python3
"""DamIT PMP <-> DamSafety PMP shared Atlas 14 core guard.

Five modules of DamIT PMP are the NOAA Atlas 14 core of both plugins: atlas14.py (PFDS point query), temporal.py
(Atlas 14 Volume 8 / NRCS temporal patterns), storm.py (pattern + losses), gisgrid.py (Atlas 14 GIS grids from NOAA)
and gridstats.py (grid basin statistics). DamSafety PMP (nickdbendickson/DWR_Plugins) carries the same five files in
DamSafety_PMP/noaa14/, so the two plugins read Atlas 14 the same way and give the same depths for the same dam.

The rule:

  * every pair damit_pmp/<name>.py <-> DamSafety_PMP/noaa14/<name>.py is BYTE-IDENTICAL; there are no accepted
    differences (unlike scripts/check_engine_parity.py);
  * DamIT is the origin of these files. A change is made in DamIT first and copied unchanged to DWR_Plugins, on
    branches of the same name in the two repos. Code only flows DamIT -> DWR_Plugins: nothing of DamSafety PMP goes
    into DamIT;
  * damit_pmp/SHARED_ATLAS14.json records the DWR_Plugins commit the copies were last checked at (synced_to) and the
    sha256 of each file. DWR_Plugins' copy has its own tripwire (DamSafety_PMP/noaa14/SHARED.json).

    python3 scripts/check_atlas14_shared.py --dwr /path/to/DWR_Plugins            # exit 1 when a pair differs
    python3 scripts/check_atlas14_shared.py --dwr /path/to/DWR_Plugins --update   # re-record (only when identical)
    python3 scripts/check_atlas14_shared.py --print-synced-to                     # the recorded DWR_Plugins commit

After changing a shared file: copy it to DamSafety_PMP/noaa14/ on the paired DWR_Plugins branch, commit there, then
run --update against that checkout and commit SHARED_ATLAS14.json with the change. CI
(.github/workflows/atlas14_shared.yml) checks pull requests against the recorded commit and, every day, against
DWR_Plugins main.

Exit codes: 0 identical (or recorded), 1 a pair differs or a file is missing, 2 bad path or no record.
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
RECORD = os.path.join(ROOT, "damit_pmp", "SHARED_ATLAS14.json")
SOURCE_REPO = "nickdbendickson/DWR_Plugins"
SCHEMA = "damit.atlas14_shared"
NAMES = ("atlas14", "temporal", "storm", "gisgrid", "gridstats")
MINE = "damit_pmp"
THEIRS = "DamSafety_PMP/noaa14"
DIFF_LINES = 40          # unified diff lines shown per differing pair


def pairs():
    """[(DamIT relative path, DWR_Plugins relative path)] of the five shared modules."""
    return [("{}/{}.py".format(MINE, n), "{}/{}.py".format(THEIRS, n)) for n in NAMES]


def is_dwr(path):
    return os.path.isdir(os.path.join(path, *THEIRS.split("/")))


def _bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def sha256(path):
    return hashlib.sha256(_bytes(path)).hexdigest()


def _commit(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _uncommitted(repo, rels):
    """The shared files that are modified or untracked in the DWR_Plugins checkout (not part of its HEAD)."""
    try:
        out = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=all", "--"] + list(rels),
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [ln[3:] for ln in out.splitlines() if ln.strip()]


def contains(repo, commit):
    """True when `commit` is HEAD or an ancestor of HEAD in `repo`, False when it is not (an older checkout, or a
    branch cut before it), None when git cannot tell (no git, not a checkout, the commit is not in this clone)."""
    if not commit:
        return None
    try:
        r = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", commit, "HEAD"], capture_output=True,
                           text=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(r.returncode)


def stale_hint(dwr, record=RECORD):
    """A note for a failed check when the DWR_Plugins checkout does not contain the recorded synced_to commit: its
    copies may simply predate the last sync (the difference is then in the checkout, not in DamIT). None otherwise.
    The check still fails: the note only says where to look."""
    try:
        pin = load_record(record).get("synced_to", "")
    except (OSError, ValueError):
        return None
    if contains(dwr, pin) is not False:
        return None
    return ("note: this DWR_Plugins checkout ({}) does not contain the recorded commit {} (SHARED_ATLAS14.json "
            "synced_to): it is older, or a branch cut before it, so its copies may predate the last sync. Check "
            "against {} or DWR_Plugins main before changing anything.".format(_commit(dwr)[:12] or "?", pin[:12],
                                                                              pin[:12]))


def short_diff(a, b, a_name, b_name, limit=DIFF_LINES):
    """A unified diff of two byte strings, cut to ``limit`` lines, with a note for invisible differences."""
    lines = list(difflib.unified_diff(a.decode("utf-8", "replace").splitlines(True),
                                      b.decode("utf-8", "replace").splitlines(True), a_name, b_name, n=1))
    out = [ln if ln.endswith("\n") else ln + "\n" for ln in lines[:limit]]
    if len(lines) > limit:
        out.append("... {} more diff lines\n".format(len(lines) - limit))
    if (b"\r\n" in a) != (b"\r\n" in b):
        out.append("(line endings differ: one file has CRLF, the other LF)\n")
    elif not lines:
        out.append("(the files differ in bytes that do not show as text)\n")
    return "".join(out)


def check(dwr, root=ROOT):
    """(problems, counts). problems: one text block per differing or missing pair (with a short diff)."""
    problems = []
    counts = {"identical": 0, "differ": 0, "missing": 0}
    for mine, theirs in pairs():
        p_mine, p_theirs = os.path.join(root, mine), os.path.join(dwr, theirs)
        gone = [r for r, p in ((mine, p_mine), (theirs, p_theirs)) if not os.path.isfile(p)]
        if gone:
            counts["missing"] += 1
            problems.append("MISSING {} (pair {} <-> {})".format(" and ".join(gone), mine, theirs))
            continue
        a, b = _bytes(p_mine), _bytes(p_theirs)
        if a == b:
            counts["identical"] += 1
            continue
        counts["differ"] += 1
        problems.append("DIFFERS {} <-> {}: the two copies must be byte-identical. Make the change in DamIT and "
                        "copy the file to DWR_Plugins unchanged.\n{}".format(
                            mine, theirs, short_diff(a, b, "damit/" + mine, "dwr/" + theirs).rstrip("\n")))
    return problems, counts


def load_record(path=RECORD):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def record_of(dwr, root=ROOT):
    """The record for the two checkouts as they stand (call only when check() found nothing)."""
    return {
        "schema": SCHEMA, "schema_version": 1,
        "about": "The five NOAA Atlas 14 core modules DamIT PMP shares with DamSafety PMP. Each pair must be "
                 "byte-identical; DamIT is the origin and code flows only DamIT -> DWR_Plugins. Written by "
                 "scripts/check_atlas14_shared.py --update; do not edit by hand.",
        "source": SOURCE_REPO,
        "synced_to": _commit(dwr),
        "pairs": {mine: {"dwr": theirs, "sha256": sha256(os.path.join(root, mine))} for mine, theirs in pairs()},
    }


def write_record(rec, path=RECORD):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")


def main(argv=None, root=ROOT, record=RECORD):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dwr", help="a checkout of " + SOURCE_REPO)
    ap.add_argument("--update", action="store_true",
                    help="write damit_pmp/SHARED_ATLAS14.json (only when every pair is identical)")
    ap.add_argument("--print-synced-to", action="store_true", help="print the recorded DWR_Plugins commit and exit")
    a = ap.parse_args(argv)
    if a.print_synced_to:
        try:
            print(load_record(record).get("synced_to", ""))
        except (OSError, ValueError) as e:
            print("cannot read {}: {}".format(record, e), file=sys.stderr)
            return 2
        return 0
    if not a.dwr:
        ap.error("--dwr is required")
    if not is_dwr(a.dwr):
        print("{} is not a DWR_Plugins checkout with the shared Atlas 14 core (no {}/)".format(a.dwr, THEIRS),
              file=sys.stderr)
        return 2
    head = _commit(a.dwr)
    problems, counts = check(a.dwr, root)
    print("Shared Atlas 14 core with DWR_Plugins {}: {} identical, {} differ, {} missing".format(
        head[:12] or "?", counts["identical"], counts["differ"], counts["missing"]))
    for p in problems:
        print(p)
    if problems:
        hint = stale_hint(a.dwr, record)
        if hint:
            print(hint)
        if a.update:
            print("SHARED_ATLAS14.json not written: every pair must be identical first.", file=sys.stderr)
        return 1
    if a.update:
        if not head:
            print("cannot read the HEAD commit of {} (is it a git checkout?); the record needs it".format(a.dwr),
                  file=sys.stderr)
            return 2
        rec = record_of(a.dwr, root)
        write_record(rec, record)
        print("{} recorded at DWR_Plugins {}".format(os.path.relpath(record, root), head))
        loose = _uncommitted(a.dwr, [t for _, t in pairs()])
        if loose:
            print("warning: not committed in DWR_Plugins: {}. CI checks out {} and will not find them there: commit "
                  "them in DWR_Plugins, then run --update again.".format(", ".join(loose), head[:12]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
