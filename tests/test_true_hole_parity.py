"""The bundled true_hole.py copies must stay byte-identical to damit_core."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = os.path.join(ROOT, "damit_core", "lib", "true_hole.py")
COPIES = (
    os.path.join(ROOT, "damit_hazard", "lib", "true_hole.py"),
    os.path.join(ROOT, "damit_runner", "lib", "true_hole.py"),
    os.path.join(ROOT, "damit_ai", "heim", "tools", "true_hole.py"),
)


class TrueHoleParity(unittest.TestCase):
    def test_bundled_copies_match_damit_core(self):
        with open(CANONICAL, "rb") as fh:
            src = fh.read()
        self.assertTrue(src, "canonical damit_core/lib/true_hole.py is empty")
        for path in COPIES:
            self.assertTrue(os.path.isfile(path), "missing bundled copy: " + path)
            with open(path, "rb") as fh:
                got = fh.read()
            self.assertEqual(got, src, "bundled copy drifted from damit_core/lib/true_hole.py: " + path)


if __name__ == "__main__":
    unittest.main()
