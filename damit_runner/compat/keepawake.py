"""Prevent the OS from sleeping during a long model run.

A no-op context manager when the platform API is not available (the model still
runs; the machine may just sleep). macOS uses IOKit via ctypes; Linux uses
systemd-inhibit or xdg-screensaver when installed.
"""
import contextlib
import logging
import os
import subprocess

LOG = logging.getLogger(__name__)


@contextlib.contextmanager
def keep_awake(reason="DamIT Runner model run"):
    """Context manager: prevent sleep while inside the block, best effort."""
    inhibitor = None
    try:
        if os.name == "posix" and os.uname().sysname == "Darwin":
            # macOS: caffeinate -i (prevent idle sleep)
            inhibitor = subprocess.Popen(["caffeinate", "-i"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "posix":
            # Linux: systemd-inhibit if available
            try:
                inhibitor = subprocess.Popen(
                    ["systemd-inhibit", "--what=idle:sleep", "--who=damit_runner", "--why=" + reason, "sleep", "infinity"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass
    except Exception as exc:
        LOG.debug("keep_awake: could not inhibit sleep: %s", exc)
    try:
        yield
    finally:
        if inhibitor is not None:
            try:
                inhibitor.terminate()
                inhibitor.wait(timeout=2)
            except Exception:
                pass
