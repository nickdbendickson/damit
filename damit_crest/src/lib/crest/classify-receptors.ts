/**
 * Downstream receptors for damit:classify (the DamIT Hazard plugin), so the jurisdiction preset or custom methods the
 * user picked on the Report step, not the desk's ND / ACER TM 11 screen, judge the downstream consequences.
 *
 * Crest receptor kinds map onto classify's receptor layers (EPSG:4326 GeoJSON, written by the desktop server):
 *   house / mobile / barn (911 points for review included) -> STRUCTURES (points)
 *   road                                                  -> ROADS (a line across the valley at the crossing)
 *   rail (if a record carries one)                        -> RAIL (same)
 * The desk has no critical-facility, lifeline or environmental receptors, so FACILITIES / LIFELINES / ENVIRONMENT are
 * never written from here. A drawn downstream area goes as DOMAIN.
 *
 * Position, in order: the seed's own lon/lat ("mapped"); a 911 seed's address point from the NG911 cache ("911
 * address point"); else where the desk's straight valley puts it from the breach along the downstream direction
 * ("desk valley", schematic). A receptor none of these can place is skipped and listed with the reason.
 */
import { downstreamDirection, fromLocal, toLocal, type XY } from "./aoi.ts";
import { damLocation } from "./engine.ts";
import { damChoice, handoffChoice, resolveChoice } from "./jurisdiction.ts";
import { halfAt } from "./results.ts";
import type { Analysis, ClassificationChoice, DamRecord, GeoJSONFeature, HazardResult, ReceptorSeed } from "./types.ts";

export const CLASSIFY_LAYERS = ["STRUCTURES", "ROADS", "RAIL", "FACILITIES", "LIFELINES", "ENVIRONMENT"] as const;
export type ClassifyLayer = (typeof CLASSIFY_LAYERS)[number];

export type ReceptorPlacement = "mapped" | "911 address point" | "desk valley";

export type ReceptorFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] } | { type: "LineString"; coordinates: [number, number][] };
  properties: Record<string, string | number | boolean | null>;
};

export type SkippedReceptor = { id: string; name: string; kind: string; reason: string };

/** What the Classify button sends as `receptors` (desktop/damit_desktop/receptors.py writes the files). */
export type ReceptorExport = {
  format: "damit_crest/classify_receptors";
  version: 1;
  crs: "EPSG:4326";
  layers: Partial<Record<ClassifyLayer, { type: "FeatureCollection"; features: ReceptorFeature[] }>>;
  /** The drawn downstream area (routed-domain polygon), when one was drawn. */
  domain: GeoJSONFeature | null;
  skipped: SkippedReceptor[];
  placement: Record<ReceptorPlacement, number>;
  /** How the downstream direction was found (desk-valley placement and road lines need it), or why it was not. */
  direction: string | null;
};

/** Hazard's receptor reader matches these names (damit_hazard engine/receptors.py ALIASES / TYPE_VALUES). */
export function hazardType(seed: Pick<ReceptorSeed, "kind" | "habitable">): string {
  const kind = String(seed.kind);
  if (kind === "mobile") return seed.habitable === false ? "outbuilding" : "mobile_home";
  if (kind === "barn") return seed.habitable === true ? "farm_occupied" : "farm_unoccupied";
  if (kind === "house") return seed.habitable === false ? "outbuilding" : "home";
  return kind;
}

