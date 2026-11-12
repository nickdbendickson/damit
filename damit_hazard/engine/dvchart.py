"""Depth-velocity chart of the HABITABLE structures a flood result inundates (DamIT Hazard 0.4.0).

One point per wet habitable structure on the TM-11 depth-velocity chart (houses: ND REG_05.2026 Fig. 5.1; mobile
homes: Fig. 5.2, a second panel only when there are any), a 0-4 ft/s, 0-3.5 ft zoom panel, the structure ID next to
every point in the high and judgment zones, and a CSV of the plotted points. Written for every Hazard classify run
(the Runner's and the Screener's result rasters, or rasters imported from elsewhere, e.g. DSS-WISE); the title names
the source.

WHICH STRUCTURES (0.4.0, Nick 2026-11-12): ONLY an ND 911 address point is habitable by itself (engine.core.
reviewed_status); every other structure is "unverified" until an engineer reviews it in Hazard
(habitable_review.json, reviewed_habitable true / false: a structure reviewed habitable is drawn as an orange
diamond). Unverified wet structures are NOT plotted: they are a count in the chart note and a worklist CSV
(damit_hazard_dv_habitable_unverified.csv: the structure key to review, the NSI occtype and the type it suggests,
the USA Structures check, depth, velocity, zone). An NSI occtype, a USA Structures footprint, a type or an
occupancy never make a non-911 structure habitable. This is NOT the rule M6 and the class follow (see
engine.core.habitable_basis, "legacy": no type = presumed a home); the report says when the two differ.
Only the `structure` kind is charted; facilities are not. Wet means sampled depth > general.wet_min_depth_ft (the
engine's test); receptors outside the routed domain are left out. Future-development and cutoff filters of the
engine are not applied: the chart shows the raster result.

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

from . import core, habitable_review, receptors as R, tm11

ZONE_TEXT = {tm11.HIGH: "high", tm11.JUDGMENT: "MEDIUM", tm11.LOW: "low"}
CHART_IDS = ("houses", "mobile_homes")          # the digitized charts a structure is drawn on
ZOOM_V_FTS, ZOOM_D_FT = 4.0, 3.5
LABEL_MAX = 80                                  # ID labels drawn per panel (the CSV has them all)
COLORS = {"high": "#ef9897", "judgment": "#f9f4a3", "low": "#c4e0ad"}
CSV_COLUMNS = ("id", "label", "struct_key", "type", "suggested_type", "occtype", "habitable_status",
               "habitable_basis", "chart", "zone", "depth_ft", "velocity_fps", "trace_depth", "usa_struct_match",
               "usa_occ_cls", "usa_occ_check", "source", "sampling")
UNVERIFIED_COLUMNS = ("id", "struct_key", "occtype", "suggested_type", "nsi_suggests", "usa_struct_match",
                      "usa_occ_cls", "usa_occ_check", "chart", "zone", "depth_ft", "velocity_fps", "source")
SAMPLING_PEAK = "peak depth and peak velocity over the structure's wet cells"
SAMPLING_POINT = "point sample at the structure (one depth, one velocity)"
CHART_NAME = "damit_hazard_dv_habitable"
BASIS_TEXT = {core.BASIS_911: "ND 911 address point", core.BASIS_REVIEWED: "reviewed habitable (engineer)"}
ORANGE = "#e08a00"


class ChartSkipped(Exception):
    pass


# ------------------------------------------------------------ other sources --
def from_screener(recs, reviews=None):
    """Hazard receptor dicts from DamIT Screener's sampled receptors (id, receptor_type, structure_type,
    depth_ground_ft, velocity_fps, in_domain ...). The Screener reads one point, so depth and velocity are
    its point sample, not wet-cell peaks. Hazard's own type normalisation (a type it does not know stays as given).
    `reviews` ({key: entry} of habitable_review.load) sets reviewed_habitable."""
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
    if reviews:
        habitable_review.apply(out, reviews)
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


def _common(r, rtype, basis=None, status=None):
    return {"id": str(r["id"]), "label": label_of(r["id"]), "struct_key": R.review_key(r), "type": r.get("type") or "",
            "suggested_type": r.get("suggested_type") or "", "occtype": r.get("occtype") or "",
            "habitable_status": status, "habitable_basis": basis, "usa_struct_match": r.get("usa_struct_match") or "",
            "usa_occ_cls": r.get("usa_occ_cls") or "", "usa_occ_check": r.get("usa_occ_check") or ""}


def select(receptors, charts, habitable_types, chart_for_type, wet_min=0.0, source="", sampling=SAMPLING_PEAK,
           trace_ids=()):
    """The wet habitable structures as chart points, the wet UNVERIFIED ones as a worklist, and how many receptors each
    rule left out.

    Returns {"points": [...], "unverified": [...], "left_out": {...counts}}; the structure kind only. Habitable =
    core.reviewed_status "yes" (a 911 address point, or reviewed habitable). The chart a point is read on follows its
    own type, else the type NSI's occtype suggests, else the house chart. A structure with no velocity cannot be placed
    and is counted under left_out["no_velocity"]."""
    pts, unv = [], []
    out = {"facilities": 0, "outside_domain": 0, "dry_or_unsampled": 0, "not_habitable": 0, "unverified": 0,
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
        status, basis = core.reviewed_status(r, habitable_types)
        if status == core.STATUS_NO:
            out["not_habitable"] += 1
            continue
        rtype = r.get("type") or r.get("suggested_type")
        cid = chart_id(rtype, chart_for_type, charts)
        v = r.get("velocity_fps")
        zone = charts.zone(cid, d, v) if cid is not None and v is not None else None
        if status == core.STATUS_UNVERIFIED:
            out["unverified"] += 1
            st = r.get("suggested_type") or (R.nsi_type(r["occtype"]) if r.get("occtype") else None)
            e = _common(r, rtype, basis, status)
            e["suggested_type"] = st or e.get("suggested_type") or ""
            e.update({"nsi_suggests": ("habitable" if st in habitable_types else "not habitable") if st else "none",
                      "chart": cid or "", "zone": zone, "depth_ft": float(d), "velocity_fps": v, "source": source})
            unv.append(e)
            continue
        if cid is None:
            out["no_chart"] += 1
            continue
        if v is None:
            out["no_velocity"] += 1
            continue
        e = _common(r, rtype, basis, status)
        e.update({"chart": cid, "zone": zone, "depth_ft": float(d), "velocity_fps": float(v),
                  "trace_depth": bool(round(d, 2) <= wet_min or str(r["id"]) in trace_ids),
                  "source": source, "sampling": sampling})
        pts.append(e)
    return {"points": pts, "unverified": unv, "left_out": out}


def counts(points):
    """{"high", "judgment", "low", "total"} over the points, plus the same per chart under "by_chart" and the points
    by basis (911 address points, reviewed habitable) under "by_basis"."""
    c = {tm11.HIGH: 0, tm11.JUDGMENT: 0, tm11.LOW: 0}
    by, basis = {}, {}
    for p in points:
        c[p["zone"]] += 1
        e = by.setdefault(p["chart"], {tm11.HIGH: 0, tm11.JUDGMENT: 0, tm11.LOW: 0})
        e[p["zone"]] += 1
        basis[p["habitable_basis"]] = basis.get(p["habitable_basis"], 0) + 1
    c["total"] = len(points)
    c["by_chart"] = by
    c["by_basis"] = basis
    c["n_911"] = basis.get(core.BASIS_911, 0)
    c["n_reviewed"] = basis.get(core.BASIS_REVIEWED, 0)
    return c


def unverified_summary(unv):
    """Counts of the wet unverified structures: what NSI suggests, and the USA Structures check."""
    s = {"total": len(unv), "nsi_suggests_habitable": 0, "nsi_suggests_not_habitable": 0, "no_suggestion": 0,
         "usa_no_footprint": 0, "usa_class_differs": 0, "usa_not_checked": 0}
    for e in unv:
        k = e["nsi_suggests"]
        s["nsi_suggests_habitable" if k == "habitable" else "nsi_suggests_not_habitable" if k == "not habitable"
          else "no_suggestion"] += 1
        m = e["usa_struct_match"]
        if not m:
            s["usa_not_checked"] += 1
        elif m == "none":
            s["usa_no_footprint"] += 1
        if e["usa_occ_check"] == "differs":
            s["usa_class_differs"] += 1
    return s


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


def unverified_text(u):
    if not u or not u.get("total"):
        return ""
    return ("{} wet unverified structure(s) (not a 911 address point, not reviewed) are not plotted: NSI suggests "
            "habitable {}, not habitable {}, no suggestion {}; no USA Structures footprint {}".format(
                u["total"], u["nsi_suggests_habitable"], u["nsi_suggests_not_habitable"], u["no_suggestion"],
                u["usa_no_footprint"]))


def title_lines(meta, c):
    dam = " ".join(x for x in (meta.get("dam_id"), meta.get("dam_name")) if x) or "(dam not named)"
    first = "{} - {} - run {}".format(dam, meta.get("source") or "(source not given)", meta.get("run_date") or "?")
    second = counts_text(c)
    third = "Habitable = ND 911 address points ({}) + structures reviewed habitable in Hazard ({}); {}".format(
        c.get("n_911", 0), c.get("n_reviewed", 0),
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
def write_csv(points, path, columns=CSV_COLUMNS, key=None):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for p in sorted(points, key=key or (lambda q: (-tm11.RANK[q["zone"]], -q["depth_ft"]))):
            row = []
            for c in columns:
                v = p.get(c)
                if c == "zone":
                    v = ZONE_TEXT.get(v, "")
                elif c in ("depth_ft", "velocity_fps"):
                    v = "" if v is None else "{:.3f}".format(v)
                elif c == "trace_depth":
                    v = "yes" if v else ""
                row.append("" if v is None else v)
            w.writerow(row)
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
            known = [p for p in pts if p["habitable_basis"] == core.BASIS_911 and not p["trace_depth"]]
            unk = [p for p in pts if p["habitable_basis"] == core.BASIS_REVIEWED and not p["trace_depth"]]
            trace = [p for p in pts if p["trace_depth"]]
            ax.scatter([p["velocity_fps"] for p in known], [p["depth_ft"] for p in known], s=30, fc="#1f4e9c",
                       ec="k", zorder=4)
            ax.scatter([p["velocity_fps"] for p in unk], [p["depth_ft"] for p in unk], s=46, marker="D", fc=ORANGE,
                       ec="k", zorder=4)
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
                   Line2D([], [], marker="o", ls="", mfc="#1f4e9c", mec="k",
                          label="ND 911 address point ({})".format(c["n_911"])),
                   Line2D([], [], marker="D", ls="", mfc=ORANGE, mec="k",
                          label="Reviewed habitable, not 911 ({})".format(c["n_reviewed"])),
                   Line2D([], [], marker="^", ls="", mfc="white", mec="k", label="Trace depth (0.00 ft)")]
        fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.0))
        fig.text(0.5, 0.075, third, ha="center", fontsize=8, color="#333")
        note = unverified_text(meta.get("unverified"))
        if note:
            fig.text(0.5, 0.045, note, ha="center", fontsize=7.5, color="#8a3b00")
        fig.tight_layout(rect=[0, 0.12, 1, 0.93])
        fig.savefig(path, dpi=dpi)
    finally:
        plt.close(fig)
    return path


# ------------------------------------------------------------------ main --
def build(receptors, charts, meta, out_dir, stem=CHART_NAME, habitable_types=None, chart_for_type=None,
          wet_min=0.0, cat=None, trace_ids=(), log=None):
    """Select the wet habitable structures, write `<stem>.csv` and `<stem>.png` (and the unverified worklist
    `<stem>_unverified.csv`) into out_dir, return a dict: {png, csv, unverified_csv, counts, unverified, text,
    left_out, note, status} with status "ok" | "csv_only" (matplotlib missing: note says why). Never raises for a
    drawing problem. meta: dam_id, dam_name, source, run_date, sampling."""
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
    u = unverified_summary(sel["unverified"])
    meta["unverified"] = u
    res = {"png": None, "csv": os.path.join(out_dir, stem + ".csv"),
           "unverified_csv": os.path.join(out_dir, stem + "_unverified.csv"), "counts": c, "unverified": u,
           "text": counts_text(c), "left_out": sel["left_out"], "note": "", "status": "ok",
           "source": meta.get("source"), "title": " - ".join(title_lines(meta, c)[:2])}
    if not pts:
        res["note"] = ("no wet habitable structures (ND 911 address points or structures reviewed habitable): the "
                       "chart shows the empty zones only")
    if u["total"]:
        res["note"] = "; ".join(x for x in (res["note"], unverified_text(u)) if x)
    write_csv(pts, res["csv"])
    write_csv(sel["unverified"], res["unverified_csv"], UNVERIFIED_COLUMNS,
              key=lambda q: (-(tm11.RANK.get(q["zone"], -1)), -q["depth_ft"]))
    try:
        res["png"] = draw(pts, meta, charts, os.path.join(out_dir, stem + ".png"))
    except ChartSkipped as e:
        res["status"] = "csv_only"
        res["note"] = "; ".join(x for x in (res["note"], "depth-velocity chart PNG skipped: {}; the CSV of the points "
                                           "was still written".format(e)) if x)
        log("depth-velocity chart PNG skipped: {}".format(e))
    except Exception as e:                                       # noqa: BLE001 - a chart must never fail a run
        res["status"] = "csv_only"
        res["note"] = "; ".join(x for x in (res["note"], "depth-velocity chart PNG failed ({}: {}); the CSV of the "
                                           "points was still written".format(type(e).__name__, e)) if x)
        log("depth-velocity chart PNG failed ({}: {})".format(type(e).__name__, e))
    return res


def png_data_uri(path):
    """data: URI of a PNG (self-contained HTML), or None."""
    try:
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")
    except (OSError, TypeError):
        return None
