"""DamIT Catalog loader (pure Python, no QGIS).

The data files in ``data/`` are the single source of truth for Appendix A of
"US Dam Hazard Classification - Corrected Edition" (2026-11-09): methods M1-M13,
scenarios S1-S7, domain cutoffs D1-D2, modifiers R1-R10, the class-label
normalization table and the jurisdiction presets. Nothing numeric lives in this
module; only ID formats are validated here.

Override the data folder (to update presets without a plugin release) with the
``DAMIT_CATALOG_DIR`` environment variable or the ``data_dir`` argument.

Preset IDs may have aliases (``presets.json`` "aliases", e.g. USBR_TM11 -> USBR): every
lookup by preset ID accepts an alias and a resolved config records the stored ID.
The optional ``hazard`` file (``hazard.json``) holds the DamIT Hazard classifier's engine
profile: structure the Appendix A files do not express (receptor-type vocabulary, TM-11
chart assignment, sampling defaults); it never repeats a threshold of the other files.
"""
import copy
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(HERE, "data")
ENV_DIR = "DAMIT_CATALOG_DIR"

MODE_PRESET = "preset"
MODE_CUSTOM = "custom"
MODES = (MODE_PRESET, MODE_CUSTOM)

# ID format validation only (the IDs themselves come from the data files)
METHOD_ID_RE = re.compile(r"^M(?:[1-9]|1[0-9])[a-z]?$")
SCENARIO_ID_RE = re.compile(r"^S[1-9][0-9]?$")
CUTOFF_ID_RE = re.compile(r"^D[1-9][0-9]?$")
MODIFIER_ID_RE = re.compile(r"^R(?:[1-9]|[1-9][0-9])$")
PRESET_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
STRENGTHS = ("rule", "advisory")
OPTIONAL_FILES = ("hazard",)    # manifest "files" entries that may be absent
FALLBACK_METHOD = "M13"          # the document's fallback for a dash; checked to exist in the data


class CatalogError(ValueError):
    """The catalog data files are missing, malformed or inconsistent."""


def data_dir(explicit=None):
    d = explicit or os.environ.get(ENV_DIR) or DEFAULT_DATA_DIR
    return os.path.abspath(d)


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise CatalogError("cannot read catalog file {}: {}".format(path, e))


def _sort_key(mid):
    m = re.match(r"^([A-Z])(\d+)([a-z]?)$", mid)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (mid, 0, "")


