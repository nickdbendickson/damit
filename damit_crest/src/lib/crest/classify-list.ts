/**
 * The real receptors the classify algorithm judged (GET /api/classify/receptors, classify_receptors.py: damit:classify's
 * damit_hazard_receptors.gpkg, or ndhazard:classify's Habitable_Structures / Roads_Inundated / Rail_Inundated), for the Dashboard and
 * the Report: names, class, depth, a point to zoom to, and which ones rest on a value that still needs a ruling.
 * Pure; the component fetches and draws. Absaraka desk test 2026-11-21: classify counted 230 wet structures while the
 * desk only listed its own 4 address points, so the two counts looked like a contradiction.
 */
import type { HazardResult } from "./types.ts";

export type ClassifyLayer = "STRUCTURES" | "ROADS" | "RAIL";

export type ClassifyReceptor = {
  rid: string;
  layer: ClassifyLayer;
  kind: string;
  name: string;
  /** Class ordinal (0-4) from a rule, or from an advisory method when `advisory`; null = wet, no hit. */
  ordinal: number | null;
  label: string;
  advisory?: boolean;
  depthFt: number | null;
  velFps: number | null;
  methods: string;
  flags: string[];
  /** [lon, lat] to zoom to (a line's middle vertex) and the feature's [west, south, east, north]. */
  at: [number, number] | null;
  bbox: [number, number, number, number] | null;
};

export type ClassifyList = {
  receptors: ClassifyReceptor[];
  total: number;
  truncated: boolean;
  counts: Partial<Record<ClassifyLayer, { total: number; wet: number; hit: number }>>;
  gpkg: string;
  /** Every receptor file read (ndhazard:classify writes one per layer); absent for damit:classify's single GeoPackage. */
  files?: string[];
  /** The report's "needs ruling" summary (qgis_run.unruled_top); undefined when the server did not say. */
  ruling?: HazardResult["ruling"];
};

export const LAYER_WORD: Record<ClassifyLayer, string> = { STRUCTURES: "Structure", ROADS: "Road", RAIL: "Rail" };

/**
 * Flags on a receptor whose value is not ruled yet: qgis_run.UNRULED_CODES (damit:classify), and classify_receptors
 * ND_UNRULED (ndhazard:classify: a road with no AADT assumed Medium, a rail crossing not confirmed, a structure whose
 * habitability is unverified).
 */
const UNRULED_FLAGS = ["trains_lookup", "aadt_assumed", "crossing_unconfirmed", "habitability_unverified"];

export const needsRuling = (r: Pick<ClassifyReceptor, "flags">): boolean => r.flags.some((f) => UNRULED_FLAGS.includes(f));

/** A checked list from the server's JSON, or null when it is not one. */
export function parseClassifyList(raw: unknown): ClassifyList | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (!Array.isArray(o.receptors)) return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const pair = (v: unknown) => (Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "number" && Number.isFinite(x)) ? (v as [number, number]) : null);
  const box = (v: unknown) => (Array.isArray(v) && v.length === 4 && v.every((x) => typeof x === "number" && Number.isFinite(x)) ? (v as [number, number, number, number]) : null);
  const receptors: ClassifyReceptor[] = [];
  for (const r of o.receptors as Record<string, unknown>[]) {
    if (!r || typeof r !== "object" || typeof r.rid !== "string") continue;
    const layer = r.layer === "ROADS" || r.layer === "RAIL" ? r.layer : "STRUCTURES";
    receptors.push({
      rid: r.rid,
      layer,
      kind: String(r.kind ?? ""),
      name: String(r.name ?? r.rid),
      ordinal: num(r.ordinal),
      label: String(r.label ?? ""),
      advisory: r.advisory === true,
      depthFt: num(r.depthFt),
      velFps: num(r.velFps),
      methods: String(r.methods ?? ""),
      flags: Array.isArray(r.flags) ? r.flags.map(String) : [],
      at: pair(r.at),
      bbox: box(r.bbox),
    });
  }
  return {
    receptors,
    total: num(o.total) ?? receptors.length,
    truncated: o.truncated === true,
    counts: (o.counts && typeof o.counts === "object" ? o.counts : {}) as ClassifyList["counts"],
    gpkg: String(o.gpkg ?? ""),
    ...(Array.isArray(o.files) ? { files: o.files.map(String) } : {}),
    ...("ruling" in o ? { ruling: parseRuling(o.ruling) } : {}),
  };
}

