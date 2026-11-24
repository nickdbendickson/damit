/**
 * The left rail's checklist (DamIT Desk UI, 2026-11-21): what holds each step, from the desk's own checks only —
 * missingForNext (nid-dams.ts), the datum and flood flags (warnings.ts) and the step-done rules (pipeline.ts) — each
 * with where "Fix…" takes the user: a step, and the field or button to focus there (a CSS selector the step renders).
 * Pure: no DOM.
 */
import { INPUT_RANGE } from "./engine.ts";
import { missingForNext } from "./nid-dams.ts";
import { screeningHold, STEP_DONE, type PipelineAnalysis } from "./pipeline.ts";
import type { DamRecord, StepId } from "./types.ts";
import { datumFlags, floodFlags, type Warning } from "./warnings.ts";

export type CheckKind = "missing" | "stop" | "warn" | "todo";

export type CheckItem = {
  key: string;
  /** The step Fix… opens (the rail may list the item under a later step it holds). */
  step: StepId;
  kind: CheckKind;
  /** Short, for the rail. */
  text: string;
  /** The whole sentence (the flag's own text), for the tooltip and screen readers. */
  detail: string;
  /** What Fix… focuses on that step (a selector), or null for the step itself. */
  target: string | null;
};

const field = (name: string) => `[data-fix="${name}"]`;

/** missingForNext's words → the Record step's field. */
export const MISSING_FIELD: Record<string, { label: string; target: string }> = {
  height: { label: "Height", target: field("heightFt") },
  storage: { label: "Storage", target: field("storageAcFt") },
  length: { label: "Length", target: field("lengthFt") },
  crest: { label: "Crest elevation", target: field("crestFt") },
  "breach bottom": { label: "Streambed (breach bottom)", target: field("streambedFt") },
  datum: { label: "Stated datum", target: field("statedDatum") },
};

const RANGE_FIELD = Object.entries(INPUT_RANGE).map(([k, r]) => ({ label: r.label, target: field(k) }));

/** Where a datum or flood flag is fixed. */
export function flagTarget(w: Warning, origin: "datum" | "flood"): { step: StepId; target: string | null } {
  if (w.code === "W-H1" || w.code === "W-H2") return { step: "record", target: field("heightFt") };
  if (w.code === "W-V1") {
    const f = RANGE_FIELD.find((r) => w.text.startsWith(`${r.label} `));
    if (f) return { step: "record", target: f.target };
  }
  if (w.code === "W-D1") {
    if (/^No DEM tie\b|DEM crest/.test(w.text)) return { step: "record", target: field("demCrestFt") };
    if (/NGVD29 offset/.test(w.text)) return { step: "record", target: field("datumOffsetFt") };
    if (/^Streambed/.test(w.text)) return { step: "record", target: field("streambedFt") };
    return { step: "record", target: field("statedDatum") };
  }
  if (origin === "flood") return { step: "flood", target: '[data-testid="outline-panel"]' };
  return { step: "record", target: null };
}

const short = (t: string, n = 70) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);

/** The rail's to-dos for one step that is not complete. */
const TODO: Partial<Record<StepId, { text: string; target: string | null }>> = {
  flood: { text: "Build the terrain layer (or import a model run)", target: '[data-testid="outline-panel"] button:not(:disabled)' },
  results: { text: "No model run imported yet", target: '[data-testid="import-lisflood-files"]' },
  screen: { text: "The screen is held at Review", target: '[data-testid="screen-source"]' },
  report: { text: "Not classified: run Classify", target: field("classify") },
};

/**
 * Every step's items, in rail order. Missing inputs and stop flags block; warn flags and to-dos do not. A step that
 * is complete by its rule shows only its flags; Dashboard's to-do points at Flood.
 */
/** Steps whose rule waits on another step's input: listed under them, fixed there. */
const WAITS_ON: Partial<Record<StepId, { needs: string[]; text: string }>> = {
  setup: { needs: ["height", "storage"], text: "Needs height and storage" },
  breach: { needs: ["breach bottom"], text: "Needs the streambed (breach bottom)" },
};

