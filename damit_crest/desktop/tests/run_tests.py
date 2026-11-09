"""Run every desktop test (headless; fake qgis_process; no QGIS, model, screening or Wine is started).

    python3 damit_crest/desktop/tests/run_tests.py      # or: npm run test:desktop
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
