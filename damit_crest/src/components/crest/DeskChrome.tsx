import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Info, Moon, Play, Search, Sun } from "lucide-react";

import damitWordmark from "@/assets/damit-wordmark-light.png";
import { currentDemSource, subscribeDemSource, type DemState } from "@/lib/crest/dem-source";
import { hasDesktopServer } from "@/lib/crest/desktop-server";
import { engineText, runText, useJobStatus } from "@/lib/crest/job-status";
import { pipelineProgress, screeningHold, stepDoneRule, TABS, type PipelineAnalysis, type TabId } from "@/lib/crest/pipeline";
import { STEPS } from "@/lib/crest/engine";
import type { DamRecord } from "@/lib/crest/types";
import { useClassifyAlg } from "./use-classify-alg";

const ABOUT =
  "One window for screening, a breach run and classification. Elevations, breach, and the map update as you edit. The flood model (LISFLOOD-FP, then ANUGA or HEC-RAS if chosen) runs through the DamIT plugins from the Export & Hand-off tab; the desk's own screen is not a model run, and nothing here assigns an official hazard class.";

const btn = "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-sm border px-3 text-sm";

/**
 * The compact one-row header (Lumo's concept, DamIT Desk UI 2026-11-21): wordmark and version, the command box that
 * opens the palette, About (the old three-line description), field mode, Settings, Batch… and the primary Run…, which
 * opens the plugin run panel (the runs need its work folder, DEM and model fields, so it never starts one by itself).
 */
export function DeskHeader({
  version,
  shortcut,
  onPalette,
  batch,
  onBatch,
  onRun,
  settingsOpen,
  onSettings,
  field,
  onField,
}: {
  version: string;
  shortcut: string;
  onPalette: () => void;
  batch: boolean;
  onBatch: () => void;
  onRun: () => void;
  settingsOpen: boolean;
  onSettings: () => void;
  field: boolean;
  onField: () => void;
}) {
  const [about, setAbout] = useState(false);
  const plain = `${btn} border-line bg-card text-ink hover:bg-sand`;
  const on = `${btn} border-water bg-water text-card`;
  return (
    <header className="border-b border-line bg-card" data-testid="desk-header">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
        <div className="flex shrink-0 items-center gap-2">
          <span className="desk-wordmark-chip">
            <img src={damitWordmark} alt="DaMiT" height={24} width={88} className="h-6 w-auto" />
          </span>
          <h1 className="text-lg leading-none">Desk</h1>
          <span className="font-mono text-xs text-muted" title={`DamIT Desk ${version}`} data-testid="desk-version">
            v{version.split("+")[0]}
          </span>
        </div>
        <button
          type="button"
          onClick={onPalette}
          className="flex h-9 min-w-[12rem] flex-1 items-center gap-2 rounded-sm border border-line bg-card px-3 text-left text-sm text-muted sm:max-w-md"
          aria-haspopup="dialog"
          aria-keyshortcuts="Control+K Meta+K"
          data-testid="command-box"
        >
          <Search className="size-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">Type a command or a step…</span>
          <kbd className="shrink-0 rounded-sm border border-line px-1.5 text-xs">{shortcut}</kbd>
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={about ? on : plain}
            aria-expanded={about}
            aria-controls="desk-about"
            title={ABOUT}
            onClick={() => setAbout((a) => !a)}
            data-testid="about-toggle"
          >
            <Info className="size-4" aria-hidden="true" />
            <span className="sr-only sm:not-sr-only">About</span>
          </button>
          <button
            type="button"
            className={field ? on : plain}
            aria-pressed={field}
            onClick={onField}
            title="Field mode: dark colours for low light"
            data-testid="field-mode-toggle"
          >
            {field ? <Sun className="size-4" aria-hidden="true" /> : <Moon className="size-4" aria-hidden="true" />}
            <span className="sr-only sm:not-sr-only">Field mode</span>
          </button>
          <button type="button" className={settingsOpen ? on : plain} aria-expanded={settingsOpen} onClick={onSettings} data-testid="settings-toggle">
            Settings
          </button>
          <button type="button" className={batch ? on : plain} aria-pressed={batch} onClick={onBatch} data-testid="batch-toggle">
            Batch…
          </button>
          <button
            type="button"
            className={`${btn} border-water bg-water font-semibold text-card`}
            onClick={onRun}
            title="Open the DamIT plugin run panel (screening, flood model, classify) for this dam"
            data-testid="run-primary"
          >
            <Play className="size-4" aria-hidden="true" />
            Run…
          </button>
        </div>
      </div>
      {about ? (
        <p id="desk-about" className="border-t border-line px-4 py-2 text-sm text-muted" data-testid="desk-about">
          {ABOUT}
        </p>
      ) : null}
    </header>
  );
}

