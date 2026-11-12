"""Rain-on-grid export of a DamIT PMP hyetograph (pure Python, writes files only; nothing is launched).

Units are explicit everywhere:

* hyetograph CSV from damit_pmp:hyetograph: ``t_end_min, incremental_in|mm, cumulative_in|mm`` (depth per
  block, inches or mm as the header says; the blocks start at 0 and run back to back);
* LISFLOOD-FP ``.rain``: rainfall *rate* in **mm/hr** against time in seconds (or hours / days). Format per
  the LISFLOOD-FP manual, section "Rainfall data file (.rain)": line 1 a comment (ignored), line 2 the number
  of time points then the time unit (``days``, ``hours`` or ``seconds``), then ``rate time`` lines. The model
  linearly interpolates between points, so every block is written as two points (start, and ``ramp_s``
  seconds before its end) to keep the rate constant within the block, followed by a 0 mm/hr point at the
  end of the storm. The rain is spatially uniform. Used with the ``rainfall`` keyword in the .par file;
* ANUGA series: CSV ``time_s, rate_m_per_s`` (m of water depth per second = mm/hr / 3.6e6) with the same
  points; ``anuga.Rate_operator(domain, rate=f)`` takes ``rate`` in m/s and ``f`` may be a function of t.

NOAA Atlas 14 is the depth source; the block pattern is the alternating-block pattern of the hyetograph,
not an Atlas 14 temporal distribution.
"""
import csv
import json
import os

MM_PER_IN = 25.4
S_PER_HR = 3600.0
M_PER_S_PER_MM_HR = 1.0 / (1000.0 * S_PER_HR)            # 1 mm/hr = 2.7778e-7 m/s
TIME_UNITS = {"seconds": 1.0, "hours": 3600.0, "days": 86400.0}


class RainError(ValueError):
    pass


def read_hyetograph(path):
    """[(t_start_min, t_end_min, depth_mm)] and the depth unit found in the header ('in' or 'mm')."""
    rows, unit = [], None
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        header = None
        for r in rd:
            if not r or r[0].lstrip().startswith("#"):
                continue
            if header is None:
                header = [c.strip() for c in r]
                inc = [c for c in header if c.startswith("incremental_")]
                if "t_end_min" not in header or not inc:
                    raise RainError("not a DamIT PMP hyetograph CSV (need columns t_end_min and incremental_in|mm): "
                                    "{}".format(path))
                unit = inc[0].split("_", 1)[1]
                if unit not in ("in", "mm"):
                    raise RainError("hyetograph depth unit must be in or mm, found {!r}".format(unit))
                ti, di = header.index("t_end_min"), header.index(inc[0])
                continue
            rows.append((float(r[ti]), float(r[di])))
    if not rows:
        raise RainError("the hyetograph CSV has no rows: {}".format(path))
    return blocks_from_rows(rows, unit), unit


def blocks_from_rows(rows, unit):
    """rows [(t_end_min, depth in ``unit``)] -> [(t0_min, t1_min, depth_mm)]."""
    f = MM_PER_IN if unit == "in" else 1.0
    out, t0 = [], 0.0
    for t1, d in rows:
        if t1 <= t0:
            raise RainError("hyetograph times must increase (t_end_min {} after {})".format(t1, t0))
        if d < 0:
            raise RainError("negative rainfall depth in the hyetograph")
        out.append((t0, t1, d * f))
        t0 = t1
    return out


def scale_blocks(blocks, factor):
    if factor <= 0:
        raise RainError("the scale factor must be positive")
    return [(a, b, d * factor) for a, b, d in blocks]


def total_mm(blocks):
    return sum(d for _, _, d in blocks)


def series(blocks, ramp_s=1, sim_time_s=None):
    """Piecewise-linear rate series [(time_s, rate_mm_hr)] holding each block's rate constant: points at the
    block start and ``ramp_s`` before its end; 0 at the end of the storm (and at ``sim_time_s`` when it is
    later). Starts at t = 0."""
    if ramp_s < 1:
        raise RainError("ramp_s must be at least 1 second (LISFLOOD-FP interpolates linearly between points)")
    pts = []
    for t0m, t1m, d in blocks:
        t0, t1 = round(t0m * 60.0), round(t1m * 60.0)
        if t1 - t0 <= ramp_s:
            raise RainError("a block of {} s is not longer than ramp_s ({} s)".format(t1 - t0, ramp_s))
        rate = d / ((t1 - t0) / S_PER_HR)                  # mm per hour
        pts.append((t0, rate))
        pts.append((t1 - ramp_s, rate))
    end = round(blocks[-1][1] * 60.0)
    pts.append((end, 0.0))
    if sim_time_s is not None and sim_time_s > end:
        pts.append((round(sim_time_s), 0.0))
    return pts


def integrate_mm(pts):
    """Depth (mm) of a piecewise-linear [(time_s, rate_mm_hr)] series (trapezoids)."""
    return sum((t1 - t0) / S_PER_HR * (r0 + r1) / 2.0 for (t0, r0), (t1, r1) in zip(pts, pts[1:]))


def to_m_per_s(rate_mm_hr):
    return rate_mm_hr * M_PER_S_PER_MM_HR


def _fmt_time(t_s, unit):
    v = t_s / TIME_UNITS[unit]
    return "{:.0f}".format(v) if unit == "seconds" else "{:.6f}".format(v).rstrip("0").rstrip(".")


