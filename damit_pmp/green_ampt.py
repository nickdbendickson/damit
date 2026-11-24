"""Green-Ampt infiltration loss for DamIT PMP hyetograph and rain-on-grid tools.

Ported from DamSafety PMP 0.7.0-0.7.3 (the inflow-hydrograph Green-Ampt loss) and adapted for DamIT: the
Atlas 14 shared core (storm.py and the other four noaa14 modules) is left byte-identical, so this
lives in its own module. The texture table and the ponding-inside-a-step scheme are unchanged.

Ponding inside a step: Mein & Larson (1973); Chow, Maidment & Mays (1988) sec. 4.4.
Soil texture means: Rawls, Brakensiek & Miller (1983) Table 1, as reprinted in Chow et al.
Table 4.3.1, checked in DamSafety PMP 0.7.2 against two USACE reprints.

Parameters are in inches (and in/hr). apply_to_rows() accepts DamIT storm rows in inches or mm
and returns the same (t_end, gross, loss, excess) table as storm.apply_losses().
"""
import math

import numpy as np

# Green-Ampt soil parameters by USDA texture class. Each row: wetting-front suction head psi (in),
# saturated hydraulic conductivity Ks (in/hr), total porosity, effective porosity theta_e.
# SOURCE: Rawls, Brakensiek & Miller (1983), "Green-Ampt infiltration parameters from soils data",
# J. Hydraulic Eng. 109(1):62-70, Table 1 (mean values), as reprinted in Chow, Maidment & Mays (1988)
# Applied Hydrology, Table 4.3.1 (cm and cm/h there; converted here at 2.54 cm/in).
# VERIFIED = True (2026-11-22, DamSafety PMP 0.7.2): all 44 values checked against two USACE reprints
# of the same Rawls et al. (1983) means - the HEC-RAS 1D Technical Reference "Green-Ampt" table
# (total porosity and Ks, exact to the printed digits) and the HEC hydrologic-model guide "Applying the Green
# and Ampt Loss Method" (suction to 0.1 in, effective porosity to 0.01, Ks in in/hr) - and they
# agree on every row. tests/test_green_ampt.py pins both checks. A run that uses a texture preset
# is stamped PRODUCTION; with the flag False it would be stamped PROVISIONAL. Typed (custom)
# values are the user's own and are not stamped.
GA_TEXTURE_SOURCE = ("Rawls, Brakensiek & Miller (1983) Table 1, mean values; reprinted in Chow, "
                     "Maidment & Mays (1988) Applied Hydrology Table 4.3.1")
GA_TEXTURE_VERIFIED = True
_CM = 1.0 / 2.54
GA_TEXTURES = {          # name: (suction_in, ks_in_hr, porosity, effective_porosity)
    "sand":            (4.95 * _CM, 11.78 * _CM, 0.437, 0.417),
    "loamy sand":      (6.13 * _CM, 2.99 * _CM, 0.437, 0.401),
    "sandy loam":      (11.01 * _CM, 1.09 * _CM, 0.453, 0.412),
    "loam":            (8.89 * _CM, 0.34 * _CM, 0.463, 0.434),
    "silt loam":       (16.68 * _CM, 0.65 * _CM, 0.501, 0.486),
    "sandy clay loam": (21.85 * _CM, 0.15 * _CM, 0.398, 0.330),
    "clay loam":       (20.88 * _CM, 0.10 * _CM, 0.464, 0.309),
    "silty clay loam": (27.30 * _CM, 0.10 * _CM, 0.471, 0.432),
    "sandy clay":      (23.90 * _CM, 0.06 * _CM, 0.430, 0.321),
    "silty clay":      (29.22 * _CM, 0.05 * _CM, 0.479, 0.423),
    "clay":            (31.63 * _CM, 0.03 * _CM, 0.475, 0.385),
}
GA_TEXTURE_NAMES = list(GA_TEXTURES)
# Processing enum: 0 = Custom, then the 11 textures in GA_TEXTURE_NAMES order
TEXTURE_LABELS = ["Custom (enter Ks, suction and moisture deficit)"] + [
    n[:1].upper() + n[1:] for n in GA_TEXTURE_NAMES
]


