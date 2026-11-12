"""Packaging checks for DamIT Core, Setup, Data, Hazard Lite, PMP and Finder (no QGIS needed)."""
import configparser
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# folder: (display name, hasProcessingProvider, plugin_dependencies, provider id)
PLUGINS = {"damit_core": ("DamIT Core", "no", None, None),
           "damit_setup": ("DamIT Setup", "no", "DamIT Core,DamIT Catalog", None),
           "damit_data": ("DamIT Data", "yes", "DamIT Core", "damit_data"),
           "damit_hazardlite": ("DamIT Hazard Lite", "yes", "DamIT Core,DamIT Catalog", "damit_lite"),
           "damit_pmp": ("DamIT PMP", "yes", "DamIT Core", "damit_pmp"),
           "damit_finder": ("DamIT Finder", "yes", None, "damit_find")}
FORBIDDEN_LAUNCH = re.compile(r"\b(subprocess|Popen|os\.system|os\.exec\w*|QProcess|startDetached)\b")
# DamIT PMP 0.3.0 / 0.4.0 write rain-on-grid FILES for LISFLOOD-FP and ANUGA (damit_pmp:raingrid) and sets up an ANUGA
# rain-on-grid job (damit_pmp:anugarain), so these files name the solvers in help text and file-format notes. They
# still may not import a solver (SOLVER_IMPORT): in QGIS the plugin only writes input files.
SOLVER_NAMES_OK = {os.path.join("damit_pmp", "rainexport.py"), os.path.join("damit_pmp", "algorithms", "pf_algs.py"),
                   os.path.join("damit_pmp", "anugarain.py"), os.path.join("damit_pmp", "launch.py"),
                   os.path.join("damit_pmp", "algorithms", "anuga_algs.py"), os.path.join("damit_pmp", "provider.py"),
                   # 0.4.0: the LISFLOOD-FP rain-on-grid job (damit_pmp:lisfloodrain), counterpart of anugarain
                   os.path.join("damit_pmp", "lisfloodrain.py"), os.path.join("damit_pmp", "algorithms", "lisflood_algs.py")}
SOLVER_IMPORT = re.compile(r"^\s*(import|from)\s+(anuga|lisflood)\b", re.M | re.I)
# The two documented exceptions in damit_pmp (0.3.0, anugarain), narrow on purpose:
#  1. SHARED_DIR: verbatim copies of damit_runner/core files (gmsh mesher, ANUGA worker helpers, launcher). They run
#     only in the ANUGA Python (or, grid.py / terrain.py / gmsh_mesher.py / wallclock.py, as plain helpers), are pinned
#     byte for byte to the runner by damit_pmp/tests/test_runner_shared_sync.py, and so are not edited here.
#  2. LAUNCH_OK: damit_pmp/launch.py, the only PMP module that starts a process (the optional gmsh mesh build, the
#     optional ANUGA run and, 0.4.0, the optional LISFLOOD-FP run). test_launch_is_opt_in checks who may import it
#     (anuga_algs.py and lisflood_algs.py) and that both run switches are off by default.
#     0.4.0 also adds lisflood.py, units.py, data_conventions.py and terrain3dep.py to SHARED_DIR (same rule).
SHARED_DIR = os.path.join("damit_pmp", "runner_shared")
LAUNCH_OK = {os.path.join("damit_pmp", "launch.py")}
TEMPLATE = os.path.join("damit_pmp", "templates", "run_anuga_rain.py")     # runs only in the ANUGA Python
LEGACY_QT_OK = {os.path.join("damit_core", "lib", "qtcompat.py")}      # the one QGIS < 3.38 field-type fallback


def meta(folder):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(ROOT, folder, "metadata.txt"), encoding="utf-8")
    return cp["general"]


def py_files(folder):
    for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def code_of(path):
    with open(path, encoding="utf-8") as fh:
        return "\n".join(ln.split("#")[0] for ln in fh.read().splitlines())


