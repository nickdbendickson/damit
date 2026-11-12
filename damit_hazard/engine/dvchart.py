"""Depth-velocity chart of the HABITABLE structures a flood result inundates (DamIT Hazard 0.4.0).

One point per wet habitable structure on the TM-11 depth-velocity chart (houses: ND REG_05.2026 Fig. 5.1;
mobile homes: Fig. 5.2, a second panel only when there are any), a 0-4 ft/s, 0-3.5 ft zoom panel, the
structure ID next to every point in the high and judgment zones, and a CSV of the plotted points. Written
for every Hazard classify run (the Runner's and the Screener's result rasters, or rasters imported from
elsewhere, e.g. DSS-WISE); the title names the source.

WHICH STRUCTURES (Hazard's own rule, engine.core.habitable_basis - the one M6 uses, not a copy):
  no type -> habitable, a home (basis "type_unknown"; the engine flags it type_unknown)
  type in the catalog's habitable_types -> habitable (basis "type")
  any other type -> habitable only with an overnight / regular / daytime occupancy (basis "occupancy")
Only the `structure` kind is charted; facilities are not. Wet means sampled depth > general.wet_min_depth_ft
(the engine's test); receptors outside the routed domain are left out. Future-development and cutoff
filters of the engine are not applied: the chart shows the raster result.

WHAT IS PLOTTED: the structure's PEAK depth (max over its wet cells) against its PEAK velocity (max over its
wet cells), the two peaks read independently (they may come from different cells). The Screener samples
one point, so its chart is a point sample (labelled so). The zone of a point is Hazard's tm11 chart zone
(a point ON a boundary takes the higher zone); the counts text calls the judgment zone MEDIUM.

Pure Python + the standard library; matplotlib (Agg, no GUI) is imported only when the PNG is drawn. A
missing or broken matplotlib skips the PNG with a clear note (the CSV is still written); it never fails a run.
"""
import base64
import csv
import os

from . import core, tm11

ZONE_TEXT = {tm11.HIGH: "high", tm11.JUDGMENT: "MEDIUM", tm11.LOW: "low"}
CHART_IDS = ("houses", "mobile_homes")          # the digitized charts a structure is drawn on
ZOOM_V_FTS, ZOOM_D_FT = 4.0, 3.5
LABEL_MAX = 80                                  # ID labels drawn per panel (the CSV has them all)
COLORS = {"high": "#ef9897", "judgment": "#f9f4a3", "low": "#c4e0ad"}
CSV_COLUMNS = ("id", "label", "type", "habitable_basis", "chart", "zone", "depth_ft", "velocity_fps",
               "trace_depth", "source", "sampling")
SAMPLING_PEAK = "peak depth and peak velocity over the structure's wet cells"
SAMPLING_POINT = "point sample at the structure (one depth, one velocity)"
CHART_NAME = "damit_hazard_dv_habitable"
BASIS_TEXT = {core.BASIS_UNKNOWN: "type unknown (presumed a home)", core.BASIS_TYPE: "habitable type",
              core.BASIS_OCCUPANCY: "habitable occupancy"}


class ChartSkipped(Exception):
    pass


# ------------------------------------------------------------ other sources --
def from_screener(recs):
    """Hazard receptor dicts from DamIT Screener's sampled receptors (id, receptor_type, structure_type,
    depth_ground_ft, velocity_fps, in_domain ...). The Screener reads one point, so depth and velocity are
    its point sample, not wet-cell peaks. Hazard's own type normalisation (a type it does not know stays as given)."""
    from . import receptors as R
    out = []
    for i, a in enumerate(recs or []):
        if str(a.get("receptor_type") or "structure").lower() != "structure":
            continue
        d = a.get("depth_ground_ft")
        hyd = {"sampled": d is not None, "depth_ft": d, "velocity_fps": a.get("velocity_fps")}
        r = R.from_attributes("structure:{}".format(a.get("id") if a.get("id") not in (None, "") else i),
                              "structure", a, hyd)
        if a.get("in_domain") is False:
            r["in_domain"] = False
        out.append(r)
    return out


# ----------------------------------------------------------------- rules --
def rules(cat=None):
    """(habitable_types, chart_for_type) from the DamIT Catalog's hazard entry, as Hazard reads them."""
    if cat is None:
        from . import catalog
        cat = catalog.load()
    return (list(cat["habitable_types"]),
            dict(cat["methods"]["M1"]["params"]["chart_for_type"]))


