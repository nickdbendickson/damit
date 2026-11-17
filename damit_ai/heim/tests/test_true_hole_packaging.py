"""Minimal-install packaging of the true-hole helper used by the Heim digest."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.abspath(os.path.join(HERE, ".."))
TOOLS = os.path.join(HEIM, "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import run_digest as RD  # noqa: E402
from strict import StrictCase  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


class TrueHolePackaging(StrictCase):
    def test_sibling_helper_is_used_in_a_local_ai_layout(self):
        """setup-local-heim.sh copies true_hole.py next to run_digest.py; that layout works."""
        tmp = tempfile.mkdtemp(prefix="heim_mininst_")
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("run_digest.py", "true_hole.py"):
            shutil.copy2(os.path.join(TOOLS, name), os.path.join(tmp, name))
        py = (
            "import os, sys\n"
            "sys.path.insert(0, os.environ['MIN_AI'])\n"
            "import run_digest as RD\n"
            "import numpy as np\n"
            "a = np.full((7, 7), np.nan); a[1:6, 1:6] = 1.0; a[3, 3] = np.nan\n"
            "g = RD.Grid(a, 0.0, 7.0, 1.0)\n"
            "holes, overs, edges = RD.split_nodata_true_holes(g, [('h1', 3.5, 3.5)], [('h1', 1.0)])\n"
            "assert holes and holes[0][0] == 'h1'\n"
            "print('heim_mininst_ok')\n"
        )
        env = dict(os.environ, MIN_AI=tmp, PYTHONPATH=tmp)
        r = subprocess.run([sys.executable, "-c", py], capture_output=True, text=True,
                           env=env, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("heim_mininst_ok", r.stdout)

    def test_missing_helper_is_not_reported_as_unreadable_rasters(self):
        """A local-ai install without true_hole.py must not collapse into NO_RUN_FILES."""
        tmp = tempfile.mkdtemp(prefix="heim_nohelper_")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(os.path.join(TOOLS, "run_digest.py"), os.path.join(tmp, "run_digest.py"))
        py = r"""
import os, sys, tempfile, json
sys.path.insert(0, os.environ['MIN_AI'])
import run_digest as RD
import numpy as np

# split_nodata must raise a dedicated error, not FileNotFoundError from a bad path
a = np.full((7, 7), np.nan); a[1:6, 1:6] = 1.0; a[3, 3] = np.nan
g = RD.Grid(a, 0.0, 7.0, 1.0)
try:
    RD.split_nodata_true_holes(g, [('h1', 3.5, 3.5)], [('h1', 1.0)])
    raise SystemExit('split_nodata unexpectedly succeeded')
except RD.TrueHoleHelperMissing as e:
    msg = str(e).lower()
    assert 'true-hole helper' in msg or 'true_hole.py' in msg, e
else:
    raise SystemExit('wrong exception for a missing helper')

# build_digest must flag TRUE_HOLE_HELPER_MISSING, not NO_RUN_FILES / unreadable rasters
import fixture_run as FX
root = tempfile.mkdtemp(prefix='digest_nohelper_')
run, dam = FX.make_run(root)
os.makedirs(os.path.join(run, 'outputs'), exist_ok=True)
open(os.path.join(run, 'outputs', 'Depth (Max).tif'), 'wb').write(b'x')
# point the in-process digest (imported from MIN_AI) at a fake raster
RD.read_tif = lambda *a, **k: g
d = RD.build_digest(run, dam_folder=dam, points=[('h1', 3.5, 3.5)])
ids = [f['id'] for f in d['flags']]
assert 'TRUE_HOLE_HELPER_MISSING' in ids, ids
assert 'NO_RUN_FILES' not in ids, ids
titles = ' '.join(f['title'] for f in d['flags'] if f['id'] == 'TRUE_HOLE_HELPER_MISSING')
assert 'could not read the result rasters' not in titles
assert 'true-hole helper' in titles.lower()
print('heim_nohelper_ok')
"""
        env = dict(os.environ, MIN_AI=tmp, PYTHONPATH=tmp + os.pathsep + HERE)
        r = subprocess.run([sys.executable, "-c", py], capture_output=True, text=True,
                           env=env, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("heim_nohelper_ok", r.stdout)

    @needs_numpy
    def test_inprocess_missing_helper_does_not_use_no_run_files(self):
        import numpy as np
        import fixture_run as FX
        root = tempfile.mkdtemp(prefix="heim_nohelper_ip_")
        self.addCleanup(shutil.rmtree, root, True)
        run, dam = FX.make_run(root)
        os.makedirs(os.path.join(run, "outputs"), exist_ok=True)
        with open(os.path.join(run, "outputs", "Depth (Max).tif"), "wb") as fh:
            fh.write(b"x")
        a = np.full((7, 7), np.nan); a[1:6, 1:6] = 1.0; a[3, 3] = np.nan
        g = RD.Grid(a, 0.0, 7.0, 1.0)
        old_tif, old_th = RD.read_tif, RD._true_hole_mod
        self.addCleanup(setattr, RD, "read_tif", old_tif)
        self.addCleanup(setattr, RD, "_true_hole_mod", old_th)
        RD.read_tif = lambda *a, **k: g
        def boom():
            raise RD.TrueHoleHelperMissing("helper missing for test")
        RD._true_hole_mod = boom
        d = RD.build_digest(run, dam_folder=dam, points=[("h1", 3.5, 3.5)])
        ids = [f["id"] for f in d["flags"]]
        self.assertIn("TRUE_HOLE_HELPER_MISSING", ids, ids)
        self.assertNotIn("NO_RUN_FILES", ids, ids)
        title = [f["title"] for f in d["flags"] if f["id"] == "TRUE_HOLE_HELPER_MISSING"][0]
        self.assertNotIn("could not read the result rasters", title)
        self.assertIn("true-hole helper", title.lower())


if __name__ == "__main__":
    unittest.main()