class Catalog(object):
    """The loaded catalog. Use :func:`load`."""

    def __init__(self, folder, manifest, parts, digest):
        self.folder = folder
        self.manifest = manifest
        self.methods = parts["methods"]["methods"]
        self.datums = parts["methods"].get("datums", {})
        self.scenarios = parts["scenarios"]["scenarios"]
        self.domain_cutoffs = parts["scenarios"].get("domain_cutoffs", {})
        self.dam_fields_all = list(parts["scenarios"].get("dam_fields_all") or [])
        self.modifiers = parts["modifiers"]["modifiers"]
        self.labels = parts["labels"]
        self.presets = parts["presets"]["presets"]
        self.preset_aliases = dict(parts["presets"].get("aliases") or {})
        self.hazard = parts.get("hazard") or {}
        self.dash_rule = parts["presets"].get("dash_rule", "")
        self.combination = manifest.get("combination", {})
        self.disclaimer = manifest.get("disclaimer", "")
        self.version = manifest.get("catalog_version", "")
        self.source = manifest.get("source", {})
        self.digest = digest

    # ---- identity -------------------------------------------------------
    def identity(self):
        """What a run records about the catalog it used."""
        return {"catalog_version": self.version, "source": self.source, "sha256": self.digest,
                "folder": self.folder}

    def method_ids(self):
        return sorted(self.methods, key=_sort_key)

    def scenario_ids(self):
        return sorted(self.scenarios, key=_sort_key)

    def modifier_ids(self):
        return sorted(self.modifiers, key=_sort_key)

    def cutoff_ids(self):
        return sorted(self.domain_cutoffs, key=_sort_key)

    def preset_ids(self):
        return list(self.presets)

    def canonical_preset_id(self, preset_id):
        """The stored preset ID for an ID or alias (case-sensitive), or None if unknown."""
        if preset_id in self.presets:
            return preset_id
        target = self.preset_aliases.get(preset_id)
        return target if target in self.presets else None

    def has_preset(self, preset_id):
        return self.canonical_preset_id(preset_id) is not None

    def preset(self, preset_id):
        """The preset record for an ID or alias. Raises CatalogError if unknown."""
        pid = self.canonical_preset_id(preset_id)
        if pid is None:
            raise CatalogError(_unknown_preset(self, preset_id))
        return self.presets[pid]

    def generic_label(self, ordinal):
        return self.labels["ordinals"].get(str(int(ordinal)), str(ordinal))

    # ---- resolution -----------------------------------------------------
    def resolve_preset(self, preset_id, scenario_ids=None, extra_overrides=None):
        """The run configuration for a preset: scenarios, merged method params and strengths,
        modifiers, label map and flags. ``scenario_ids`` replaces the preset's scenarios (needed
        when the preset has none confirmed)."""
        requested = preset_id
        preset_id = self.canonical_preset_id(preset_id)
        if preset_id is None:
            raise CatalogError(_unknown_preset(self, requested))
        pr = self.presets[preset_id]
        flags = []
        method_over = copy.deepcopy(pr.get("methods") or {})
        if not method_over or not pr.get("methods_confirmed", True):
            flags.append(_flag("method_fallback_m13", "No confirmed method for this preset: falling back to "
                               "{} and engineering judgment.".format(FALLBACK_METHOD)))
            method_over.setdefault(FALLBACK_METHOD, {})
        for mid, ov in (extra_overrides or {}).items():
            method_over.setdefault(mid, {}).update(ov or {})
        methods = self._merge_methods(method_over, flags)
        for mid, status in (pr.get("verification") or {}).items():
            if mid in methods:
                methods[mid]["verification"] = status
                flags.append(_flag("unverified_or_secondary", "{} is marked ({}) for this preset; confirm before "
                                   "relying on it.".format(mid, status), method=mid))
        scen = list(scenario_ids) if scenario_ids else list(pr.get("scenarios") or [])
        if not scen:
            flags.append(_flag("scenario_unconfirmed", "The document confirms no scenario for this preset{}; "
                               "choose one explicitly.".format(
                                   " (" + pr["scenario_note"] + ")" if pr.get("scenario_note") else "")))
        elif not pr.get("scenarios_confirmed", True) and not scenario_ids:
            flags.append(_flag("scenario_unconfirmed", "Scenario not confirmed by the document."))
        for cs in pr.get("conditional_scenarios") or []:
            flags.append(_flag("unverified_or_secondary" if cs.get("verification") else "conditional_scenario",
                               "Conditional scenario {} ({}){}.".format(
                                   cs["id"], cs.get("when", ""),
                                   ", " + cs["verification"] if cs.get("verification") else "")))
        scenarios = self._scenarios(scen, pr.get("scenario_overrides") or {})
        modifiers = self._modifiers(pr.get("modifiers") or [], pr.get("modifier_overrides") or {})
        cutoffs = self._cutoffs(pr.get("domain_cutoffs") or [])
        label_map = {str(k): v for k, v in (pr.get("label_map") or {}).items()}
        return {"mode": MODE_PRESET, "preset_id": preset_id, "requested_preset_id": requested,
                "preset_label": pr.get("label", preset_id),
                "citation": pr.get("citation", ""), "scenarios": scenarios, "domain_cutoffs": cutoffs,
                "methods": methods, "modifiers": modifiers, "label_map": label_map,
                "labels": list(pr.get("labels") or []),
                "conditional_scenarios": copy.deepcopy(pr.get("conditional_scenarios") or []),
                "notes": pr.get("notes", ""), "flags": flags, "catalog": self.identity()}

    def resolve_custom(self, method_ids, scenario_ids=None, modifier_ids=None, cutoff_ids=None,
                       param_overrides=None):
        """Custom mode: method IDs ticked with no state/agency names; generic labels."""
        flags = []
        ids = [m for m in (method_ids or []) if m]
        if not ids:
            flags.append(_flag("method_fallback_m13", "No method ticked: falling back to {} and engineering "
                               "judgment.".format(FALLBACK_METHOD)))
            ids = [FALLBACK_METHOD]
        over = {m: dict((param_overrides or {}).get(m) or {}) for m in ids}
        methods = self._merge_methods(over, flags)
        for m in methods.values():                 # no branding in custom mode
            m.pop("source", None)
        scen = list(scenario_ids or [])
        if not scen:
            flags.append(_flag("scenario_unconfirmed", "No scenario chosen."))
        label_map = {k: v for k, v in self.labels["ordinals"].items()}
        return {"mode": MODE_CUSTOM, "preset_id": None, "preset_label": "Custom", "citation": "",
                "scenarios": self._scenarios(scen, {}, brand=False),
                "domain_cutoffs": self._cutoffs(cutoff_ids or [], brand=False),
                "methods": methods, "modifiers": self._modifiers(modifier_ids or [], {}, brand=False),
                "label_map": label_map, "labels": [label_map[k] for k in sorted(label_map)],
                "conditional_scenarios": [], "notes": "", "flags": flags, "catalog": self.identity()}

    def citations(self, config):
        """Source citations for every ID in a resolved config (for the run report, custom mode too)."""
        out = {}
        for mid in config.get("methods", {}):
            out[mid] = self.methods.get(mid, {}).get("source", "")
        for s in config.get("scenarios", []):
            out[s["id"]] = self.scenarios.get(s["id"], {}).get("source", "")
        for r in config.get("modifiers", []):
            out[r["id"]] = self.modifiers.get(r["id"], {}).get("source", "")
        for d in config.get("domain_cutoffs", []):
            out[d["id"]] = self.domain_cutoffs.get(d["id"], {}).get("source", "")
        return out

    # ---- helpers --------------------------------------------------------
    def _merge_methods(self, overrides, flags):
        out = {}
        for mid in sorted(overrides, key=_sort_key):
            if mid not in self.methods:
                raise CatalogError("unknown method {!r}".format(mid))
            base = copy.deepcopy(self.methods[mid])
            ov = dict(overrides[mid] or {})
            strength = ov.pop("strength", None)
            params = dict(base.get("params") or {})
            params.update(ov)
            base["params"] = params
            base["id"] = mid
            if strength:
                if strength not in STRENGTHS:
                    raise CatalogError("{}: strength must be one of {}".format(mid, STRENGTHS))
                base["strength"] = strength
            if base.get("evaluation") == "manual":
                flags.append(_flag("manual_method", "{} ({}) needs engineering judgment; it is not evaluated "
                                   "automatically.".format(mid, base["name"]), method=mid))
            out[mid] = base
        return out

    def _scenarios(self, ids, overrides, brand=True):
        out = []
        for sid in ids:
            if sid not in self.scenarios:
                raise CatalogError("unknown scenario {!r}".format(sid))
            s = copy.deepcopy(self.scenarios[sid])
            s.update(copy.deepcopy(overrides.get(sid) or {}))
            s["id"] = sid
            if not brand:
                s.pop("source", None)
            out.append(s)
        return out

    def _modifiers(self, ids, overrides, brand=True):
        out = []
        for rid in ids:
            if rid not in self.modifiers:
                raise CatalogError("unknown modifier {!r}".format(rid))
            r = copy.deepcopy(self.modifiers[rid])
            ov = copy.deepcopy(overrides.get(rid) or {})
            if "params" in ov:
                p = dict(r.get("params") or {})
                p.update(ov.pop("params"))
                r["params"] = p
            r.update(ov)
            r["id"] = rid
            if not brand:
                r.pop("source", None)
            out.append(r)
        return out

    def _cutoffs(self, ids, brand=True):
        out = []
        for did in ids:
            if did not in self.domain_cutoffs:
                raise CatalogError("unknown domain cutoff {!r}".format(did))
            d = copy.deepcopy(self.domain_cutoffs[did])
            d["id"] = did
            if not brand:
                d.pop("source", None)
            out.append(d)
        return out


