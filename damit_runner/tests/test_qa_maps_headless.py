"""DamIT Runner 0.6.0 (DamSafety Runner 3.20.0): the QA maps do not end the process when there is
no Qt application and no matplotlib.

In a batch worker or a script there is no Qt application. With no matplotlib either, the plain Qt
map drew its title with QPainter.drawText, and Qt does not raise there: it aborts the process,
after the model had finished and before the run report was written. The title is now left off.
The maps are drawn in a child process, so an abort is a failed test and not a dead test run."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PNG = b"\x89PNG\r\n\x1a\n"

CHILD = r"""
import sys
sys.modules["matplotlib"] = None                 # import matplotlib -> ImportError
try:
    import numpy as np
    from qgis.PyQt.QtGui import QImage, QPainter
    from qgis.PyQt.QtCore import QCoreApplication
except Exception:
    print("NOQT")
    raise SystemExit(0)
from damit_runner.core import qa_maps as QA
from damit_runner.core.grid import Grid
assert QCoreApplication.instance() is None       # a worker, a script: no Qt application
n, cell = 60, 10.0
x = -300 + (np.arange(n) + 0.5) * cell
y = 300 - (np.arange(n) + 0.5) * cell
X, Y = np.meshgrid(x, y)
z = 100.0 + 0.002 * -X + 0.01 * np.abs(Y)
z = np.where(np.abs(X) < 15, 110.0, z)           # embankment, crest 110
z = np.where(X > 15, z - 4.0, z)                 # downstream channel lower
g = Grid(z, -300.0, 300.0, cell)
depth = np.where(g.x_centers()[None, :] > 15, 1.2, 0.0) * np.ones((g.ny, 1))
info, problems = QA.write_qa_maps("inflow+depth", sys.argv[1], "T1", g, (0.0, 0.0),
                                  (25.0, 0.0), 110.0, radius_m=90.0, model_grid=g,
                                  depth_m=depth, trace=[(25.0, 0.0), (250.0, 10.0)],
                                  basemap="hillshade")
print("MAPS", sorted(k for k in ("inflow_map", "depth_map") if info.get(k)), problems)
"""


class Headless(unittest.TestCase):
    def test_no_matplotlib_and_no_qt_application_do_not_end_the_process(self):
        d = tempfile.mkdtemp(prefix="qa_noapp_")
        try:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            env["PYTHONPATH"] = os.pathsep.join([p for p in (ROOT, env.get("PYTHONPATH", "")) if p])
            r = subprocess.run([sys.executable, "-c", CHILD, d], env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, (r.stdout[-400:], r.stderr[-800:]))
            if "NOQT" in r.stdout:
                self.skipTest("no numpy or Qt in this Python")
            self.assertIn("MAPS ['depth_map', 'inflow_map'] []", r.stdout, r.stderr[-800:])
            from damit_runner.core import qa_maps as QA
            for name in (QA.INFLOW_PNG, QA.DEPTH_PNG):
                with open(os.path.join(d, name), "rb") as fh:
                    self.assertEqual(fh.read(8), PNG)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
