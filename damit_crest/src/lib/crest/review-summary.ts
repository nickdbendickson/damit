/**
 * The Review tab's summary band (DamIT Desk UI, 2026-11-21): the class badge from the actual damit:classify result,
 * the key figures, and the criteria-hit table rows. Everything comes from the stored result's structured fields
 * (HazardResult: hits, driving, layers, impacted, complete) and the desk analysis; nothing is scraped from text and
 * nothing is invented. Pure: no DOM.
 */
import { choiceText, classifyReceptors, hazardOrdinal, hazardStatus } from "./classify-receptors.ts";
import { damChoice } from "./jurisdiction.ts";
import type { Analysis, DamRecord, HazardHit, HazardResult } from "./types.ts";

/** The disclaimer under the class badge, naming the classify algorithm (damit:classify, or ndhazard:classify for ND). */
export const suggestedDisclaimer = (alg = "damit:classify"): string =>
  `A suggested class from ${alg}: the engineer of record and the regulating agency make the determination.`;
export const SUGGESTED_DISCLAIMER = suggestedDisclaimer();

export type ClassBadge = {
  state: "none" | "stale" | "partial" | "current";
  /** The badge's words: the class, "At least High", "Out of date", "Not classified". */
  text: string;
  /** The line under it. */
  note: string;
  ordinal: number | null;
  jurisdiction: string;
};

export function classBadge(dam: DamRecord, result: Pick<Analysis, "flood">, alg = "damit:classify"): ClassBadge {
  const st = hazardStatus(dam, result);
  const jurisdiction = choiceText(damChoice(dam));
  if (st.state === "none") return { state: "none", text: "Not classified", note: `${alg} has not run for this dam: Classify is on the Export & Hand-off tab.`, ordinal: null, jurisdiction };
  const r = st.result;
  if (st.state === "stale") return { state: "stale", text: "Out of date", note: `Last result ${r.suggestedClass}, not shown as the class: ${st.why}.`, ordinal: null, jurisdiction };
  const ord = hazardOrdinal(r);
  if (r.complete === false) {
    const missing = Object.keys(r.notChecked ?? {}).map((k) => k.toLowerCase());
    return { state: "partial", text: `Partial: at least ${r.suggestedClass}`, note: `${missing.join(", ") || "some layers"} not checked, so this is a lower bound.`, ordinal: ord, jurisdiction };
  }
  return { state: "current", text: r.suggestedClass, note: `Classified ${r.classifiedAt.slice(0, 10)}${r.warnings ? `; ${r.warnings} warning${r.warnings === 1 ? "" : "s"} in the run report` : ""}.`, ordinal: ord, jurisdiction };
}

export type Tile = { key: string; label: string; value: string; note: string };

const n = (v: number) => v.toLocaleString("en-US");

/**
 * Peak discharge, then structures, roads and rail: the receptors the last classify actually sent (and how many it
 * scored a hit for), or, with no result, the receptors the desk would send now (marked so).
 */
export function summaryTiles(dam: DamRecord, result: Pick<Analysis, "flood" | "breach">, alg = "damit:classify"): Tile[] {
  const tiles: Tile[] = [
    { key: "peak", label: "Peak discharge", value: Number.isFinite(result.breach.peakCfs) ? `${n(Math.round(result.breach.peakCfs))} cfs` : "—", note: "desk breach hydrograph" },
  ];
  const st = hazardStatus(dam, result);
  const r: HazardResult | null = st.state === "none" ? null : st.result;
  const layers: [string, string][] = [["STRUCTURES", "Structures"], ["ROADS", "Roads"], ["RAIL", "Rail"]];
  if (r?.layers && Object.keys(r.layers).length) {
    for (const [k, label] of layers) {
      const sent = r.layers[k] ?? 0;
      const hit = k === "STRUCTURES" ? (r.wetStructures ?? r.impacted?.[k]) : r.impacted?.[k];
      tiles.push({
        key: k.toLowerCase(),
        label,
        value: n(sent),
        note: `${alg === "ndhazard:classify" ? "checked by" : "sent to"} ${alg}${hit != null ? `; ${n(hit)} ${k === "STRUCTURES" && r.wetStructures != null ? "wet" : "with a hit"}` : ""}${st.state === "stale" ? " (out of date)" : ""}`,
      });
    }
    return tiles;
  }
  const exp = classifyReceptors(dam, result);
  for (const [k, label] of layers) {
    const c = exp.layers[k as keyof typeof exp.layers]?.features.length ?? 0;
    tiles.push({ key: k.toLowerCase(), label, value: n(c), note: "desk receptors Classify would send (not run yet)" });
  }
  return tiles;
}

