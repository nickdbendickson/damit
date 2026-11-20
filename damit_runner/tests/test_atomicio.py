"""core/atomicio.write_text (Runner 0.7.5, damit #134): whole file or nothing, temp unique per writer, no temp left."""
import os
import tempfile
import threading
import unittest
from unittest import mock

from damit_runner.core import atomicio


class WriteText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_and_replaces(self):
        p = os.path.join(self.dir, "sub", "a.json")
        atomicio.write_text(p, "one\n")
        atomicio.write_text(p, "two\n")
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "two\n")
        self.assertEqual(os.listdir(os.path.dirname(p)), ["a.json"])

    def test_failed_write_keeps_old_file_and_no_temp(self):
        p = os.path.join(self.dir, "a.json")
        atomicio.write_text(p, "good\n")
        with mock.patch("damit_runner.core.atomicio.os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                atomicio.write_text(p, "half")
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "good\n")
        self.assertEqual(os.listdir(self.dir), ["a.json"])

    def test_temp_name_unique_per_writer(self):
        p = os.path.join(self.dir, "a.json")
        seen = []
        real_open = open

        def spy(path, *a, **k):
            seen.append(path)
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", side_effect=spy):
            atomicio.write_text(p, "x")
        self.assertEqual(seen, ["{}.{}.{}.tmp".format(p, os.getpid(), threading.get_ident())])


if __name__ == "__main__":
    unittest.main()
