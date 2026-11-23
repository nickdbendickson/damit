/**
 * The left rail's checklist and progress ring (DamIT Desk UI, 2026-11-21). The items come from lib/crest/checklist.ts
 * (missingForNext, the datum and flood flags, the step-done rules); "Fix…" jumps to the step and focuses the field.
 */
import { blocks, RAIL_ITEMS_MAX, type CheckItem } from "@/lib/crest/checklist";
import { STEPS } from "@/lib/crest/engine";
import { pipelineProgress, screeningHold, stepDoneRule, type PipelineAnalysis } from "@/lib/crest/pipeline";
import type { DamRecord, StepId } from "@/lib/crest/types";
import { useClassifyAlg } from "./use-classify-alg";

const KIND: Record<CheckItem["kind"], { glyph: string; cls: string; word: string }> = {
  missing: { glyph: "○", cls: "text-flag-red", word: "Missing" },
  stop: { glyph: "■", cls: "text-flag-red", word: "Stop" },
  warn: { glyph: "▲", cls: "text-flag-amber", word: "Check" },
  todo: { glyph: "·", cls: "text-muted", word: "To do" },
};

export function RailChecklist({ stepId, label, items, onFix }: { stepId: StepId; label: string; items: CheckItem[]; onFix: (i: CheckItem) => void }) {
  if (!items.length) return null;
  const shown = items.slice(0, RAIL_ITEMS_MAX);
  const more = items.length - shown.length;
  return (
    <ul className="mb-1 ml-[2.6rem] mr-1 flex flex-col gap-1" aria-label={`${label}: ${items.length} item${items.length === 1 ? "" : "s"} to check${blocks(items) ? ", blocking" : ""}`} data-testid={`rail-check-${stepId}`}>
      {shown.map((i) => {
        const k = KIND[i.kind];
        return (
          <li key={i.key} className="flex items-start gap-1.5 text-xs leading-snug" data-kind={i.kind}>
            <span aria-hidden="true" className={"mt-px shrink-0 " + k.cls}>
              {k.glyph}
            </span>
            <span className="min-w-0 flex-1 text-ink" title={i.detail}>
              <span className="sr-only">{k.word}: </span>
              {i.text}
            </span>
            <button
              type="button"
              className="shrink-0 whitespace-nowrap rounded-sm border border-line bg-card px-1.5 text-xs font-medium text-water hover:bg-sand"
              aria-label={`Fix: ${i.detail} (${label} step)`}
              data-testid="rail-fix"
              onClick={() => onFix(i)}
            >
              Fix…
            </button>
          </li>
        );
      })}
      {more > 0 ? <li className="text-xs text-muted">+{more} more on this step</li> : null}
    </ul>
  );
}

/** "n of 8 done" as a ring: the same step-done rules as the status bar's progress (pipeline.ts STEP_DONE). */
export function ProgressRing({ dam, analysis }: { dam: DamRecord; analysis: PipelineAnalysis }) {
  const p = pipelineProgress(dam, analysis);
  const hold = screeningHold(dam);
  const classifyAlg = useClassifyAlg();
  const r = 15;
  const c = 2 * Math.PI * r;
  const open = p.steps.filter((s) => !s.done).map((s) => STEPS.find((x) => x.id === s.id)?.label ?? s.id);
  const title = p.steps.map((s) => `${s.done ? "✓" : "○"} ${STEPS.find((x) => x.id === s.id)?.label}: ${stepDoneRule(s.id, classifyAlg)}`).join("\n");
  return (
    <div className="flex items-center gap-3 rounded-md border border-line bg-card px-3 py-2" data-testid="progress-ring" title={title}>
      <svg
        viewBox="0 0 36 36"
        className="size-10 shrink-0 -rotate-90"
        role="progressbar"
        aria-label="Pipeline steps done"
        aria-valuemin={0}
        aria-valuemax={p.total}
        aria-valuenow={p.done}
        aria-valuetext={`${p.done} of ${p.total} steps done`}
      >
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--color-line)" strokeWidth="4" />
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--color-water)" strokeWidth="4" strokeLinecap="round" strokeDasharray={`${(c * p.done) / p.total} ${c}`} />
      </svg>
      <div className="min-w-0 text-sm">
        <p className="font-medium text-ink">
          {p.done} of {p.total} done
        </p>
        <p className="truncate text-xs text-muted" title={hold?.text}>
          {hold ? `Screening ${hold.kind}. ` : ""}
          {open.length ? `Open: ${open.join(", ")}` : "Every step complete"}
        </p>
      </div>
    </div>
  );
}
