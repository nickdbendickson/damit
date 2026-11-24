"""core/metalterrain (BoannGrid) is a copy of DamSafety Runner's core/metalterrain (DWR_Plugins main 01758ea1,
DamSafety Runner 3.74.0), ported in DamIT Runner 0.9.0. METALTERRAIN_SOURCE.json records each file: a byte-for-byte
copy ('identical') or a copy with DamIT's noted differences ('modified'). An edit to either kind, or a file added or
removed, fails here until the record is updated with the change."""
import hashlib
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class MetalterrainProvenance(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "METALTERRAIN_SOURCE.json"), encoding="utf-8") as fh:
            self.rec = json.load(fh)
        self.folder = os.path.join(ROOT, "core", "metalterrain")

    def test_files_match_the_record(self):
        have = sorted(f for f in os.listdir(self.folder) if os.path.isfile(os.path.join(self.folder, f)))
        want = sorted(list(self.rec["identical"]) + list(self.rec["modified"]))
        self.assertEqual(have, want, "core/metalterrain files differ from METALTERRAIN_SOURCE.json")
        for name, sha in self.rec["identical"].items():
            self.assertEqual(_sha(os.path.join(self.folder, name)), sha, name + " is no longer the DamSafety copy")
        for name, m in self.rec["modified"].items():
            self.assertEqual(_sha(os.path.join(self.folder, name)), m["damit_sha256"],
                             name + " changed since its DamIT difference was recorded")
            self.assertTrue(m.get("note"), name + " has no note saying what DamIT changed")

    def test_default_bankfull_curve_is_national(self):
        from damit_runner.core.metalterrain import prism
        from damit_runner.core import sgc
        self.assertEqual(prism.DEFAULT_COEFFS, prism.BIEGER_2015_US)
        self.assertEqual(sgc.DEFAULT_CURVE, sgc.BIEGER_2015_US)
        self.assertEqual(sgc.SGC_CURVES["nd_usgs_2026"], sgc.ND_USGS_2026)

    def test_no_damsuite_import(self):
        for f in os.listdir(self.folder):
            if f.endswith(".py"):
                with open(os.path.join(self.folder, f), encoding="utf-8") as fh:
                    text = fh.read()
                for bad in ("from ..." + "damsuite", "from " + "damsuite"):   # split: the CI grep
                    self.assertNotIn(bad, text, f)


if __name__ == "__main__":
    unittest.main()
