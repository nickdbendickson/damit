"""Flagged structures: inventory records that are not a dam to breach.

DamIT's copy of the DamSafety suite library module (DamSafety Core damsuite/structure_flags.py): the same
functions, with an EMPTY list. DamSafety ships North Dakota's flagged records (a highway fill listed as a dam);
DamIT covers every state and ships none, so no dam is refused here. The ported Runner tools (batch, sensitivity,
cascade ...) call lookup() before a run; it returns None. To flag a structure for your own agency, append an entry
with every key of REQUIRED to FLAGS (ids: an NID id such as 'ND00597'; `dwr_id` is the state's own id).

Pure Python, no QGIS, no Qt.
"""
import os
import re

CLASS_ROAD_FILL_BACKWATER = "road_fill_backwater"
CLASS_LABELS = {CLASS_ROAD_FILL_BACKWATER: "road fill over backwater"}
ENV_ALLOW = "ALLOW_FLAGGED_STRUCTURE"
HAZARDS = ("Low", "Significant", "High")
REQUIRED = ("dwr_id", "nid_id", "name", "structure_class", "hazard", "hazard_source",
            "breach_analysis", "reason", "evidence", "date", "decided_by")

FLAGS = ()          # DamIT: no state's flagged list is shipped

_DWR_RX = re.compile(r"^(?:DWR)?[-_ ]?0*(\d+)$")
_NID_RX = re.compile(r"^(?:NID[-_ ]?)?([A-Z]{2}\d{5})$")


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip().upper()
    return "" if s in ("NULL", "NONE") else s


def _keys(dam_id=None, nid_id=None, structure_id=None):
    """The set of normalized keys ('DWR:3161', 'NID:ND00597') the given ids stand for."""
    out = set()
    for v in (dam_id, nid_id, structure_id):
        s = _clean(v)
        if not s:
            continue
        m = _DWR_RX.match(s)
        if m:
            out.add("DWR:" + m.group(1).lstrip("0"))
            continue
        m = _NID_RX.match(s)
        if m:
            out.add("NID:" + m.group(1))
    return out


def entry_keys(entry):
    return _keys(entry.get("dwr_id"), entry.get("nid_id"), entry.get("structure_id"))


def lookup(dam_id=None, nid_id=None, structure_id=None, flags=None):
    """The flag entry (a copy of the dict) for a dam given by any of its ids, else None.

    dam_id may be 'DWR-3161', '3161' (a DWR structure id, as folder names and Screening's
    'Only these dams' use it), 'ND00597' or 'NID-ND00597'; nid_id an NID id; structure_id a
    DWR structure id. Never raises."""
    try:
        want = _keys(dam_id, nid_id, structure_id)
        if not want:
            return None
        for e in (FLAGS if flags is None else flags):
            if entry_keys(e) & want:
                return dict(e)
    except Exception:                                  # noqa  (a flag check never fails a run)
        return None
    return None


def lookup_folder(folder, record=None, flags=None):
    """The flag for a dam folder: its name, and the dam.json record's dam_id / nid_id when a
    record (damsuite.dam_record.DamRecord or a dict) is given."""
    ids = [os.path.basename(os.path.normpath(folder or ""))]
    if record is not None:
        for k in ("dam_id", "nid_id", "structure_id"):
            try:
                ids.append(record.get(k))
            except Exception:                          # noqa
                pass
    for i in ids:
        e = lookup(i, flags=flags)
        if e:
            return e
    return None


def label(entry):
    return CLASS_LABELS.get(entry.get("structure_class"), str(entry.get("structure_class") or
                                                              "flagged structure"))


def note(entry):
    """'road fill over backwater; breach analysis not applicable; hazard Low (DWR record)'."""
    return "{}; breach analysis {}; hazard {} ({})".format(
        label(entry), entry.get("breach_analysis") or "not applicable", entry.get("hazard"),
        entry.get("hazard_source") or "record")


def short_ref(entry):
    return "{} / {}".format(entry.get("dwr_id"), entry.get("nid_id"))


def allowed(option=None, env=None):
    """True when a flagged structure may be run anyway: the option, or ALLOW_FLAGGED_STRUCTURE
    = 1 / true / yes / on in the environment."""
    if option:
        return True
    v = str((os.environ if env is None else env).get(ENV_ALLOW, "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def refusal(entry, what="breach run", dam_id=None, how=None):
    """The message a tool stops with for a flagged structure."""
    how = how or "the ALLOW_FLAGGED_STRUCTURE parameter or the environment variable {}=1".format(
        ENV_ALLOW)
    return ("{} ({}, {}) is a flagged structure: {}. {}: no {}. Reason: {} To run it anyway "
            "(for information only; the hazard of record stays {}), set {}. ".format(
                dam_id or entry.get("dwr_id"), entry.get("name"), short_ref(entry), note(entry),
                "Not modelled" if "run" in what else "Not classified", what,
                entry.get("reason"), entry.get("hazard"), how))


def overridden_text(entry, dam_id=None):
    return ("FLAGGED STRUCTURE (run allowed by ALLOW_FLAGGED_STRUCTURE): {} ({}) is a {}. The "
            "hazard of record is {} ({}); the results of this run are for information only."
            .format(dam_id or entry.get("dwr_id"), short_ref(entry), note(entry),
                    entry.get("hazard"), entry.get("hazard_source")))


def problems(flags=None):
    """[] when every entry is complete and no two entries share an id."""
    out, seen = [], {}
    for i, e in enumerate(FLAGS if flags is None else flags):
        for k in REQUIRED:
            if not str(e.get(k) or "").strip():
                out.append("entry {}: {} is empty".format(i, k))
        if e.get("structure_class") not in CLASS_LABELS:
            out.append("entry {}: unknown structure_class {!r}".format(i, e.get("structure_class")))
        if e.get("hazard") not in HAZARDS:
            out.append("entry {}: hazard {!r} is not one of {}".format(i, e.get("hazard"), HAZARDS))
        ks = entry_keys(e)
        if not any(k.startswith("DWR:") for k in ks) and not any(k.startswith("NID:") for k in ks):
            out.append("entry {}: no usable DWR or NID id".format(i))
        for k in ks:
            if k in seen:
                out.append("entry {}: {} also in entry {}".format(i, k, seen[k]))
            seen[k] = i
    return out
