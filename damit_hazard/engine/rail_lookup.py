"""Trains per day for rail lines whose layer has no trains-per-day field.

NARN (the national rail network) carries no trains-per-day attribute, so M9a's High test (10+ freight trains or a
passenger line) cannot be confirmed from it. DamSafety scored the DWR-2801 BNSF KO subdivision High at 15 trains a
day (NARN RROWNER1 = BNSF, SUBDIV = KO, the fields DamSafety Hazard Lite reads).

0.1.3: DamIT Hazard ships that one row as its default lookup, data/rail_trains_lookup.csv (Nick's ruling,
2026-11-10). It is used when no RAIL_TRAINS_LOOKUP is given; an explicit RAIL_TRAINS_LOOKUP replaces it entirely.

    RAIL_TRAINS_LOOKUP (damit:classify): a CSV with the columns
        field, value, trains_per_day, source [, ruling]
    e.g.  RROWNER1&SUBDIV,BNSF&KO,15,"DamSafety value, Nick ruling 2026-11-10",2026-11-10

`field` / `value` may join several conditions with '&' (all must match, case-insensitive); the first matching row
wins and only fills a line whose own trains_per_day is empty. A row with a `ruling` (the shipped default) is a
ruled value: reported as INFO trains_lookup_ruled. A row without one (any user lookup that does not give a ruling)
is flagged trains_lookup, "needs Nick's ruling". Lines no row matches keep the trains_unknown warning. A row
without a source is refused.
"""
import csv
import os

COLUMNS = ("field", "value", "trains_per_day", "source")
RULING_NOTE = "needs Nick's ruling"
DEFAULT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                            "rail_trains_lookup.csv")


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
            ruling = (r.get(cols["ruling"]) or "").strip() if "ruling" in cols else ""
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
            fields, values = g["field"].split("&"), g["value"].split("&")
            if len(fields) != len(values) or not all(f.strip() for f in fields):
                raise LookupError_("rail trains lookup {} line {}: field and value need the same number of "
                                   "'&'-joined parts".format(path, n))
            row = {"field": g["field"], "value": g["value"], "trains_per_day": t, "source": g["source"]}
            if ruling:
                row["ruling"] = ruling
            rows.append(row)
    return rows


def default_rows():
    """The shipped lookup (DEFAULT_FILE): BNSF KO at 15 trains a day (DamSafety value, Nick ruling 2026-11-10)."""
    return load(DEFAULT_FILE)


def rows_for(path=None):
    """(rows, where): the explicit lookup when a path is given (it wins), else the shipped default."""
    if path:
        return load(path), path
    return default_rows(), "DamIT Hazard default ({})".format(os.path.basename(DEFAULT_FILE))


def _matches(raw, row):
    pairs = zip(row["field"].split("&"), row["value"].split("&"))
    for f, v in pairs:
        got = raw.get(_key(f))
        if got is None or _key(got) != _key(v):
            return False
    return True


def apply(receptors, rows):
    """Fill trains_per_day on rail receptors that have none from the first matching row; marks them
    trains_source and, unless the row carries a ruling, trains_needs_ruling. Returns how many were filled."""
    n = 0
    for r in receptors:
        if r.get("kind") != "rail" or r.get("trains_per_day") is not None:
            continue
        raw = {_key(k): v for k, v in (r.get("raw") or {}).items()}
        for row in rows or []:
            if _matches(raw, row):
                r["trains_per_day"] = row["trains_per_day"]
                r["trains_source"] = "{} ({} = {})".format(row["source"], row["field"], row["value"])
                r["trains_needs_ruling"] = not row.get("ruling")
                r["trains_ruling"] = row.get("ruling")
                n += 1
                break
    return n