class GreenAmptError(ValueError):
    """A Green-Ampt parameter the tool cannot use; the message says what to change."""


def ga_texture(name, initial_saturation=0.0):
    """(suction_in, ks_in_hr, moisture_deficit) of a texture class at an initial effective saturation
    Se (0 = dry, 1 = saturated): deficit = theta_e * (1 - Se) (Chow et al. 1988 eq. 4.3.13)."""
    key = str(name).strip().lower()
    if key not in GA_TEXTURES:
        raise GreenAmptError("Unknown Green-Ampt texture %r (one of: %s)" % (name, ", ".join(GA_TEXTURE_NAMES)))
    if not 0.0 <= initial_saturation <= 1.0:
        raise GreenAmptError("Initial effective saturation must be 0-1")
    psi, ks, _, te = GA_TEXTURES[key]
    return psi, ks, te * (1.0 - initial_saturation)


def texture_status():
    """PRODUCTION once the texture table has been checked; otherwise PROVISIONAL."""
    return "PRODUCTION" if GA_TEXTURE_VERIFIED else "PROVISIONAL"


def resolve_params(texture=None, initial_saturation=0.0, ks_in_hr=None, suction_in=None,
                   moisture_deficit=None):
    """(ks_in_hr, suction_in, moisture_deficit, texture_name or 'custom', status or None)."""
    name = (str(texture).strip().lower() if texture not in (None, "", "custom") else "")
    if name:
        psi, ks, dth = ga_texture(name, initial_saturation)
        return ks, psi, dth, name, texture_status()
    try:
        ks = float(ks_in_hr)
        psi = float(suction_in)
        dth = float(moisture_deficit)
    except (TypeError, ValueError):
        raise GreenAmptError("Green-Ampt custom parameters need Ks (in/hr), suction (in) and "
                             "moisture deficit (all numbers)")
    if ks < 0 or psi < 0 or dth < 0:
        raise GreenAmptError("Green-Ampt Ks, suction and moisture deficit must be >= 0")
    return ks, psi, dth, "custom", None


def _ga_ponded_F(F0, dt, ks, pd):
    """Cumulative infiltration after dt of ponded infiltration from F0: the implicit Green-Ampt
    F - F0 - pd ln((F + pd) / (F0 + pd)) = Ks dt (Chow et al. 1988 eq. 4.4.4), solved by Newton
    (the function is convex and increasing in F, so Newton from F0 + Ks dt converges monotonically)."""
    if pd <= 0.0:
        return F0 + ks * dt
    F = F0 + ks * dt
    for _ in range(100):
        g = F - F0 - pd * math.log((F + pd) / (F0 + pd)) - ks * dt
        dg = 1.0 - pd / (F + pd)
        step = g / dg
        F -= step
        if abs(step) < 1e-10:
            break
    return max(F, F0)


