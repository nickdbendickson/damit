"""Recompute a saved classification. The published class is the higher of the two.

A recompute that would be lower is a review flag. It is not published.
"""


def published_class(saved, recomputed):
    """The class to publish. None stays None. Otherwise the higher ordinal (never lower)."""
    def _ord(v):
        if v is None or v == "":
            return None
        return int(v)
    a, b = _ord(saved), _ord(recomputed)
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def compare(saved, recomputed):
    """saved and recomputed are integer classes (0-4) or None."""
    published = published_class(saved, recomputed)
    would_lower = False
    try:
        would_lower = recomputed is not None and saved is not None and int(recomputed) < int(saved)
    except (TypeError, ValueError):
        would_lower = False
    raised = False
    try:
        raised = recomputed is not None and saved is not None and int(recomputed) > int(saved)
    except (TypeError, ValueError):
        raised = False
    return {"saved_class": saved, "recomputed_class": recomputed,
            "published_class": published, "would_lower": would_lower, "raised": raised,
            "class_lowered": False,
            "note": ("recompute is lower than the saved class; the published class stays "
                     "the saved class" if would_lower else
                     "recompute is higher; the published class is the higher one" if raised else
                     "recompute matches the saved class" if saved == recomputed else
                     "one side had no class; the published class is the one that exists")}