def _finder_version():
    with open(os.path.join(ROOT, "damit_finder", "finder.py"), encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("VERSION = "):
                return ln.split("=", 1)[1].strip().strip('"')


FINDER_VERSION = _finder_version()
PMP_VERSION = "0.4.1"           # DamIT PMP 0.4.0: watershed, temporal patterns, losses, lisfloodrain (the others are 0.2.0)


class Metadata(unittest.TestCase):
    def test_metadata(self):
        for folder, (name, provider, dep, _) in PLUGINS.items():
            m = meta(folder)
            self.assertEqual(m["name"], name)
            # the Finder engine is shared with DamSafety Finder and versioned with it (its
            # run_info records finder.VERSION); the rest are versioned with the DamIT suite
            self.assertEqual(m["version"], {"damit_finder": FINDER_VERSION, "damit_pmp": PMP_VERSION}.get(folder, "0.2.0"))
            self.assertEqual(m["qgisMinimumVersion"], "3.28")
            self.assertEqual(m["qgisMaximumVersion"], "4.99")
            self.assertEqual(m["supportsQt6"], "True")
            self.assertEqual(m["author"], "N.D. Bendickson")
            self.assertEqual(m["repository"], "https://github.com/nickdbendickson/damit")
            self.assertEqual(m["hasProcessingProvider"], provider, folder)
            self.assertEqual(m.get("plugin_dependencies"), dep, folder)
            for f in ("__init__.py", "plugin.py", "icon.svg", "README.md"):
                self.assertTrue(os.path.exists(os.path.join(ROOT, folder, f)), (folder, f))

    def test_no_damsafety_dependency(self):
        for folder in PLUGINS:
            self.assertNotIn("DamSafety", meta(folder).get("plugin_dependencies", ""), folder)
            for p in py_files(folder):
                self.assertNotRegex(code_of(p), r"\b(DamSafety_\w+|nd_dam_screening|nd_breach_runner)\b", p)

    def test_provider_ids(self):
        ids = {}
        for folder, (_, _, _, pid) in PLUGINS.items():
            if pid:
                with open(os.path.join(ROOT, folder, "provider.py"), encoding="utf-8") as fh:
                    self.assertIn('PROVIDER_ID = "{}"'.format(pid), fh.read())
                ids[pid] = folder
        self.assertFalse(set(ids) & {"damit", "damit_screen", "damit_run", "nddam", "ndbreach"})

    def test_qt6_safe_imports(self):
        for folder in PLUGINS:
            for p in py_files(folder):
                src = code_of(p)
                self.assertNotRegex(src, r"\bfrom PyQt[56]\b|\bimport PyQt[56]\b", p)
                if os.path.relpath(p, ROOT) not in LEGACY_QT_OK:
                    self.assertNotIn("QVariant", src, p)

    def test_no_process_launch_and_no_foreign_algorithms(self):
        for folder in PLUGINS:
            for p in py_files(folder):
                code = code_of(p)
                rel = os.path.relpath(p, ROOT)
                if rel.startswith(SHARED_DIR + os.sep):
                    continue                              # the runner's own files, pinned by the sync test
                if rel not in LAUNCH_OK:
                    self.assertIsNone(FORBIDDEN_LAUNCH.search(code), p)
                self.assertNotRegex(code, r"['\"](ndbreach|nddam):\w", p)
                if rel == TEMPLATE:
                    self.assertNotRegex(code.lower(), r"hec-?ras|\bwine\b", p)
                elif rel in SOLVER_NAMES_OK:
                    self.assertIsNone(SOLVER_IMPORT.search(code), p)
                    self.assertNotRegex(code.lower(), r"hec-?ras|\bwine\b", p)
                else:
                    self.assertNotRegex(code.lower(), r"lisflood|anuga|hec-?ras|\bwine\b", p)

    def test_launch_is_opt_in(self):
        """damit_pmp's one launcher: shell-free, imported only by the anugarain and lisfloodrain algorithms, both runs off by default."""
        launch = os.path.join(ROOT, "damit_pmp", "launch.py")
        self.assertNotRegex(code_of(launch), r"shell\s*=\s*True|os\.system")
        for p in py_files("damit_pmp"):
            rel = os.path.relpath(p, ROOT)
            if rel.startswith(SHARED_DIR + os.sep) or rel in LAUNCH_OK:
                continue
            code = code_of(p)
            if re.search(r"import launch\b|from \.launch\b|from \.\.launch\b|runner_shared\.wallclock|import wallclock",
                         code):
                self.assertIn(rel, (os.path.join("damit_pmp", "algorithms", "anuga_algs.py"),
                                    os.path.join("damit_pmp", "algorithms", "lisflood_algs.py")), p)
        with open(os.path.join(ROOT, "damit_pmp", "algorithms", "anuga_algs.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertRegex(src, r'"RUN_ANUGA"[\s\S]{0,200}?defaultValue=False')
        self.assertRegex(src, r'"ANUGA_PYTHON"[\s\S]{0,260}?optional=True')
        self.assertIn("ANUGA Python", src)
        with open(os.path.join(ROOT, "damit_pmp", "algorithms", "lisflood_algs.py"), encoding="utf-8") as fh:
            lsrc = fh.read()
        self.assertRegex(lsrc, r'"RUN_LISFLOOD"[\s\S]{0,200}?defaultValue=False')
        self.assertRegex(lsrc, r'"LISFLOOD_EXE"[\s\S]{0,260}?optional=True')
        self.assertNotIn("subprocess", lsrc)                       # only launch.py starts the process


if __name__ == "__main__":
    unittest.main()
