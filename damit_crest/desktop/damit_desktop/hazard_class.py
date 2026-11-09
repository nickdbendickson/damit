"""Map a class-of-record value to the DamIT ordinal 0-4 that damit:classify reads as ``current_class``.

The DamIT catalog's ordinal classes (Appendix A): 0 Minimal, 1 Low, 2 Significant, 3 High, 4 Extremely High.
damit:classify's S6 looks ``by_current_class`` up by ``str(current_class)`` and R8 does ``int(current_class)``, so a
free-text class of record such as ``"ND MEDIUM (NID hazard Significant)"`` must become ``2`` before the hand-off.
A value that cannot be mapped gives None, and the caller omits ``current_class`` rather than pass the text on.
"""

from __future__ import annotations

import math
import re

#: (pattern, ordinal), matched on lower-case text. Longer phrases come before the words they contain
#: ("extremely high" before "high", "very low" before "low"); the earliest match in the text wins, so the primary
#: class leads ("ND MEDIUM (NID hazard Significant)" reads MEDIUM first).
LABELS: tuple[tuple[str, int], ...] = (
    (r"\bextremely[\s_-]+high\b", 4),
    (r"\bno[\s_-]+public[\s_-]+hazard\b", 0),
    (r"\bvery[\s_-]+low\b", 0),
    (r"\bminimal\b", 0),
    (r"\bsignificant\b", 2),
    (r"\bintermediate\b", 2),
    (r"\bmedium\b", 2),
    (r"\bmoderate\b", 2),
    (r"\bhigh\b", 3),
    (r"\blow\b", 1),
    # Class A / B / C (e.g. New York): A low, B intermediate, C high. damit:classify already reads "class c" as 3.
    (r"\bclass[\s_-]*a\b", 1),
    (r"\bclass[\s_-]*b\b", 2),
    (r"\bclass[\s_-]*c\b", 3),
)

#: Text that says there is no class to carry over. Checked before the labels.
NO_CLASS = re.compile(r"\b(undetermined|unknown|not[\s_-]+(rated|classified|assigned)|cleared|none|n/?a|review)\b")


def class_ordinal(value) -> int | None:
    """The ordinal 0-4 of a class of record, or None when it cannot be mapped (empty, unknown wording, out of range)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value != int(value):
            return None
        return int(value) if 0 <= value <= 4 else None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if re.fullmatch(r"[0-4](\.0)?", text):
        return int(float(text))
    best: tuple[int, int] | None = None  # (position, ordinal)
    for pattern, ordinal in LABELS:
        m = re.search(pattern, text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), ordinal)
    if best is None:
        return None
    no = NO_CLASS.search(text)
    if no and no.start() < best[0]:
        return None
    return best[1]
