"""DamIT Runner 0.8.0: the GPU engine with LISFLOOD-FP's sub-grid channels (core/metalflood/engine_sgc,
ported byte-for-byte from DamSafety Runner 3.41.0). The word and the run-tool choice select it, it is
labelled NOT LISFLOOD-FP, sub-grid channels with the plain GPU engine are refused, and on the CPU build
it matches the float64 reference (sgc_ref) and reduces to the ACC engine without channels.

    python3 damit_runner/tests/test_gpu_sgc.py"""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import lisflood as lf  # noqa: E402
from damit_runner.core.metalflood import backends as mfb  # noqa: E402
from damit_runner.core.metalflood import engine as mfe  # noqa: E402
from damit_runner.core.metalflood import engine_sgc as sge  # noqa: E402
from damit_runner.core.metalflood import sgc_ref as sgr  # noqa: E402
from damit_runner.core.metalflood.cases import read_asc, write_asc  # noqa: E402
from damit_runner.core import builtin_lisflood as bl  # noqa: E402

XLL, YLL = 500000.0, 5200000.0


def _cpu_ok():
    return os.name != "nt" and bool(mfb.find_compiler())


def _sgc_deck(folder, z, w, bed, dx=10.0, sim=600.0, inflow=None, sgcn=0.035):
    os.makedirs(folder, exist_ok=True)
    ny, nx = z.shape
    write_asc(os.path.join(folder, "run.dem.asc"), z, XLL, YLL, dx)
    write_asc(os.path.join(folder, "run.sgcwidth.asc"), w, XLL, YLL, dx)
    write_asc(os.path.join(folder, "run.sgcbank.asc"), z, XLL, YLL, dx)
    write_asc(os.path.join(folder, "run.sgcbed.asc"), bed, XLL, YLL, dx)
    lines = ["DEMfile run.dem.asc", "resroot run", "dirroot results", "sim_time {:.1f}".format(sim),
             "initial_tstep 1.0", "massint {:.1f}".format(sim), "saveint {:.1f}".format(sim + 10),
             "fpfric 0.06", "SGCwidth run.sgcwidth.asc", "SGCbank run.sgcbank.asc",
             "SGCbed run.sgcbed.asc", "SGCn {:.4f}".format(sgcn), "physicalinflow"]
    if inflow is not None:
        (r, c), q = inflow
        gx, gy = XLL + (c + 0.5) * dx, YLL + ny * dx - (r + 0.5) * dx
        with open(os.path.join(folder, "run.bci"), "w") as f:
            f.write("P {:.3f} {:.3f} QVAR breach\n".format(gx, gy))
        with open(os.path.join(folder, "run.bdy"), "w") as f:     # the deck multiplies by dx
            f.write("sgc inflow\nbreach\n2 seconds\n{:.6f} 0\n{:.6f} 1000000000\n".format(q / dx, q / dx))
        lines += ["bdyfile run.bdy", "bcifile run.bci"]
    with open(os.path.join(folder, "run.par"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.join(folder, "run.par")


class SgcChoice(unittest.TestCase):
    def test_words_predicates_and_labels(self):
        for w in ("gpu-sgc", "SGC", " metal-sgc ", "sub-grid channels"):
            self.assertEqual(lf.resolve_exe(w), lf.GPU_SGC_EXE, w)
        e = lf.GPU_SGC_EXE
        self.assertTrue(os.path.isfile(e))
        self.assertTrue(lf.is_gpu_sgc(e) and lf.is_gpu_any(e) and lf.is_inprocess(e))
        self.assertFalse(lf.is_gpu(e))
        self.assertFalse(lf.is_gpu_sgc(lf.GPU_EXE))
        self.assertEqual(lf.resolve_exe("gpu"), lf.GPU_EXE)       # the ACC word is unchanged
        for text in (lf.engine_label(e), lf.describe_exe(e)):
            self.assertIn("NOT LISFLOOD-FP", text)
            self.assertIn("sub-grid channels", text)
        self.assertEqual(lf.engine_name(e), "Boann (sub-grid channels)")   # 0.10.0: DamSafety wording

    def test_run_tool_choice_is_appended(self):
        try:
            from damit_runner.algorithms import engine as algs
        except Exception as e:  # no QGIS here
            self.skipTest("algorithms need QGIS ({})".format(e))
        self.assertEqual(algs.FLOOD_ENGINES[:2], ("lisflood", "gpu"))   # saved indices unchanged
        self.assertEqual(algs.FLOOD_ENGINES[2], "gpu-sgc")
        # 0.10.0: the other Boann solvers and "Recommended (auto)" appended after DamIT's three
        self.assertEqual(algs.FLOOD_ENGINES[3:], ("gpu-fv", "gpu-fv2", "gpu-dg2", "gpu-subfv", "auto",
                                                  "gpu-subli"))
        self.assertEqual(len(algs.FLOOD_ENGINES_TEXT), len(algs.FLOOD_ENGINES))
        self.assertFalse(any("Apple GPU" in t for t in algs.FLOOD_ENGINES_TEXT))


@unittest.skipUnless(_cpu_ok(), "no C++ compiler for the engine's CPU build")
class SgcEngine(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="damit_sgc_")

    def tearDown(self):
        shutil.rmtree(self.d, True)

    def test_matches_the_float64_reference(self):
        ny, nx, dx = 16, 50, 10.0
        z = (50.0 - 0.02 * np.arange(nx))[None, :] * np.ones((ny, 1))
        w = np.zeros((ny, nx)); w[8, :] = 3.0
        D = np.zeros((ny, nx)); D[8, :] = 1.5
        q = 20.0                     # overbanks the ~4.7 m3/s channel: both regimes run
        p = _sgc_deck(os.path.join(self.d, "ref"), z, w, z - D, dx=dx, sim=500.0, inflow=((8, 0), q))
        deck = sge.Deck(p, build_from_dem=False)
        bk = mfb.CpuBackend(mfb.SGC_SPEC)
        eng = sge.Engine(deck, bk)
        t, T = 0.0, 500.0
        while t < T - 1e-6:
            out = eng.batch(t, T, sge.BATCH_STEPS, clip=True)
            if out["steps"] == 0:
                break
            t += out["t_local"]
        hk = eng.h2().astype(np.float64).copy()
        bk.close()
        r = sgr.SGCRef(z, w, D, 0.035, 0.06, dx)
        r.set_h(np.where(w > 0, -D, 0.0))
        src = np.zeros((ny, nx)); src[8, 0] = q
        r.run(src, T=T, dt0=1.0, cfl=bl.ALPHA)
        self.assertLess(np.abs(hk - r.h).max(), 5e-3)

    def test_reduces_to_acc_without_channels(self):
        ny, nx, dx = 20, 20, 10.0
        z = np.full((ny, nx), 30.0)
        h0 = np.zeros((ny, nx)); h0[8:12, 8:12] = 0.6
        a = os.path.join(self.d, "acc")
        os.makedirs(a)
        write_asc(os.path.join(a, "run.dem.asc"), z, XLL, YLL, dx)
        write_asc(os.path.join(a, "run.start"), h0, XLL, YLL, dx)
        with open(os.path.join(a, "run.par"), "w") as f:
            f.write("\n".join(["DEMfile run.dem.asc", "resroot run", "dirroot results",
                               "startfile run.start", "sim_time 200.0", "initial_tstep 1.0",
                               "massint 200.0", "saveint 210.0", "fpfric 0.06", "1Dfriction"]) + "\n")
        mfe.run_par(os.path.join(a, "run.par"), backend="cpu")
        ha = read_asc(os.path.join(a, "results", "run.max"))
        s = os.path.join(self.d, "sgc")
        sp = _sgc_deck(s, z, np.zeros((ny, nx)), z, dx=dx, sim=200.0)
        write_asc(os.path.join(s, "run.start"), h0, XLL, YLL, dx)
        with open(sp, "a") as f:
            f.write("startfile run.start\n")
        ss = sge.run_par(sp, backend="cpu", build_from_dem=False)
        hs = read_asc(os.path.join(s, "results", "run.max"))
        both = (ha != bl.NODATA) & (hs != bl.NODATA)
        self.assertLess(np.abs(ha[both] - hs[both]).max(), 1e-3)
        self.assertEqual(ss["channel_cells"], 0)


if __name__ == "__main__":
    unittest.main()
