"""Depth change between two samples. A review list only. No class is computed.

creep_watch is the same comparison stored as a watch: the later sample against the
sample already on file. quick_creep is that comparison for one new structures sample,
without running a model.
"""


def depth_change(rows, threshold_ft=0.0):
    """rows: {id, depth_before_ft, depth_after_ft}. Flag where the depth rose by more
    than threshold_ft. A drop is listed and is not a lower class, because no class is set."""
    flagged = []
    dropped = []
    for row in rows or []:
        try:
            before = float(row.get("depth_before_ft"))
            after = float(row.get("depth_after_ft"))
        except (TypeError, ValueError):
            continue
        delta = after - before
        item = {"id": row.get("id"), "depth_before_ft": before, "depth_after_ft": after,
                "delta_ft": delta}
        if delta > float(threshold_ft):
            flagged.append(item)
        elif delta < -float(threshold_ft):
            dropped.append(item)
    return {"increased": flagged, "decreased": dropped, "n_increased": len(flagged),
            "n_decreased": len(dropped), "threshold_ft": float(threshold_ft),
            "class_changed": False}


def watch(stored_rows, new_rows, threshold_ft=0.0):
    """Match on id. Missing ids are skipped, not invented."""
    new = {r.get("id"): r for r in new_rows or []}
    paired = []
    for old in stored_rows or []:
        nxt = new.get(old.get("id"))
        if nxt is None:
            continue
        paired.append({"id": old.get("id"),
                       "depth_before_ft": old.get("depth_ft", old.get("depth_before_ft")),
                       "depth_after_ft": nxt.get("depth_ft", nxt.get("depth_after_ft"))})
    return depth_change(paired, threshold_ft)
