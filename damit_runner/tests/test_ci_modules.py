"""CI lists every test_*.py. unittest exits 0 when it collects nothing, so the
launcher (ci_modules.py) is the guard, not a test that discover would skip.

The live-tree test is what makes a new test_*.py fail CI until it is enrolled
or excluded with a reason. The temp-tree tests are the rules themselves.
"""
import os
import tempfile
import unittest

from damit_runner.tests import ci_modules as cm

HERE = os.path.dirname(os.path.abspath(__file__))
SCIPY = (
    "test_inflow_depth",
    "test_dam_point_check",
    "test_inflow_side",
    "test_dam_line_centre",
)


def _tree(files, exclude="", scipy=""):
    d = tempfile.mkdtemp()
    for name in files:
        open(os.path.join(d, name), "w").close()
    with open(os.path.join(d, "CI_EXCLUDE.txt"), "w") as fh:
        fh.write(exclude)
    with open(os.path.join(d, "CI_SCIPY.txt"), "w") as fh:
        fh.write(scipy)
    return d


class LiveTree(unittest.TestCase):
    def test_every_module_is_in_one_place(self):
        got = cm.classify(HERE)
        self.assertEqual(got["errors"], [])
        files = set(cm.test_stems(HERE))
        placed = set(got["numpy"]) | set(got["scipy"]) | set(got["excluded"])
        self.assertEqual(placed, files)
        self.assertFalse(set(got["numpy"]) & set(got["scipy"]))
        self.assertFalse(set(got["numpy"]) & set(got["excluded"]))
        self.assertFalse(set(got["scipy"]) & set(got["excluded"]))
        self.assertEqual(got["scipy"], list(SCIPY))
        self.assertEqual(got["excluded"], [])
        self.assertIn("test_ci_modules", got["numpy"])
        self.assertNotIn("test_streamstats_golden", got["scipy"])
        self.assertIn("test_streamstats_golden", got["numpy"])

    def test_cli_prints_importable_names(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cm.main(["--tier", "numpy"])
        self.assertEqual(rc, 0)
        names = buf.getvalue().split()
        self.assertTrue(all(n.startswith("damit_runner.tests.test_") for n in names))
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("damit_runner.tests.test_inflow_depth", names)


class Rules(unittest.TestCase):
    def _ok_scipy(self):
        return "test_inflow_depth  # needs scipy\n"

    def test_exclude_without_a_reason_fails(self):
        d = _tree(["test_a.py", "test_inflow_depth.py"],
                  exclude="test_a\n", scipy=self._ok_scipy())
        errs = cm.classify(d)["errors"]
        self.assertTrue(any("no reason" in e for e in errs), errs)

    def test_exclude_stem_with_no_file_fails(self):
        d = _tree(["test_inflow_depth.py"],
                  exclude="test_gone  # removed last year\n", scipy=self._ok_scipy())
        errs = cm.classify(d)["errors"]
        self.assertTrue(any("test_gone" in e and "not a test_" in e for e in errs), errs)

    def test_a_new_file_is_enrolled_in_the_numpy_tier(self):
        d = _tree(["test_a.py", "test_zz_canary.py", "test_inflow_depth.py"],
                  scipy=self._ok_scipy())
        got = cm.classify(d)
        self.assertEqual(got["errors"], [])
        self.assertEqual(got["numpy"], ["test_a", "test_zz_canary"])
        self.assertEqual(got["scipy"], ["test_inflow_depth"])

    def test_scipy_module_is_not_also_numpy(self):
        d = _tree(["test_a.py", "test_inflow_depth.py"], scipy=self._ok_scipy())
        got = cm.classify(d)
        self.assertEqual(got["errors"], [])
        self.assertNotIn("test_inflow_depth", got["numpy"])

    def test_empty_numpy_tier_fails(self):
        d = _tree(["test_inflow_depth.py"],
                  exclude="", scipy=self._ok_scipy())
        # only the scipy module exists, so numpy is empty
        errs = cm.classify(d)["errors"]
        self.assertTrue(any("numpy tier is empty" in e for e in errs), errs)

    def test_both_lists_fails(self):
        d = _tree(["test_a.py", "test_inflow_depth.py"],
                  exclude="test_inflow_depth  # no\n", scipy=self._ok_scipy())
        errs = cm.classify(d)["errors"]
        self.assertTrue(any("both" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
