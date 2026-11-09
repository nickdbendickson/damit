"""DamIT Crest desktop entry. `python run.py` from this folder (Python 3.10 or newer)."""

import sys

if sys.version_info[:2] < (3, 10):
    sys.exit(f"DamIT Crest desktop needs Python 3.10 or newer (this is {sys.version.split()[0]}).")

from damit_desktop.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