def green_ampt_excess(precip_incr, dt, ks_in_hr, suction_in, moisture_deficit, initial_in=0.0,
                      impervious_pct=0.0):
    """Excess rain (in per step) by Green-Ampt with ponding inside a step (Mein & Larson 1973; the
    step scheme of Chow, Maidment & Mays 1988 sec. 4.4). Rain falls at a constant rate within a step.
    An initial loss (in) is taken from the pervious area's rain first; the impervious fraction sheds all
    its rain. Water left on the surface leaves as excess at once (no ponded run-on), as in the HEC hydrologic model.

    ``dt`` is a scalar hours, or one value per step.
    """
    ks, psi, dth = float(ks_in_hr), float(suction_in), float(moisture_deficit)
    if ks < 0 or psi < 0 or dth < 0:
        raise GreenAmptError("Green-Ampt Ks, suction and moisture deficit must be >= 0")
    if not 0.0 <= impervious_pct <= 100.0:
        raise GreenAmptError("Percent impervious must be 0-100")
    imp = impervious_pct / 100.0
    pd = psi * dth
    precip = np.asarray(precip_incr, float)
    dt_arr = np.broadcast_to(np.asarray(dt, float), precip.shape)
    ex = np.zeros(len(precip))
    F = 0.0
    ia_left = float(initial_in)
    ponded = False
    for k, p in enumerate(precip):
        p = max(0.0, float(p))
        step_dt = float(dt_arr[k])
        take = min(p, ia_left)
        ia_left -= take
        pp = p - take                      # rain reaching the pervious soil this step
        t_left = step_dt * (1.0 - take / p) if p > 0 else step_dt
        F0 = F
        if pp > 0.0 and ks > 0.0:
            i = pp / t_left                # rate over the rest of the step
            if F > 0.0:
                fcap = ks * (1.0 + pd / F)
            else:
                fcap = ks if pd == 0.0 else np.inf
            if fcap <= i:                  # ponded all step
                F = _ga_ponded_F(F, t_left, ks, pd)
                ponded = True
            else:
                Ft = F + pp                # all of it infiltrates, unless ponding starts within the step
                if i > ks and ks * (1.0 + pd / Ft) <= i:
                    Fp = ks * pd / (i - ks)            # cumulative infiltration at ponding (eq. 4.4.2)
                    tp = (Fp - F) / i
                    F = _ga_ponded_F(Fp, t_left - tp, ks, pd)
                    ponded = True
                else:
                    F = Ft
            F = min(F, F0 + pp)            # never more than the rain that fell
        elif pp > 0.0 and ks == 0.0:
            pass                           # no infiltration at all
        infil = F - F0
        ex[k] = imp * p + (1.0 - imp) * (pp - infil)
    info = {"ga_ks_in_hr": ks, "ga_suction_in": psi, "ga_moisture_deficit": dth,
            "ga_initial_in": float(initial_in), "ga_impervious_pct": float(impervious_pct),
            "ga_infiltrated_in": (1.0 - imp) * F, "ga_ponded": ponded}
    return np.maximum(ex, 0.0), info


def apply_to_rows(rows, ks_in_hr, suction_in, moisture_deficit, initial=0.0, impervious_pct=0.0,
                  unit="in", step_min=None):
    """rows [(t_end, incremental, cumulative)] in ``unit`` -> [(t_end, gross, loss, excess)]
    in the same unit. Ks, suction and deficit are always in inches (and in/hr). ``initial`` is a
    depth in ``unit``, like storm.apply_losses().
    """
    from . import storm as S
    if unit not in S.UNITS:
        raise GreenAmptError("loss units must be 'in' or 'mm'")
    times, incr, dts = [], [], []
    t_prev = 0.0
    for t_end, gross, _ in rows:
        dt_h = ((t_end - t_prev) if step_min is None else step_min) / 60.0
        t_prev = t_end
        times.append(t_end)
        incr.append(float(gross))
        dts.append(dt_h)
    if unit == "mm":
        incr_in = [v / S.MM_PER_IN for v in incr]
        ia_in = float(initial) / S.MM_PER_IN
    else:
        incr_in = incr
        ia_in = float(initial)
    ex_in, info = green_ampt_excess(incr_in, dts, ks_in_hr, suction_in, moisture_deficit,
                                    initial_in=ia_in, impervious_pct=impervious_pct)
    out = []
    for t_end, gross, excess_in in zip(times, incr, ex_in):
        excess = float(excess_in) * (S.MM_PER_IN if unit == "mm" else 1.0)
        loss = float(gross) - excess
        out.append((t_end, round(float(gross), 4), round(loss, 4), round(excess, 4)))
    info = dict(info)
    if unit == "mm":
        info["ga_initial_" + unit] = float(initial)
        info["ga_infiltrated_" + unit] = info["ga_infiltrated_in"] * S.MM_PER_IN
    return out, info

