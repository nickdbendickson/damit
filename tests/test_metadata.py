"""Packaging checks for all DamIT plugins in this repo (no QGIS needed)."""
import configparser
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = {"damit_catalog": ("DamIT Catalog", "no", None, "0.1.1"),
           "damit_screener": ("DamIT Screener", "yes", "DamIT Catalog,DamIT Runner", "0.2.0"),
           "damit_runner": ("DamIT Runner", "yes", "DamIT Catalog", "0.2.0")}
FORBIDDEN_LAUNCH = re.compile(r"\b(subprocess|Popen|os\.system|os\.exec\w*|QProcess|startDetached)\b")
# DamIT Runner 0.2.0 launches the flood model: only this module may start a process (LISFLOOD-FP or the ANUGA
# worker); everything else in the three plugins still may not
LAUNCH_OK = {os.path.join("damit_runner", "flood", "lisflood.py")}
FOREIGN_RUN = re.compile(r"['\"](wine|wine64)['\"]|\b(ndbreach|nddam):|HEC-?RAS\.exe|RasUnsteady", re.I)


def meta(folder):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(ROOT, folder, "metadata.txt"), encoding="utf-8")
    return cp["general"]


def py_files(folder):
    for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
        if os.sep + "tests" in base:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


class Metadata(unittest.TestCase):
    def test_metadata(self):
        for folder, (name, provider, dep, version) in PLUGINS.items():
            m = meta(folder)
            self.assertEqual(m["name"], name)
            self.assertEqual(m["version"], version)
            self.assertTrue(m["changelog"].startswith(version + " - "), folder)
            self.assertEqual(m["qgisMinimumVersion"], "3.28")
            self.assertEqual(m["qgisMaximumVersion"], "4.99")
            self.assertEqual(m["supportsQt6"], "True")
            self.assertEqual(m["author"], "Nick Bendickson")
            self.assertEqual(m["repository"], "https://github.com/nickdbendickson/damit")
            self.assertEqual(m["tracker"], "https://github.com/nickdbendickson/damit/issues")
            self.assertEqual(m["homepage"], "https://github.com/nickdbendickson/damit")
            self.assertEqual(m["hasProcessingProvider"], provider)
            self.assertEqual(m.get("plugin_dependencies"), dep)
            for f in ("__init__.py", "plugin.py", "icon.svg", m["icon"]):
                self.assertTrue(os.path.exists(os.path.join(ROOT, folder, f)), (folder, f))

    def test_qt6_safe_imports(self):
        for folder in PLUGINS:
            for p in py_files(folder):
                with open(p, encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotRegex(src, r"\bfrom PyQt[56]\b|\bimport PyQt[56]\b", p)
                self.assertFalse("QVariant" in src, p)

    def test_no_process_launch_and_no_foreign_providers(self):
        for folder in PLUGINS:
            for p in py_files(folder):
                with open(p, encoding="utf-8") as fh:
                    src = fh.read()
                code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
                if os.path.relpath(p, ROOT) in LAUNCH_OK:
                    # the one launcher: argv lists only (no shell), never a foreign provider or HEC-RAS / Wine
                    self.assertNotRegex(code, r"shell\s*=\s*True", p)
                    self.assertIsNone(FOREIGN_RUN.search(code), p)
                    continue
                self.assertIsNone(FORBIDDEN_LAUNCH.search(code), p)
                self.assertNotRegex(code, r"processing\.run\(\s*['\"](ndbreach|nddam):", p)

    def test_hazard_depends_on_catalog(self):
        # DamIT Hazard reads its presets and thresholds from DamIT Catalog and ships no catalog of its own
        m = meta("damit_hazard")
        self.assertEqual(m["name"], "DamIT Hazard")
        self.assertEqual(m["hasProcessingProvider"], "yes")
        self.assertEqual(m.get("plugin_dependencies"), "DamIT Catalog")
        self.assertFalse(os.path.exists(os.path.join(ROOT, "damit_hazard", "data", "catalog.json")))


if __name__ == "__main__":
    unittest.main()
