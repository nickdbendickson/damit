"""damit_pmp/runner_shared must be byte copies of damit_runner/core (pure Python, no numpy).

The plugins install independently, so damit_pmp carries the runner's ANUGA / gmsh files verbatim
(the repo's pattern for shared code: catalog_bridge.py, _deps.py, compat/). Edit the runner, then
run `python3 scripts/sync_pmp_runner_shared.py`."""
import hashlib
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARED = os.path.join(ROOT, "damit_pmp", "runner_shared")
CORE = os.path.join(ROOT, "damit_runner", "core")
FILES = ("gmsh_mesher.py", "grid.py", "terrain.py", "anuga_worker.py", "omp_probe.py", "anuga_dtdiag.py",
         "wallclock.py")


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class RunnerSharedSync(unittest.TestCase):
    def test_every_copy_is_identical_to_the_runner_file(self):
        for f in FILES:
            self.assertTrue(os.path.isfile(os.path.join(SHARED, f)), f)
            self.assertEqual(sha(os.path.join(SHARED, f)), sha(os.path.join(CORE, f)),
                             "damit_pmp/runner_shared/{0} differs from damit_runner/core/{0}: run "
                             "python3 scripts/sync_pmp_runner_shared.py".format(f))

    def test_no_other_python_file_in_the_folder(self):
        have = sorted(f for f in os.listdir(SHARED) if f.endswith(".py") and f != "__init__.py")
        self.assertEqual(have, sorted(FILES))

    def test_the_sync_script_agrees(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "sync_pmp_runner_shared.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_readme_lists_every_copy(self):
        with open(os.path.join(SHARED, "README.md"), encoding="utf-8") as fh:
            txt = fh.read()
        for f in FILES:
            self.assertIn("`" + f + "`", txt)


if __name__ == "__main__":
    unittest.main()
