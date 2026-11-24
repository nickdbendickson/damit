/**
 * The figures printed over the Workflow map (DamIT Desk UI, 2026-11-21): max depth, max velocity, the first arrival
 * at a wet structure, peak discharge and wet area, read from the analysis of record (the desk estimate, or an imported
 * run's rasters when it is the source of record, results.ts analysisOfRecord). Nothing is made up: a figure the
 * analysis does not have is shown as "—" with the reason.
 */
import { num } from "./format.ts";
import type { Analysis } from "./types.ts";

export type Callout = { key: "depth" | "velocity" | "arrival" | "peak" | "area"; label: string; value: string; note: string };

/**
 * The mapped layer drawn under the callouts when it is not the analysis of record (the terrain layer built on the
 * Flood step while the desk estimate is the source of record). Absaraka desk test 2026-11-21: the map showed the
 * 10,329 ac terrain layer while the callouts said 14.8 ft / 2,374 ac from the schematic strip.
 */
export type MappedLayer = { areaAc: number; maxDepthFt: number | null; label: string };

/** The terrain layer's figures: its mapped area and the deepest band's maximum depth. */
export function mappedLayerOf(outline: { properties: { outline_area_ac: number }; features: { properties: { depth_max_ft?: number } }[] }, label: string): MappedLayer {
  const depths = outline.features.map((f) => f.properties.depth_max_ft).filter((d): d is number => typeof d === "number" && Number.isFinite(d));
  return { areaAc: outline.properties.outline_area_ac, maxDepthFt: depths.length ? Math.max(...depths) : null, label };
}

export function mapCallouts(result: Pick<Analysis, "flood" | "breach">, source: string, layer?: MappedLayer | null): Callout[] {
  const f = result.flood;
  const wet = f.receptors.filter((r) => r.flooded && r.arrivalHr != null && Number.isFinite(r.arrivalHr));
  const first = wet.length ? wet.reduce((a, b) => ((b.arrivalHr as number) < (a.arrivalHr as number) ? b : a)) : null;
  const fin = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);
  const depth = layer && fin(layer.maxDepthFt) ? { v: layer.maxDepthFt, note: layer.label } : { v: f.maxDepthFt, note: source };
  const area = layer && fin(layer.areaAc) ? { v: layer.areaAc, note: `${layer.label} (mapped, ≥ 0.1 ft)` } : { v: f.acres, note: source };
  // A max velocity of 0 means no receptor produced an estimate (none entered or none wet), not a still flood.
  const vel = fin(f.maxVelocityFps) && f.maxVelocityFps > 0;
  return [
    { key: "depth", label: "Max depth", value: fin(depth.v) ? `${num(depth.v, 1)} ft` : "—", note: depth.note },
    {
      key: "velocity",
      label: "Max velocity",
      value: vel ? `${num(f.maxVelocityFps, 1)} ft/s` : "—",
      note: vel ? f.velocityBasis || source : "no velocity estimate: no wet receptor with a velocity (import a model run for its velocity raster)",
    },
    {
      key: "arrival",
      label: "First arrival",
      value: first ? `${num(first.arrivalHr as number, 2)} hr` : "—",
      note: first ? `at ${first.name}` : "no wet structure with an arrival time",
    },
    { key: "peak", label: "Peak discharge", value: fin(result.breach.peakCfs) ? `${num(result.breach.peakCfs, 0)} cfs` : "—", note: "desk breach hydrograph" },
    { key: "area", label: "Wet area", value: fin(area.v) ? `${num(area.v, 0)} ac` : "—", note: area.note },
  ];
}
