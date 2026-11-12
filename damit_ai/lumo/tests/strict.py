"""Test helpers: file reads that close their files, and a TestCase that FAILS on a ResourceWarning (an unclosed
file, socket or subprocess) or on any warning raised from this package's own code."""
import gc
import json
import os
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
LUMO = os.path.abspath(os.path.join(HERE, ".."))


def slurp(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


def spit(path, text, mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        f.write(text)


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class StrictCase(unittest.TestCase):
    """Records every warning during a test; at the end (after a gc pass, which is when an unclosed file is reported)
    fails when one was a ResourceWarning or came from the lumo package. Third-party warnings do not fail a test."""

    def setUp(self):
        super(StrictCase, self).setUp()
        ctx = warnings.catch_warnings(record=True)
        log = ctx.__enter__()
        warnings.simplefilter("always")
        self._warn_log = log
        self.addCleanup(self._check_warnings, ctx)           # added first, so it runs last

    def _check_warnings(self, ctx):
        gc.collect()
        ctx.__exit__(None, None, None)
        bad = [w for w in self._warn_log if issubclass(w.category, ResourceWarning) or
               os.path.abspath(str(w.filename)).startswith(LUMO + os.sep)]
        if bad:
            self.fail("warnings: " + "; ".join("%s: %s (%s:%s)" % (w.category.__name__, w.message, w.filename, w.lineno)
                                                for w in bad[:5]))
