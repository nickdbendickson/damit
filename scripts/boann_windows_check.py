#!/usr/bin/env python3
"""Run Boann end to end from an unpacked DamIT Runner zip, the way a computer with no C++ compiler
gets it (a Windows PC): every engine from the libraries the zip ships under
damit_runner/boann/hydro/prebuilt/<platform>/, nothing compiled.

    python scripts/boann_windows_check.py PLUGINS_DIR

PLUGINS_DIR holds the unpacked damit_runner/ (unzip damit_runner-*.zip there). The check
  1. takes every C++ compiler off PATH and points the build cache at an empty folder, so a library
     can only come from the zip;
  2. asks the Runner what "Recommended (auto)" would run with no LISFLOOD-FP and no Apple GPU
     (core.lisflood.choose_auto) and wants Boann on the CPU;
  3. runs a short valley deck through Boann's own command line (python -I boann.py run DECK.par,
     ACC and FV1) and checks the result grids and the water balance;
  4. runs every engine's library once (ACC, FV1, FV2, DG2, SGC, sub-grid FV, sub-grid local
     inertial) and BoannGrid's fill, each loaded from prebuilt/.
Used by .github/workflows/boann_windows.yml on windows-latest, which damit's release and
damit-desk's CI both run. Needs numpy only. Exit 0 when all pass."""
import os
import shutil
import subprocess
import sys
import tempfile

COMPILERS = ("c++", "g++", "clang++", "cl", "x86_64-w64-mingw32-g++")


