"""Packaging checks for all DamIT plugins in this repo (no QGIS needed)."""
import configparser
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = {"damit_catalog": ("DamIT Catalog", "no", None, "0.2.0"),
           "damit_screener": ("DamIT Screener", "yes", "DamIT Catalog,DamIT Runner", "0.3.3"),
           "damit_runner": ("DamIT Runner", "yes", "DamIT Catalog", "0.4.1")}
# DamIT Runner 0.3.0 carries the full ported flood engine, so these plugins MAY spawn processes directly
# (LISFLOOD-FP, the ANUGA worker, HEC-RAS and Wine, ffmpeg, pandoc, conda, caffeinate). Two teeth stay:
# never through a shell, and never the North Dakota breach/screening suite's processing ids. The HEC-RAS ->
# Hazard hand-off targets ndhazard:* and is allowed.
SHELL_LAUNCH = re.compile(r"shell\s*=\s*True|\bos\.system\b|\bos\.popen\b")
FOREIGN_PROVIDER = re.compile(r"\b(ndbreach|nddam):")


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

    def test_no_shell_and_no_foreign_providers(self):
        # the full engine may spawn processes, but never through a shell, and never the ND breach /
        # screening suite (ndbreach:* / nddam:*); the ndhazard:* Hazard hand-off stays allowed
        for folder in PLUGINS:
            for p in py_files(folder):
                with open(p, encoding="utf-8") as fh:
                    src = fh.read()
                code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
                self.assertIsNone(SHELL_LAUNCH.search(code), p)
                self.assertIsNone(FOREIGN_PROVIDER.search(code), p)

    def test_hazard_depends_on_catalog(self):
        # DamIT Hazard reads its presets and thresholds from DamIT Catalog and ships no catalog of its own
        m = meta("damit_hazard")
        self.assertEqual(m["name"], "DamIT Hazard")
        self.assertEqual(m["hasProcessingProvider"], "yes")
        self.assertEqual(m.get("plugin_dependencies"), "DamIT Catalog")
        self.assertFalse(os.path.exists(os.path.join(ROOT, "damit_hazard", "data", "catalog.json")))


if __name__ == "__main__":
    unittest.main()
