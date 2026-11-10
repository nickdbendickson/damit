"""ANUGA 2D refinement engine — stub for Phase 1.

The full ANUGA model (~1,900 lines) will be ported in Phase 4.
For now, ``available()`` returns False so the workflow skips ANUGA
refinement and uses LISFLOOD-FP results directly."""


def available():
    """Whether ANUGA is available for 2D refinement."""
    return False


def run(*args, **kwargs):
    raise NotImplementedError("ANUGA refinement not yet ported (Phase 4)")
