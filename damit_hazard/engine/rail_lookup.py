"""Trains per day for rail lines whose layer has no trains-per-day field (0.1.2).

NARN (the national rail network) carries no trains-per-day attribute, so M9a's High test (10+ freight trains or a
passenger line) cannot be confirmed from it and an impacted active line stays Medium. DamSafety scored the
DWR-2801 BNSF KO subdivision High at 15 trains a day. DamIT ships NO default value: the number has to come from
the user, as an explicit input:

    RAIL_TRAINS_LOOKUP (damit:classify): a CSV with the columns
        field, value, trains_per_day, source
    e.g.  SUBDIV,KO,15,"DamSafety 2801 pass (BNSF KO subdivision) - needs Nick's ruling"

A rail line whose own trains_per_day is empty and whose attribute <field> equals <value> (case-insensitive,
first matching row wins) gets that number. Every value applied this way is flagged in the report
(trains_lookup, needs Nick's ruling) so a High that rests on it is never silent. A row without a source is
refused.
"""
import csv

COLUMNS = ("field", "value", "trains_per_day", "source")
RULING_NOTE = "needs Nick's ruling"


class LookupError_(ValueError):
    pass


def _key(s):
    return str(s or "").strip().lower()


def load(path):
    """The lookup rows [{'field', 'value', 'trains_per_day', 'source'}] from a CSV (see the module doc)."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        cols = {_key(c): c for c in (rd.fieldnames or [])}
        missing = [c for c in COLUMNS if c not in cols]
        if missing:
            raise LookupError_("rail trains lookup {}: missing column(s) {} (need {})".format(
                path, ", ".join(missing), ", ".join(COLUMNS)))
        for n, r in enumerate(rd, start=2):
            g = {c: (r.get(cols[c]) or "").strip() for c in COLUMNS}
            if not any(g.values()):
                continue
            try:
                t = float(g["trains_per_day"])
            except ValueError:
                raise LookupError_("rail trains lookup {} line {}: trains_per_day {!r} is not a number".format(
                    path, n, g["trains_per_day"]))
            if t < 0 or t != t:
                raise LookupError_("rail trains lookup {} line {}: trains_per_day must be 0 or more".format(path, n))
            if not g["field"] or not g["source"]:
                raise LookupError_("rail trains lookup {} line {}: field and source are required".format(path, n))
            rows.append({"field": g["field"], "value": g["value"], "trains_per_day": t, "source": g["source"]})
    return rows


def apply(receptors, rows):
    """Fill trains_per_day on rail receptors that have none from the first matching row; marks them
    trains_source / trains_needs_ruling. Returns how many were filled."""
    n = 0
    for r in receptors:
        if r.get("kind") != "rail" or r.get("trains_per_day") is not None:
            continue
        raw = {_key(k): v for k, v in (r.get("raw") or {}).items()}
        for row in rows or []:
            v = raw.get(_key(row["field"]))
            if v is not None and _key(v) == _key(row["value"]):
                r["trains_per_day"] = row["trains_per_day"]
                r["trains_source"] = "{} ({} = {})".format(row["source"], row["field"], row["value"])
                r["trains_needs_ruling"] = True
                n += 1
                break
    return n
