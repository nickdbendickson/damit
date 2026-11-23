"""B2: the placeholder tables stay at the values the audit recorded. No source number is filled in."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PlaceholderTables(unittest.TestCase):
    def test_fatality_and_breach_factors_unchanged(self):
        from damit_runner.core.consequences import DEFAULT_FATALITY_TABLE, GENERIC_CURVES
        from damit_runner.core.probabilistic import default_width, default_time, default_manning
        self.assertEqual(DEFAULT_FATALITY_TABLE["low"],
                         {"none": 0.01, "short": 0.01, "some": 0.007, "adequate": 0.0003})
        self.assertEqual(DEFAULT_FATALITY_TABLE["medium"],
                         {"none": 0.15, "short": 0.15, "some": 0.04, "adequate": 0.03})
        self.assertEqual(DEFAULT_FATALITY_TABLE["high"],
                         {"none": 0.75, "short": 0.75, "some": 0.15, "adequate": 0.04})
        self.assertEqual(GENERIC_CURVES["residential"]["structure_pct"], [0, 15, 25, 40, 55, 70, 90])
        self.assertEqual(default_width().params, (0.5, 1.0, 1.5))
        self.assertEqual(default_time().params, (0.5, 1.0, 2.0))
        self.assertEqual(default_manning().params, (0.75, 1.0, 1.3))

    def test_audit_leaves_the_values(self):
        path = os.path.join(ROOT, "docs", "PLACEHOLDER_TABLES.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("No number", text)
        self.assertIn("was changed", text)
        self.assertIn("DSO-99-06", text)
        self.assertIn("Table 7", text)
        self.assertIn("printed page 38", text)
        self.assertIn("not replaced", text)
        self.assertIn("0.15", text)   # high / some stays; Table 7 has no rate there
        self.assertIn("Froehlich", text)
        self.assertNotIn("REG_05", text)


if __name__ == "__main__":
    unittest.main()
