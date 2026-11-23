"""Dams in series: a review flag when an upstream depth reaches a downstream dam.

The flag does not change either dam's class.
"""


def screen(dams):
    """dams: {id, suggested_class, reaches: [downstream ids]}.

    `reaches` lists downstream dams whose location is wet in this dam's depth raster
    (the caller sampled that; this function does not read a raster). Classes are copied
    through. Each downstream id that is reached gets a review flag.
    """
    by_id = {}
    order = []
    for d in dams or []:
        i = d.get("id")
        by_id[i] = {"id": i, "suggested_class": d.get("suggested_class"),
                    "reached_by": [], "reaches": list(d.get("reaches") or [])}
        order.append(i)
    for d in by_id.values():
        for down in d["reaches"]:
            if down in by_id and down != d["id"]:
                by_id[down]["reached_by"].append(d["id"])
    rows = []
    for i in order:
        row = by_id[i]
        row["review"] = bool(row["reached_by"])
        row["class_changed"] = False
        rows.append(row)
    return {"dams": rows, "class_changed": False,
            "n_flagged": sum(1 for r in rows if r["review"])}
