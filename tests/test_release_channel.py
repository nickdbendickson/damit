"""The release channel (scripts/package_plugins.py + scripts/make_plugins_xml.py, .github/workflows/release.yml).

No QGIS needed. QGIS's plugin manager reads every metadata.txt with configparser and % interpolation, so a
bare % makes a field unreadable there (it shows as an error); every field of every plugin must read cleanly."""
import configparser
import glob
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import make_plugins_xml as MPX  # noqa: E402


def _metadata_files():
    return sorted(glob.glob(os.path.join(ROOT, "damit_*", "metadata.txt")))


class MetadataReadable(unittest.TestCase):
    def test_every_field_reads_with_interpolation(self):
        files = _metadata_files()
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            cp = configparser.ConfigParser()
            cp.read(f, encoding="utf-8")
            for key in cp.options("general"):
                with self.subTest(file=os.path.relpath(f, ROOT), key=key):
                    try:
                        cp.get("general", key)
                    except configparser.Error as e:
                        self.fail("{} {}: {} (write a percent sign as %%)".format(f, key, type(e).__name__))


class ReleaseRoundTrip(unittest.TestCase):
    def test_package_then_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = os.path.join(tmp, "dist")
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "package_plugins.py"), dist],
                           check=True, stdout=subprocess.DEVNULL)
            zips = sorted(n for n in os.listdir(dist) if n.endswith(".zip"))
            self.assertEqual(len(zips), len(_metadata_files()))
            root = MPX.build("v9.9.9", dist, date="2026-01-01")
            entries = root.findall("pyqgis_plugin")
            self.assertEqual(len(entries), len(zips))
            for el in entries:
                url = el.find("download_url").text
                self.assertTrue(url.startswith("https://github.com/nickdbendickson/damit/releases/download/v9.9.9/"))
                self.assertTrue(el.get("version"))
                self.assertTrue(el.find("qgis_minimum_version").text)
                self.assertNotIn("__error__", ET.tostring(el, encoding="unicode"))
            names = {el.get("name") for el in entries}
            self.assertIn("DamIT Core", names)

    def test_merge_keeps_plugins_not_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old.xml")
            with open(old, "w", encoding="utf-8") as fh:
                fh.write('<plugins><pyqgis_plugin name="DamIT Other" version="1.0.0"/>'
                         '<pyqgis_plugin name="DamIT Core" version="0.0.1"/></plugins>')
            dist = os.path.join(tmp, "dist")
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "package_plugins.py"), dist],
                           check=True, stdout=subprocess.DEVNULL)
            root = MPX.build("v1", dist, merge=old, date="2026-01-01")
            got = [(el.get("name"), el.get("version")) for el in root.findall("pyqgis_plugin")]
            self.assertIn(("DamIT Other", "1.0.0"), got)
            self.assertNotIn(("DamIT Core", "0.0.1"), got)

    def test_zip_name_version_must_match_metadata(self):
        self.assertEqual(MPX.zip_version("damit_core_0_3_3.zip"), "0.3.3")
        self.assertIsNone(MPX.zip_version("DamSafety_Core_1.0.0.zip"))


if __name__ == "__main__":
    unittest.main()