export function stepChecklist(
  dam: DamRecord,
  desk: { datum: { warnings: string[]; flags?: Warning[] }; flood: { warnings: string[]; flags?: Warning[] } },
  record: PipelineAnalysis,
  /** The classify algorithm to name in the Report to-do (the active profile's: damit:classify or ndhazard:classify). */
  classifyAlg = "damit:classify",
): Record<StepId, CheckItem[]> {
  const out: Record<StepId, CheckItem[]> = { setup: [], record: [], breach: [], flood: [], results: [], dashboard: [], screen: [], report: [] };
  for (const m of missingForNext(dam)) {
    const f = MISSING_FIELD[m] ?? { label: m, target: null };
    out.record.push({ key: `missing-${m}`, step: "record", kind: "missing", text: `${f.label} is missing`, detail: `${f.label} is missing: enter it on the Record step.`, target: f.target });
  }
  const missingTargets = new Set(out.record.map((i) => i.target));
  for (const [id, w] of Object.entries(WAITS_ON) as [StepId, { needs: string[]; text: string }][]) {
    if (STEP_DONE[id](dam, record)) continue;
    const first = missingForNext(dam).find((m) => w.needs.includes(m));
    if (!first) continue;
    out[id].push({ key: `waits-${id}`, step: "record", kind: "missing", text: w.text, detail: `${w.text}: enter it on the Record step.`, target: MISSING_FIELD[first].target });
  }
  const flags: [Warning, "datum" | "flood", number][] = [
    ...datumFlags(desk).map((w, i): [Warning, "datum", number] => [w, "datum", i]),
    ...floodFlags(desk).map((w, i): [Warning, "flood", number] => [w, "flood", i]),
  ];
  for (const [w, origin, i] of flags) {
    if (w.severity === "info") continue;
    const t = flagTarget(w, origin);
    // A flag that only repeats a missing input above (W-D1 "Elevations missing", a W-V1 placeholder) is not listed twice.
    if (missingTargets.size && (/^Elevations missing/.test(w.text) || / is missing\b/.test(w.text) || (t.target && missingTargets.has(t.target)))) continue;
    out[t.step].push({ key: `${origin}-${w.code}-${i}`, step: t.step, kind: w.severity === "stop" ? "stop" : "warn", text: `${w.code} ${short(w.text)}`, detail: `${w.code}: ${w.text}`, target: t.target });
  }
  // A PARTIAL / not-determined / failed QGIS screening holds the Screen step: say so, and point at the hand-off panel.
  const hold = screeningHold(dam);
  if (hold)
    out.screen.push({ key: `screening-${hold.kind}`, step: "report", kind: "warn", text: short(hold.text), detail: `${hold.text}. Raise the time limit (DAMIT_SCREENING_TIMEOUT_S) or import a finished model run, then classify.`, target: '[data-testid="screening-partial"], #handoff-panel' });
  for (const [id, todo] of Object.entries(TODO) as [StepId, { text: string; target: string | null }][]) {
    if (STEP_DONE[id](dam, record)) continue;
    if (id === "screen" && missingForNext(dam).length) continue; // the missing inputs above are the reason
    if (id === "screen" && hold) continue; // the screening item above is the reason
    if (id === "flood" && !STEP_DONE.dashboard(dam, record))
      out.dashboard.push({ key: "todo-dashboard", step: "flood", kind: "todo", text: "Needs a flood layer (Flood step)", detail: "The Dashboard needs a flood layer: build it on the Flood step or import a model run.", target: todo.target });
    const text = id === "report" ? `Not classified: run ${classifyAlg}` : todo.text;
    out[id].push({ key: `todo-${id}`, step: id, kind: "todo", text, detail: text, target: todo.target });
  }
  return out;
}

/** Whether a step's items hold it (missing inputs or a stop flag), not just ask for a look. */
export function blocks(items: readonly CheckItem[]): boolean {
  return items.some((i) => i.kind === "missing" || i.kind === "stop");
}

/** Most items a step lists in the rail; the rest are on the step itself. */
export const RAIL_ITEMS_MAX = 4;