def _strip_compilers():
    """PATH without any folder that holds a C++ compiler; CXX unset."""
    keep = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        if any(shutil.which(c, path=d) for c in COMPILERS):
            print("  PATH without {}".format(d))
            continue
        keep.append(d)
    os.environ["PATH"] = os.pathsep.join(keep)
    os.environ.pop("CXX", None)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    plugins = os.path.abspath(argv[0])
    hydro_dir = os.path.join(plugins, "damit_runner", "boann", "hydro")
    if not os.path.isfile(os.path.join(hydro_dir, "boann.py")):
        raise SystemExit("no damit_runner/boann/hydro/boann.py in " + plugins)

    print("1. no compiler, empty build cache")
    _strip_compilers()
    cache = tempfile.mkdtemp(prefix="boann_cache_")
    os.environ["DAMSAFETY_MF_CACHE"] = cache
    sys.path.insert(0, plugins)
    from damit_runner.boann.hydro import backends as be
    from damit_runner.boann.hydro import engine as mfe, engine_fv as fve, engine_fv2 as fv2e
    from damit_runner.boann.hydro import engine_dg2 as dg2e, engine_sgc as sgce
    from damit_runner.boann.hydro import engine_subfv as sfve, subfv_backend as sfb
    from damit_runner.boann.hydro import engine_subli as slie, subli_backend as slb
    from damit_runner.boann.hydro.cases import valley_deck
    from damit_runner.boann.hydro.version import BOANN_VERSION
    from damit_runner.boann.grid import cases as mt_cases, fill as mt_fill
    assert be.find_compiler() is None, "a compiler is still reachable: " + str(be.find_compiler())
    assert os.path.abspath(be.HERE) == hydro_dir, "imported Boann from " + be.HERE
    dest = os.path.join(be.PREBUILT_DIR, be.platform_tag())
    if not os.path.isdir(dest):
        raise SystemExit("the zip ships no prebuilt/{} folder".format(be.platform_tag()))
    print("  Boann {} on {}, {} libraries in prebuilt/{}".format(
        BOANN_VERSION, be.platform_tag(), len(os.listdir(dest)), be.platform_tag()))

    ok, why = be.metal_available()
    assert not ok, "this check is for a computer with no Metal GPU"
    print("2. the Runner's engine choice")
    from damit_runner.core import lisflood as lf
    exe, line = lf.choose_auto("", cell_m=10.0)
    print("  " + line)
    assert exe == lf.GPU_EXE and "Boann ACC on the CPU" in line, (exe, line)
    print("  " + lf.gpu_backend_note())

    tmp = tempfile.mkdtemp(prefix="boann_e2e_")
    bad = 0
    try:
        print("3. boann.py run DECK.par from the zip (python -I, nothing else on sys.path)")
        for solver in ("acc", "fv"):
            d = os.path.join(tmp, "cli_" + solver)
            par = valley_deck(d, ny=40, nx=60, sim_s=900.0, hole=False, pond=False, gauge=False,
                              free="E")
            r = subprocess.run([sys.executable, "-I", os.path.join(hydro_dir, "boann.py"), "run",
                                par, "--solver", solver, "--backend", "cpu"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, cwd=d)
            out = r.stdout.strip().splitlines()
            try:
                assert r.returncode == 0, "exit {}".format(r.returncode)
                res = os.path.join(d, "results")
                for ext in ("max", "mxe"):
                    p = os.path.join(res, "run." + ext)
                    assert os.path.isfile(p) and os.path.getsize(p) > 0, "no run." + ext
                print("ok   {:6s} {}".format(solver, out[-1] if out else ""))
            except AssertionError as e:
                bad += 1
                print("FAIL {:6s} {}\n{}".format(solver, e, "\n".join(out[-30:])))

        print("4. every engine's library from prebuilt/")
        engines = (("acc", mfe.run_par, be.FLOOD_SPEC), ("fv", fve.run_par, be.FV_SPEC),
                   ("fv2", fv2e.run_par, be.FV2_SPEC), ("dg2", dg2e.run_par, be.DG2_SPEC),
                   ("sgc", sgce.run_par, be.SGC_SPEC), ("subfv", sfve.run_par, sfb.SUBFV_SPEC),
                   ("subli", slie.run_par, slb.SUBLI_SPEC))
        for name, run, spec in engines:
            try:
                bk = be.CpuBackend(spec)
                assert os.path.dirname(os.path.abspath(bk.path)) == os.path.abspath(dest), bk.path
                device = bk.device
                bk.close()
                p = valley_deck(os.path.join(tmp, name), ny=40, nx=60, sim_s=900.0, hole=False,
                                pond=False, gauge=False, free="E")
                st = run(p, backend="cpu")
                err = abs(st["mass_error_m3"]) / max(st["injected_m3"], 1.0)
                assert err < 1e-3, "mass error {:.2e}".format(err)
                print("ok   {:6s} {}  ({} steps, mass error {:.1e})".format(
                    name, device, st["steps"], err))
            except Exception as e:                          # report every engine, then fail
                bad += 1
                print("FAIL {:6s} {}: {}".format(name, type(e).__name__, e))
        try:
            import numpy as np
            mt_fill._PF_LIB = None
            lib = mt_fill._pf_library()
            assert os.path.dirname(os.path.abspath(lib._name)) == os.path.abspath(dest), lib._name
            z = mt_cases.pitted_plane(ny=40, nx=60)
            f, info = mt_fill.fill_dem(z, method="priority-flood", conn=8)
            assert info["backend"] == "cpu" and info["unreached"] == 0, info
            assert bool(np.all(f[np.isfinite(z)] >= z[np.isfinite(z)] - 1e-6))
            print("ok   fill   BoannGrid priority-flood from prebuilt/")
        except Exception as e:
            bad += 1
            print("FAIL fill   BoannGrid {}: {}".format(type(e).__name__, e))
        built = [n for n in os.listdir(cache) if not n.startswith(".")]
        if built:
            bad += 1
            print("FAIL something was compiled into the cache: {}".format(built))
    finally:
        shutil.rmtree(tmp, True)
        shutil.rmtree(cache, True)
    if bad:
        raise SystemExit("{} Boann check(s) failed".format(bad))
    print("\nBoann runs from the DamIT Runner zip with no compiler.")


if __name__ == "__main__":
    main()
