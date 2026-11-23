"""A table of classes already stored on dam reports. This does not reclassify.

When the same dam has more than one stored class, the row shows the higher one and flags
the disagreement. It never shows a lower class than the highest stored class.
"""


def _ord(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def rows_from_reports(reports):
    """reports: {dam_id, suggested_class, suggested_label, source}."""
    grouped = {}
    order = []
    for rep in reports or []:
        i = rep.get("dam_id") or rep.get("id")
        if i not in grouped:
            grouped[i] = []
            order.append(i)
        grouped[i].append(rep)
    rows = []
    for i in order:
        items = grouped[i]
        ords = [( _ord(it.get("suggested_class")), it) for it in items]
        known = [o for o, _it in ords if o is not None]
        show = max(known) if known else None
        label = None
        for o, it in ords:
            if o == show and it.get("suggested_label"):
                label = it["suggested_label"]
                break
        distinct = sorted(set(known))
        rows.append({"dam_id": i, "suggested_class": show, "suggested_label": label,
                     "n_reports": len(items), "classes_seen": distinct,
                     "review": len(distinct) > 1,
                     "class_lowered": False})
    return {"dams": rows, "class_changed": False}
