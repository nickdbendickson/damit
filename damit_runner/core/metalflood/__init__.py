"""Boann's flood engine is vendored once, byte-identical, at damit_runner/boann/hydro (pinned to
DWR_Plugins' DamSafety_Core/boann by damit_runner/BOANN.lock, DamIT Runner 0.11.0). This shim makes
`damit_runner.core.metalflood` that very package (compat/alias.py), so the old import path and
`python -m damit_runner.core.metalflood...` keep working. Nothing else may live in this folder
(tests/test_boann_lock.py checks)."""
from ...compat import alias as _alias
_alias.install(__name__, "damit_runner.boann.hydro")