def chart_id(rtype, chart_for_type, charts):
    """The digitized houses / mobile-homes chart a structure type is read on (M1's chart_for_type map; no type
    = a home, as the engine's charts_for), or None (a type read on a chart that is not digitized: campground).
    A habitable type the map does not list (habitable only by its occupancy) is drawn on the houses chart, the
    map's entry for a home; M1 itself scores no chart for it."""
    v = chart_for_type.get(rtype or "home", chart_for_type.get("home"))
    for cid in ([v] if isinstance(v, str) else list(v or [])):
        if cid in CHART_IDS and charts.digitized(cid):
            return cid
    return None


def label_of(rid):
    return str(rid).split(":", 1)[-1]


def select(receptors, charts, habitable_types, chart_for_type, wet_min=0.0, source="", sampling=SAMPLING_PEAK,
           trace_ids=()):
    """The wet habitable structures as chart points, plus how many receptors each rule left out.

    Returns {"points": [{id, label, type, habitable_basis, chart, zone, depth_ft, velocity_fps, trace_depth,
    source, sampling}], "left_out": {...counts}}; the structure kind only; a structure with no velocity cannot
    be placed and is counted under left_out["no_velocity"]."""
    pts, out = [], {"facilities": 0, "outside_domain": 0, "dry_or_unsampled": 0, "not_habitable": 0,
                    "no_chart": 0, "no_velocity": 0}
    for r in receptors:
        if r.get("kind") == "facility":
            out["facilities"] += 1
            continue
        if r.get("kind") != "structure":
            continue
        if r.get("in_domain") is False:
            out["outside_domain"] += 1
            continue
        d = r.get("depth_ft")
        if not r.get("sampled") or d is None or not d > wet_min:
            out["dry_or_unsampled"] += 1
            continue
        ok, basis = core.habitable_basis(r, habitable_types)
        if not ok:
            out["not_habitable"] += 1
            continue
        cid = chart_id(r.get("type"), chart_for_type, charts)
        if cid is None:
            out["no_chart"] += 1
            continue
        v = r.get("velocity_fps")
        if v is None:
            out["no_velocity"] += 1
            continue
        pts.append({"id": str(r["id"]), "label": label_of(r["id"]), "type": r.get("type") or "",
                    "habitable_basis": basis, "chart": cid, "zone": charts.zone(cid, d, v),
                    "depth_ft": float(d), "velocity_fps": float(v),
                    "trace_depth": bool(round(d, 2) <= wet_min or str(r["id"]) in trace_ids),
                    "source": source, "sampling": sampling})
    return {"points": pts, "left_out": out}


def counts(points):
    """{"high", "judgment", "low", "total"} over the points, plus the same per chart under "by_chart"."""
    c = {tm11.HIGH: 0, tm11.JUDGMENT: 0, tm11.LOW: 0}
    by = {}
    for p in points:
        c[p["zone"]] += 1
        e = by.setdefault(p["chart"], {tm11.HIGH: 0, tm11.JUDGMENT: 0, tm11.LOW: 0})
        e[p["zone"]] += 1
    c["total"] = len(points)
    c["by_chart"] = by
    c["unknown_type"] = sum(1 for p in points if p["habitable_basis"] == core.BASIS_UNKNOWN)
    return c


def counts_text(c):
    return "{} wet habitable structure(s): {} high, {} MEDIUM (judgment), {} low".format(
        c["total"], c[tm11.HIGH], c[tm11.JUDGMENT], c[tm11.LOW])


# ------------------------------------------------------------ source label --
def detect_source(depth_path, override=None):
    """(label, kind) of the flood result the depth raster is: 'Screener' (a 'Screening Depth (Max).tif'),
    'Runner' (a model run's 'Depth (Max).tif'), else the imported raster's own name; a given label wins."""
    if override and str(override).strip():
        return str(override).strip(), "given"
    name = os.path.basename(str(depth_path or "").split("|")[0])
    low = name.lower()
    if low.startswith("screening "):
        return "Screener", "screener"
    if low == "depth (max).tif":
        return "Runner", "runner"
    return ("Imported raster: " + name) if name else "Imported raster", "imported"


