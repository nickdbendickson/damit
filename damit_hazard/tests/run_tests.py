#!/usr/bin/env python3
"""Run every damit_hazard test without pytest (pytest also works on this folder).

    python3 damit_hazard/tests/run_tests.py           # QGIS-free tests; QGIS ones skip
    QT_QPA_PLATFORM=offscreen <QGIS python> damit_hazard/tests/run_tests.py   # all
Exit status 1 on any failure.
"""
import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class Skip(Exception):
    pass


def main():
    names = sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    if len(sys.argv) > 1:
        names = [n for n in names if any(a in n for a in sys.argv[1:])]
    n_ok = n_fail = n_skip = 0
    for name in names:
        try:
            mod = importlib.import_module(name)
        except Exception as e:
            if type(e).__name__ in ("Skipped", "Skip") or "skip" in type(e).__name__.lower():
                print("SKIP {} ({})".format(name, e))
                n_skip += 1
                continue
            print("FAIL import {}".format(name))
            traceback.print_exc()
            n_fail += 1
            continue
        for attr in sorted(a for a in dir(mod) if a.startswith("test_")):
            fn = getattr(mod, attr)
            if not callable(fn):
                continue
            try:
                fn()
                print("ok   {}.{}".format(name, attr))
                n_ok += 1
            except Exception as e:
                if "skip" in type(e).__name__.lower():
                    print("SKIP {}.{} ({})".format(name, attr, e))
                    n_skip += 1
                    continue
                print("FAIL {}.{}".format(name, attr))
                traceback.print_exc()
                n_fail += 1
    print("\n{} passed, {} failed, {} skipped".format(n_ok, n_fail, n_skip))
    sys.stdout.flush()
    return 1 if n_fail else 0


if __name__ == "__main__":
    os._exit(main())