export function layerFor(kind: string): ClassifyLayer | null {
  if (kind === "house" || kind === "mobile" || kind === "barn") return "STRUCTURES";
  if (kind === "road") return "ROADS";
  if (kind === "rail") return "RAIL";
  return null;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const r7 = (v: number) => Math.round(v * 1e7) / 1e7;

function nd911Point(dam: DamRecord, seed: ReceptorSeed): [number, number] | null {
  if (seed.source !== "nd911" || !seed.sourceRef) return null;
  const p = dam.nd911?.points?.find((q) => q.nguid === seed.sourceRef);
  return p && finite(p.lon) && finite(p.lat) ? [p.lon, p.lat] : null;
}

/** The receptor layers and DOMAIN for damit:classify, from the record's seeds and the desk analysis' reach. */
export function classifyReceptors(dam: DamRecord, result: Pick<Analysis, "flood">): ReceptorExport {
  const loc = damLocation(dam);
  const dir = loc ? downstreamDirection(dam.geometry, loc) : null;
  const u: XY | null = dir?.u ?? null;
  const layers: ReceptorExport["layers"] = {};
  const skipped: SkippedReceptor[] = [];
  const placement: Record<ReceptorPlacement, number> = { mapped: 0, "911 address point": 0, "desk valley": 0 };
  dam.receptors.forEach((seed, i) => {
    const kind = String(seed.kind);
    const skip = (reason: string) => skipped.push({ id: seed.id, name: seed.name, kind, reason });
    const layer = layerFor(kind);
    if (!layer) return skip(`kind "${kind}" has no damit:classify receptor layer`);
    const ranked = result.flood.receptors[i];
    let at: [number, number] | null = null;
    let placed: ReceptorPlacement = "mapped";
    if (finite(seed.lon) && finite(seed.lat)) at = [seed.lon, seed.lat];
    else if ((at = nd911Point(dam, seed))) placed = "911 address point";
    else if (loc && u && ranked && finite(ranked.distanceKm)) {
      const x = ranked.distanceKm * 1000;
      const h = halfAt(result.flood.stations, ranked.distanceKm);
      const left: XY = [-u[1], u[0]];
      at = fromLocal([u[0] * x - seed.lateral * h * left[0], u[1] * x - seed.lateral * h * left[1]], loc);
      placed = "desk valley";
    }
    if (!at || !finite(at[0]) || !finite(at[1]) || Math.abs(at[0]) > 180 || Math.abs(at[1]) > 90) {
      return skip(
        !loc
          ? "no position: it has no longitude/latitude and the dam has no breach point or location to place it from"
          : "no position: it has no longitude/latitude and the downstream direction is unknown (draw the dam line and the reservoir point)",
      );
    }
    const props: ReceptorFeature["properties"] = {
      crest_id: seed.id,
      name: seed.name,
      kind,
      type: layer === "STRUCTURES" ? hazardType(seed) : kind,
      placed,
      distance_km: ranked && finite(ranked.distanceKm) ? Math.round(ranked.distanceKm * 1000) / 1000 : null,
      pad_ft: finite(seed.padFt) ? seed.padFt : null,
      source: seed.source ?? "crest",
      source_ref: seed.sourceRef ?? null,
    };
    if (layer === "STRUCTURES") props.habitable = seed.habitable ?? null;
    let geometry: ReceptorFeature["geometry"];
    if (layer === "ROADS" || layer === "RAIL") {
      // damit:classify reads roads and rail as lines. The desk knows a crossing point, so the line is drawn across the
      // valley there (perpendicular to the downstream direction, the desk half-width each side).
      if (!loc || !u) return skip("a road crossing needs the downstream direction to be drawn as a line (draw the dam line and the reservoir point)");
      const d = ranked && finite(ranked.distanceKm) ? ranked.distanceKm : 0;
      const h = Math.max(50, halfAt(result.flood.stations, d));
      const c = toLocal(at[0], at[1], loc);
      const left: XY = [-u[1], u[0]];
      const a = fromLocal([c[0] - left[0] * h, c[1] - left[1] * h], loc);
      const b = fromLocal([c[0] + left[0] * h, c[1] + left[1] * h], loc);
      geometry = { type: "LineString", coordinates: [[r7(a[0]), r7(a[1])], [r7(b[0]), r7(b[1])]] };
      props.road_class = seed.roadClass ?? null;
      props.aadt = finite(seed.aadt) ? seed.aadt : null;
      props.geom_basis = "line across the valley at the crossing";
    } else {
      geometry = { type: "Point", coordinates: [r7(at[0]), r7(at[1])] };
    }
    placement[placed] += 1;
    const fc = (layers[layer] ??= { type: "FeatureCollection", features: [] });
    fc.features.push({ type: "Feature", geometry, properties: props });
  });
  const aoi = dam.geometry?.aoi;
  const domain = aoi && (aoi.geometry?.type === "Polygon" || aoi.geometry?.type === "MultiPolygon") ? aoi : null;
  return {
    format: "damit_crest/classify_receptors",
    version: 1,
    crs: "EPSG:4326",
    layers,
    domain,
    skipped,
    placement,
    direction: dir?.note ?? (loc ? null : "no breach location"),
  };
}

export function receptorCount(exp: ReceptorExport): number {
  return Object.values(exp.layers).reduce((n, fc) => n + (fc?.features.length ?? 0), 0);
}

function hash(text: string): string {
  let h = 5381;
  for (let i = 0; i < text.length; i++) h = ((h * 33) ^ text.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

/** Identifies the jurisdiction choice a classify result was made for (preset id or the method ids + advisory). */
export function choiceKey(choice: ClassificationChoice | undefined | null): string {
  const c = resolveChoice(choice);
  return c.mode === "custom"
    ? `custom:${[...(c.methods ?? [])].sort().join(",")}:${c.advisory ? "adv" : ""}`
    : `preset:${c.preset}:${c.advisory ? "adv" : ""}`;
}

/** Identifies the receptors (and domain) a classify result was made from. */
export function receptorKey(exp: ReceptorExport): string {
  return hash(JSON.stringify([exp.layers, exp.domain?.geometry ?? null]));
}

/** Plain words for the choice: the preset's label, or the custom method ids. */
export function choiceText(choice: ClassificationChoice | undefined | null): string {
  const c = handoffChoice(choice);
  return c.mode === "custom" ? `custom methods ${(c.methods ?? []).join(", ") || "(none ticked)"}` : (c.presetLabel ?? c.preset ?? "");
}

export type HazardStatus =
  | { state: "none" }
  | { state: "current"; result: HazardResult }
  | { state: "stale"; result: HazardResult; why: string };

/** The record's damit:classify result, and whether it still belongs to the chosen jurisdiction and receptors. */
export function hazardStatus(dam: DamRecord, result: Pick<Analysis, "flood">): HazardStatus {
  const r = dam.hazardResult;
  if (!r || !r.suggestedClass) return { state: "none" };
  if (r.choiceKey !== choiceKey(damChoice(dam)))
    return { state: "stale", result: r, why: `it was classified for ${r.choiceText}, not the current choice (${choiceText(damChoice(dam))})` };
  if (r.receptorKey !== receptorKey(classifyReceptors(dam, result)))
    return { state: "stale", result: r, why: "the downstream receptors or the drawn area changed since it was classified" };
  return { state: "current", result: r };
}

/** The ordinal Hazard returned as a number 0-4, or null. */
export function hazardOrdinal(r: Pick<HazardResult, "ordinal">): number | null {
  const n = Number(r.ordinal);
  return Number.isFinite(n) && n >= 0 && n <= 4 ? Math.round(n) : null;
}

/** The Report's lead: damit:classify's class for the chosen jurisdiction once it has run, else why there is none. */
export type ReportLead = {
  kind: "hazard" | "stale" | "none";
  /** e.g. "DamIT classification (Nebraska): Significant". Never the desk screen. */
  title: string;
  lines: string[];
};

export function reportLead(dam: DamRecord, result: Pick<Analysis, "flood">): ReportLead {
  const st = hazardStatus(dam, result);
  const chosen = choiceText(damChoice(dam));
  if (st.state === "current") {
    const r = st.result;
    const ord = hazardOrdinal(r);
    const lines = [
      `damit:classify judged the downstream receptors with ${chosen}: ${r.suggestedClass}` +
        (ord != null ? ` (ordinal ${ord}${r.genericLabel && r.genericLabel !== r.suggestedClass ? `, ${r.genericLabel}` : ""})` : "") +
        ". A suggested class; the engineer of record and the regulating agency make the determination.",
    ];
    for (const h of r.driving ?? []) lines.push(`${h.method} ${h.label}: ${h.reason}${h.receptors ? ` (${h.receptors} receptor${h.receptors === 1 ? "" : "s"})` : ""}`);
    if (r.layers) lines.push(`Receptors sent: ${Object.entries(r.layers).map(([k, n]) => `${k} ${n}`).join(", ")}${r.skipped ? `; ${r.skipped} not sent (no position)` : ""}.`);
    if (r.warnings) lines.push(`${r.warnings} warning${r.warnings === 1 ? "" : "s"} in the run report.`);
    if (r.report) lines.push(`Run report: ${r.report}`);
    if (r.gpkg) lines.push(`Receptors by class: ${r.gpkg}`);
    return { kind: "hazard", title: `DamIT classification (${chosen}): ${r.suggestedClass}`, lines };
  }
  if (st.state === "stale")
    return {
      kind: "stale",
      title: `DamIT classification (${chosen}): out of date`,
      lines: [
        `The last damit:classify result (${st.result.suggestedClass}) is not shown as this jurisdiction's class: ${st.why}. Run Classify again.`,
      ],
    };
  const exp = classifyReceptors(dam, result);
  const n = receptorCount(exp);
  return {
    kind: "none",
    title: `DamIT classification (${chosen}): not run yet`,
    lines: [
      n
        ? `Classify (below) sends ${n} downstream receptor${n === 1 ? "" : "s"} to damit:classify with ${chosen}; the class for this choice comes from there.`
        : "No downstream receptor can be sent to damit:classify yet (none has a position). Add or map receptors and draw the breach point, dam line and reservoir point.",
      ...(exp.skipped.length ? [`${exp.skipped.length} receptor${exp.skipped.length === 1 ? "" : "s"} cannot be placed and would not be sent.`] : []),
    ],
  };
}

/** The paper sheet's stamp: Hazard's class when it is current, else the desk screen marked as a schematic preview. */
export function paperStamp(level: string, lead: ReportLead, hazardClass?: string): string {
  return lead.kind === "hazard" && hazardClass ? `DAMIT CLASSIFY: ${hazardClass}`.toUpperCase() : `SCHEMATIC PREVIEW: ${level}`.toUpperCase();
}