def run_date_of(path, now=None):
    """YYYY-MM-DD of the raster file (its modified date, box-local), else today."""
    import datetime
    try:
        return datetime.datetime.fromtimestamp(os.stat(str(path).split("|")[0]).st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return (now or datetime.datetime.now()).strftime("%Y-%m-%d")


def title_lines(meta, c):
    dam = " ".join(x for x in (meta.get("dam_id"), meta.get("dam_name")) if x) or "(dam not named)"
    first = "{} - {} - run {}".format(dam, meta.get("source") or "(source not given)", meta.get("run_date") or "?")
    second = counts_text(c)
    third = "Depth-velocity chart, habitable structures only; " + (
        "peak depth vs peak velocity over each structure's wet cells" if meta.get("sampling") != SAMPLING_POINT
        else "point sample (one depth, one velocity per structure)")
    return first, second, third


# ------------------------------------------------------------- polygons --
def zone_polygons(charts, cid):
    """{"low", "judgment", "high"} -> [(velocity ft/s, depth ft), ...] closed polygons of the chart as Hazard's
    tm11.zone() reads it (the chart's table: below the low line, between the lines, above the high line up to
    the depth axis; a velocity or depth beyond the axis is high, outside the polygons)."""
    c = charts.charts[cid]
    v, lo, hi, dm = c["v_fts"], c["low_ft"], c["high_ft"], c["d_max_ft"]
    n = len(v)
    low = [(v[i], 0.0) for i in range(n)] + [(v[i], lo[i]) for i in reversed(range(n))]
    jud = [(v[i], lo[i]) for i in range(n)] + [(v[i], hi[i]) for i in reversed(range(n))]
    high = [(v[i], hi[i]) for i in range(n)] + [(v[-1], dm), (v[0], dm)]
    return {"low": low, "judgment": jud, "high": high}


# ------------------------------------------------------------------ csv --
def write_csv(points, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for p in sorted(points, key=lambda q: (-tm11.RANK[q["zone"]], -q["depth_ft"])):
            w.writerow([p["id"], p["label"], p["type"], p["habitable_basis"], p["chart"], ZONE_TEXT[p["zone"]],
                        "{:.3f}".format(p["depth_ft"]), "{:.3f}".format(p["velocity_fps"]),
                        "yes" if p["trace_depth"] else "", p["source"], p["sampling"]])
    return path


# ------------------------------------------------------------------ png --
def _pyplot():
    """matplotlib.pyplot on the Agg backend, or ChartSkipped with the reason (never any other exception)."""
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch, Polygon
        return plt, Polygon, Patch, Line2D
    except Exception as e:                                       # noqa: BLE001 - ImportError and broken installs
        raise ChartSkipped("matplotlib is not available ({}: {})".format(type(e).__name__, e))


def draw(points, meta, charts, path, dpi=130):
    """Write the PNG. Raises ChartSkipped when matplotlib is missing."""
    plt, Polygon, Patch, Line2D = _pyplot()
    c = counts(points)
    houses = [p for p in points if p["chart"] == "houses"]
    mobile = [p for p in points if p["chart"] == "mobile_homes"]
    panels = [("houses", None, houses), ("houses", (ZOOM_V_FTS, ZOOM_D_FT), houses)]
    if mobile:
        panels.append(("mobile_homes", None, mobile))
    fig, axs = plt.subplots(1, len(panels), figsize=(7.0 * len(panels), 6.4))
    axs = [axs] if len(panels) == 1 else list(axs)
    try:
        for ax, (cid, zoom, pts) in zip(axs, panels):
            ch = charts.charts[cid]
            vm, dm = ch["v_max_fts"], ch["d_max_ft"]
            poly = zone_polygons(charts, cid)
            ax.add_patch(Polygon([(0, 0), (vm, 0), (vm, dm), (0, dm)], fc=COLORS["high"], ec="none"))
            ax.add_patch(Polygon(poly["judgment"], fc=COLORS["judgment"], ec="#b58400", lw=0.8))
            ax.add_patch(Polygon(poly["low"], fc=COLORS["low"], ec="#4d7a2b", lw=0.8))
            known = [p for p in pts if p["habitable_basis"] != core.BASIS_UNKNOWN and not p["trace_depth"]]
            unk = [p for p in pts if p["habitable_basis"] == core.BASIS_UNKNOWN and not p["trace_depth"]]
            trace = [p for p in pts if p["trace_depth"]]
            ax.scatter([p["velocity_fps"] for p in known], [p["depth_ft"] for p in known], s=30, fc="#1f4e9c",
                       ec="k", zorder=4)
            ax.scatter([p["velocity_fps"] for p in unk], [p["depth_ft"] for p in unk], s=30, fc="none",
                       ec="#1f4e9c", lw=1.4, zorder=4)
            ax.scatter([p["velocity_fps"] for p in trace], [p["depth_ft"] for p in trace], s=26, marker="^",
                       fc="white", ec="k", zorder=3)
            xl, yl = (zoom if zoom else (vm, dm))
            ax.set_xlim(0, xl)
            ax.set_ylim(0, yl)
            shown = 0
            for p in sorted(pts, key=lambda q: -q["depth_ft"]):
                if p["zone"] == tm11.LOW or shown >= LABEL_MAX:
                    continue
                if p["velocity_fps"] > xl or p["depth_ft"] > yl:
                    continue
                ax.annotate(p["label"], (p["velocity_fps"], p["depth_ft"]), xytext=(4, 4),
                            textcoords="offset points", fontsize=6.5, zorder=5)
                shown += 1
            ax.set_xlabel("Peak velocity (ft/s)")
            ax.set_ylabel("Peak depth (ft)")
            ax.grid(alpha=0.3)
            name = charts.title(cid)
            ax.set_title(("ZOOM {:g}-{:g} ft/s, 0-{:g} ft: ".format(0, xl, yl) if zoom else "") + str(name), fontsize=8)
            if not pts:
                ax.text(0.5, 0.5, "no wet habitable structures\non this chart", transform=ax.transAxes,
                        ha="center", va="center", fontsize=11, color="#444", zorder=6,
                        bbox={"fc": "white", "ec": "#888", "alpha": 0.9})
        first, second, third = title_lines(meta, c)
        fig.suptitle(first + "\n" + second, fontsize=10.5)
        handles = [Patch(fc=COLORS["high"], label="High danger"),
                   Patch(fc=COLORS["judgment"], label="Judgment (MEDIUM)"),
                   Patch(fc=COLORS["low"], label="Low danger"),
                   Line2D([], [], marker="o", ls="", mfc="#1f4e9c", mec="k", label="Habitable structure"),
                   Line2D([], [], marker="o", ls="", mfc="none", mec="#1f4e9c", label="Type unknown, presumed habitable"
                          " ({})".format(c["unknown_type"])),
                   Line2D([], [], marker="^", ls="", mfc="white", mec="k", label="Trace depth (0.00 ft)")]
        fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=8)
        fig.text(0.5, 0.075, third, ha="center", fontsize=8, color="#333")
        fig.tight_layout(rect=[0, 0.1, 1, 0.93])
        fig.savefig(path, dpi=dpi)
    finally:
        plt.close(fig)
    return path


# ------------------------------------------------------------------ main --
def build(receptors, charts, meta, out_dir, stem=CHART_NAME, habitable_types=None, chart_for_type=None,
          wet_min=0.0, cat=None, trace_ids=(), log=None):
    """Select the wet habitable structures, write `<stem>.csv` and `<stem>.png` into out_dir, return a dict:
    {png, csv, counts, text, left_out, note, status} with status "ok" | "csv_only" (matplotlib missing: note says
    why). Never raises for a drawing problem. meta: dam_id, dam_name, source, run_date, sampling."""
    log = log or (lambda m: None)
    if habitable_types is None or chart_for_type is None:
        habitable_types, chart_for_type = rules(cat)
    os.makedirs(out_dir, exist_ok=True)
    meta = dict(meta)
    meta.setdefault("sampling", SAMPLING_PEAK)
    sel = select(receptors, charts, habitable_types, chart_for_type, wet_min, meta.get("source") or "",
                 meta["sampling"], trace_ids)
    pts = sel["points"]
    c = counts(pts)
    res = {"png": None, "csv": os.path.join(out_dir, stem + ".csv"), "counts": c, "text": counts_text(c),
           "left_out": sel["left_out"], "note": "", "status": "ok", "source": meta.get("source"),
           "title": " - ".join(title_lines(meta, c)[:2])}
    if not pts:
        res["note"] = "no wet habitable structures: the chart shows the empty zones only"
    write_csv(pts, res["csv"])
    try:
        res["png"] = draw(pts, meta, charts, os.path.join(out_dir, stem + ".png"))
    except ChartSkipped as e:
        res["status"] = "csv_only"
        res["note"] = "depth-velocity chart PNG skipped: {}; the CSV of the points was still written".format(e)
        log(res["note"])
    except Exception as e:                                       # noqa: BLE001 - a chart must never fail a run
        res["status"] = "csv_only"
        res["note"] = "depth-velocity chart PNG failed ({}: {}); the CSV of the points was still written".format(
            type(e).__name__, e)
        log(res["note"])
    return res


def png_data_uri(path):
    """data: URI of a PNG (self-contained HTML), or None."""
    try:
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")
    except (OSError, TypeError):
        return None
