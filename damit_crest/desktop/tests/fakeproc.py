"""Fake executables for the headless desk tests.

The desk launches qgis_process as a program. A shebang script runs on Linux and
macOS. Windows cannot start an extensionless script (WinError 193), so there the
fake is a .cmd that runs the same script with this Python.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def write_exe(path: Path, text: str) -> Path:
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#!"))
    if os.name == "nt":
        # Windows cannot start an extensionless script. Write a .py; the desk runs a .py with this Python.
        script = path if path.suffix == ".py" else path.with_suffix(".py")
        script.write_text(body + "\n", encoding="utf-8")
        return script
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def pin_home(env: dict, home: Path) -> None:
    """Make Path.home() and expanduser('~') land in the test home on every OS."""
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