export type HitRow = {
  id: string;
  /** Structure / Road / Rail / … from the receptor id, or "—". */
  type: string;
  receptor: string;
  criterion: string;
  strength: string;
  finding: string;
  label: string;
  ordinal: number | null;
};

const TYPE_WORD: Record<string, string> = { structure: "Structure", road: "Road", rail: "Rail", facility: "Facility", lifeline: "Lifeline", environment: "Environment" };

function typeOf(ids: string[]): string {
  const kinds = [...new Set(ids.map((i) => i.split(":", 1)[0]))];
  if (!kinds.length) return "—";
  return kinds.map((k) => TYPE_WORD[k] ?? k).join(", ");
}

/** The criteria-hit table: the stored hits, else (a result from before hits were kept) the driving hits. */
export function hitRows(r: HazardResult | null | undefined): { rows: HitRow[]; total: number; source: "hits" | "driving" | "none" } {
  if (!r) return { rows: [], total: 0, source: "none" };
  if (Array.isArray(r.hits) && r.hits.length) {
    const rows = r.hits.map((h: HazardHit, i) => ({
      id: `h${i}`,
      type: typeOf(h.receptors),
      receptor: h.receptors.length ? h.receptors.join(", ") + (h.receptorCount > h.receptors.length ? ` +${h.receptorCount - h.receptors.length} more` : "") : "—",
      criterion: h.method + (h.scenario ? ` (${h.scenario})` : ""),
      strength: h.strength || "—",
      finding: h.reason,
      label: h.label,
      ordinal: h.ordinal,
    }));
    return { rows, total: r.hitsTotal ?? rows.length, source: "hits" };
  }
  const rows = (r.driving ?? []).map((h, i) => ({
    id: `d${i}`,
    type: "—",
    receptor: `${h.receptors} receptor${h.receptors === 1 ? "" : "s"}`,
    criterion: h.method,
    strength: "—",
    finding: h.reason,
    label: h.label,
    ordinal: null,
  }));
  return { rows, total: rows.length, source: rows.length ? "driving" : "none" };
}

export type HitSortKey = "type" | "receptor" | "criterion" | "strength" | "finding" | "class";

/** Sorted rows: class by its ordinal (then label); the rest as text with numbers in order. */
export function sortHits(rows: readonly HitRow[], key: HitSortKey, desc: boolean): HitRow[] {
  const cmpText = (a: string, b: string) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
  const cmp = (a: HitRow, b: HitRow) =>
    key === "class" ? (a.ordinal ?? -1) - (b.ordinal ?? -1) || cmpText(a.label, b.label) : cmpText(String(a[key]), String(b[key]));
  return [...rows].sort((a, b) => (desc ? -cmp(a, b) : cmp(a, b)) || cmpText(a.id, b.id));
}

/** Validate hits handed back by the desk server (GET /api/job classification.hits) before they are stored. */
export function parseHits(v: unknown): HazardHit[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const str = (x: unknown, max: number) => (typeof x === "string" ? x.slice(0, max) : "");
  const out: HazardHit[] = [];
  for (const h of v.slice(0, 300)) {
    if (!h || typeof h !== "object") continue;
    const o = h as Record<string, unknown>;
    const recs = Array.isArray(o.receptors) ? o.receptors.filter((x): x is string => typeof x === "string").slice(0, 5) : [];
    out.push({
      method: str(o.method, 40),
      ordinal: typeof o.ordinal === "number" && Number.isInteger(o.ordinal) ? o.ordinal : null,
      label: str(o.label, 40),
      strength: str(o.strength, 20),
      reason: str(o.reason, 200),
      scenario: str(o.scenario, 20),
      receptors: recs,
      receptorCount: typeof o.receptorCount === "number" ? o.receptorCount : recs.length,
    });
  }
  return out;
}