/** The top tabs. Each step belongs to one tab (pipeline.ts), so the tab and the left rail always agree. */
export function DeskTabs({ tab, onTab, reviewFlags }: { tab: TabId | null; onTab: (t: TabId) => void; reviewFlags: number }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const n = TABS.length;
    const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    refs.current[j]?.focus();
    onTab(TABS[j].id);
  };
  return (
    <div className="border-b border-line bg-card px-4">
      <div role="tablist" aria-label="Desk views" className="flex gap-1 overflow-x-auto" data-testid="desk-tabs">
        {TABS.map((t, i) => {
          const sel = tab === t.id;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={sel}
              aria-controls="desk-tabpanel"
              tabIndex={sel || (tab === null && i === 0) ? 0 : -1}
              onClick={() => onTab(t.id)}
              onKeyDown={(e) => onKey(e, i)}
              data-testid={`tab-${t.id}`}
              className={
                "inline-flex h-10 shrink-0 items-center gap-1.5 border-b-2 px-3 text-sm " +
                (sel ? "border-water font-semibold text-ink" : "border-transparent text-muted hover:text-ink")
              }
            >
              {t.label}
              {t.id === "review" && reviewFlags > 0 ? (
                <>
                  {/* A plain span cannot carry an aria-label (Absaraka desk test 2026-11-21): the count is shown, and read as words. */}
                  <span
                    aria-hidden="true"
                    title={`${reviewFlags} flag${reviewFlags === 1 ? "" : "s"} to check before review (datum and flood checks; the rail lists them under their steps)`}
                    className="rounded-full bg-amber-bg px-1.5 text-xs font-semibold text-flag-amber"
                    data-testid="review-flag-badge"
                  >
                    {reviewFlags}
                  </span>
                  <span className="sr-only">
                    , {reviewFlags} flag{reviewFlags === 1 ? "" : "s"} to check
                  </span>
                </>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function useDemSource(): DemState | null {
  return useSyncExternalStore(subscribeDemSource, currentDemSource, () => null);
}

const baseName = (p: string) => p.split(/[\\/]/).pop() || p;

/**
 * The narrow status bar along the bottom: the QGIS hand-off (the last Check QGIS hand-off; it is never run by
 * itself), the terrain source, the CRS of the record, the plugin job state and the pipeline's n/8.
 */
export function DeskStatusBar({ dam, analysis }: { dam: DamRecord; analysis: PipelineAnalysis }) {
  const job = useJobStatus();
  const [server, setServer] = useState(false);
  useEffect(() => setServer(hasDesktopServer()), []);
  const dem = useDemSource();
  const engine = engineText(job, server);
  const prog = pipelineProgress(dam, analysis);
  const hold = screeningHold(dam);
  const classifyAlg = useClassifyAlg();
  const ref = dam.resultsOfRecord;
  const crs = ref ? `${ref.crs} (${ref.label})` : "EPSG:4326 lon/lat (desk record)";
  const demText = !dem || dem.kind === "unavailable" ? "Terrain: USGS 3DEP" : dem.kind === "local" ? `DEM: ${baseName(dem.path)}` : "Terrain: USGS 3DEP";
  const tone = { ok: "text-flag-green", warn: "text-flag-amber", muted: "text-muted" }[engine.tone];
  const rule = prog.steps.map((s) => `${s.done ? "✓" : "·"} ${STEPS.find((x) => x.id === s.id)?.label}: ${stepDoneRule(s.id, classifyAlg)}`).join("\n");
  return (
    <footer
      className="sticky bottom-0 z-[1100] flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line bg-card px-4 py-1 text-xs text-muted"
      aria-label="Desk status"
      data-testid="desk-statusbar"
    >
      <span className={tone} data-testid="status-engine">
        {engine.text}
      </span>
      <span data-testid="status-dem" title={dem && dem.kind === "local" ? dem.path : undefined}>
        {demText}
      </span>
      <span data-testid="status-crs">CRS {crs}</span>
      <span className={job.busy ? "font-semibold text-ink" : ""} role="status" data-testid="status-run">
        {runText(job)}
      </span>
      <span className="ml-auto flex items-center gap-2" title={rule} data-testid="status-progress">
        <span
          role="progressbar"
          aria-label="Pipeline steps complete"
          aria-valuemin={0}
          aria-valuemax={prog.total}
          aria-valuenow={prog.done}
          aria-valuetext={`${prog.done} of ${prog.total} steps complete`}
          className="block h-1.5 w-28 overflow-hidden rounded-full bg-sand"
        >
          <span className="block h-full bg-water" style={{ width: `${(100 * prog.done) / prog.total}%` }} />
        </span>
        <span className="text-ink">
          {prog.done}/{prog.total} steps
        </span>
        {hold ? (
          <span className="font-semibold text-flag-amber" data-testid="status-screening" title={hold.text}>
            · screening {hold.kind}
          </span>
        ) : null}
      </span>
    </footer>
  );
}
