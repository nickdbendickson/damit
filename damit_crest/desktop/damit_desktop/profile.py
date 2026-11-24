"""The desk profile a hand-off job runs under: "us" (the DamIT plugins; the default) or "nd" (North Dakota: the DWR
DamSafety suite, ``nddam:`` / ``ndbreach:`` / ``ndhazard:``).

The page sends its profile (src/lib/crest/profile.ts: Settings, or ``?profile=nd``) with every job and with
``/api/handoff``. The server runs the job inside :func:`profile_scope`, and the hand-off code reads :func:`current`
where the two suites differ: the algorithm ids (algorithms.load_config), the qgis_process that reads the right QGIS
profile (qgis_run.find_qgis_process), the dam ids handed off (handoff.handoff_ids) and the data folder
(layers.find_data_folder). A context variable, so two jobs on two threads never see each other's profile.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

PROFILES = ("us", "nd")

_current: ContextVar[str] = ContextVar("damit_desk_profile", default="us")


def normalize(value) -> str:
    """"nd" for the North Dakota profile, else "us" (anything unknown, missing or malformed)."""
    text = str(value or "").strip().lower()
    return text if text in PROFILES else "us"


def current() -> str:
    return _current.get()


def is_nd() -> bool:
    return _current.get() == "nd"


@contextmanager
def profile_scope(value):
    """Run the block under this profile (normalized), then restore the one before."""
    token = _current.set(normalize(value))
    try:
        yield _current.get()
    finally:
        _current.reset(token)
