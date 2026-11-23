import { lazy, Suspense, useMemo } from "react";

import { boundsOf, crest } from "@/lib/crest/dashboard";
import { DEPTH_BANDS, floodStrip, type FloodStrip } from "@/lib/crest/floodstrip";
import { num } from "@/lib/crest/format";
import { mapCallouts, mappedLayerOf } from "@/lib/crest/map-callouts";
import { outlineState } from "@/lib/crest/outline";
import { receptorPoints } from "@/lib/crest/results";
import type { Analysis, DamRecord } from "@/lib/crest/types";
import { ClientOnly } from "./ClientOnly";
import type { DashPoint } from "./DashboardMap";
import { useAnalysisOfRecord, useStripOfRecord } from "./results-flow";
import { useOnline } from "./use-online";

const DashboardMap = lazy(() => import("./DashboardMap").then((m) => ({ default: m.DashboardMap })));

const CLASS_COLOR: Record<string, string> = { High: crest.red, Medium: crest.amber, Low: crest.green };

/**
 * The layer the Workflow map draws, the same one the Dashboard draws: an imported run's raster strip when it is the
 * source of record and loaded, else the terrain outline when it is built, else the desk's schematic strip. Null when
 * the record cannot make any (no breach location or a dry valley): the Workflow then shows only the step's form.
 */
function useWorkflowMapLayer(dam: DamRecord, deskResult: Analysis) {
  const { result, label } = useAnalysisOfRecord(dam, deskResult);
  const online = useOnline();
  const outline = useMemo(() => outlineState(dam, result, online), [dam, result, online]);
  const record = useStripOfRecord(dam, deskResult);
  const depth = useMemo<FloodStrip | null>(
    () => (record.fromRun ? record.strip : outline.state === "ready" ? outline.outline : floodStrip(dam, result).strip),
    [record, outline, dam, result],
  );
  const basis = record.fromRun ? `${label} max depth` : outline.state === "ready" ? "Terrain outline (fast layer, not a 2-D model)" : "Desk estimate: schematic strip, not a mapped extent";
  // The callouts read the layer drawn: the terrain layer's area and depth when it is drawn instead of a run.
  const layer = useMemo(() => (!record.fromRun && outline.state === "ready" ? mappedLayerOf(outline.outline, "terrain layer") : null), [record.fromRun, outline]);
  return { depth, result, label, basis, layer };
}

/**
 * The map in the centre of the Workflow tab (Lumo's concept, DamIT Desk UI 2026-11-21): the flood layer of record with
 * the structures coloured by class, the arrival time at each wet structure, a depth legend, and the figures of record
 * over it. Every number is read from the analysis of record; the map is the Dashboard's map, not a new one.
 */
export function WorkflowMap({ dam, deskResult, open, onToggle }: { dam: DamRecord; deskResult: Analysis; open: boolean; onToggle: () => void }) {
  const { depth, result, label, basis, layer } = useWorkflowMapLayer(dam, deskResult);
  const fit = useMemo(() => boundsOf(depth), [depth]);
  const placed = useMemo(() => {
    const byId = new Map(result.flood.receptors.map((r) => [r.id, r]));
    return receptorPoints(dam, result).map((p) => ({ p, r: byId.get(p.id) }));
  }, [dam, result]);
  const points = useMemo<DashPoint[]>(
    () =>
      placed.map(({ p, r }) => ({
        id: p.id,
        name: p.name,
        lon: p.lon,
        lat: p.lat,
        color: r?.ndClass ? CLASS_COLOR[r.ndClass] : r?.flooded ? crest.teal : "#9CA3AF",
        label: `${p.name}: ${r ? (r.flooded ? `${num(r.depthFt, 2)} ft, ${num(r.velocityFps, 1)} ft/s` : r.unresolved ? "unresolved" : "dry") : "—"}${r?.ndClass ? ` · ${r.ndClass}` : ""}`,
      })),
    [placed],
  );
  const arrival = useMemo(
    () =>
      placed
        .filter(({ r }) => r?.flooded && r.arrivalHr != null)
        .map(({ p, r }) => ({ id: p.id, lon: p.lon, lat: p.lat, text: `${num(r!.arrivalHr!, 1)} h` })),
    [placed],
  );
  const callouts = useMemo(() => mapCallouts(result, label, layer), [result, label, layer]);
  if (!depth) return null;
  const toggle = (
    <button type="button" className="wf-map-toggle" aria-expanded={open} aria-controls="workflow-map-body" onClick={onToggle} data-testid="map-toggle">
      {open ? "Hide map" : "Show map"}
    </button>
  );
  if (!open)
    return (
      <section className="flex items-center justify-between gap-3 rounded-md border border-line bg-card px-3 py-2 text-sm" aria-label="Flood map" data-testid="workflow-map">
        <span className="text-muted">
          Flood map hidden · {callouts.map((c) => `${c.label} ${c.value}`).join(" · ")}
        </span>
        {toggle}
      </section>
    );
  const classes = (["High", "Medium", "Low"] as const).filter((c) => result.flood.receptors.some((r) => r.ndClass === c));
  return (
    <section className="wf-map relative overflow-hidden rounded-md border border-line bg-card" aria-label="Flood map" data-testid="workflow-map" id="workflow-map-body">
      <div className="wf-map-canvas">
        <ClientOnly fallback={<p className="p-4 text-sm text-muted">Loading the map…</p>}>
          <Suspense fallback={<p className="p-4 text-sm text-muted">Loading the map…</p>}>
            <DashboardMap depth={depth} points={points} arrival={arrival} hillshade={false} overlays={[]} fit={fit} />
          </Suspense>
        </ClientOnly>
      </div>
      <dl className="wf-callouts" data-testid="map-callouts">
        {callouts.map((c) => (
          <div key={c.key} className="wf-callout" title={c.note} data-testid={`callout-${c.key}`}>
            <dt>{c.label}</dt>
            <dd>{c.value}</dd>
          </div>
        ))}
      </dl>
      <div className="wf-legend" data-testid="map-legend">
        <p className="wf-legend-title">Max depth</p>
        {[...DEPTH_BANDS].reverse().map((b) => (
          <p key={b.id} className="wf-legend-row">
            <span style={{ background: b.color }} aria-hidden="true" /> {b.label}
          </p>
        ))}
        {classes.length ? <p className="wf-legend-title mt-1">Structures</p> : null}
        {classes.map((c) => (
          <p key={c} className="wf-legend-row">
            <span className="round" style={{ background: CLASS_COLOR[c] }} aria-hidden="true" /> {c}
          </p>
        ))}
        {arrival.length ? <p className="wf-legend-row">Labels in hours: arrival at each wet structure</p> : null}
      </div>
      <p className="wf-basis" data-testid="map-basis">
        {basis}
      </p>
      <div className="wf-map-tools">{toggle}</div>
    </section>
  );
}
