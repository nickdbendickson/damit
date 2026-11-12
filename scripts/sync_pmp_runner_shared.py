#!/usr/bin/env python3
"""Copy damit_runner/core/<file>.py into damit_pmp/runner_shared/ verbatim (see its README.md).

    python3 scripts/sync_pmp_runner_shared.py          # copy
    python3 scripts/sync_pmp_runner_shared.py --check  # exit 1 when a copy differs (the CI test does the same)
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("gmsh_mesher.py", "grid.py", "terrain.py", "anuga_worker.py", "omp_probe.py",
         "anuga_dtdiag.py", "wallclock.py")
SRC = os.path.join(ROOT, "damit_runner", "core")
DST = os.path.join(ROOT, "damit_pmp", "runner_shared")


def differs():
    out = []
    for f in FILES:
        with open(os.path.join(SRC, f), "rb") as a, open(os.path.join(DST, f), "rb") as b:
            if a.read() != b.read():
                out.append(f)
    return out


def main(argv):
    if "--check" in argv:
        bad = differs()
        for f in bad:
            print("differs from damit_runner/core/" + f)
        return 1 if bad else 0
    for f in FILES:
        shutil.copyfile(os.path.join(SRC, f), os.path.join(DST, f))
        print("copied", f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