def rain_text(pts, time_unit="seconds", comment="DamIT PMP rainfall (NOAA Atlas 14), rate in mm/hr"):
    if time_unit not in TIME_UNITS:
        raise RainError("time unit must be one of {}".format(", ".join(TIME_UNITS)))
    lines = ["# " + " ".join(comment.split()), "{} {}".format(len(pts), time_unit)]
    lines += ["{:.5f} {}".format(r, _fmt_time(t, time_unit)) for t, r in pts]
    return "\n".join(lines) + "\n"


def parse_rain(text):
    """Read a .rain file back: [(time_s, rate_mm_hr)] (used by the tests and the round-trip check)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    n_s, unit = lines[1].split()
    if unit not in TIME_UNITS:
        raise RainError("bad time unit {!r}".format(unit))
    out = []
    for ln in lines[2:]:
        r, t = ln.split()
        out.append((float(t) * TIME_UNITS[unit], float(r)))
    if len(out) != int(n_s):
        raise RainError("point count {} does not match the {} rows".format(n_s, len(out)))
    return out


def anuga_text(pts):
    lines = ["time_s,rate_m_per_s"]
    lines += ["{:.0f},{:.9e}".format(t, to_m_per_s(r)) for t, r in pts]
    return "\n".join(lines) + "\n"


ANUGA_README = """DamIT PMP rain-on-grid series for ANUGA ({stem})
=====================================================================
Source: {source}
Storm: {desc}
Depth: {total_in:.3f} in = {total_mm:.2f} mm over {dur_h:g} hours (spatially uniform).

Files
  {csv}   time_s, rate_m_per_s   (m of water depth per second; 1 mm/hr = 2.7778e-7 m/s)
  {rain}  the same storm for LISFLOOD-FP (rate in mm/hr)

The CSV is a piecewise-linear series: every block of the hyetograph is held at its rate between its start and
{ramp} s before its end (linear interpolation in between), and the rate is 0 after {end_s} s.
Interpolating the series reproduces the storm depth to {err:.4f} %.

Use with ANUGA (the rate is in m/s and may be a function of time; do not multiply by anything else):

    import numpy as np, anuga
    t, r = np.loadtxt("{csv}", delimiter=",", skiprows=1, unpack=True)

    def rain(t_now):                       # m/s; 0 outside the storm
        return float(np.interp(t_now, t, r, left=0.0, right=0.0))

    rain_op = anuga.Rate_operator(domain, rate=rain)          # whole domain, uniform
    # ... then the usual: for t in domain.evolve(yieldstep=60.0, finaltime=...): ...

Atlas 14 gives point estimates up to the 1000-year ARI; this is not a probable maximum precipitation and the
block pattern is an alternating-block pattern, not an Atlas 14 temporal distribution.
"""


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def export(blocks, rain_path=None, anuga_path=None, time_unit="seconds", ramp_s=1, sim_time_s=None,
           source="", desc="", extra=None):
    """Write the .rain and / or ANUGA files; returns the record (also written as JSON by the algorithm)."""
    if not rain_path and not anuga_path:
        raise RainError("nothing to write")
    pts = series(blocks, ramp_s, sim_time_s)
    depth_in = total_mm(blocks) / MM_PER_IN
    written_mm = integrate_mm(pts)
    err_pct = (written_mm - total_mm(blocks)) / total_mm(blocks) * 100.0 if total_mm(blocks) else 0.0
    dur_h = (blocks[-1][1]) / 60.0
    rec = {"schema": "damit.pmp.raingrid", "schema_version": 1, "storm": desc, "source": source,
           "total_depth_in": round(depth_in, 4), "total_depth_mm": round(total_mm(blocks), 3),
           "storm_duration_hr": dur_h, "blocks": len(blocks), "ramp_s": ramp_s,
           "points": len(pts), "series_depth_mm": round(written_mm, 4), "series_depth_error_pct": round(err_pct, 5),
           "peak_rate_mm_hr": round(max(r for _, r in pts), 4),
           "peak_rate_m_per_s": max(to_m_per_s(r) for _, r in pts),
           "uniform": True, "units": {"lisflood_rain": "mm/hr vs time ({})".format(time_unit),
                                      "anuga_csv": "m/s vs time_s"}}
    rec.update(extra or {})
    if rain_path:
        write_text(rain_path, rain_text(pts, time_unit, "DamIT PMP rainfall (NOAA Atlas 14), rate in mm/hr: " + desc))
        rec["lisflood_rain"] = rain_path
    if anuga_path:
        write_text(anuga_path, anuga_text(pts))
        rec["anuga_csv"] = anuga_path
        readme = os.path.splitext(anuga_path)[0] + "_README.txt"
        write_text(readme, ANUGA_README.format(
            stem=os.path.basename(os.path.splitext(anuga_path)[0]), source=source or "NOAA Atlas 14", desc=desc,
            total_in=depth_in, total_mm=total_mm(blocks), dur_h=dur_h, csv=os.path.basename(anuga_path),
            rain=os.path.basename(rain_path) if rain_path else "(not written)", ramp=ramp_s,
            end_s=round(blocks[-1][1] * 60.0), err=err_pct))
        rec["anuga_readme"] = readme
    return rec


def dump_json(path, rec):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1)
