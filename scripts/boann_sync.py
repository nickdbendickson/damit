#!/usr/bin/env python3
"""DamIT's one pinned copy of Boann (DamIT Runner 0.11.0; Boann extraction plan, phase 2).

Boann, the flood engine (hydro/) and terrain conditioner (grid/), lives once in DamSafety Core
(nickdbendickson/DWR_Plugins, DamSafety_Core/boann/). DamIT vendors that folder byte for byte at
damit_runner/boann/ and pins it with damit_runner/BOANN.lock: the DWR_Plugins commit, BOANN_VERSION
and the sha256 of every vendored file. Nobody edits damit_runner/boann/ by hand: an engine change is
made in DWR_Plugins, merged there, and then pulled here with this script in a sync PR.

    python3 scripts/boann_sync.py --dwr /path/to/DWR_Plugins            # copy + rewrite the lock
    python3 scripts/boann_sync.py --check                               # vendored files == lock
    python3 scripts/boann_sync.py --check --dwr /path/to/DWR_Plugins    # ... and lock == DWR there
    python3 scripts/boann_sync.py --print-ref                           # the locked DWR commit

The DWR checkout must be at the commit to pin (sync) or at the locked commit (--check --dwr; CI
checks it out by --print-ref). DWR's own DamSafety_Core/boann/FILES.json is vendored too, and
--check also requires it to agree with the lock, so the lock is DWR's manifest plus that file.
Pure stdlib, no QGIS.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_REL = "damit_runner/boann"
VENDOR = os.path.join(ROOT, *VENDOR_REL.split("/"))
LOCK = os.path.join(ROOT, "damit_runner", "BOANN.lock")
SOURCE_REPO = "nickdbendickson/DWR_Plugins"
SOURCE_REL = "DamSafety_Core/boann"
MANIFEST = "FILES.json"                               # DWR's own manifest, vendored with the rest
SKIP_DIRS = ("__pycache__", "prebuilt")               # build output, never committed (as DWR's tools/boann_files.py)
SKIP_SUFFIX = (".pyc", ".pyo", ".so", ".dll", ".dylib", ".metallib", ".air")
VERSION_RE = re.compile(r'^BOANN_VERSION\s*=\s*"([^"]+)"', re.M)
ABOUT = ("damit_runner/boann/ is a byte-for-byte copy of DWR_Plugins' DamSafety_Core/boann/ at "
         "'commit' (Boann 'boann_version'); 'files' holds the sha256 of every vendored file. Written "
         "by scripts/boann_sync.py; do not edit damit_runner/boann/ or this file by hand. DamIT's "
         "own choices (LISFLOOD-FP the default engine, Bieger 2015 the default channel curve) live in "
         "the Runner around Boann, not in it.")


def files(folder):
    """{posix path relative to folder: sha256} of every file that ships, sorted."""
    out = {}
    for d, subdirs, names in os.walk(folder):
        subdirs[:] = sorted(s for s in subdirs if s not in SKIP_DIRS and not s.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or name.endswith(SKIP_SUFFIX):
                continue
            p = os.path.join(d, name)
            with open(p, "rb") as f:
                out[os.path.relpath(p, folder).replace(os.sep, "/")] = hashlib.sha256(f.read()).hexdigest()
    return dict(sorted(out.items()))


def boann_version(folder):
    try:
        with open(os.path.join(folder, "hydro", "version.py"), encoding="utf-8") as f:
            m = VERSION_RE.search(f.read())
    except OSError:
        return ""
    return m.group(1) if m else ""


def git_head(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def load_lock(path=LOCK):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lock_text(lock):
    return json.dumps(lock, indent=1, sort_keys=True) + "\n"


def check_vendored(lock, folder=VENDOR):
    """Problems (strings) with the vendored copy against the lock; [] when it matches."""
    problems = []
    have, want = files(folder), lock.get("files") or {}
    for rel in sorted(set(have) | set(want)):
        if rel not in have:
            problems.append("{}/{} is in BOANN.lock but missing".format(VENDOR_REL, rel))
        elif rel not in want:
            problems.append("{}/{} is not in BOANN.lock (Boann is changed in DWR_Plugins, then "
                            "synced: scripts/boann_sync.py)".format(VENDOR_REL, rel))
        elif have[rel] != want[rel]:
            problems.append("{}/{} differs from BOANN.lock (edited by hand? Boann is changed in "
                            "DWR_Plugins, then synced)".format(VENDOR_REL, rel))
    v = boann_version(folder)
    if v != lock.get("boann_version"):
        problems.append("BOANN_VERSION {} != BOANN.lock's {}".format(v, lock.get("boann_version")))
    # DWR's own manifest says the same as the lock about every other file
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            man = json.load(f)
        mine = {k: h for k, h in want.items() if k != MANIFEST}
        if man.get("files") != mine:
            problems.append("{}/{} (DWR's manifest) disagrees with BOANN.lock".format(VENDOR_REL, MANIFEST))
        if man.get("boann_version") != lock.get("boann_version"):
            problems.append("{}/{} says Boann {}, BOANN.lock {}".format(
                VENDOR_REL, MANIFEST, man.get("boann_version"), lock.get("boann_version")))
    except (OSError, ValueError) as e:
        problems.append("{}/{} unreadable: {}".format(VENDOR_REL, MANIFEST, e))
    return problems


def check_upstream(lock, dwr):
    """Problems with the lock against a DWR_Plugins checkout (expected at the locked commit)."""
    src = os.path.join(dwr, *SOURCE_REL.split("/"))
    if not os.path.isdir(src):
        return ["{} has no {}".format(dwr, SOURCE_REL)]
    problems = []
    head = git_head(dwr)
    if head and head != lock.get("commit"):
        problems.append("DWR checkout is at {}, BOANN.lock pins {}".format(head, lock.get("commit")))
    theirs, want = files(src), lock.get("files") or {}
    for rel in sorted(set(theirs) | set(want)):
        if theirs.get(rel) != want.get(rel):
            problems.append("{}/{} at the pinned commit differs from BOANN.lock".format(SOURCE_REL, rel))
    return problems


def sync(dwr):
    src = os.path.join(dwr, *SOURCE_REL.split("/"))
    if not os.path.isdir(src):
        raise SystemExit("{} has no {}".format(dwr, SOURCE_REL))
    head = git_head(dwr)
    if not head:
        raise SystemExit("{} is not a git checkout: the lock needs the commit".format(dwr))
    if os.path.isdir(VENDOR):
        shutil.rmtree(VENDOR)
    want = files(src)
    for rel in want:
        dst = os.path.join(VENDOR, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(src, *rel.split("/")), dst)
    lock = {"about": ABOUT, "source_repo": SOURCE_REPO, "source_path": SOURCE_REL,
            "vendored_at": VENDOR_REL, "commit": head, "boann_version": boann_version(src),
            "files": files(VENDOR)}
    with open(LOCK, "w", encoding="utf-8", newline="\n") as f:
        f.write(lock_text(lock))
    return lock


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dwr", help="DWR_Plugins checkout (sync source, or the upstream to check)")
    ap.add_argument("--check", action="store_true", help="exit 1 when the copy or lock is off")
    ap.add_argument("--print-ref", action="store_true", help="print the locked DWR_Plugins commit")
    a = ap.parse_args(argv)
    if a.print_ref:
        print(load_lock()["commit"])
        return 0
    if a.check:
        lock = load_lock()
        problems = check_vendored(lock)
        if a.dwr:
            problems += check_upstream(lock, a.dwr)
        for p in problems:
            print("BOANN.lock: " + p)
        if not problems:
            print("Boann {} pinned to {}@{}: {} files match{}".format(
                lock["boann_version"], SOURCE_REPO, lock["commit"][:10], len(lock["files"]),
                " (and upstream)" if a.dwr else ""))
        return 1 if problems else 0
    if not a.dwr:
        ap.error("sync needs --dwr")
    lock = sync(a.dwr)
    print("vendored Boann {} from {}@{} ({} files)".format(lock["boann_version"], SOURCE_REPO,
                                                         lock["commit"][:10], len(lock["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
