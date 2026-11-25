"""Engine version pins (audit follow-up 2026-11-19): the engines' minimum versions are
declared in damit_runner.core.engines.ENGINES and every declared engine is detectable,
enforceable, and (when its env var points at a real binary) actually probed.

Offline legs run everywhere. Live legs run only when DAMIT_LISFLOOD / DAMIT_ANUGA_PYTHON
are set (the same opt-in convention as the pmp real-solver tests)."""
import os
import unittest

from damit_runner.core import engines


class Registry(unittest.TestCase):
    def test_every_engine_entry_is_well_formed(self):
        for name, spec in engines.ENGINES.items():
            self.assertIsInstance(spec["min"], (str, type(None)), name)
            self.assertIn(spec["probe"], ("banner", "python", "none"), name)
            self.assertTrue(spec["banner_re"], name)
            if spec["probe"] == "banner":
                self.assertTrue(spec.get("probe_argv"), name + " needs probe_argv")

    def test_hecras_and_optional_gmsh_are_never_auto_enforced(self):
        # no automatic probe -> probe_and_require must refuse rather than guess
        for eng in ("hec_ras",):
            with self.assertRaises(engines.EngineVersionError):
                engines.probe_and_require(eng)


class BannerParsing(unittest.TestCase):
    LISFLOOD_BANNERS = [
        "LISFLOOD-FP 8.0.3",                        # current-ish build
        "lisflood-fp v8.1",                         # lowercase, v-prefix
        "LISFLOOD FP 8.0 build 2023-05-01",         # spaces around FP, trailing build
    ]
    OLD_LISFLOOD = "LISFLOOD-FP 5.9.2"

    def test_lisflood_banner_variants_parse(self):
        for banner in self.LISFLOOD_BANNERS:
            ver = engines.parse_banner(banner, "lisflood_fp")
            self.assertIsNotNone(ver, banner)
            self.assertTrue(ver.startswith("8."), banner)

    def test_old_lisflood_is_refused(self):
        ver = engines.parse_banner(self.OLD_LISFLOOD, "lisflood_fp")
        with self.assertRaises(engines.EngineVersionError):
            engines.require_minimum("lisflood_fp", ver)

    def test_empty_probe_raises(self):
        with self.assertRaises(engines.EngineVersionError):
            engines.parse_banner("", "lisflood_fp")
        with self.assertRaises(engines.EngineVersionError):
            engines.parse_banner("   \n", "lisflood_fp")

    def test_unrecognized_banner_returns_none_not_crash(self):
        self.assertIsNone(engines.parse_banner("segmentation fault (core dumped)", "lisflood_fp"))

    def test_anuga_style_one_liner_parses(self):
        self.assertEqual(engines.parse_banner("3.6.0", "anuga"), "3.6.0")

    def test_rc_suffix_stops_cleanly(self):
        # '8.0rc1' -> the numeric tuple is (8, 0); never a crash on suffixes
        self.assertEqual(engines.require_minimum("lisflood_fp", "8.0rc1"), "8.0rc1")


