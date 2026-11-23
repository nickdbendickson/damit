"""Known-class benchmark harness (no QGIS, no GDAL).

The official dams.json list is empty. The LOWER exit is proved with a fixture that says it
is not an official class.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "run_class_benchmark.py")
DAMS = os.path.join(ROOT, "tests", "class_benchmark", "dams.json")
PROBE = os.path.join(ROOT, "tests", "class_benchmark", "fixtures", "lower_probe.json")


def _run(args):
    return subprocess.run([sys.executable, SCRIPT] + args, cwd=ROOT, capture_output=True, text=True)


class ClassBenchmark(unittest.TestCase):
    def test_official_list_is_empty_and_exits_0(self):
        with open(DAMS, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["dams"], [])
        self.assertEqual(doc["purpose"], "official")
        r = _run([])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("official list is empty", r.stdout)
        self.assertIn("LOWER: 0", r.stdout)
        self.assertIn("preset NRCS  status=unverified", r.stdout)
        self.assertIn("preset NY  status=draft", r.stdout)
        self.assertIn("preset BIA  status=(none)  verification=M5=secondary", r.stdout)

    def test_self_test_lower_exits_1(self):
        with open(PROBE, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["purpose"], "self-test")
        self.assertFalse(doc["dams"][0]["official_record"])
        r = _run(["--dams", PROBE])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SELF-TEST", r.stdout)
        self.assertIn("LOWER", r.stdout)
        self.assertNotIn("official list is empty", r.stdout)

    def test_agree_exits_0(self):
        dam = {
            "schema": "damit.class_benchmark",
            "purpose": "self-test",
            "dams": [{
                "id": "selftest-agree",
                "name": "Synthetic agree probe",
                "official_record": False,
                "presets": ["FEMA333"],
                "official_class": 3,
                "official_source": "Not a published class.",
                "receptors": [{
                    "id": "h1", "kind": "structure", "type": "home",
                    "depth_ft": 6.5, "velocity_fps": 1.0, "occupants": 1,
                }],
            }],
        }
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dam, fh)
            r = _run(["--dams", path])
        finally:
            os.remove(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("agree", r.stdout)
        self.assertIn("LOWER: 0", r.stdout)

    def test_missing_raster_is_not_lower(self):
        dam = {
            "purpose": "official",
            "dams": [{
                "id": "no-rasters",
                "presets": ["USBR"],
                "official_class": 3,
                "official_source": "fixture only; rasters are absent",
                "rasters": "does-not-exist",
            }],
        }
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dam, fh)
            r = _run(["--dams", path])
        finally:
            os.remove(path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skipped", r.stdout)
        self.assertIn("LOWER: 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
