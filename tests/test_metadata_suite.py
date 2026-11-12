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
           "damit_finder": ("DamIT Finder", "yes", "DamIT Core", "damit_find")}
FORBIDDEN_LAUNCH = re.compile(r"\b(subprocess|Popen|os\.system|os\.exec\w*|QProcess|startDetached)\b")
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


class Metadata(unittest.TestCase):
    def test_metadata(self):
        for folder, (name, provider, dep, _) in PLUGINS.items():
            m = meta(folder)
            self.assertEqual(m["name"], name)
            # the Finder engine is shared with DamSafety Finder and versioned with it (its
            # run_info records finder.VERSION); the rest are versioned with the DamIT suite
            self.assertEqual(m["version"], FINDER_VERSION if folder == "damit_finder" else "0.2.0")
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
                self.assertIsNone(FORBIDDEN_LAUNCH.search(code), p)
                self.assertNotRegex(code, r"['\"](ndbreach|nddam):\w", p)
                self.assertNotRegex(code.lower(), r"lisflood|anuga|hec-?ras|\bwine\b", p)


if __name__ == "__main__":
    unittest.main()