/** The classification's "needs ruling" summary from the server (qgis_run.unruled_top), checked; null = none. */
export function parseRuling(v: unknown): HazardResult["ruling"] {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const n = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : 0);
  if (!(n(o.unruled) > 0)) return null;
  return { label: String(o.label ?? ""), hits: n(o.hits), unruled: n(o.unruled), why: Array.isArray(o.why) ? o.why.map(String).slice(0, 3) : [] };
}

export type LayerFilter = ClassifyLayer | "all" | "ruling";

/** The rows shown for a layer chip and a search (name, id, class or method), in the server's order. */
export function filterClassify(list: readonly ClassifyReceptor[], layer: LayerFilter, query = ""): ClassifyReceptor[] {
  const q = query.trim().toLowerCase();
  return list.filter(
    (r) =>
      (layer === "all" || (layer === "ruling" ? needsRuling(r) : r.layer === layer)) &&
      (!q || [r.name, r.rid, r.label, r.methods].some((s) => s.toLowerCase().includes(q))),
  );
}

/** "252 of 1,670 structures wet · 11 of 263 roads with a hit · 6 of 34 rail lines with a hit". */
export function countsLine(c: ClassifyList["counts"]): string {
  const n = (v: number) => v.toLocaleString("en-US");
  const parts: string[] = [];
  if (c.STRUCTURES) parts.push(`${n(c.STRUCTURES.wet)} of ${n(c.STRUCTURES.total)} structures wet`);
  if (c.ROADS) parts.push(`${n(c.ROADS.hit)} of ${n(c.ROADS.total)} roads with a hit`);
  if (c.RAIL) parts.push(`${n(c.RAIL.hit)} of ${n(c.RAIL.total)} rail lines with a hit`);
  return parts.join(" · ");
}

/** Map dot colour by class: High and above red, Medium amber, Low blue, wet without a class teal. */
export function classColor(ordinal: number | null): string {
  if (ordinal == null) return "#0E768A";
  if (ordinal >= 3) return "#B91C1C";
  if (ordinal === 2) return "#B45309";
  return "#2563EB";
}

/** The bounds to zoom to for a receptor: its own box, grown to at least ~150 m so a house is not zoomed to a pixel. */
export function zoomBounds(r: Pick<ClassifyReceptor, "at" | "bbox">): { west: number; south: number; east: number; north: number } | null {
  const pad = 0.0015;
  if (r.bbox) {
    const [w, s, e, n] = r.bbox;
    const cx = (w + e) / 2,
      cy = (s + n) / 2;
    const hx = Math.max((e - w) / 2, pad),
      hy = Math.max((n - s) / 2, pad);
    return { west: cx - hx, south: cy - hy, east: cx + hx, north: cy + hy };
  }
  if (r.at) return { west: r.at[0] - pad, south: r.at[1] - pad, east: r.at[0] + pad, north: r.at[1] + pad };
  return null;
}

/** The class badge's "needs ruling" flag (qgis_run.unruled_top), in words; null when the class rests on ruled values. */
export function rulingFlag(r: Pick<HazardResult, "ruling"> | null | undefined): { short: string; text: string } | null {
  const g = r?.ruling;
  if (!g || !(g.unruled > 0)) return null;
  const all = g.unruled >= g.hits;
  const text = all
    ? `${g.label} rests only on values that still need a ruling (${g.unruled} of ${g.hits} ${g.label} hits).`
    : `${g.unruled} of ${g.hits} ${g.label} hits rest on values that still need a ruling; the other ${g.hits - g.unruled} are by rule.`;
  return { short: all ? "needs ruling" : "partly needs ruling", text: [text, ...g.why].join(" ") };
}
