"""Green-Ampt infiltration excess.

Soil parameters by USDA texture class. Each row: wetting-front suction head psi (in),
saturated hydraulic conductivity Ks (in/hr), total porosity, effective porosity theta_e.
SOURCE: Rawls, Brakensiek and Miller (1983), "Green-Ampt infiltration parameters from
soils data", J. Hydraulic Eng. 109(1):62-70, Table 1 (mean values), as reprinted in
Chow, Maidment and Mays (1988) Applied Hydrology, Table 4.3.1 (cm and cm/h there;
converted here at 2.54 cm/in).

VERIFIED: the 11 textures were checked against two USACE reprints of the same means
(the 1D technical-reference Green-Ampt table, and the HMS guide "Applying the Green
and Ampt Loss Method"). A texture preset is stamped PRODUCTION. Typed values are the
user's and are not stamped.

The arithmetic is the DWR PMP 0.7.2 function (pin 6816c7f, core/hydro.py), copied on
its own. The SCS and Clark unit hydrographs in that file were not copied.
"""

import numpy as np

GA_TEXTURE_SOURCE = ("Rawls, Brakensiek & Miller (1983) Table 1, mean values; reprinted in Chow, Maidment & "
                     "Mays (1988) Applied Hydrology Table 4.3.1")
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


class GreenAmptError(ValueError):
    pass


def ga_texture(name, initial_saturation=0.0):
    """(suction_in, ks_in_hr, moisture_deficit) at an initial effective saturation Se.

    Se 0 is dry and 1 is saturated. Deficit = theta_e * (1 - Se).
    """
    key = str(name).strip().lower()
    if key not in GA_TEXTURES:
        raise GreenAmptError("Unknown Green-Ampt texture {!r} (one of: {})".format(
            name, ", ".join(GA_TEXTURE_NAMES)))
    if not 0.0 <= float(initial_saturation) <= 1.0:
        raise GreenAmptError("Initial effective saturation must be 0-1")
    psi, ks, _, te = GA_TEXTURES[key]
    return psi, ks, te * (1.0 - float(initial_saturation))


def _ga_ponded_F(F0, dt, ks, pd):
    """Cumulative infiltration after dt of ponded infiltration from F0.

    F - F0 - pd ln((F + pd) / (F0 + pd)) = Ks dt, Newton from F0 + Ks dt.
    """
    if pd <= 0.0:
        return F0 + ks * dt
    F = F0 + ks * dt
    for _ in range(100):
        g = F - F0 - pd * np.log((F + pd) / (F0 + pd)) - ks * dt
        dg = 1.0 - pd / (F + pd)
        step = g / dg
        F -= step
        if abs(step) < 1e-10:
            break
    return max(F, F0)


def green_ampt_excess(precip_incr, dt, ks_in_hr, suction_in, moisture_deficit, initial_in=0.0,
                      impervious_pct=0.0):
    """Excess rain (in per step). Ponding inside a step follows Mein and Larson 1973.

    Rain is constant within a step. An initial loss (in) is taken from the pervious rain
    first. The impervious fraction sheds all of its rain. Depths are inches. dt is hours.
    """
    ks, psi, dth = float(ks_in_hr), float(suction_in), float(moisture_deficit)
    if ks < 0 or psi < 0 or dth < 0:
        raise GreenAmptError("Green-Ampt Ks, suction and moisture deficit must be >= 0")
    if not 0.0 <= float(impervious_pct) <= 100.0:
        raise GreenAmptError("Percent impervious must be 0-100")
    imp = float(impervious_pct) / 100.0
    pd = psi * dth
    ex = np.zeros(len(precip_incr))
    F = 0.0
    ia_left = float(initial_in)
    ponded = False
    for k, p in enumerate(np.asarray(precip_incr, float)):
        p = max(0.0, float(p))
        take = min(p, ia_left)
        ia_left -= take
        pp = p - take
        t_left = dt * (1.0 - take / p) if p > 0 else dt
        F0 = F
        if pp > 0.0 and ks > 0.0:
            i = pp / t_left
            if F > 0.0:
                fcap = ks * (1.0 + pd / F)
            else:
                fcap = ks if pd == 0.0 else np.inf
            if fcap <= i:
                F = _ga_ponded_F(F, t_left, ks, pd)
                ponded = True
            else:
                Ft = F + pp
                if i > ks and ks * (1.0 + pd / Ft) <= i:
                    Fp = ks * pd / (i - ks)
                    tp = (Fp - F) / i
                    F = _ga_ponded_F(Fp, t_left - tp, ks, pd)
                    ponded = True
                else:
                    F = Ft
            F = min(F, F0 + pp)
        elif pp > 0.0 and ks == 0.0:
            pass
        infil = F - F0
        ex[k] = imp * p + (1.0 - imp) * (pp - infil)
    info = {"ga_ks_in_hr": ks, "ga_suction_in": psi, "ga_moisture_deficit": dth,
            "ga_initial_in": float(initial_in), "ga_impervious_pct": float(impervious_pct),
            "ga_infiltrated_in": (1.0 - imp) * F, "ga_ponded": ponded,
            "loss": "green_ampt", "excess_in": float(np.maximum(ex, 0.0).sum())}
    return np.maximum(ex, 0.0), info


def apply_storm(precip_in, dt_hr, texture=None, initial_saturation=0.0, ks_in_hr=None,
                suction_in=None, moisture_deficit=None, initial_in=0.0, impervious_pct=0.0):
    """Excess inches and a record. A texture name uses the checked table. Otherwise the three values."""
    if texture:
        psi, ks, dth = ga_texture(texture, initial_saturation)
        status = "PRODUCTION" if GA_TEXTURE_VERIFIED else "PROVISIONAL"
        used = str(texture).strip().lower()
    else:
        if ks_in_hr is None or suction_in is None or moisture_deficit is None:
            raise GreenAmptError("Green-Ampt needs a texture or Ks, suction and moisture deficit")
        psi, ks, dth = float(suction_in), float(ks_in_hr), float(moisture_deficit)
        status = None
        used = "custom"
    ex, info = green_ampt_excess(precip_in, dt_hr, ks, psi, dth, initial_in, impervious_pct)
    info["loss_texture"] = used
    if status:
        info["loss_param_status"] = status
    return ex, info