class MinimumLogic(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(engines.require_minimum("lisflood_fp", "8.0"), "8.0")
        self.assertEqual(engines.require_minimum("lisflood_fp", "8.0.1"), "8.0.1")
        self.assertEqual(engines.require_minimum("lisflood_fp", "12.0"), "12.0")
        with self.assertRaises(engines.EngineVersionError):
            engines.require_minimum("lisflood_fp", "7.9.9")
        self.assertEqual(engines.require_minimum("lisflood_fp", "8"), "8")  # 8 is 8.0, not below it

    def test_none_min_never_enforces(self):
        self.assertEqual(engines.require_minimum("gmsh", "0.1"), "0.1")

    def test_unknown_engine_raises_keyerror(self):
        with self.assertRaises(KeyError):
            engines.require_minimum("swmm", "1.0")


class LaunchersAreCovered(unittest.TestCase):
    """The contract: a launcher that spawns an engine without a version check must be
    recorded here with a reason. New engines appear in ENGINES and gain a check; this
    test greps the production launchers so the contract is mechanical, not aspirational."""

    # launchers WITHOUT an inline pin check, each with the reason it is exempt
    EXEMPT = {
        "damit_runner/core/hecras_engine.py":
            "HEC-RAS controller API only on Windows; ENGINES['hec_ras'].probe == 'none' "
            "(documented, live check pending a Windows controller probe)",
        "damit_runner/core/builtin_lisflood.py":
            "in-process numpy screening approximation, not the LISFLOOD-FP executable",
        "damit_pmp/runner_shared/lisflood.py":
            "sha-pinned byte-copy of damit_runner/core/lisflood.py (RUNNER_FILES); "
            "inherits the runner's check",
        "damit_runner/core/data_conventions.py":
            "spawns 'conda env list' for engine discovery, not an engine run; the found "
            "interpreters are then version-checked (check_anuga, engines probes)",
        "damit_pmp/runner_shared/data_conventions.py":
            "sha-pinned twin of the runner's data_conventions; conda env discovery only",
        "damit_runner/core/report_docx.py":
            "spawns document tooling (pandoc/ffmpeg) for report rendering, not a solver",
        "damit_runner/core/solve_gate.py":
            "the LISFLOOD 1-second sanity grid (its own launch check, timeout=60) and "
            "gdalinfo -json; the real run's version pin lives in core/lisflood.py",
        "damit_pmp/launch.py":
            "probes the ANUGA interpreter for installed modules (introspection that "
            "complements engines.ENGINES; the pin is enforced in check_anuga)",
        "damit_runner/core/hecras_windows.py":
            "Windows process-tree management for the HEC-RAS controller (taskkill etc.); "
            "the version question is ENGINES['hec_ras'] with probe 'none'",
        "damit_runner/core/engines.py":
            "the pin infrastructure itself (this module); subprocess only for the opt-in "
            "live probes that call probe_and_require",
        "damit_pmp/runner_shared/engines.py":
            "sha-pinned twin of the runner's engines.py; the pin infrastructure itself",
        "damit_runner/boann/hydro/backends.py":
            "compiles this engine's own CPU kernels with the system C++ compiler; "
            "not a pinned external solver",
        "damit_runner/boann/hydro/bench.py":
            "local speed-test CLI, not a production launcher; a real LISFLOOD-FP run "
            "is pinned in core/lisflood.check_log_version",
        "damit_runner/core/anuga_detach.py":
            "detached ANUGA worker launcher; the ANUGA version pin is enforced upstream "
            "in check_anuga (anuga_model.py) before any worker starts",
        "damit_runner/core/batch_workers.py":
            "spawns ffmpeg for the animation frames of a finished run, not a solver",
        "damit_runner/core/hecras_seeds.py":
            "spawns python seeds for HEC-RAS plan prep on Windows; controller-side, "
            "covered by the ENGINES['hec_ras'] 'none'-probe exemption",
        "damit_runner/core/animation.py":
            "spawns ffmpeg for movie export of finished results, not a solver",
        "damit_runner/core/wallclock.py":
            "the timeout infrastructure itself; spawns nothing of its own accord",
        "damit_pmp/runner_shared/wallclock.py":
            "sha-pinned twin of the runner's wallclock; the timeout infrastructure",
    }

    LAUNCH_GREP = ("subprocess.Popen", "subprocess.run")

    def test_engine_launchers_declare_a_pin_or_an_exemption(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        checked = []        # launchers that reference engines.ENGINES (a pin present)
        missing = []
        for sub in ("damit_runner/core", "damit_pmp"):
            for base, dirs, files in os.walk(os.path.join(root, sub)):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    p = os.path.join(base, f)
                    rel = os.path.relpath(p, root)
                    src = open(p, encoding="utf-8", errors="replace").read()
                    spawns = any(g in src for g in self.LAUNCH_GREP)
                    if not spawns:
                        continue
                    if "engines.require_minimum" in src or "engines.probe_and_require" in src \
                            or "from .engines import" in src or "from .core.engines import" in src:
                        checked.append(rel)
                    elif rel in self.EXEMPT:
                        checked.append(rel + " (exempt: " + self.EXEMPT[rel][:40] + "...)")
                    else:
                        missing.append(rel)
        self.assertEqual(missing, [],
                         "engine-spawning files without a pin or an exemption:\n  " +
                         "\n  ".join(missing) +
                         "\nadd engines.probe_and_require(...) at launch, or record an "
                         "EXEMPT entry with a reason")


class LiveProbes(unittest.TestCase):
    """Opt-in: run only when the engine env vars point at real binaries."""

    def test_live_lisflood(self):
        exe = os.environ.get("DAMIT_LISFLOOD", "")
        if not (exe and os.path.isfile(exe)):
            self.skipTest("set DAMIT_LISFLOOD to a LISFLOOD-FP executable to probe it")
        ver = engines.probe_and_require("lisflood_fp", exe=exe)
        print("LISFLOOD-FP probe: {}".format(ver))

    def test_live_anuga(self):
        py = os.environ.get("DAMIT_ANUGA_PYTHON", "")
        if not (py and os.path.isfile(py)):
            self.skipTest("set DAMIT_ANUGA_PYTHON to an ANUGA conda env python to probe it")
        ver = engines.probe_and_require("anuga", python=py)
        print("ANUGA probe: {}".format(ver))


class Report(unittest.TestCase):
    def test_report_lists_every_engine(self):
        r = engines.report()
        for name in engines.ENGINES:
            self.assertIn(name, r)


if __name__ == "__main__":
    unittest.main()
