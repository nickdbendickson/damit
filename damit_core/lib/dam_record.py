"""Dam records: map a layer's field names onto the DamIT Screener dam fields.

The DamIT dam fields are DamIT Screener's ``DAM_FIELDS`` (feet, acre-feet); the alias table below
only recognizes common field spellings (the National Inventory of Dams export and generic names)
so DamIT Setup can propose a ``FIELD_MAP`` for ``damit_screen:preflight``. It holds no thresholds.
"""
import re

DAM_FIELDS = ("dam_id", "name", "height_ft", "storage_acft", "top_of_dam_elev_ft", "normal_pool_elev_ft",
              "emergency_spillway_elev_ft", "pmf_peak_elev_ft", "peak_pool_100yr_elev_ft", "existing_class",
              "new_or_existing", "breach_azimuth_deg", "surface_area_ac", "storage_curve_csv",
              "hydrograph_csv", "flood_hydrograph_csv", "breach_locations", "downstream_dam_class")

ALIASES = {
    "dam_id": ("dam_id", "nidid", "nid_id", "federal_id", "federalid", "state_id", "stateid", "damid", "id"),
    "name": ("name", "dam_name", "damname"),
    "height_ft": ("height_ft", "nid_height", "dam_height", "height", "nidheight"),
    "storage_acft": ("storage_acft", "nid_storage", "max_storage", "storage", "nidstorage"),
    "top_of_dam_elev_ft": ("top_of_dam_elev_ft", "crest_elev", "top_elev", "crest_elevation"),
    "normal_pool_elev_ft": ("normal_pool_elev_ft", "normal_pool", "normal_elev"),
    "emergency_spillway_elev_ft": ("emergency_spillway_elev_ft", "spillway_elev", "aux_spillway_elev"),
    "existing_class": ("existing_class", "hazard_potential", "hazard", "hazard_class", "hazardpotential"),
    "surface_area_ac": ("surface_area_ac", "surface_area", "surfacearea"),
}


def _key(name):
    return re.sub(r"[^a-z0-9]", "_", str(name).strip().lower()).strip("_")


def suggest_field_map(field_names):
    """{damit_field: layer_field} for every DamIT dam field a layer field matches (exact field
    names win over aliases; each layer field is used once)."""
    keys = {_key(f): f for f in field_names}
    out, used = {}, set()
    for target in DAM_FIELDS:
        for alias in (target,) + tuple(ALIASES.get(target, ())):
            f = keys.get(_key(alias))
            if f is not None and f not in used:
                out[target] = f
                used.add(f)
                break
    return out


def field_map_string(field_map):
    """The ``FIELD_MAP`` parameter text of the DamIT Screener tools (damit_field=layer_field,...),
    identity entries left out."""
    return ",".join("{}={}".format(k, v) for k, v in sorted(field_map.items()) if k != v)


def normalize(attrs, field_map=None):
    """A dam record dict with the DamIT field names from one feature's attributes."""
    fm = dict(field_map or suggest_field_map(list(attrs)))
    rec = {}
    for k in DAM_FIELDS:
        src = fm.get(k)
        if src is not None and src in attrs:
            v = attrs[src]
            rec[k] = None if v in ("", None) else v
    if rec.get("dam_id") is not None:
        rec["dam_id"] = str(rec["dam_id"]).strip()
    return rec
