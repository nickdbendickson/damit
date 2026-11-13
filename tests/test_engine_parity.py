"""The DamIT <-> DamSafety engine parity gate (scripts/check_engine_parity.py). Pure Python.

The record itself is checked against a DamSafety checkout in CI (.github/workflows/engine_parity.yml) and
here when DAMIT_DWR_CHECKOUT names one."""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("check_engine_parity",
                                               os.path.join(ROOT, "scripts", "check_engine_parity.py"))
EP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EP)


def _tree(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)


class DiffSha(unittest.TestCase):
    def test_identical_is_empty(self):
        self.assertEqual(EP.diff_sha("a\nb\n", "a\nb\n"), "")

    def test_same_change_on_both_sides_keeps_the_sha(self):
        theirs, mine = "x = 1\nname = 'ND'\ny = 2\n", "x = 1\nname = 'DamIT'\ny = 2\n"
        before = EP.diff_sha(theirs, mine)
        self.assertTrue(before)
        # a fix made on both sides, above and below the branded line (line numbers move)
        fix = lambda s: "import os\n" + s.replace("y = 2", "y = 3")      # noqa: E731
        self.assertEqual(EP.diff_sha(fix(theirs), fix(mine)), before)

    def test_a_change_on_one_side_moves_the_sha(self):
        theirs, mine = "x = 1\nname = 'ND'\n", "x = 1\nname = 'DamIT'\n"
        self.assertNotEqual(EP.diff_sha(theirs + "limit = 24\n", mine), EP.diff_sha(theirs, mine))


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_parity_")
        self.dwr, self.me = os.path.join(self.tmp, "dwr"), os.path.join(self.tmp, "damit")
        _tree(self.dwr, {"DamSafety_Runner/core/breach.py": "A = 1\nTOOL = 'ND'\n",
                         "DamSafety_Runner/core/grid.py": "G = 1\n",
                         "DamSafety_Runner/core/nd_data.py": "ND = 1\n",
                         "DamSafety_Runner/algorithms.py": "ALG = 1\n",
                         "DamSafety_Core/damsuite/nodata_sample.py": "N = 1\n",
                         "DamSafety_Finder/core/score.py": "S = 1\n"})
        _tree(self.me, {"damit_runner/core/breach.py": "A = 1\nTOOL = 'DamIT'\n",
                        "damit_runner/core/grid.py": "G = 1\n",
                        "damit_runner/core/rundam.py": "OWN = 1\n",          # DamIT's own: not a pair
                        "damit_runner/flood/breach.py": "A = 1\nTOOL = 'ND'\n",
                        "damit_runner/algorithms/engine.py": "ALG = 1\n",
                        "damit_runner/compat/nodata_sample.py": "N = 1\n",
                        "damit_finder/core/score.py": "S = 1\n"})
        self.rec_path = os.path.join(self.me, "damit_runner", "PARITY.json")
        self.rec = EP.update(self.dwr, self.me, self.rec_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check(self):
        return EP.check(self.dwr, EP.load_record(self.rec_path), self.me)

    def test_recorded_state_passes(self):
        problems, counts = self._check()
        self.assertEqual(problems, [])
        self.assertEqual(counts, {"identical": 5, "accepted": 1, "drift": 0})
        self.assertNotIn("damit_runner/core/rundam.py", self.rec["pairs"])
        self.assertEqual(self.rec["not_ported"], ["DamSafety_Runner/core/nd_data.py"])

    def test_damsafety_fix_not_ported_is_drift(self):
        _tree(self.dwr, {"DamSafety_Runner/core/breach.py": "A = 2\nTOOL = 'ND'\n"})
        problems, counts = self._check()
        self.assertEqual(counts["drift"], 2)                     # core/breach.py and flood/breach.py
        self.assertTrue(any(p.startswith("damit_runner/core/breach.py") and "port it" in p for p in problems))

    def test_fix_ported_to_both_passes_again(self):
        _tree(self.dwr, {"DamSafety_Runner/core/breach.py": "A = 2\nTOOL = 'ND'\n"})
        _tree(self.me, {"damit_runner/core/breach.py": "A = 2\nTOOL = 'DamIT'\n",
                        "damit_runner/flood/breach.py": "A = 2\nTOOL = 'ND'\n"})
        self.assertEqual(self._check()[0], [])

    def test_damit_edit_of_an_identical_file_is_drift(self):
        _tree(self.me, {"damit_runner/core/grid.py": "G = 9\n"})
        problems, _ = self._check()
        self.assertEqual(len(problems), 1)
        self.assertIn("damit_runner/core/grid.py", problems[0])

    def test_new_damsafety_module_is_drift_until_listed(self):
        _tree(self.dwr, {"DamSafety_Runner/core/model_terrain.py": "M = 1\n"})
        problems, _ = self._check()
        self.assertEqual(len(problems), 1)
        self.assertIn("DamSafety_Runner/core/model_terrain.py", problems[0])

    def test_new_ported_file_must_be_recorded(self):
        _tree(self.dwr, {"DamSafety_Runner/core/model_terrain.py": "M = 1\n"})
        _tree(self.me, {"damit_runner/core/model_terrain.py": "M = 1\n"})
        problems, _ = self._check()
        self.assertEqual(len(problems), 1)
        self.assertIn("not in PARITY.json", problems[0])


class Record(unittest.TestCase):
    """The committed PARITY.json."""

    def setUp(self):
        self.rec = EP.load_record()

    def test_shape(self):
        self.assertEqual(self.rec["schema"], "damit.engine_parity")
        self.assertRegex(self.rec["synced_to"], r"^[0-9a-f]{40}$")
        self.assertGreater(len(self.rec["pairs"]), 80)

    def test_every_recorded_file_exists(self):
        for mine in self.rec["pairs"]:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, mine)), mine)

    def test_the_hydraulic_core_is_covered(self):
        for f in ("breach.py", "lisflood.py", "flood.py", "refine.py", "hydrology.py", "workflow.py",
                  "builtin_lisflood.py", "anuga_model.py"):
            self.assertIn("damit_runner/core/" + f, self.rec["pairs"])
        self.assertIn("damit_runner/flood/breach.py", self.rec["pairs"])

    def test_no_ported_file_is_missing_from_the_record(self):
        # a .py under a mapped folder whose DamSafety original was recorded stays recorded; DamIT's own files
        # (no original) are not pairs, so only the count against a real checkout can prove the rest
        dwr = os.environ.get("DAMIT_DWR_CHECKOUT")
        if not dwr:
            self.skipTest("DAMIT_DWR_CHECKOUT not set")
        problems, _ = EP.check(dwr, self.rec)
        self.assertEqual(problems, [])

    def test_json_is_stable(self):
        with open(EP.RECORD, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, json.dumps(self.rec, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
