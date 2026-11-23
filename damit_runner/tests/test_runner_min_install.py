"""The Runner plugin loads with only damit_runner + damit_catalog (bundled true_hole.py).

Pre-#111 main (a44b4fb) loaded eleven damit_run algorithms from a Runner+Catalog install.
#111's hard damit_core import broke that; this test pins the restored set.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# Pinned to a44b4fb / tests.test_qgis_integration.test_runner_ported_tools_are_registered.
try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

EXPECTED_ALGORITHMS = [
    "damit_run:animation",
    "damit_run:batch",
    "damit_run:benchmark",
    "damit_run:cascade",
    "damit_run:chainbatch",
    "damit_run:check",
    "damit_run:checkhandoff",
    "damit_run:conditiondem",
    "damit_run:consequences",
    "damit_run:culvertprep",
    "damit_run:delineate",
    "damit_run:estimate",
    "damit_run:fillgaps",
    "damit_run:finishanuga",
    "damit_run:hazardhandoff",
    "damit_run:hecrasexport",
    "damit_run:hecrasimport",
    "damit_run:hydrograph",
    "damit_run:nested",
    "damit_run:nlcdmanning",
    "damit_run:probabilistic",
    "damit_run:products",
    "damit_run:rainfallrunoff",
    "damit_run:rundam",
    "damit_run:selftest",
    "damit_run:sensitivity",
    "damit_run:spillwayadequacy",
    "damit_run:submittal",
    "damit_run:validationrecord",
    "damit_run:verification",
    "damit_run:verifymanifest",
]



def _qgis_python_path():
    """Directories to put on PYTHONPATH so qgis.core imports, excluding this checkout."""
    extra = []
    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        extra.append(os.path.join(conda, "share", "qgis", "python"))
    for pth in (os.environ.get("PYTHONPATH") or "").split(os.pathsep):
        if not pth:
            continue
        ap = os.path.abspath(pth)
        if ap == ROOT or ap.startswith(ROOT + os.sep):
            continue
        extra.append(pth)
    seen = []
    for pth in extra:
        if pth not in seen:
            seen.append(pth)
    import importlib
    old = sys.path[:]
    try:
        sys.path[:0] = seen
        importlib.import_module("qgis.core")
        return seen
    except ImportError:
        return None
    finally:
        sys.path[:] = old


def _min_plugins(tmp):
    plug = os.path.join(tmp, "plugins")
    os.makedirs(plug)
    for pkg in ("damit_runner", "damit_catalog"):
        shutil.copytree(os.path.join(ROOT, pkg), os.path.join(plug, pkg),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    return plug


class RunnerMinInstall(unittest.TestCase):
    @unittest.skipUnless(HAVE_NUMPY, "numpy")
    def test_runner_imports_without_damit_core(self):
        """nodata_sample and impacts import with only Runner + Catalog on the path."""
        tmp = tempfile.mkdtemp(prefix="runner_mininst_")
        self.addCleanup(shutil.rmtree, tmp, True)
        plug = _min_plugins(tmp)
        py = (
            "import os, sys\n"
            "sys.path[:0] = [os.environ['MIN_PLUGINS']]\n"
            "sys.modules.pop('damit_core', None)\n"
            "try:\n"
            "    import damit_core\n"
            "except ImportError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('damit_core must not be importable in this install')\n"
            "import damit_runner.compat.nodata_sample as NDS\n"
            "assert NDS.TRUE_HOLE_MAX_CELLS == 25\n"
            "assert NDS.TRUE_HOLE_CONNECTIVITY == 4\n"
            "import numpy as np\n"
            "a = np.full((5, 5), np.nan); a[1:4, 1:4] = 1.0; a[2, 2] = np.nan\n"
            "m = NDS.true_hole_mask_array(a)\n"
            "assert bool(m[2, 2])\n"
            "import damit_runner.core.impacts as IMP  # noqa: F401\n"
            "print('runner_mininst_ok')\n"
        )
        env = dict(os.environ, MIN_PLUGINS=plug, PYTHONPATH=plug)
        r = subprocess.run([sys.executable, "-c", py], capture_output=True, text=True,
                           env=env, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("runner_mininst_ok", r.stdout)

    def test_runner_min_install_loads_algorithms(self):
        """A Runner + Catalog plugin folder registers the ported damit_run tools."""
        qgis_py = _qgis_python_path()
        if not qgis_py:
            self.skipTest("qgis not importable")
        tmp = tempfile.mkdtemp(prefix="runner_mininst_qgis_")
        self.addCleanup(shutil.rmtree, tmp, True)
        plug = _min_plugins(tmp)
        profile = os.path.join(tmp, "qgis_cfg")
        os.makedirs(profile)
        py = r"""
import os, sys
sys.path[:0] = [os.environ['MIN_PLUGINS']]
sys.modules.pop('damit_core', None)
try:
    import damit_core
except ImportError:
    pass
else:
    raise SystemExit('damit_core must not be importable in this install')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('GDAL_PAM_ENABLED', 'NO')
from qgis.core import QgsApplication
profile = os.environ['QGIS_CUSTOM_CONFIG_PATH']
app = QgsApplication([], False, profile)
app.initQgis()
plug = os.path.join(QgsApplication.pkgDataPath(), 'python', 'plugins')
if plug not in sys.path:
    sys.path.append(plug)
from processing.core.Processing import Processing
Processing.initialize()
import damit_catalog, damit_runner
cat = damit_catalog.classFactory(None)
cat.initGui()
run = damit_runner.classFactory(None)
run.initProcessing()
from damit_runner import provider as RP
assert RP.ENGINE_IMPORT_ERROR is None, RP.ENGINE_IMPORT_ERROR
reg = QgsApplication.processingRegistry()
prov = reg.providerById('damit_run')
assert prov is not None, 'damit_run provider missing'
have = sorted(a.id() for a in prov.algorithms())
want = [
    'damit_run:animation', 'damit_run:batch', 'damit_run:benchmark', 'damit_run:cascade',
    'damit_run:chainbatch', 'damit_run:check', 'damit_run:checkhandoff',
    'damit_run:conditiondem', 'damit_run:consequences', 'damit_run:culvertprep',
    'damit_run:delineate', 'damit_run:estimate', 'damit_run:fillgaps', 'damit_run:finishanuga',
    'damit_run:hazardhandoff', 'damit_run:hecrasexport', 'damit_run:hecrasimport', 'damit_run:hydrograph',
    'damit_run:nested', 'damit_run:nlcdmanning', 'damit_run:probabilistic',
    'damit_run:products', 'damit_run:rainfallrunoff', 'damit_run:rundam',
    'damit_run:selftest', 'damit_run:sensitivity', 'damit_run:spillwayadequacy',
    'damit_run:submittal', 'damit_run:validationrecord', 'damit_run:verification',
    'damit_run:verifymanifest',
]
assert have == want, have
print('runner_mininst_algos_ok', len(have), ','.join(have))
run.unload()
cat.unload()
app.exitQgis()
"""
        env = dict(os.environ, MIN_PLUGINS=plug,
                   PYTHONPATH=os.pathsep.join([plug] + qgis_py),
                   QGIS_CUSTOM_CONFIG_PATH=profile, QT_QPA_PLATFORM="offscreen",
                   GDAL_PAM_ENABLED="NO")
        r = subprocess.run([sys.executable, "-c", py], capture_output=True, text=True,
                           env=env, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("runner_mininst_algos_ok", r.stdout)
        self.assertIn("runner_mininst_algos_ok 31 ", r.stdout)


if __name__ == "__main__":
    unittest.main()
