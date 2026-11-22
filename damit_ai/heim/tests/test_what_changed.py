"""what_changed.py: the knowledge pack's generated change list, and heim-doctor saying when it is old.

Why this exists: the hand-written pages fell four days and six flood engines behind (2026-11-22), and
nothing said so. No model, no network: a throwaway git repository.
"""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_wc_test", os.path.join(TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(shutil.which("git") is None, "no git")
class WhatChangedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="heim-wc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "DWR_Plugins")
        os.makedirs(self.repo)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        run = lambda *a: subprocess.run(["git", "-C", self.repo] + list(a), check=True, env=env,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("commit", "-q", "--allow-empty", "-m", "Runner 3.42.0: wire Boann sub-grid FV (#457)")
        run("checkout", "-q", "-b", "fix")
        run("commit", "-q", "--allow-empty", "-m", "inner commit that should not be listed")
        run("checkout", "-q", "main")
        run("merge", "-q", "--no-ff", "fix", "-m",
            "Merge pull request #462 from someone/fix\n\nRunner 3.42.1: subfv reads open edges from the true grid")
        self.wc = load("what_changed")

    def test_lists_first_parent_commits_with_the_pull_request_title(self):
        text = self.wc.build([("DWR_Plugins", self.repo)], 30, today="2026-11-22")
        self.assertIn("Generated 2026-11-22 from DWR_Plugins ", text)
        self.assertIn("Runner 3.42.1: subfv reads open edges from the true grid (#462)", text)
        self.assertIn("Runner 3.42.0: wire Boann sub-grid FV (#457)", text)
        self.assertNotIn("inner commit", text)
        self.assertNotIn("Merge pull request", text)

    def test_doctor_reads_the_age_of_the_page(self):
        rag = load("rag_index")
        page = os.path.join(self.tmp, "WHAT-CHANGED.md")
        with open(page, "w") as f:
            f.write(self.wc.build([("DWR_Plugins", self.repo)], 30, today="2026-11-01"))
        now = time.mktime(time.strptime("2026-11-30", "%Y-%m-%d"))
        self.assertEqual(rag.what_changed_age(page, today=now), 29)
        self.assertIsNone(rag.what_changed_age(os.path.join(self.tmp, "missing.md")))


if __name__ == "__main__":
    unittest.main()
