"""rag_query 2.7 (2026-11-22): one long file may not fill every passage handed to the model.

The first real-model run of the word-and-meaning search gave the sunny-day question 7 of its 10
passages from ALGORITHM-HELP-DAMIT.md, and KNOWN-BEHAVIOURS.md, where the rule is written, was
squeezed out. These check the limit without a model.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import rag_query  # noqa: E402


class Spread(unittest.TestCase):
    def test_one_file_cannot_fill_the_list(self):
        files = ["help"] * 7 + ["known", "known", "digest", "changed", "recipes", "casebook", "contracts", "help"]
        got = rag_query.spread(list(range(len(files))), lambda i: files[i], 10, 3)
        self.assertEqual([files[i] for i in got].count("help"), 3)
        self.assertIn(7, got)                       # the first KNOWN-BEHAVIOURS passage is back in
        self.assertEqual(got, sorted(got))          # best first, as fused

    def test_a_single_file_still_gets_every_place(self):
        got = rag_query.spread(list(range(12)), lambda i: "only", 10, 3)
        self.assertEqual(got, list(range(10)))

    def test_short_of_others_the_skipped_ones_fill_in_order(self):
        files = ["a"] * 6 + ["b"]
        got = rag_query.spread(list(range(7)), lambda i: files[i], 5, 3)
        self.assertEqual(got, [0, 1, 2, 3, 6])

    def test_zero_turns_the_limit_off(self):
        self.assertEqual(rag_query.spread(list(range(12)), lambda i: "x", 10, 0), list(range(10)))

    def test_search_uses_it(self):
        src = open(os.path.join(HERE, "..", "tools", "rag_query.py"), encoding="utf-8").read()
        self.assertIn("spread(sorted(fused", src)
        self.assertEqual(rag_query.PER_FILE, int(os.environ.get("HEIM_PER_FILE", "3")))


if __name__ == "__main__":
    unittest.main()