def _unknown_preset(cat, preset_id):
    known = ", ".join(cat.presets)
    if cat.preset_aliases:
        known += " (aliases: {})".format(", ".join("{} = {}".format(a, t) for a, t in cat.preset_aliases.items()))
    return "unknown preset {!r}; known: {}".format(preset_id, known)


def _flag(code, message, method=None, receptor=None, scenario=None):
    f = {"code": code, "message": message}
    if method:
        f["method"] = method
    if receptor is not None:
        f["receptor"] = receptor
    if scenario:
        f["scenario"] = scenario
    return f


def validate(parts):
    """Structural and cross-reference checks; returns a list of problems (empty = valid)."""
    errs = []
    methods = parts["methods"].get("methods") or {}
    scen = parts["scenarios"].get("scenarios") or {}
    cut = parts["scenarios"].get("domain_cutoffs") or {}
    mods = parts["modifiers"].get("modifiers") or {}
    presets = parts["presets"].get("presets") or {}
    for mid, m in methods.items():
        if not METHOD_ID_RE.match(mid):
            errs.append("bad method id {!r}".format(mid))
        for k in ("name", "inputs", "params", "returns", "strength", "source", "verification"):
            if k not in m:
                errs.append("{}: missing {}".format(mid, k))
        if m.get("strength") not in STRENGTHS:
            errs.append("{}: strength {!r}".format(mid, m.get("strength")))
    for sid in scen:
        if not SCENARIO_ID_RE.match(sid):
            errs.append("bad scenario id {!r}".format(sid))
    for did in cut:
        if not CUTOFF_ID_RE.match(did):
            errs.append("bad cutoff id {!r}".format(did))
    for rid in mods:
        if not MODIFIER_ID_RE.match(rid):
            errs.append("bad modifier id {!r}".format(rid))
    if FALLBACK_METHOD not in methods:
        errs.append("fallback method {} missing".format(FALLBACK_METHOD))
    ordinals = (parts["labels"].get("ordinals") or {})
    for pid, p in presets.items():
        if not PRESET_ID_RE.match(pid):
            errs.append("bad preset id {!r}".format(pid))
        for k in ("label", "scenarios", "methods", "modifiers", "labels", "label_map"):
            if k not in p:
                errs.append("{}: missing {}".format(pid, k))
        for s in p.get("scenarios") or []:
            if s not in scen:
                errs.append("{}: unknown scenario {}".format(pid, s))
        for m in p.get("methods") or {}:
            if m not in methods:
                errs.append("{}: unknown method {}".format(pid, m))
        for r in p.get("modifiers") or []:
            if r not in mods:
                errs.append("{}: unknown modifier {}".format(pid, r))
        for d in p.get("domain_cutoffs") or []:
            if d not in cut:
                errs.append("{}: unknown cutoff {}".format(pid, d))
        for k in (p.get("label_map") or {}):
            if str(k) not in ordinals:
                errs.append("{}: label_map ordinal {} not in labels.json".format(pid, k))
    for alias, target in (parts["presets"].get("aliases") or {}).items():
        if not PRESET_ID_RE.match(str(alias)):
            errs.append("bad preset alias {!r}".format(alias))
        if alias in presets:
            errs.append("preset alias {} is also a stored preset ID".format(alias))
        if target not in presets:
            errs.append("preset alias {} points to unknown preset {!r}".format(alias, target))
    hz = parts.get("hazard")
    if hz is not None:
        aliases = parts["presets"].get("aliases") or {}
        for pid in (hz.get("presets") or {}):
            if pid not in presets and aliases.get(pid) not in presets:
                errs.append("hazard.json: unknown preset {}".format(pid))
        for mid in (hz.get("methods") or {}):
            if mid not in methods:
                errs.append("hazard.json: unknown method {}".format(mid))
        for rid in (hz.get("modifiers") or {}):
            if rid not in mods:
                errs.append("hazard.json: unknown modifier {}".format(rid))
    return errs


def load(folder=None):
    """Load and validate the catalog. Raises CatalogError on any problem."""
    folder = data_dir(folder)
    manifest = _read(os.path.join(folder, "catalog.json"))
    files = manifest.get("files") or {}
    parts = {}
    h = hashlib.sha256()
    for key in ("methods", "scenarios", "modifiers", "labels", "presets"):
        name = files.get(key)
        if not name or os.path.basename(name) != name:
            raise CatalogError("catalog.json: bad file entry for {}".format(key))
        path = os.path.join(folder, name)
        parts[key] = _read(path)
        with open(path, "rb") as fh:
            h.update(fh.read())
    for key in OPTIONAL_FILES:                     # optional parts (DamIT Hazard's engine profile)
        name = files.get(key)
        if not name:
            continue
        if os.path.basename(name) != name:
            raise CatalogError("catalog.json: bad file entry for {}".format(key))
        path = os.path.join(folder, name)
        parts[key] = _read(path)
        with open(path, "rb") as fh:
            h.update(fh.read())
    errs = validate(parts)
    if errs:
        raise CatalogError("catalog invalid: " + "; ".join(errs[:20]))
    return Catalog(folder, manifest, parts, h.hexdigest())
