import { Fragment, lazy, type ReactNode, Suspense, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ChevronLeft, ChevronRight, Plus, RotateCcw } from "lucide-react";

import { analyze, crestNavdLabel, INPUT_RANGE, inputRangeWarning, STEPS } from "@/lib/crest/engine";
import { datumFlags, floodFlags, warningKey, type Warning } from "@/lib/crest/warnings";
import { locationProblem } from "@/lib/crest/guided";
import { DEFAULT_ALGORITHMS, ND_ALGORITHMS, handoffDam } from "@/lib/crest/handoff";
import { fillPlan, type Autofill, type FillField } from "@/lib/crest/handoff-fill";
import { choiceKey, choiceText, classifyReceptors, receptorKey, reportLead } from "@/lib/crest/classify-receptors";
import { crestApiHeaders, hasDesktopServer, serverNotices, workFolderHint } from "@/lib/crest/desktop-server";
import { ClassificationPanel } from "@/components/crest/ClassificationPanel";
import { lookupPads, padPoints, padsToRetry, resetFailedPads } from "@/lib/crest/nd911-pads";
import { exportDamJson, exportHydrographCsv, generateLisfloodPackage } from "@/lib/crest/export";
import { floodStrip, type FloodStrip } from "@/lib/crest/floodstrip";
import {
  exportFloodStripGeoJsonWithPlss,
  exportFloodStripKmlWithPlss,
  exportPlssCsv,
  fetchPlss,
  PLSS_ATTRIBUTION,
  plssState,
  SLIVER_AC,
  type PlssState,
} from "@/lib/crest/plss";
import {
  addNd911Seeds,
  exportFloodGeoJson,
  exportFloodKml,
  exportNd911Csv,
  fetchStructures,
  nd911AutoPatch,
  wantsNd911Lookup,
  ND911_ATTRIBUTION,
  ND911_DROPPED_FIELDS,
  nd911State,
  removeNd911Seeds,
  seedId,
  structureWords,
  type Nd911Row,
  type Nd911State,
} from "@/lib/crest/nd911";
import { NSI_ATTRIBUTION } from "@/lib/crest/nsi";
import {
  currentTerrain,
  DEM_ATTRIBUTION,
  DEM_ATTRIBUTION_SHORT,
  labelWithTerrain,
  layerLabel,
  lookupArea,
  OUTLINE_LABEL,
  stampTerrain,
  terrainInfo,
  outlineAcresNote,
  traceStartNote,
  deepCellsNote,
  pitsExcludedNote,
  channelPitsNote,
  volumeLimitNote,
  SMALL_RELEASE_ACFT,
  fetchDem,
  outlineInputs,
  outlineState,
  type OutlineState,
} from "@/lib/crest/outline";
import { ROUTED_LABEL, volumeCheck } from "@/lib/crest/inundation";
import { buildInundationInWorker, CANCELLED } from "@/lib/crest/inundation-client";
import { layerOfRecord } from "@/lib/crest/layer-of-record";
import { CONFIDENCE_LABEL, triageDam } from "@/lib/crest/triage";
import { num } from "@/lib/crest/format";
import { saveText } from "@/lib/crest/save";
import { demTieOffer, missingForNext, needsDemTie } from "@/lib/crest/nid-dams";
import { onOutlineSaveChange, outlineSaveError } from "@/lib/crest/outline-store";
import { activeDam, hydrateDesk, useDesk, useSaveStatus } from "@/lib/crest/store";
import { DeskFiles } from "./DeskFiles";
import type {
  BreachMethod,
  DamGeometry,
  DamRecord,
  DatumName,
  EngineName,
  FailureMode,
  HazardResult,
  ScreenLevel,
  StepId,
} from "@/lib/crest/types";
import { damChoice, screenAgainstChoice } from "@/lib/crest/jurisdiction";
import { HydroChart, ValleyMap } from "./charts";
import { useOnline } from "./use-online";
import { AboutData, FieldTag, NidDamPicker, NidHazardLine, NidRecordPanel } from "./NidDamPicker";
import { useNidData } from "@/lib/crest/use-nid-data";
import { NdDamPicker } from "./NdDamPicker";
import { StructurePicker } from "./StructurePicker";
import { useProfile, type DeskProfile } from "@/lib/crest/profile";
import { useClassifyAlg } from "./use-classify-alg";
import { ResultsStep } from "./ResultsStep";
import { useAnalysisOfRecord, useResultsSync, useStripOfRecord } from "./results-flow";
import { PaperReport } from "./PaperReport";
import { Dashboard } from "./Dashboard";
import { HybridSetup } from "./HybridSetup";
import { ViewExport } from "./ViewExport";
import { ClientOnly } from "./ClientOnly";
import { TerrainSource } from "./TerrainSource";
import { ServerFilePicker } from "./ServerFilePicker";
import { getServer, hasDeskServer, pickOnServer, postServer } from "@/lib/crest/server-picker";
import { isDesktop } from "@/lib/crest/save";
import { ensureDemSource } from "@/lib/crest/dem-source";
import type { PointRole } from "./MapDraw";
import { autoBreachPoint } from "@/lib/crest/breach-point";
import { CREST_SNAP_M, deriveFromDem, nearRequest } from "@/lib/crest/batch";
import { assumptions } from "@/lib/crest/settings";
import { loadSettings, sharedNow } from "@/lib/crest/settings-store";
import { CREST_VERSION } from "@/lib/crest/version";
import { BreachAdvanced } from "./BreachAdvanced";
import { SettingsPanel } from "./SettingsPanel";
import { CommandPalette, type Command } from "./CommandPalette";
import { DeskHeader, DeskStatusBar, DeskTabs } from "./DeskChrome";
import { WorkflowMap } from "./WorkflowMap";
import { parseRuling } from "@/lib/crest/classify-list";
import { classifyActionLabel, DESK_ACTIONS, isPaletteShortcut, shortcutLabel } from "@/lib/crest/commands";
import { jobFinished, jobNoServer, jobStarted, requestJob, setJobStarter, useJobStatus } from "@/lib/crest/job-status";
import {
  firstOpenWorkflowStep,
  railState,
  screeningHold,
  screeningOutcome,
  STEP_DONE,
  stepForTab,
  tabForStep,
  TABS,
  type TabId,
} from "@/lib/crest/pipeline";
import { saveDeskFile } from "@/lib/crest/desk-save";
import { parseHits } from "@/lib/crest/review-summary";
import { stepChecklist, type CheckItem } from "@/lib/crest/checklist";
import { ProgressRing, RailChecklist } from "./RailChecklist";
import { ReviewSummary } from "./ReviewSummary";
import { ClassifyReceptorsPanel } from "./ClassifyReceptors";
import { useRulingBackfill } from "./use-classify-receptors";

// Leaflet touches `window` when it loads, so the map is a client-only chunk.
const MapDraw = lazy(() => import("./MapDraw").then((m) => ({ default: m.MapDraw })));
// The batch screen loads the structure lists (about 2 MB), so it is its own chunk, fetched only when opened.
const LocationPicker = lazy(() => import("./LocationPicker").then((m) => ({ default: m.LocationPicker })));
const BatchScreen = lazy(() => import("./BatchScreen").then((m) => ({ default: m.BatchScreen })));

const LEVEL_CLASS: Record<ScreenLevel, string> = {
  High: "bg-amber text-card",
  Medium: "bg-water text-card",
  Low: "bg-ink text-card",
  Review: "bg-sand text-ink",
};
/** A non-colour mark beside the screen level, so the badge reads in grayscale and to a screen reader: a glyph and the
 * level's first letter in a bordered box, the way the paper report's stamp carries its word. */
const LEVEL_MARK: Record<ScreenLevel, { glyph: string; title: string }> = {
  High: { glyph: "▲ H", title: "High: probable loss of life" },
  Medium: { glyph: "■ M", title: "Medium: economic loss, no probable loss of life" },
  Low: { glyph: "● L", title: "Low" },
  Review: { glyph: "? R", title: "Review: the screen is held" },
};

/** The screen level as a badge: colour plus a glyph-and-letter mark and an aria-label, never colour alone. */
function LevelBadge({ level, label }: { level: ScreenLevel; label: string }) {
  const m = LEVEL_MARK[level];
  return (
    <span className={`inline-flex items-center gap-2 rounded-sm px-3 py-1 text-lg ${LEVEL_CLASS[level]}`} aria-label={`${label}. ${m.title}`} data-level={level}>
      <span className="rounded-sm border border-current px-1 text-xs font-semibold tracking-wide" aria-hidden="true">
        {m.glyph}
      </span>
      {label}
    </span>
  );
}

/** A review flag with its catalogue code (warnings.ts) in front, keyed by code and position, never by its text. */
function FlagList({ flags, className, testId }: { flags: Warning[]; className: string; testId?: string }) {
  return (
    <ul className={className} data-testid={testId}>
      {flags.map((w, i) => (
        <li key={warningKey(w, i)}>
          <code
            className="mr-1 rounded-sm border border-current/40 px-1 align-middle text-[0.7rem]"
            title={w.severity === "stop" ? "Holds the screen at Review" : w.severity === "warn" ? "Check before relying on the result" : "For information"}
          >
            {w.code}
          </code>
          {w.text}
        </li>
      ))}
    </ul>
  );
}

const FIELD_MODE_KEY = "damit-desk-field-mode";
const MAP_OPEN_KEY = "damit-desk-workflow-map";

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v == null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

function writeFlag(key: string, on: boolean): void {
  try {
    window.localStorage.setItem(key, on ? "1" : "0");
  } catch {
    /* storage full or blocked: the choice lasts for this window only */
  }
}

/** Field mode (the dark palette in styles.css, body.field-mode), kept per browser. */
function useFieldMode(): [boolean, () => void] {
  const [on, setOn] = useState(() => typeof window !== "undefined" && readFlag(FIELD_MODE_KEY, false));
  useEffect(() => {
    document.body.classList.toggle("field-mode", on);
    writeFlag(FIELD_MODE_KEY, on);
  }, [on]);
  return [on, useCallback(() => setOn((v) => !v), [])];
}

/** Whether the Workflow map is shown (Hide map / Show map), kept per browser. */
function useMapOpen(): [boolean, () => void] {
  const [on, setOn] = useState(() => typeof window === "undefined" || readFlag(MAP_OPEN_KEY, true));
  useEffect(() => writeFlag(MAP_OPEN_KEY, on), [on]);
  return [on, useCallback(() => setOn((v) => !v), [])];
}

/** Call `f` with the element once it is on screen (a step that has just been picked renders on the next frames). */
function whenShown(id: string, f: (el: HTMLElement) => void, tries = 60): void {
  const el = document.getElementById(id);
  if (el) f(el);
  else if (tries > 0) window.requestAnimationFrame(() => whenShown(id, f, tries - 1));
}

/**
 * Focus what a checklist item's Fix… points at once its step has rendered: the first visible match of `target`,
 * scrolled into view and briefly outlined; with no target (or none after ~1 s), the step's content panel. It starts a
 * frame late and checks the focus held, because the step it leaves can hold the same field (Guided setup shows the
 * Record form) and unmounts after the switch.
 */
function focusFix(target: string | null, tries = 60): void {
  window.requestAnimationFrame(() => {
    const el = target ? [...document.querySelectorAll<HTMLElement>(target)].find((e) => e.offsetParent !== null || e.closest("label")?.offsetParent != null) : undefined;
    if (!el && target && tries > 0) return focusFix(target, tries - 1);
    const to = el ?? document.getElementById("step-content");
    if (!to) return;
    if (to.tabIndex < 0 && !to.hasAttribute("tabindex")) to.setAttribute("tabindex", "-1");
    const shown = to.closest("label") ?? to;
    shown.scrollIntoView({ block: "center", behavior: "smooth" });
    to.focus({ preventScroll: true });
    window.requestAnimationFrame(() => {
      if (!to.isConnected && tries > 0) return focusFix(target, tries - 1);
      shown.classList.add("fix-flash");
      window.setTimeout(() => shown.classList.remove("fix-flash"), 2000);
    });
  });
}

/** "Open desk file or dam.json…" from the palette: the visible desk-file chooser's own file input. */
function openDeskFilePicker(show: () => void): void {
  show();
  const pick = (tries: number) => {
    const input = [...document.querySelectorAll<HTMLInputElement>('[data-testid="desk-open"]')].find((i) => i.offsetParent !== null);
    if (input) input.click();
    else if (tries > 0) window.requestAnimationFrame(() => pick(tries - 1));
  };
  pick(30);
}

export function Desk() {
  const dams = useDesk((s) => s.dams);
  const activeId = useDesk((s) => s.activeId);
  const step = useDesk((s) => s.step);
  const setStep = useDesk((s) => s.setStep);
  const select = useDesk((s) => s.select);
  const add = useDesk((s) => s.add);
  const restore = useDesk((s) => s.restore);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<"desk" | "batch">("desk");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [field, toggleField] = useFieldMode();
  const [mapOpen, toggleMap] = useMapOpen();
  // What "Open in desk" did (selected an existing record or added one), shown once over the desk.
  const [openNote, setOpenNote] = useState<string | null>(null);
  const saveBlocked = useSaveStatus((s) => s.blocked);
  const staleTab = useSaveStatus((s) => s.stale);

  useEffect(() => {
    void hydrateDesk();
    setReady(true);
    // The desktop's saved local DEM (if any) becomes the terrain for every read on the desk.
    void ensureDemSource();
    // The shared defaults a new record starts from: your defaults file (desktop) or this browser's copy (web).
    void loadSettings();
  }, []);

  // The note stays on the step and dam it was shown on (Absaraka desk test 2026-11-21: "Desk file opened…" stayed on
  // every step until dismissed). Moving to another step or dam clears it.
  const here = `${activeId}|${step}`;
  const hereRef = useRef(here);
  hereRef.current = here;
  const noteAt = useRef<string | null>(null);
  useEffect(() => {
    noteAt.current = openNote ? hereRef.current : null;
  }, [openNote]);
  useEffect(() => {
    if (noteAt.current && noteAt.current !== here) setOpenNote(null);
  }, [here]);

  const dam = activeDam({ dams, activeId });
  useRulingBackfill(dam);
  const result = useMemo(() => analyze(dam), [dam]);
  useResultsSync(dam, result);
  const recordAnalysis = useAnalysisOfRecord(dam, result).result;

  // Top tabs (Lumo's concept, 2026-11-21): every step belongs to one tab (pipeline.ts), so the tab is read from the
  // step and the left rail and the tabs cannot disagree. Workflow goes back to the last Workflow step used.
  const lastWorkflow = useRef<StepId | null>(null);
  useEffect(() => {
    if (tabForStep(step) === "workflow") lastWorkflow.current = step;
  }, [step]);
  const tab: TabId | null = view === "batch" ? null : tabForStep(step);
  const goStep = useCallback(
    (s: StepId) => {
      setView("desk");
      setStep(s);
    },
    [setStep],
  );
  const goTab = useCallback(
    (t: TabId) => goStep(stepForTab(t, lastWorkflow.current, firstOpenWorkflowStep(dam, recordAnalysis))),
    [goStep, dam, recordAnalysis],
  );
  // Run…: the plugin run panel on the Export & Hand-off tab, scrolled into view with its first button focused. It
  // starts nothing: screening and the flood model need the panel's work folder, DEM and model fields first.
  const openRun = useCallback(() => {
    goStep("report");
    whenShown("handoff-panel", (el) => {
      el.scrollIntoView({ block: "start", behavior: "smooth" });
      el.querySelector<HTMLButtonElement>('[data-testid="handoff-actions"] button:not(:disabled)')?.focus({ preventScroll: true });
    });
  }, [goStep]);
  // Fix… in the rail checklist: the item's step, then its field or button focused (or the step itself).
  const fixItem = useCallback(
    (i: CheckItem) => {
      goStep(i.step);
      focusFix(i.target);
    },
    [goStep],
  );
  const startJob = useCallback(
    (path: string) => {
      goStep("report");
      requestJob(path);
      whenShown("handoff-panel", (el) => el.scrollIntoView({ block: "start", behavior: "smooth" }));
    },
    [goStep],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isPaletteShortcut(e)) return;
      e.preventDefault();
      setPaletteOpen((o) => !o);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const jobBusy = useJobStatus((s) => s.busy);
  // The palette names the classify algorithm this profile runs (ndhazard:classify under North Dakota).
  const classifyAlg = useClassifyAlg();
  const [server, setServer] = useState(false);
  useEffect(() => setServer(hasDesktopServer()), []);
  const commands = useMemo<Command[]>(() => {
    const noServer = server ? undefined : "needs the desk server (bin/damit-desk)";
    const list: Command[] = [
      ...TABS.map((t) => ({ id: `tab-${t.id}`, group: "Views", label: `Go to ${t.label}`, run: () => goTab(t.id) })),
      ...STEPS.map((s, i) => ({
        id: `step-${s.id}`,
        group: "Steps",
        label: `Step ${i + 1}: ${s.label}`,
        hint: STEP_DONE[s.id as StepId](dam, recordAnalysis) ? "complete" : s.id === step ? "current" : undefined,
        keywords: ["go", "step"],
        run: () => goStep(s.id as StepId),
      })),
      ...DESK_ACTIONS.map((a): Command => {
        const busyHint = jobBusy ? "a plugin job is running" : a.hint;
        switch (a.id) {
          case "classify":
            return { ...a, label: classifyActionLabel(classifyAlg), hint: noServer ?? busyHint, disabled: !server || jobBusy, run: () => startJob("/api/classify") };
          case "screening":
            return { ...a, hint: noServer ?? busyHint, disabled: !server || jobBusy, run: () => startJob("/api/screen") };
          case "import-run":
            return { ...a, run: () => (goStep("results"), focusFix('[data-testid="import-lisflood-files"]')) };
          case "choose-dem":
            return { ...a, hint: noServer ?? a.hint, disabled: !server, run: () => (goStep("flood"), focusFix('[data-testid="terrain-choose-dem"]')) };
          default:
            return { ...a, run: () => (goStep("flood"), focusFix('[data-testid="outline-build"]')) };
        }
      }),
      { id: "run", group: "Run", label: "Run…", hint: "open the DamIT plugin run panel", keywords: ["screening", "flood model", "classify", "pipeline"], run: openRun },
      {
        id: "check",
        group: "Run",
        label: "Check QGIS hand-off",
        hint: noServer ?? (jobBusy ? "a plugin job is running" : "finds qgis_process and the 4 algorithms; runs no dam"),
        keywords: ["engine", "qgis", "algorithms"],
        disabled: !server || jobBusy,
        run: () => startJob("/api/check"),
      },
      {
        id: "handoff",
        group: "Run",
        label: "Write the dam folder (hand-off)",
        hint: noServer ?? (jobBusy ? "a plugin job is running" : "the folder the DamIT plugins read"),
        keywords: ["write", "hand-off", "handoff", "package", "folder"],
        disabled: !server || jobBusy,
        run: () => startJob("/api/folder"),
      },
      {
        id: "save",
        group: "Desk",
        label: "Save desk to file",
        keywords: ["backup", "export"],
        run: () => {
          setView("desk");
          void saveDeskFile().then((r) => setOpenNote(r.note ?? r.error ?? null));
        },
      },
      { id: "open", group: "Desk", label: "Open desk file or dam.json…", keywords: ["import", "load"], run: () => openDeskFilePicker(() => setView("desk")) },
      { id: "new", group: "Desk", label: "New dam", run: () => (setView("desk"), add()) },
      { id: "batch", group: "Desk", label: "Batch…", hint: "screen many dams", run: () => setView("batch") },
      { id: "settings", group: "Desk", label: "Settings", hint: "shared starting values", keywords: ["defaults", "preferences"], run: () => setSettingsOpen(true) },
      { id: "field", group: "Desk", label: field ? "Field mode: turn off" : "Field mode: turn on", hint: "dark colours for low light", keywords: ["dark", "theme", "night"], run: toggleField },
      ...dams.map((d) => ({
        id: `dam-${d.id}`,
        group: "Dams",
        label: `Open dam: ${d.name}`,
        hint: d.id === dam.id ? "open now" : d.nid,
        run: () => (setView("desk"), select(d.id)),
      })),
    ];
    return list;
  }, [server, jobBusy, classifyAlg, goTab, goStep, openRun, startJob, dam, recordAnalysis, step, dams, field, toggleField, add, select]);
  const reviewFlags = useMemo(
    () => [...datumFlags(recordAnalysis), ...floodFlags(recordAnalysis)].filter((w) => w.severity !== "info").length,
    [recordAnalysis],
  );

  return (
    <div className="min-h-screen bg-paper text-ink">
      <ServerFilePicker />
      {staleTab ? (
        <div className="border-b border-line bg-card px-4 py-2 text-sm text-amber" role="alert" data-testid="stale-tab">
          This desk was changed in another tab, so your edits here are no longer being saved. Reload to pick up the
          latest, or your changes in this tab will be lost.
        </div>
      ) : saveBlocked ? (
        <div className="border-b border-line bg-card px-4 py-2 text-sm text-amber" role="alert" data-testid="save-blocked">
          This desk is over your browser&rsquo;s storage limit, so your latest edits are no longer being saved.
          Use &ldquo;Save desk to file&rdquo; (under the dam list) to keep your work, then reload, or remove a
          dam&rsquo;s terrain layer to free space.
        </div>
      ) : null}
      <DeskHeader
        version={CREST_VERSION}
        shortcut={shortcutLabel(typeof navigator === "undefined" ? "" : navigator.platform || navigator.userAgent)}
        onPalette={() => setPaletteOpen(true)}
        batch={view === "batch"}
        onBatch={() => setView((v) => (v === "batch" ? "desk" : "batch"))}
        onRun={openRun}
        settingsOpen={settingsOpen}
        onSettings={() => setSettingsOpen((o) => !o)}
        field={field}
        onField={toggleField}
      />
      <DeskTabs tab={tab} onTab={goTab} reviewFlags={reviewFlags} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
      {settingsOpen ? <SettingsPanel onClose={() => setSettingsOpen(false)} /> : null}

      {view === "batch" ? (
        <main className="mx-auto w-full max-w-[1600px] min-w-0 px-4 py-4">
          <Suspense fallback={<p className="text-sm text-muted">Opening the batch screen…</p>}>
            <BatchScreen
              onOpen={(note) => {
                setOpenNote(note ?? null);
                setView("desk");
              }}
            />
          </Suspense>
        </main>
      ) : (
      <div className="mx-auto grid w-full max-w-[1600px] min-w-0 gap-0 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="min-w-0 border-b border-line bg-card lg:border-r lg:border-b-0">
          <div className="flex items-center justify-between px-4 pt-4">
            <h2 className="text-base">Dams</h2>
            <button
              type="button"
              onClick={add}
              className="inline-flex h-11 items-center gap-1 rounded-sm px-2 text-sm text-water"
            >
              <Plus className="size-4" aria-hidden="true" />
              New
            </button>
          </div>
          <ul className="flex min-w-0 gap-2 overflow-x-auto px-3 py-3 lg:block lg:space-y-1 lg:overflow-visible">
            {dams.map((d) => {
              const on = d.id === dam.id;
              return (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => select(d.id)}
                    className={
                      "w-max rounded-sm px-3 py-2 text-left text-sm lg:w-full " +
                      (on ? "bg-water text-card" : "text-ink hover:bg-sand")
                    }
                  >
                    <span className="block font-medium">{d.name}</span>
                    <span className={on ? "text-card/80" : "text-muted"}>{d.nid}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="hidden px-4 pb-4 lg:block">
            <DeskFiles onNote={setOpenNote} />
            <button
              type="button"
              onClick={restore}
              className="inline-flex h-11 items-center gap-2 text-sm text-muted"
            >
              <RotateCcw className="size-4" aria-hidden="true" />
              Restore samples
            </button>
          </div>
        </aside>

        <main className="min-w-0 px-4 py-4">
          {!ready ? <p className="text-sm text-muted">Opening the desk…</p> : null}
          {openNote ? (
            <p className="mb-3 flex items-start gap-2 rounded-sm border border-line bg-sand px-3 py-2 text-sm" role="status" data-testid="open-in-desk-note">
              <span className="min-w-0 flex-1">{openNote}</span>
              <button type="button" className="shrink-0 text-muted underline" onClick={() => setOpenNote(null)} aria-label="Dismiss">
                Dismiss
              </button>
            </p>
          ) : null}
          {/* Map-centric redesign (matches Damit Crest PR #148): the workflow moves from a horizontal
              tab strip to a persistent three-pane layout — pipeline rail left, step content centre,
              inspector right. The old tab nav is retired; states show prerequisite problems before
              the jump instead of surfacing them as late errors. 2026-11-21 (Lumo's concept): the top
              tabs pick the view (each step is in one tab), the Workflow centre leads with the flood
              map when the record has a flood layer, and the Dashboard tab uses the full width. */}
          <div
            role="tabpanel"
            id="desk-tabpanel"
            aria-labelledby={tab ? `tab-${tab}` : undefined}
            data-tab={tab ?? ""}
            className={
              "grid min-w-0 gap-4 " +
              (tab === "dashboard" ? "xl:grid-cols-[210px_minmax(0,1fr)]" : "xl:grid-cols-[210px_minmax(0,1fr)_280px]")
            }
          >
            <div className="min-w-0 flex flex-col gap-3 xl:order-1">
              <SituationStrip dam={dam} result={result} />
              <ProgressRing dam={dam} analysis={recordAnalysis} />
              <StepRail dam={dam} result={recordAnalysis} desk={result} step={step} setStep={setStep} onFix={fixItem} />
            </div>
            <div className="min-w-0 flex flex-col gap-4 xl:order-2" id="step-content" tabIndex={-1}>
          {/* Guided setup and Flood draw on their own map; the other Workflow steps lead with the flood map. */}
          {tab === "workflow" && step !== "setup" && step !== "flood" ? (
            <WorkflowMap dam={dam} deskResult={result} open={mapOpen} onToggle={toggleMap} />
          ) : null}
          {step === "setup" ? (
            <HybridSetup
              dam={dam}
              result={result}
              renderStep={(k, onStatus) =>
                k === "record" ? (
                  <RecordStep dam={dam} result={result} />
                ) : k === "breach" ? (
                  <BreachStep dam={dam} result={result} />
                ) : (
                  <TerrainStep dam={dam} result={result} onStatus={onStatus} />
                )
              }
            />
          ) : null}
          {step === "record" ? <RecordStep dam={dam} result={result} /> : null}
          {step === "breach" ? <BreachStep dam={dam} result={result} /> : null}
          {step === "flood" ? <FloodStep dam={dam} result={result} /> : null}
          {step === "results" ? <ResultsStep dam={dam} result={result} /> : null}
          {step === "dashboard" ? <Dashboard dam={dam} result={result} /> : null}
          {step === "screen" ? <ScreenStep dam={dam} result={result} /> : null}
          {step === "report" ? <ReportStep dam={dam} result={result} /> : null}

          <StepNav step={step} setStep={setStep} blocked={step === "record" ? missingForNext(dam) : []} />
            </div>
            {tab === "dashboard" ? null : (
              <div className="min-w-0 xl:order-3">
                <InspectorPanel dam={dam} result={result} step={step} />
              </div>
            )}
          </div>

          <div className="mt-6 lg:hidden">
            <DeskFiles onNote={setOpenNote} />
          </div>
          <button
            type="button"
            onClick={restore}
            className="inline-flex h-11 items-center gap-2 text-sm text-muted lg:hidden"
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            Restore samples
          </button>
          <AboutData />
        </main>
      </div>
      )}
      <DeskStatusBar dam={dam} analysis={recordAnalysis} />
      <footer className="border-t border-line bg-card">
        <div className="mx-auto max-w-[1600px] px-4 py-3 text-xs text-muted">
          <details>
            <summary className="cursor-pointer">About DamIT Desk and its data sources</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>DamIT Desk is a multi-jurisdiction desk screen for dam breach and hazard studies, adapted from Crest. Its own screen is not a flood model: LISFLOOD-FP (and ANUGA or HEC-RAS) run through the DamIT plugins from the Report step. It does not assign an official hazard class: classification is consequence-based and the engineer of record and the regulating agency make the determination.</li>
              <li>Basemaps: USGS The National Map, or OpenStreetMap contributors (as credited on the map).</li>
              <li data-testid="plss-attribution">{PLSS_ATTRIBUTION}</li>
              <li data-testid="nd911-attribution">{ND911_ATTRIBUTION}</li>
              <li data-testid="dem-attribution">{DEM_ATTRIBUTION}</li>
            </ul>
          </details>
          <p className="mt-1">
            Data: {PLSS_ATTRIBUTION.split(" Public data")[0]}; {ND911_ATTRIBUTION.split(" Public data")[0]}; {currentTerrain().local ? `${DEM_ATTRIBUTION_SHORT} or ${currentTerrain().label}` : DEM_ATTRIBUTION_SHORT}.
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * The flood areas of one dam: the schematic strip, the terrain outline when it is built, and the PLSS and 911 lists
 * against the outline when there is one (else the strip). Lookups cover the strip and the outline together, so one
 * saved lookup serves both.
 */
function useFloodAreas(dam: DamRecord, result: ReturnType<typeof analyze>) {
  const online = useOnline();
  // The strip of record: an imported run's raster strip when it is the source of record and loaded, else the desk strip.
  const strip = useStripOfRecord(dam, result);
  const basis = strip.basis;
  const outline = useMemo(() => outlineState(dam, result, online), [dam, result, online]);
  const ol = outline.state === "ready" ? outline.outline : null;
  // An imported run of record is the layer of record whatever the gate picks (layer-of-record.ts): once its raster
  // strip is built, the PLSS and 911 lists run against it, not against the terrain layer.
  const run = strip.fromRun && dam.resultsOfRecord ? dam.resultsOfRecord.label : null;
  const against = run ? `${run} run` : ol ? (outline.state === "ready" && outline.layer === "routed" ? "routed flood" : "terrain outline") : "flood strip";
  const area = run ? strip.strip : (ol ?? strip.strip);
  const lookup = useMemo(() => (strip.strip ? (run ? strip.strip : lookupArea(strip.strip, ol)) : null), [strip.strip, ol, run]);
  const plss = useMemo<PlssState>(() => plssState(dam, area, online, against), [dam, area, online, against]);
  const nd911 = useMemo<Nd911State>(() => nd911State(dam, area, online, against), [dam, area, online, against]);
  return { online, strip, outline, ol, area, against, lookup, plss, nd911, basis };
}

function DemTiePanel({ dam }: { dam: DamRecord }) {
  const update = useDesk((s) => s.update);
  if (!needsDemTie(dam)) return null;
  const offer = demTieOffer(dam);
  return (
    <div className="mt-3 rounded-md border border-line bg-sand p-3 text-sm" data-testid="dem-tie">
      <p>
        Datum is {dam.statedDatum === "" ? "blank" : "local"}: tie the elevations to the DEM crest (NAVD 88). Crest 0–300 ft counts as local and
        is shifted by the DEM mid-crest offset; a mismatch over 100 ft is flagged for review.
      </p>
      {offer.review ? <p className="mt-1 font-semibold text-red-700">{offer.review}</p> : <p className="mt-1 text-muted">{offer.note}</p>}
      {offer.patch ? (
        <button type="button" className="mt-2 rounded border border-line bg-card px-3 py-1" onClick={() => update(offer.patch!)}>
          Tie to DEM crest{offer.offsetFt ? ` (${offer.offsetFt > 0 ? "+" : ""}${offer.offsetFt} ft)` : ""}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Record step: set the dam's latitude and longitude by clicking a map (a new dam with no inventory point), and read
 * the ground there from the terrain into the DEM crest field.
 */
function LocationPanel({ dam }: { dam: DamRecord }) {
  const update = useDesk((s) => s.update);
  const [open, setOpen] = useState(false);
  const [ground, setGround] = useState<{ busy: boolean; msg: string | null }>({ busy: false, msg: null });
  const has = Number.isFinite(dam.lat) && Number.isFinite(dam.lon);
  const readGround = async () => {
    setGround({ busy: true, msg: null });
    const id = dam.id;
    try {
      const g = await fetchDem(nearRequest(dam.lon!, dam.lat!, 0.3, 5));
      const d = deriveFromDem(g, dam.lon!, dam.lat!);
      if (!d) throw new Error("No terrain at this point.");
      if (useDesk.getState().activeId !== id) return setGround({ busy: false, msg: null });
      update({ demCrestFt: d.crestFt });
      setGround({ busy: false, msg: `DEM crest set to ${d.crestFt.toFixed(1)} ft NAVD 88: the highest ground within ${CREST_SNAP_M} m of the point. Use it for the crest if the point is on the embankment top.` });
    } catch (e) {
      setGround({ busy: false, msg: (e as Error).message });
    }
  };
  const btn = "inline-flex h-11 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:opacity-50";
  return (
    <div className="mt-4" data-testid="location-panel">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btn} aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Close the map" : has ? "Move the dam on the map" : "Pick the dam's location on the map"}
        </button>
        {has ? (
          <button type="button" className={btn} disabled={ground.busy} onClick={() => void readGround()}>
            {ground.busy ? "Reading the terrain…" : "Read the ground here (DEM crest)"}
          </button>
        ) : null}
      </div>
      {open ? (
        <div className="mt-2">
          <p className="mb-2 text-sm text-muted">Click the dam (the embankment top, near the old channel). Latitude and longitude update as you click.</p>
          <ClientOnly fallback={<p className="text-sm text-muted">Loading the map…</p>}>
            <Suspense fallback={<p className="text-sm text-muted">Loading the map…</p>}>
              <LocationPicker lat={dam.lat} lon={dam.lon} onPick={(lat, lon) => update({ lat, lon })} />
            </Suspense>
          </ClientOnly>
        </div>
      ) : null}
      {ground.msg ? <p className="mt-2 text-sm text-muted">{ground.msg}</p> : null}
    </div>
  );
}

function RecordStep({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const classifyAlg = useClassifyAlg();
  const update = useDesk((s) => s.update);
  const profile = useProfile((s) => s.profile);
  return (
    <section className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div className="rounded-md border border-line bg-card p-4">
        <h2 className="text-xl">Dam record</h2>
        <div className="mt-3">
          {profile === "nd" ? (
            <>
              <NdDamPicker dam={dam} />
              <StructurePicker />
            </>
          ) : (
            <NidDamPicker dam={dam} />
          )}
        </div>
        <NidHazardLine dam={dam} />
        <p className="mt-2 text-sm text-muted">{result.datum.rule}</p>
        <DemTiePanel dam={dam} />
        {dam.nidId ? (
          <div className="mt-3">
            <NidRecordPanel dam={dam} />
          </div>
        ) : null}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <TextField label="Name" value={dam.name} onChange={(name) => update({ name })} tag={<FieldTag dam={dam} field="name" />} />
          <TextField label="NID" value={dam.nid} onChange={(nid) => update({ nid })} tag={<FieldTag dam={dam} field="nid" />} />
          <TextField label="County" value={dam.county} onChange={(county) => update({ county })} tag={<FieldTag dam={dam} field="county" />} />
          <NumField label="Year" value={dam.year} onChange={(year) => update({ year })} tag={<FieldTag dam={dam} field="year" />} />
          <NumField label="Height" suffix="ft" fix="heightFt" value={dam.heightFt} step={0.1} {...inputRange("heightFt", dam.heightFt)} onChange={(heightFt) => update({ heightFt })} tag={<FieldTag dam={dam} field="heightFt" />} />
          <NumField label="Length" suffix="ft" fix="lengthFt" value={dam.lengthFt} {...inputRange("lengthFt", dam.lengthFt)} onChange={(lengthFt) => update({ lengthFt })} tag={<FieldTag dam={dam} field="lengthFt" />} />
          <NumField label="Crest" suffix="ft" fix="crestFt" value={dam.crestFt} step={0.1} onChange={(crestFt) => update({ crestFt })} tag={
            <>
              <FieldTag dam={dam} field="crestFt" />
              {crestNavdLabel(dam, result.datum).includes("converted") ? (
                <span className="mt-1 block text-xs text-muted" data-testid="crest-converted">
                  {crestNavdLabel(dam, result.datum)}
                </span>
              ) : null}
            </>
          } />
          <NumField label="Streambed (breach bottom)" fix="streambedFt" suffix="ft" value={dam.streambedFt} step={0.1} onChange={(streambedFt) => update({ streambedFt })} tag={<FieldTag dam={dam} field="streambedFt" />} />
          <NumField label="Spillway" suffix="ft" value={dam.spillwayFt} step={0.1} onChange={(spillwayFt) => update({ spillwayFt })} />
          <NumField label="Normal pool" suffix="ft" value={dam.normalPoolFt} step={0.1} onChange={(normalPoolFt) => update({ normalPoolFt })} />
          <NumField label="Storage" suffix="ac-ft" fix="storageAcFt" value={dam.storageAcFt} {...inputRange("storageAcFt", dam.storageAcFt)} onChange={(storageAcFt) => update({ storageAcFt })} tag={<FieldTag dam={dam} field="storageAcFt" />} />
          <NumField
            label="Surface area at top of dam"
            suffix="ac, 0 = unknown"
            value={dam.surfaceAreaAc ?? 0}
            step={0.1}
            onChange={(surfaceAreaAc) => update({ surfaceAreaAc })}
            tag={
              <>
                <FieldTag dam={dam} field="surfaceAreaAc" />
                {dam.nidRef?.surfaceAreaNormalAc != null ? (
                  <span className="mt-1 block text-xs text-muted">
                    NID normal-pool area {dam.nidRef.surfaceAreaNormalAc} ac (reference only; not the area at the top of dam)
                  </span>
                ) : null}
              </>
            }
          />
          <NumField label="Drainage" suffix="mi²" value={dam.drainageMi2} step={0.1} onChange={(drainageMi2) => update({ drainageMi2 })} tag={<FieldTag dam={dam} field="drainageMi2" />} />
          <NumField label="DEM crest" fix="demCrestFt" suffix="ft NAVD88, from the DEM" value={dam.demCrestFt} step={0.1} onChange={(demCrestFt) => update({ demCrestFt })} />
          <SelectField
            label="Stated datum" fix="statedDatum"
            value={dam.statedDatum}
            options={[...(dam.statedDatum === "" ? [["", "— choose —"] as [string, string]] : []), "Local", "NAVD88", "NGVD29"]}
            onChange={(statedDatum) => update({ statedDatum: statedDatum as DatumName })}
          />
          <NumField label="Latitude" suffix="°" value={dam.lat ?? NaN} step={0.00001} min={-90} max={90} warning={latLonWarning(dam, "lat")} onChange={(lat) => update({ lat })} tag={<FieldTag dam={dam} field="lat" />} />
          <NumField label="Longitude" suffix="°" value={dam.lon ?? NaN} step={0.00001} min={-180} max={180} warning={latLonWarning(dam, "lon")} onChange={(lon) => update({ lon })} tag={<FieldTag dam={dam} field="lon" />} />
          {dam.statedDatum === "NGVD29" ? (
            <NumField
              label="NGVD29 → NAVD88 offset" fix="datumOffsetFt"
              suffix="ft, 0 = VERTCON"
              value={dam.datumOffsetFt ?? 0}
              step={0.01}
              onChange={(datumOffsetFt) => update({ datumOffsetFt })}
            />
          ) : null}
        </div>
        <label className="mt-3 flex items-start gap-2 text-sm" data-testid="new-dam">
          <input
            type="checkbox"
            className="mt-1"
            checked={dam.isNew === true}
            onChange={(e) => update({ isNew: e.target.checked })}
          />
          <span>
            New dam (proposed or not yet built)
            <span className="block text-xs text-muted">
              {classifyAlg === "damit:classify"
                ? "Unticked = an existing dam. Sent to damit:classify as is_new; it changes the starting class (S6) and turns on the new-dam proximity check (R6). A missing class of record does not make a dam new."
                : `Unticked = an existing dam. Written into dam.json as is_new; ${classifyAlg} does not take it. A missing class of record does not make a dam new.`}
            </span>
          </span>
        </label>
        <LocationPanel dam={dam} />
      </div>
      <aside className="rounded-md border border-line bg-sand p-4">
        <h3 className="text-lg">Tied to NAVD88</h3>
        <dl className="mt-3 space-y-2 text-sm">
          <Row k="Crest" v={crestNavdLabel(dam, result.datum)} />
          <Row k="Streambed" v={result.datum.streambedNavdFt == null ? "not used" : `${num(result.datum.streambedNavdFt, 1)} ft NAVD88`} />
          <Row k="Spillway" v={result.datum.spillwayNavdFt == null ? "not used" : `${num(result.datum.spillwayNavdFt, 1)} ft NAVD88`} />
          <Row k="Pool" v={result.datum.poolNavdFt == null ? "not used" : `${num(result.datum.poolNavdFt, 1)} ft NAVD88`} />
          <Row k="Offset" v={result.datum.offsetFt == null ? "—" : `${num(result.datum.offsetFt, 2)} ft`} />
        </dl>
        {result.datum.warnings.length > 0 ? (
          <FlagList flags={datumFlags(result)} className="mt-4 space-y-2 text-sm text-amber" testId="datum-flags" />
        ) : (
          <p className="mt-4 text-sm text-muted">No review flags on this record.</p>
        )}
      </aside>
    </section>
  );
}

function BreachStep({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const update = useDesk((s) => s.update);
  return (
    <section className="space-y-4">
      <div className="rounded-md border border-line bg-card p-4">
        <h2 className="text-xl">Breach</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <SelectField
            label="Method"
            value={dam.method}
            options={[
              ["froehlich", "Froehlich 2008"],
              ["macdonald", "MacDonald"],
              ["tr60", "Height-multiple width (screening)"],
            ]}
            onChange={(method) => update({ method: method as BreachMethod })}
          />
          <SelectField
            label="Failure"
            value={dam.failureMode}
            options={[
              ["piping", "Piping (default)"],
              ["overtopping", "Overtopping"],
            ]}
            onChange={(failureMode) => update({ failureMode: failureMode as FailureMode })}
          />
          <div className="rounded-sm bg-sand px-3 py-2">
            <p className="text-xs tracking-wide text-muted uppercase">Formation</p>
            <p className="font-medium tabular-nums">{num(result.breach.timeHr, 2)} hr</p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-sm bg-line sm:grid-cols-4">
          <Stat k="Average width" v={`${num(result.breach.widthFt, 0)} ft`} />
          <Stat k="Head on breach" v={`${num(result.breach.headFt, 1)} ft`} />
          <Stat k="Routed peak" v={`${num(result.breach.peakCfs, 0)} cfs`} />
          <Stat k="Froehlich 1995 check" v={`${num(result.breach.empiricalPeakCfs, 0)} cfs`} />
          <Stat k="Time to peak" v={`${num(result.breach.timeToPeakHr, 2)} hr`} />
          <Stat k="Duration (pool drained)" v={`${num(result.breach.durationHr, 2)} hr`} />
          <Stat k="Bottom width" v={`${num(result.breach.bottomWidthFt, 0)} ft`} />
          <Stat k="Released volume" v={`${num(result.breach.volumeAcFt, 0)} ac-ft`} />
        </div>
      </div>
      <BreachAdvanced dam={dam} result={result} />
      <div className="rounded-md border border-line bg-card p-4">
        <h3 className="text-lg">Outflow</h3>
        <HydroChart series={result.breach.series} />
        <ul className="mt-2 space-y-1 text-sm text-muted">
          {result.breach.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function FloodStep({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const update = useDesk((s) => s.update);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const onGeometry = useCallback((geometry: DamGeometry) => update({ geometry }), [update]);
  const { strip, outline, ol, against, lookup, plss, nd911, basis } = useFloodAreas(dam, result);
  const view = useRef<HTMLElement>(null);
  const [placing, setPlacing] = useState<PointRole | null>(null);
  const onPlaced = useCallback(() => setPlacing(null), []);
  // Bumped when geometry is set from outside the map (pick automatically), so the map reloads it.
  const [mapRev, setMapRev] = useState(0);
  const [auto, setAuto] = useState<{ busy: boolean; note: string | null; error: string | null }>({ busy: false, note: null, error: null });
  const pickAuto = async () => {
    setAuto({ busy: true, note: null, error: null });
    const id = dam.id;
    const r = await autoBreachPoint(dam);
    if (useDesk.getState().activeId !== id) return setAuto({ busy: false, note: null, error: null });
    if (r.ok) {
      update({ geometry: r.geometry });
      setMapRev((v) => v + 1);
      setAuto({ busy: false, note: r.note, error: null });
    } else setAuto({ busy: false, note: null, error: r.reason });
  };
  const pointBtn = "inline-flex h-11 items-center rounded-sm border px-3 text-sm disabled:opacity-50";
  return (
    <section ref={view} className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl">Layout & schematic flood</h2>
          <p className="text-sm text-muted">
            Draw the dam line, reservoir point, breach point, and downstream area (DSS-WISE style). Then see the
            schematic flood: {result.flood.engineLabel}. Receptors are seeds on this valley, not an inventory. Desk
            reach {num(result.flood.lengthM / 1000, 1)} km
            {result.flood.reachSource === "user"
              ? " (set by you)"
              : result.flood.reachSource === "aoi"
                ? " (to where the valley leaves the drawn area)"
                : " (to the 0.1 ft wet limit)"}
            ; receptors past it{result.flood.aoi?.applied ? " or outside the drawn area" : ""} are unresolved.
          </p>
          <p className="text-xs text-muted">Velocity: {result.flood.velocityBasis}</p>
          <p className="mt-1 text-xs text-muted">
            The schematic flood is a dated screening aid, not an inundation map. Build the terrain inundation layer below
            (3DEP terrain) for the layer of record; the schematic strip stays only as the last-resort fallback.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <SelectField
            label="Desk decay curve"
            value={dam.engine}
            options={[
              ["lisflood", "Slow decay (schematic)"],
              ["anuga", "Medium decay (schematic)"],
              ["routing", "Fast decay (schematic)"],
            ]}
            onChange={(engine) => update({ engine: engine as EngineName })}
          />
          <NumField
            label="Reach"
            suffix="km, 0 = auto"
            value={dam.reachKm ?? 0}
            step={0.5}
            onChange={(reachKm) => update({ reachKm })}
          />
          <ViewExport target={view} kind="flood" dam={dam} result={result} />
        </div>
      </div>
      <div className="rounded-md border border-line bg-card p-4">
        <h3 className="text-lg">Dam line, points, and area of interest</h3>
        <p className="mt-1 text-sm text-muted">
          Draw the dam line and the area of interest, and place the breach and reservoir points: click a button above the
          map and then the spot, or let DamIT Desk pick the breach point from the terrain (where the ground at the downstream
          toe is lowest along the dam line, the old channel crossing; with no dam line drawn, one is laid across the
          downhill slope at the record's point). Markers drawn with the map's own marker tool still count in order
          (first = reservoir, second = breach). They are saved on this dam record. A drawn area limits the schematic flood: the valley runs
          downstream from the breach (across the dam at the breach, away from the reservoir; a curved dam uses the
          segment nearest the breach, not the line from end to end), the reach stops where it
          leaves the drawn area, the wet area is clipped to it, and receptors outside it are unresolved (a house that
          would rank higher is still named). The strip is straight down that valley. It does not follow later bends
          in the stream. With no dam line or reservoir point, a drawn area around the breach is cut at its nearest edge, and one that does not contain the breach is not applied.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="breach-point-tools">
          <button type="button" className={`${pointBtn} border-water bg-water text-card`} disabled={auto.busy} onClick={() => void pickAuto()}>
            {auto.busy ? "Reading the terrain…" : "Pick breach point automatically"}
          </button>
          {(["breach", "reservoir"] as const).map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={placing === r}
              className={`${pointBtn} ${placing === r ? "border-amber bg-amber text-card" : "border-line bg-card text-ink"}`}
              onClick={() => setPlacing(placing === r ? null : r)}
            >
              {placing === r ? `Click the map to place the ${r} point (cancel)` : `Click to place ${r} point`}
            </button>
          ))}
        </div>
        {auto.note ? <p className="mt-2 text-sm text-muted">{auto.note}</p> : null}
        <TerrainSource />
        {auto.error ? <p className="mt-2 text-sm text-red-700">{auto.error}</p> : null}
        <div className="mt-3">
          {mounted ? (
            <Suspense fallback={<p className="text-sm text-muted">Loading the map…</p>}>
              <MapDraw
                key={`${dam.id}-${mapRev}`}
                placing={placing}
                onPlaced={onPlaced}
                geometry={dam.geometry}
                lat={dam.lat}
                lon={dam.lon}
                onChange={onGeometry}
                strip={strip.strip}
                stripMessage={strip.reason}
                plss={plss.state === "ready" ? plss.table.rows : null}
                plssMessage={plss.state === "ready" ? null : plss.message}
                nd911={nd911.state === "ready" ? { inside: nd911.table.rows, outside: nd911.table.outside } : null}
                nd911Message={nd911.state === "ready" ? null : nd911.message}
                outline={ol}
                outlineMessage={outline.state === "ready" ? null : outline.message}
              />
            </Suspense>
          ) : (
            <p className="text-sm text-muted">Loading the map…</p>
          )}
        </div>
      </div>
      <OutlinePanel dam={dam} result={result} outline={outline} />
      <PlssPanel lookup={lookup} plss={plss} against={against} basis={basis} />
      <Nd911Panel dam={dam} result={result} lookup={lookup} nd911={nd911} />
      <div className="overflow-hidden rounded-md border border-line">
        <ValleyMap flood={result.flood} />
      </div>
      <div className="grid grid-cols-3 gap-px overflow-hidden rounded-sm bg-line">
        <Stat k="Max depth" v={`${num(result.flood.maxDepthFt, 1)} ft`} />
        <Stat k="Wet area" v={`${num(result.flood.acres, 0)} ac`} />
        {/* 0 means no receptor velocity was estimated (none entered, or none flooded) — show "—", not a false 0.0. */}
        <Stat k="Fastest seed (est.)" v={result.flood.maxVelocityFps ? `${num(result.flood.maxVelocityFps, 1)} ft/s` : "—"} />
      </div>
      <AoiNote flood={result.flood} />
    </section>
  );
}

/** The guided setup's terrain step: the Flood step's terrain build panel, reporting its progress to the step rail. */
function TerrainStep({
  dam,
  result,
  onStatus,
}: {
  dam: DamRecord;
  result: ReturnType<typeof analyze>;
  onStatus: (s: { busy: string | null; error: string | null }) => void;
}) {
  const online = useOnline();
  const outline = useMemo(() => outlineState(dam, result, online), [dam, result, online]);
  return outline.state === "none" ? (
    <div className="rounded-md border border-line bg-card p-4">
      <h3 className="text-lg">Terrain inundation (approximate)</h3>
      <p className="mt-1 text-sm text-muted">{outline.message}</p>
    </div>
  ) : (
    <OutlinePanel dam={dam} result={result} outline={outline} onStatus={onStatus} />
  );
}

const breathe = () => new Promise<void>((r) => setTimeout(r, 0));

/** The IndexedDB error of this dam's last layer save, or null (outline-store.ts). Starts null, so SSR and the first client render agree. */
function useOutlineSaveError(id: string): string | null {
  return useSyncExternalStore(
    onOutlineSaveChange,
    () => outlineSaveError(id),
    () => null,
  );
}

/** "and saved with this dam", or the storage error when IndexedDB refused the layer. */
function SavedNote({ id }: { id: string }) {
  const err = useOutlineSaveError(id);
  if (!err)
    return <>and saved with this dam (the terrain itself is not kept).</>;
  return (
    <>
      but <span className="text-amber" data-testid="outline-not-saved">layer not saved (storage error: {err}). It stays on the desk for this visit only; the browser may be out of storage or in a private window.</span>
    </>
  );
}

/**
 * The terrain outline: built on request from one 3DEP terrain request (about 3.5 MB for a 10 km reach), saved on the
 * dam so it shows offline. The build runs in a Web Worker (inundation-client.ts), so the page stays responsive and
 * Cancel stops it; where no worker can be made it runs in-thread in short chunks, as before.
 */
function OutlinePanel({
  dam,
  result,
  outline,
  onStatus,
}: {
  dam: DamRecord;
  result: ReturnType<typeof analyze>;
  outline: OutlineState;
  /** The guided setup's step rail listens here for the build's progress and errors. */
  onStatus?: (s: { busy: string | null; error: string | null }) => void;
}) {
  const update = useDesk((s) => s.update);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const building = useRef<AbortController | null>(null);
  useEffect(() => onStatus?.({ busy, error }), [busy, error, onStatus]);
  // A build keeps running when the user moves to another step meanwhile; its result is still saved on its own dam
  // (the activeId guard below drops it only if another dam is active by then). Only Cancel stops it.
  if (outline.state === "none") return null;
  const build = async () => {
    const io = outlineInputs(dam, result);
    if (!io.ok) return setError(io.reason);
    const id = dam.id;
    setError(null);
    const ctl = new AbortController();
    building.current = ctl;
    try {
      setBusy("Preparing the terrain request…");
      const r = await buildInundationInWorker(dam, result, { yieldFn: breathe, onStatus: setBusy, signal: ctl.signal });
      if (useDesk.getState().activeId !== id) return;
      // Stamped with the terrain it was built on (the local DEM in use, else 3DEP): labels and credits read it.
      if (r.ok) update({ outline: stampTerrain(r.cache) });
      else setError(r.reason);
    } catch (e) {
      if ((e as Error).message !== CANCELLED) setError((e as Error).message);
    } finally {
      if (building.current === ctl) building.current = null;
      setBusy(null);
    }
  };
  const cancel = () => building.current?.abort();
  const s = outline.state === "ready" ? outline.stats : null;
  const layer = outline.state === "ready" ? outline.layer : "outline";
  const rec = layerOfRecord(dam, result, outline);
  const triage = triageDam(dam, result, outline);
  const routed = outline.state === "ready" ? outline.routed : undefined;
  // The volume soft limit is the outline's (outline.ts); the routed flood keeps its own volume logic.
  const vol = s
    ? volumeCheck(routed ? routed.fillAcFt : s.laidAcFt, routed ? routed.releasedAcFt : result.breach.volumeAcFt, {
        rawLaidAcFt: routed ? null : s.volumeLimit?.rawLaidAcFt,
      })
    : null;
  const limitNote = s && !routed ? volumeLimitNote(s, result.breach.volumeAcFt) : null;
  const volLine = vol ? (
    <>
      {vol.label ? (
        <p className="mt-1 text-sm font-medium text-amber" role="status" data-testid="outline-volume-label">
          <span className="rounded-sm border border-amber px-1.5 py-0.5">{vol.label}</span>{" "}
          <span className="font-normal">
            Under {SMALL_RELEASE_ACFT} ac-ft released: a terrain layer is a poor guide to so little water. Run this dam in the DamIT Runner (Run the flood model, on Report) and import the run on Results.
          </span>
        </p>
      ) : null}
      <p className={"mt-1 text-sm " + (vol.warn ? "text-amber" : "text-muted")} role={vol.warn ? "alert" : undefined} data-testid="outline-volume-check">
        {vol.text}
      </p>
      {limitNote ? (
        <p className="mt-1 text-xs text-muted" data-testid="outline-volume-limit">
          {limitNote}
        </p>
      ) : null}
    </>
  ) : null;
  const btn = "inline-flex h-10 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:opacity-50";
  return (
    <div className="rounded-md border border-line bg-card p-4" data-testid="outline-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg">Terrain inundation (approximate)</h3>
        <div className="flex flex-wrap gap-2">
          {outline.state !== "offline" ? (
            <button type="button" onClick={() => void build()} disabled={busy != null} className={btn} data-testid="outline-build">
              {busy ? "Building…" : s ? "Build again" : "Build the inundation layer"}
            </button>
          ) : null}
          {busy ? (
            <button type="button" onClick={cancel} className={btn} data-testid="outline-cancel">
              Cancel
            </button>
          ) : null}
          {dam.outline ? (
            <button type="button" onClick={() => update({ outline: undefined })} disabled={busy != null} className={btn}>
              Remove layer
            </button>
          ) : null}
        </div>
      </div>
      <p className="mt-1 text-sm font-medium" data-testid="outline-label">
        {outline.state === "ready" ? layerLabel(dam.outline, ROUTED_LABEL) : labelWithTerrain(layer === "routed" ? ROUTED_LABEL : OUTLINE_LABEL, currentTerrain())}.
      </p>
      <p className={"mt-1 text-sm " + (rec.needsRunner ? "text-amber" : "text-muted")} role={rec.needsRunner ? "alert" : undefined} data-testid="inundation-primary-note">
        {rec.note}
      </p>
      {!dam.resultsOfRecord ? (
        <div className="mt-2 rounded-sm border border-line bg-paper p-3" data-testid="triage">
          <p className={"text-sm font-medium " + (triage.recommendation === "needs-runner" ? "text-amber" : "")}>
            Triage: {triage.label} · {CONFIDENCE_LABEL[triage.confidence]}
          </p>
          <ul className="mt-1 list-disc pl-5 text-sm text-muted">
            {triage.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">
            A screening call for ordering the Runner worklist, not a hazard classification: the desk's own screen is a stand-in, never the layer of record.
          </p>
        </div>
      ) : null}
      {outline.message ? (
        <p className="mt-1 text-sm text-muted" role="status">
          {outline.message}
        </p>
      ) : null}
      {busy ? (
        <p className="mt-1 text-sm text-muted" role="status">
          {busy}
        </p>
      ) : null}
      {error ? (
        <p className="mt-1 text-sm text-amber" role="alert">
          {error}
        </p>
      ) : null}
      {s && routed ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-sm bg-line sm:grid-cols-4">
            <Stat k="Flooded area (mapped, ≥ 0.1 ft)" v={`${num(s.outlineAc, 0)} ac`} />
            <Stat k="Routed peak out" v={`${num(routed.peakOutCfs, 0)} cfs`} />
            <Stat k="Peak attenuated" v={`${num(routed.routedPeakFellBy * 100, 0)} %`} />
            <Stat k="Channel routed" v={`${num(routed.channelKm, 1)} km`} />
          </div>
          <p className="mt-2 text-sm" data-testid="routed-summary">
            Routed {num(routed.channelKm, 1)} km down the drainage: peak {num(routed.peakInCfs, 0)} → {num(routed.peakOutCfs, 0)} cfs.
          </p>
          <details className="mt-1 text-sm" data-testid="routed-details">
            <summary className="cursor-pointer text-xs text-muted">How it was routed, and the area by depth…</summary>
          <p className="mt-1 text-sm" data-testid="routed-note">
            The routed flood carries the breach hydrograph down the drainage the terrain traces ({num(routed.channelKm, 1)} km),
            attenuating the {num(routed.peakInCfs, 0)} cfs breach peak to {num(routed.peakOutCfs, 0)} cfs,{" "}
            {routed.method === "spread"
              ? `then pours the water each stretch holds at its own peak onto the ground beside it (${num(routed.fillAcFt, 0)} ac-ft laid down for ${num(routed.releasedAcFt, 0)} ac-ft released, ${num(routed.volumeRatio, 1)}×).`
              : "then fills the water surface onto the ground."}{" "}
            {routed.cappedSections > 0
              ? `${routed.cappedSections} of ${routed.sections} cross-sections could not carry the routed peak within the cut height, so their stage is a floor, not a fit.`
              : `All ${routed.sections} cross-sections carried the routed peak.`}
          </p>
          <p className="mt-1 text-xs text-muted">
            By depth band: {s.bands.map((b) => `${b.label} ${num(b.ac, 0)} ac`).join(" · ")}
            {Math.abs(routed.floodedAc - s.outlineAc) >= 1
              ? ` (${num(s.outlineAc, 0)} ac on the map; ${num(routed.floodedAc, 0)} ac counting every wet cell, also water shallower than 0.1 ft)`
              : ""}
            . The PLSS and 911 lists below are
            against this flood; the dated flood strip stays on the map only as the last-resort fallback.
          </p>
          </details>
          {routed.reach?.incomplete ? (
            <p className="mt-1 text-sm text-amber" role="alert" data-testid="routed-incomplete">
              Incomplete downstream: after {routed.reach.rounds} terrain extension{routed.reach.rounds === 1 ? "" : "s"} (+
              {num(routed.reach.extendedKm, 1)} km) the routed wave still reaches the terrain's edge with {num(routed.reach.strandedAcFt, 0)} ac-ft
              to carry. The flood runs further than this layer shows; a Runner run is the layer of record there.
            </p>
          ) : null}
          {deepCellsNote(s) ? (
            <p className="mt-1 text-xs text-amber" role="status" data-testid="outline-deep-cells">
              {deepCellsNote(s)}
            </p>
          ) : null}
          {volLine}
          {routed.notes.length ? (
            <p className="mt-1 text-xs text-amber" data-testid="routed-flags">
              {routed.notes.join(" ")}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-muted" data-testid="outline-dem">
            Terrain: {s.dem.width} × {s.dem.height} cells at {num(s.dem.cellM, 0)} m (NAVD88); depth from Muskingum-Cunge
            routing of the breach hydrograph on DEM cross-sections and {routed.method === "spread" ? "a volume spread" : "a terrain fill"}, not a full 2-D hydraulic model. Built{" "}
            {new Date(outline.state === "ready" ? outline.builtAt : "").toLocaleString()} <SavedNote id={dam.id} /> {terrainInfo(dam.outline?.source).attribution}
          </p>
        </>
      ) : s ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-sm bg-line sm:grid-cols-4">
            <Stat k="Outline area" v={`${num(s.outlineAc, 0)} ac`} />
            <Stat k="Engine wet area" v={`${num(s.engineAc, 0)} ac`} />
            <Stat k="Channel traced" v={`${num(s.channelKm, 1)} km`} />
            <Stat k="Bed, top to end" v={`${num(s.bedTopFt, 0)} → ${num(s.bedEndFt, 0)} ft`} />
          </div>
          <p className="mt-2 text-sm" data-testid="outline-acres-note">
            {outlineAcresNote(s)}
          </p>
          {volLine}
          {traceStartNote(s) ? (
            <p className="mt-1 text-sm" data-testid="outline-trace-start">
              {traceStartNote(s)}
            </p>
          ) : null}
          {channelPitsNote(s) ? (
            <p className="mt-1 text-xs text-muted" data-testid="outline-channel-pits">
              {channelPitsNote(s)}
            </p>
          ) : null}
          {pitsExcludedNote(s) ? (
            <p className="mt-1 text-xs text-muted" data-testid="outline-pits-excluded">
              {pitsExcludedNote(s)}
            </p>
          ) : null}
          {deepCellsNote(s) ? (
            <p className="mt-1 text-xs text-amber" role="status" data-testid="outline-deep-cells">
              {deepCellsNote(s)}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-muted">
            By depth band:{" "}
            {s.bands.map((b) => `${b.label} ${num(b.ac, 0)} ac`).join(" · ")}. The PLSS and 911 lists below are against
            this outline; the dated flood strip stays on the map only as the last-resort fallback.
          </p>
          <p className="mt-1 text-xs text-muted" data-testid="outline-dem">
            Terrain: {s.dem.width} × {s.dem.height} cells at {num(s.dem.cellM, 0)} m ({num(s.dem.bytes / 1e6, 1)} MB, NAVD88),
            {s.dem.missing ? ` ${s.dem.missing} cells missing,` : ""} {s.rings} rings after smoothing; {s.droppedPatches}{" "}
            patches under the minimum dropped, {s.filledHoles} holes filled. Water surface = the traced channel bed (pits
            filled) + the desk depth at that distance downstream; ground must be under it and connected to the channel.
            Built {new Date(outline.state === "ready" ? outline.builtAt : "").toLocaleString()} <SavedNote id={dam.id} /> {terrainInfo(dam.outline?.source).attribution}
          </p>
        </>
      ) : null}
    </div>
  );
}

function PlssPanel({ lookup, plss, against, basis }: { lookup: FloodStrip | null; plss: PlssState; against: string; basis: string }) {
  const update = useDesk((s) => s.update);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (plss.state === "none") return null;
  const lookUp = async () => {
    if (!lookup) return;
    setBusy(true);
    setError(null);
    const id = useDesk.getState().activeId;
    try {
      const p = await fetchPlss(lookup);
      if (useDesk.getState().activeId === id) update({ plss: p });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const t = plss.state === "ready" ? plss.table : null;
  return (
    <div className="rounded-md border border-line bg-card p-4" data-testid="plss-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg">PLSS sections the {against === "flood strip" ? "strip" : against} touches</h3>
        {plss.state !== "offline" ? (
          <button
            type="button"
            onClick={() => void lookUp()}
            disabled={busy}
            className="inline-flex h-10 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:opacity-50"
          >
            {busy ? "Looking up…" : t ? "Look up again" : "Look up PLSS sections"}
          </button>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-muted" data-testid="plss-basis">Strip: {basis}.</p>
      {plss.message ? <p className="mt-1 text-sm text-muted" role="status">{plss.message}</p> : null}
      {error ? <p className="mt-1 text-sm text-amber" role="alert">{error}</p> : null}
      {t ? (
        <>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm" data-testid="plss-table">
              <thead className="text-left text-xs tracking-wide text-muted uppercase">
                <tr>
                  <th className="px-2 py-1">#</th>
                  <th className="px-2 py-1">Section</th>
                  <th className="px-2 py-1">Wet ac</th>
                  <th className="px-2 py-1">Deepest band</th>
                  <th className="px-2 py-1">km downstream</th>
                </tr>
              </thead>
              <tbody>
                {t.rows.map((r) => (
                  <tr key={r.id} className="border-t border-line">
                    <td className="px-2 py-1 tabular-nums">{r.order}</td>
                    <td className="px-2 py-1">{r.label}</td>
                    <td className="px-2 py-1 tabular-nums">{num(r.wetAc, 1)}</td>
                    <td className="px-2 py-1">{r.bandLabel}</td>
                    <td className="px-2 py-1 tabular-nums">
                      {num(r.fromKm, 2)}–{num(r.toKm, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">
            {t.rows.length} sections, {num(t.listedAc, 1)} of the {against}&apos;s {num(t.stripAc, 1)} ac. Slivers under {SLIVER_AC} ac
            not listed: {t.sliversIgnored}
            {t.uncoveredAc >= SLIVER_AC ? `; ${num(t.uncoveredAc, 1)} ac of the ${against} lies outside every fetched section` : ""}.
            {against === "routed flood"
              ? ` ${(lookup?.properties as { disclaimer?: string } | undefined)?.disclaimer ?? ROUTED_LABEL}.`
              : against !== "flood strip"
                ? ` ${(lookup?.properties as { disclaimer?: string } | undefined)?.disclaimer ?? OUTLINE_LABEL}.`
                : basis.startsWith("the schematic")
                  ? " Approximate, and a dated last resort: the strip is the schematic desk valley, not a mapped flood extent — build the terrain inundation layer for the current method."
                  : ` Strip from ${basis}.`}{" "}
            Looked up{" "}
            {new Date(t.fetchedAt).toLocaleString()} and saved with this dam.
          </p>
          <p className="mt-1 text-xs text-muted">{PLSS_ATTRIBUTION}</p>
        </>
      ) : null}
    </div>
  );
}

const HAB_OPTIONS: [string, string][] = [
  ["", "Not classified (counted as habitable)"],
  ["yes", "Habitable"],
  ["no", "Not habitable"],
];

/**
 * 911 address points: looked up on request, listed when inside the strip. They never change the screen on their own;
 * "Add for review" makes receptor seeds the user classifies, and "Remove" takes them away again.
 */
function Nd911Panel({
  dam,
  result,
  lookup,
  nd911,
}: {
  dam: DamRecord;
  result: ReturnType<typeof analyze>;
  lookup: FloodStrip | null;
  nd911: Nd911State;
}) {
  const update = useDesk((s) => s.update);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Picked ND dams: look the points up and add the ones inside the strip without a click (once).
  const autoTried = useRef(false);
  useEffect(() => {
    if (!lookup || autoTried.current || !wantsNd911Lookup(dam, nd911)) return;
    autoTried.current = true;
    setBusy(true);
    const id = dam.id;
    fetchStructures(dam, lookup)
      .then((c) => { if (useDesk.getState().activeId === id) update({ nd911: c }); })
      .catch((e) => setError((e as Error).message))
      .finally(() => setBusy(false));
  }, [dam, nd911, lookup, update]);
  useEffect(() => {
    const p = nd911AutoPatch(dam, nd911, result);
    if (p) update(p);
  }, [dam, nd911, result, update]);
  // Pads for the 911 seeds: ground at the point minus the channel bed at its station, from 3DEP (once per seed).
  const padTried = useRef(new Set<string>());
  useEffect(() => {
    const todo = padPoints(dam).filter((p) => !padTried.current.has(p.id));
    if (todo.length === 0) return;
    todo.forEach((p) => padTried.current.add(p.id));
    const id = dam.id;
    lookupPads(dam, result)
      .then((receptors) => {
        // dam switched mid-read: do not write this dam's receptors onto whatever is active now,
        // and drop the tried ids so the lookup runs again when this dam is active.
        if (useDesk.getState().activeId !== id) {
          todo.forEach((p) => padTried.current.delete(p.id));
          return;
        }
        if (receptors) update({ receptors });
      })
      .catch((e) => {
        todo.forEach((p) => padTried.current.delete(p.id));
        setError((e as Error).message);
      });
  }, [dam, result, update]);
  if (nd911.state === "none") return null;
  const lookUp = async () => {
    if (!lookup) return;
    setBusy(true);
    setError(null);
    const id = dam.id;
    try {
      const c = await fetchStructures(dam, lookup);
      if (useDesk.getState().activeId === id) update({ nd911: c });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const t = nd911.state === "ready" ? nd911.table : null;
  const w = structureWords(dam);
  const isNsi = w.short === "NSI";
  const seeds = new Map(dam.receptors.filter((r) => r.source === "nd911").map((r) => [r.id, r]));
  const addRows = (rows: Nd911Row[]) => update({ receptors: addNd911Seeds(dam.receptors, rows, result) });
  const remove = (ids?: string[]) => update({ receptors: removeNd911Seeds(dam.receptors, ids) });
  const classify = (id: string, v: string) =>
    update({
      receptors: dam.receptors.map((r) => (r.id === id ? { ...r, habitable: v === "" ? undefined : v === "yes" } : r)),
    });
  const notAdded = t ? t.rows.filter((r) => !r.added) : [];
  // Pads left estimated because the terrain REQUEST failed (3DEP 502, timeout), as against no terrain at the point.
  const padRetry = padsToRetry(dam.receptors);
  const retryPads = () => {
    padRetry.forEach((r) => padTried.current.delete(r.id));
    update({ receptors: resetFailedPads(dam.receptors) });
  };
  const btn = "inline-flex h-10 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:opacity-50";
  const small = "inline-flex h-9 items-center rounded-sm border border-line bg-paper px-2 text-xs text-ink";
  return (
    <div className="rounded-md border border-line bg-card p-4" data-testid="nd911-panel">
      {padRetry.length ? (
        <p className="mb-2 text-sm text-amber" role="alert" data-testid="nd911-pad-retry">
          The terrain request for {padRetry.length} structure{padRetry.length === 1 ? "'s" : "s'"} ground height failed ({padRetry[0].padNote?.replace(/^pad estimated: terrain request failed \((.*?)\);.*$/, "$1")}), so{" "}
          {padRetry.length === 1 ? "it sits" : "they sit"} on the channel bed (pad 0) and the screen holds at Review. This is not "no terrain at the point".{" "}
          <button type="button" className="underline" onClick={retryPads}>
            Look the pads up again
          </button>
        </p>
      ) : null}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg">{w.noun[0].toUpperCase() + w.noun.slice(1)} {t ? `inside the ${t.against}` : "near the strip"}</h3>
        {nd911.state !== "offline" ? (
          <button type="button" onClick={() => void lookUp()} disabled={busy} className={btn}>
            {busy ? "Looking up…" : t ? "Look up again" : `Look up ${w.noun}`}
          </button>
        ) : null}
      </div>
      {nd911.message ? (
        <p className="mt-1 text-sm text-muted" role="status">
          {nd911.message}
        </p>
      ) : null}
      {error ? (
        <p className="mt-1 text-sm text-amber" role="alert">
          {error}
        </p>
      ) : null}
      {t ? (
        <>
          <p className="mt-1 text-sm" data-testid="nd911-count">
            <span className="font-medium">{t.rows.length}</span> of {t.total} {isNsi ? "structures" : "address points"} in the
            looked-up box are inside the {t.against}. They do not change the desk screen unless you add them for review.
          </p>
          {t.rows.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" className={btn} disabled={notAdded.length === 0} onClick={() => addRows(notAdded)}>
                Add all {notAdded.length || ""} as structures for review
              </button>
              <button type="button" className={btn} disabled={seeds.size === 0} onClick={() => remove()}>
                Remove {w.short} structures{seeds.size ? ` (${seeds.size})` : ""}
              </button>
            </div>
          ) : null}
          {t.rows.length > 0 ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm" data-testid="nd911-table">
                <thead className="text-left text-xs tracking-wide text-muted uppercase">
                  <tr>
                    <th className="px-2 py-1">#</th>
                    <th className="px-2 py-1">{isNsi ? "Structure" : "Address"}</th>
                    <th className="px-2 py-1">Depth band</th>
                    <th className="px-2 py-1">km downstream</th>
                    <th className="px-2 py-1">{isNsi ? "Occupancy" : "Place type"}</th>
                    <th className="px-2 py-1">For review</th>
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((r) => {
                    const id = seedId(r.nguid, r.lon, r.lat);
                    const seed = seeds.get(id);
                    return (
                      <tr key={id} className="border-t border-line align-top">
                        <td className="px-2 py-1 tabular-nums">{r.order}</td>
                        <td className="px-2 py-1">{r.address}</td>
                        <td className="px-2 py-1">{r.bandLabel}</td>
                        <td className="px-2 py-1 tabular-nums">{num(r.downstreamKm, 2)}</td>
                        <td className="px-2 py-1">{r.placeType || "—"}</td>
                        <td className="px-2 py-1">
                          {seed ? (
                            <div className="flex flex-wrap items-center gap-2">
                              <select
                                aria-label={`Classify ${r.address}`}
                                className="h-9 rounded-sm border border-line bg-paper px-2 text-xs"
                                value={seed.habitable == null ? "" : seed.habitable ? "yes" : "no"}
                                onChange={(e) => classify(id, e.target.value)}
                              >
                                {HAB_OPTIONS.map(([v, l]) => (
                                  <option key={v} value={v}>
                                    {l}
                                  </option>
                                ))}
                              </select>
                              <button type="button" className={small} onClick={() => remove([id])}>
                                Remove
                              </button>
                            </div>
                          ) : (
                            <button type="button" className={small} onClick={() => addRows([r])}>
                              Add as structure
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="mt-2 text-xs text-muted">
            Inside means within the {t.against}&apos;s depth bands; the band is the one the point falls in.{" "}
            {isNsi
              ? "An NSI structure is a modelled record (USACE), not a survey: its occupancy, foundation height and day / night population are estimates to review."
              : "An address point marks an address, not a surveyed structure or floor height."} Added points become home seeds on the channel
            bed (pad 0 ft, the desk&apos;s deepest case) at their distance downstream, listed under &quot;Needs an
            engineer&apos;s call&quot; until you classify them. Looked up{" "}
            {new Date(t.fetchedAt).toLocaleString()} and saved with this dam.
          </p>
          {isNsi ? (
            <p className="mt-1 text-xs text-muted">
              Fields kept: the NSI id, occupancy type and damage category, building type, stories, year built, foundation
              height and type, and the day / night population estimates. The NSI holds no address, owner or occupant name.{" "}
              {NSI_ATTRIBUTION}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted">
              Fields kept: the published address, unit, community, ZIP, county, place type and placement, and the NG911 site
              id. Not kept: {ND911_DROPPED_FIELDS.slice(0, 3).map((d) => d.field).join(", ")} (free text that can name people
              or businesses) and duplicate or record-keeping fields. {ND911_ATTRIBUTION}
            </p>
          )}
        </>
      ) : null}
      {!t && seeds.size > 0 ? (
        <div className="mt-2">
          <button type="button" className={btn} onClick={() => remove()}>
            Remove {w.short} structures ({seeds.size})
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The last QGIS screening for this dam (Absaraka desk test 2026-11-21): PARTIAL at its time limit, finished with no
 * class (not determined), failed, or finished with a preliminary class. The desk screen below is a separate thing.
 */
function ScreeningState({ dam }: { dam: DamRecord }) {
  const r = dam.screeningResult;
  if (!r) return null;
  const hold = screeningHold(dam);
  const when = new Date(r.at);
  const at = Number.isNaN(when.getTime()) ? "" : ` (${when.toLocaleString()})`;
  const figures = [r.areaAc != null ? `${Math.round(r.areaAc).toLocaleString()} ac wet` : null, r.maxDepthFt != null ? `max ${r.maxDepthFt.toFixed(1)} ft` : null].filter(Boolean).join(", ");
  return (
    <div
      className={"rounded-md border p-3 text-sm " + (hold ? "border-2 border-amber bg-sand" : "border-line bg-card")}
      role={hold ? "status" : undefined}
      data-testid="screening-state"
      data-state={hold ? hold.kind : "done"}
    >
      <p className="text-xs tracking-widest text-muted uppercase">QGIS screening (DamIT Screener){at}</p>
      <p className="mt-1 font-medium">{hold ? hold.text : `QGIS screening finished: preliminary ${r.label}`}</p>
      {figures ? <p className="text-muted">Screening flood so far: {figures}{hold?.kind === "partial" ? " (a lower bound: the flood had not finished spreading)" : ""}.</p> : null}
      {hold ? (
        <p className="mt-1 text-muted">
          Stays open until a screening finishes with a class. Next: raise DAMIT_SCREENING_TIMEOUT_S, or import the model run on Results.
        </p>
      ) : null}
    </div>
  );
}

function ScreenStep({ dam, result: deskResult }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const update = useDesk((s) => s.update);
  const { result, ref } = useAnalysisOfRecord(dam, deskResult);
  return (
    <section className="space-y-4">
      <ReviewSummary dam={dam} result={result} where="review" />
      <ScreeningState dam={dam} />
      <div className="rounded-md border border-line bg-card p-4">
        <p className="text-xs tracking-widest text-muted uppercase" data-testid="screen-source">
          {ref ? `Schematic preview on the source of record: ${ref.label}` : "Desk screen: schematic preview"} (ND / ACER TM 11
          desk rules, not the DamIT classification)
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <LevelBadge level={result.screen.level} label={result.screen.label} />
          <p className="max-w-lg text-sm text-muted">
            ND rules on the ACER TM 11 depth-velocity charts: a home in the high-danger zone reads High; in the judgment
            zone it reads {result.screen.judgmentAsProbable ? "High (flagged; old option)" : "Medium by rule"}; any wet home reads at
            least Medium (economic loss); roads by AADT and class. Barns and sheds do not count.
            {result.screen.acerLevel ? ` Worst TM 11 zone: ${result.screen.acerLevel}.` : ""}
          </p>
        </div>
        <NidHazardLine dam={dam} />
        {result.screen.classOfRecord || dam.sampleNote ? (
          <div className="mt-3 rounded-sm border border-line bg-sand p-3 text-sm">
            {result.screen.classOfRecord ? (
              <p>
                <span className="font-medium">Class of record: {result.screen.classOfRecord}.</span> The desk screen above
                ({result.screen.label}) is not the class of record.
              </p>
            ) : null}
            {dam.sampleNote ? <p className="mt-1 text-muted">{dam.sampleNote}</p> : null}
          </div>
        ) : null}
        <div className="mt-3 max-w-xs">
          <SelectField
            label="Judgment zone"
            value={dam.judgmentAsProbable === true ? "high" : "medium"}
            options={[
              ["medium", "Medium by rule (default)"],
              ["high", "Count as probable loss of life (High, old option)"],
            ]}
            onChange={(v) => update({ judgmentAsProbable: v === "high" })}
          />
        </div>
        <ul className="mt-4 space-y-2 text-sm">
          {result.screen.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        {result.screen.judgment.length > 0 ? (
          <div className="mt-4 rounded-sm bg-sand p-3 text-sm">
            <p className="font-medium">Needs an engineer&apos;s call</p>
            <ul className="mt-1 space-y-1">
              {result.screen.judgment.map((j) => (
                <li key={j}>{j}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <ReceptorTable result={result} />
    </section>
  );
}

function ReportStep({ dam, result: deskResult }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const { result, ref, label } = useAnalysisOfRecord(dam, deskResult);
  const update = useDesk((s) => s.update);
  const view = useRef<HTMLElement>(null);
  // The inventory pull dates for the Report's age line, only for a record that came from the inventories.
  const { data: nd } = useNidData(Boolean(dam.nidId || dam.nidRef));
  const bundles = nd ? { nidFetchedUtc: nd.nidSource.fetchedUtc, state: nd.state } : undefined;
  return (
    <section ref={view} className="space-y-4">
      <ReviewSummary dam={dam} result={result} where="report" />
      <ClassifyReceptorsPanel dam={dam} result={result} where="report" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs tracking-widest text-muted uppercase">Read from this desk</p>
          <h2 className="text-2xl">
            {dam.name} <span className="text-muted">({dam.nid})</span>
          </h2>
          <p className="text-sm text-muted">
            {dam.county ? `${dam.county} · ` : ""}
            {result.breach.label} · {result.flood.engineLabel}
          </p>
          <p className="text-sm" data-testid="report-source">
            Source of record: <span className="font-medium">{label}</span>
            {ref
              ? ` (imported ${ref.importedAt.slice(0, 10)}; ${ref.files.join(", ")}). Depths, wet area, velocities and the screen are from this run; breach and hydrograph are the desk's.`
              : " (schematic valley). Import a model run on the Results step to use it instead."}
          </p>
          {ref?.warnings.length ? (
            <ul className="mt-1 list-disc pl-5 text-xs text-amber">
              {ref.warnings.map((w, i) => (
                <li key={`run-${i}`}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <ViewExport target={view} kind="report" dam={dam} result={result} />
      </div>
      <HazardLead dam={dam} result={result} />
      <AoiNote flood={result.flood} />
      <PaperReport dam={dam} result={result} source={label} runWarnings={ref?.warnings ?? []} bundles={bundles} />
      <ExportPanel dam={dam} result={result} desk={deskResult} />
      <ClassificationPanel dam={dam} level={result.screen.level} update={update} />
      <PluginPanel dam={dam} result={result} />
      {dam.nidId ? <SourcesNote dam={dam} /> : null}
    </section>
  );
}

/**
 * The Report's lead: the class damit:classify gave the downstream receptors with the chosen preset or custom methods.
 * The desk screen is shown under it only as a schematic preview (ND / ACER TM 11 desk rules), never as that class.
 */
function HazardLead({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const profile = useProfile((s) => s.profile);
  const classifyAlg = useClassifyAlg(dam.hazardResult);
  const lead = useMemo(() => reportLead(dam, result, profile), [dam, result, profile]);
  const tone = lead.incomplete
    ? "border-2 border-amber bg-sand"
    : lead.kind === "hazard"
      ? "border-water bg-card"
      : lead.kind === "stale"
        ? "border-amber bg-sand"
        : "border-line bg-sand";
  return (
    <div
      className={`rounded-md border p-4 ${tone}`}
      data-testid="hazard-lead"
      data-kind={lead.kind}
      data-incomplete={lead.incomplete ? "true" : undefined}
      role={lead.incomplete ? "alert" : undefined}
    >
      <p className="text-xs tracking-widest text-muted uppercase">Downstream consequences, judged by the chosen jurisdiction</p>
      <h3 className="mt-1 text-xl">{lead.title}</h3>
      <ul className="mt-2 space-y-1 text-sm">
        {lead.lines.map((l) => (
          <li key={l} className="break-words">
            {l}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{screenAgainstChoice(result.screen.level, damChoice(dam), classifyAlg)}</p>
    </div>
  );
}


const handoff = {
  depth: "",
  velocity: "",
  dv: "",
  wse: "",
  nonbreach: "",
  arrival: "",
  railLookup: "",
  work: "",
  dem: "",
  model: "lisflood",
  source: "data",
  log: "No DamIT plugin has been started.",
  /** What the desk filled in itself (handoff-fill.ts) and for which dam: cleared on another dam unless edited. */
  auto: {} as Partial<Record<FillField, string>>,
  autoFor: "",
  autoNote: "",
  /** A screening that ended with a partial (time-limited) preliminary result: shown above the log. */
  warning: "",
  busy: false,
  job: "",
};
let handoffTimer = 0;

type JobPath =
  | "/api/screen"
  | "/api/model"
  | "/api/folder"
  | "/api/layers"
  | "/api/classify"
  | "/api/check"
  | "/api/data"
  | "/api/pmp"
  | "/api/finder";

/** The algorithm ids the desktop server will call (GET /api/handoff): DamIT defaults or the user's overrides. */
type HandoffInfo = {
  algorithms: Record<string, string>;
  sources: Record<string, string>;
  problems: string[];
  cli: string | null;
  /** The folder a blank Work folder field means (DAMIT_WORK, else ~/DamITDams), from the desk server. */
  work?: string;
  /** One-line notices from the desk server (the first-start copy of the old DamIT Crest settings folder). */
  notices?: string[];
};
/** The server's answer per desk profile: the ND profile hands off to the DWR DamSafety plugins (profile.py). */
const handoffInfos: Partial<Record<DeskProfile, HandoffInfo>> = {};

/** Shown until the desktop server answers (or in a page with no server): the compiled-in DamIT defaults. */
const DEFAULT_ALGS: Record<DeskProfile, Record<string, string>> = { us: { ...DEFAULT_ALGORITHMS }, nd: { ...ND_ALGORITHMS } };

function PluginPanel({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const [, bump] = useState(0);
  const profile = useProfile((s) => s.profile);
  const handoffInfo = handoffInfos[profile] ?? null;
  const update = useDesk((st) => st.update);
  useEffect(() => {
    const id = window.setInterval(() => {
      if (handoff.busy) bump((n) => n + 1);
    }, 500);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    if (handoffInfos[profile] || !hasDesktopServer()) return;
    let live = true;
    fetch(`/api/handoff?profile=${profile}`, { headers: crestApiHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((info: HandoffInfo | null) => {
        if (live && info && info.algorithms) {
          handoffInfos[profile] = info;
          bump((n) => n + 1);
        }
      })
      .catch(() => {
        /* no desktop server: the defaults are shown */
      });
    return () => {
      live = false;
    };
  }, [profile]);
  // Auto-fill (Absaraka desk test 2026-11-21): the DEM chosen in the desk, the imported run's rasters (found by name on
  // this computer by the desk server) and a rail lookup CSV go into the blank fields; typed values are never replaced.
  const runFiles = dam.resultsOfRecord?.files ?? [];
  const runKeyText = runFiles.join("|");
  const runLabel = dam.resultsOfRecord?.label ? `the imported ${dam.resultsOfRecord.label} run` : "the imported run";
  const autofill = useCallback(async () => {
    if (!hasDesktopServer() || handoff.busy) return;
    if (handoff.autoFor !== dam.id) {
      // Another dam: drop what was filled for the last one (unless it was edited since).
      for (const [k, v] of Object.entries(handoff.auto) as [FillField, string][]) if (handoff[k] === v) handoff[k] = "";
      handoff.auto = {};
      handoff.autoNote = "";
    }
    handoff.autoFor = dam.id;
    const names = runFiles.map((f) => f.split(/[\\/]/).pop() ?? f).join(",");
    try {
      const r = await fetch(`/api/handoff/autofill?names=${encodeURIComponent(names)}`, { headers: crestApiHeaders() });
      if (!r.ok) return;
      const auto = (await r.json()) as Autofill;
      if (handoff.autoFor !== dam.id) return;
      const plan = fillPlan(handoff, runFiles, auto, runLabel);
      Object.assign(handoff, plan.set);
      handoff.auto = { ...handoff.auto, ...plan.set };
      const missing = plan.unresolved.length
        ? ` Not found on this computer: ${plan.unresolved.join(", ")} (put the run folder under the work folder or DAMIT_DEM_ROOTS, or use Choose…).`
        : "";
      if (plan.note || missing) handoff.autoNote = (plan.note ?? "") + missing;
      bump((n) => n + 1);
    } catch {
      /* no server answer: the fields stay as they are */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runKeyText stands for runFiles
  }, [dam.id, runKeyText, runLabel]);
  useEffect(() => {
    void autofill();
  }, [autofill]);
  const algs = handoffInfo?.algorithms ?? DEFAULT_ALGS[profile];
  const online = useOnline();
  const strip = useMemo(() => floodStrip(dam, result), [dam, result]);
  const plss = useMemo(() => plssState(dam, strip.strip, online), [dam, strip.strip, online]);
  const files = useMemo(() => {
    const out: Record<string, string> = {};
    const root = (dam.nid || dam.id).toLowerCase().replace(/[^a-z0-9]/g, "_").replace(/^_+/, "") || "dam";
    try {
      const pkg = generateLisfloodPackage(dam, result.breach.series, {
        cellSizeM: dam.lisflood?.cellSizeM,
        pointX: dam.lisflood?.pointX,
        pointY: dam.lisflood?.pointY,
      });
      out[`${root}.par`] = pkg.par;
      out[`${root}.bci`] = pkg.bci;
      out[`${root}.bdy`] = pkg.bdy;
    } catch {
      /* the package stays out of the folder when the desk cannot build it */
    }
    if (strip.strip) {
      const table = plss.state === "ready" ? plss.table : null;
      out["flood_strip.geojson"] = exportFloodStripGeoJsonWithPlss(strip.strip, table);
      out["flood_strip.kml"] = exportFloodStripKmlWithPlss(strip.strip, table);
      if (table) out["plss.csv"] = exportPlssCsv(table);
    }
    return out;
  }, [dam, result.breach.series, strip.strip, plss]);

  const start = useCallback(
    async (path: JobPath) => {
      if (handoffTimer) window.clearInterval(handoffTimer);
      handoff.busy = true;
      handoff.log = "Starting…\n";
      handoff.warning = "";
      jobStarted(path);
      bump((n) => n + 1);
      // Classify: the downstream receptors (and drawn area) go to damit:classify, so the chosen preset or custom
      // methods judge them. The keys tie the result to this choice and these receptors.
      const receptors = path === "/api/classify" ? classifyReceptors(dam, result) : undefined;
      // The screening's outcome is kept with the dam it ran for (rail, status bar and Screen step).
      const screenFor = path === "/api/screen" ? dam.id : null;
      const ran = receptors
        ? { damId: dam.id, choiceKey: choiceKey(damChoice(dam)), receptorKey: receptorKey(receptors), choiceText: choiceText(damChoice(dam)) }
        : null;
      let response: Response;
      try {
        response = await fetch(path, {
          method: "POST",
          headers: crestApiHeaders(true),
          body: JSON.stringify({
            // The desk profile: "nd" hands off to the DWR DamSafety plugins (desktop/damit_desktop/profile.py).
            profile,
            // Piping when no failure mode was chosen; the server fills piping as well (handoff.resolved_failure_mode).
            dam: handoffDam(dam),
            // With what this record used of the shared defaults, for the dam.json the hand-off writes.
            analysis: { ...result, assumptions: assumptions(dam, sharedNow(), CREST_VERSION, result.breach.startPool) },
            work: handoff.work,
            dem: handoff.dem,
            depth: path === "/api/classify" ? handoff.depth : undefined,
            velocity: path === "/api/classify" ? handoff.velocity : undefined,
            dv: path === "/api/classify" ? handoff.dv : undefined,
            wse: path === "/api/classify" ? handoff.wse : undefined,
            nonbreach: path === "/api/classify" ? handoff.nonbreach : undefined,
            arrival: path === "/api/classify" ? handoff.arrival : undefined,
            railLookup: path === "/api/classify" ? handoff.railLookup : undefined,
            receptors,
            model: handoff.model,
            source: handoff.source,
            files: path === "/api/layers" || path === "/api/check" ? undefined : files,
          }),
        });
      } catch {
        // fetch itself rejected: nothing is listening on this origin, so there is no desktop server running.
        handoff.busy = false;
        handoff.log =
          "This page has no DamIT Desk server, so QGIS was not started. Start the desk with bin/damit-desk (or bin\\damit-desk.cmd) and open the address it prints.";
        jobNoServer();
        bump((n) => n + 1);
        return;
      }
      try {
        if (!response.ok) throw new Error(`The DamIT Desk server rejected the job (HTTP ${response.status}).`);
        const job = (await response.json()) as { id?: string };
        if (!job.id) throw new Error("The DamIT Desk server did not return a job id.");
        handoff.job = job.id;
        handoffTimer = window.setInterval(async () => {
          try {
            const found = await (await fetch(`/api/job?id=${job.id}`, { headers: crestApiHeaders() })).json();
            handoff.log = String(found.log || "");
            if (found.done && found.partial && typeof found.warning === "string") handoff.warning = found.warning;
            if (found.done && screenFor && useDesk.getState().activeId === screenFor) update({ screeningResult: screeningOutcome(found) });
            if (found.done && ran && found.ok && found.classification?.suggestedClass && useDesk.getState().activeId === ran.damId) {
              const c = found.classification as Record<string, unknown>;
              const str = (v: unknown) => (typeof v === "string" && v ? v : null);
              update({
                hazardResult: {
                  suggestedClass: String(c.suggestedClass),
                  ordinal: c.ordinal == null ? null : String(c.ordinal),
                  genericLabel: str(c.genericLabel),
                  report: str(c.report),
                  gpkg: str(c.gpkg),
                  ranPreset: str(c.ranPreset),
                  ranPresetLabel: str(c.ranPresetLabel),
                  ranMode: str(c.ranMode),
                  driving: Array.isArray(c.driving) ? (c.driving as NonNullable<HazardResult["driving"]>).slice(0, 8) : [],
                  hits: parseHits(c.hits),
                  hitsTotal: typeof c.hitsTotal === "number" ? c.hitsTotal : undefined,
                  warnings: typeof c.warnings === "number" ? c.warnings : 0,
                  layers: (c.layers as Record<string, number>) ?? {},
                  impacted: (c.impacted as Record<string, number>) ?? {},
                  wetStructures: typeof c.wetStructures === "number" ? c.wetStructures : null,
                  skipped: typeof c.skipped === "number" ? c.skipped : 0,
                  complete: typeof c.complete === "boolean" ? c.complete : null,
                  notChecked: (c.notChecked as Record<string, string>) ?? {},
                  layerSources: (c.layerSources as Record<string, string>) ?? {},
                  railTrainsLookup: str(c.railTrainsLookup),
                  ruling: parseRuling(c.ruling),
                  source: str(c.source),
                  tm11Class: str(c.tm11Class),
                  classifiedAt: new Date().toISOString(),
                  choiceKey: ran.choiceKey,
                  receptorKey: ran.receptorKey,
                  choiceText: ran.choiceText,
                },
              });
            }
            if (found.done) {
              window.clearInterval(handoffTimer);
              handoffTimer = 0;
              handoff.busy = false;
              handoff.job = "";
              jobFinished(path, found);
              bump((n) => n + 1);
            }
          } catch {
            window.clearInterval(handoffTimer);
            handoffTimer = 0;
            handoff.busy = false;
            handoff.job = "";
            handoff.log = "Lost the job log.";
            jobFinished(path, null);
            bump((n) => n + 1);
          }
        }, 1000);
      } catch (e) {
        // A response came back, so a server is there — surface its real error, not the generic "no server" text.
        handoff.busy = false;
        handoff.log = `The DamIT Desk server returned an error: ${(e as Error).message}`;
        jobFinished(path, { ok: false });
        bump((n) => n + 1);
      }
    },
    [dam, result, files, update, profile],
  );
  // The command palette's "Check QGIS hand-off" and "Write the dam folder" start here, with this panel's fields.
  useEffect(() => setJobStarter((p) => (handoff.busy ? undefined : void start(p as JobPath))), [start]);

  const cancel = useCallback(async () => {
    if (!handoff.job) return;
    try {
      await fetch(`/api/cancel?id=${handoff.job}`, { method: "POST", headers: crestApiHeaders() });
    } catch {
      /* the job log shows whether the run stopped */
    }
  }, []);

  const field = "mt-1 h-10 w-full rounded-sm border border-line bg-paper px-3 text-sm";
  const btn =
    "inline-flex h-10 items-center rounded-sm border border-water bg-water px-3 text-sm text-card disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <div className="scroll-mt-4 rounded-md border border-line bg-card p-4" id="handoff-panel" data-testid="handoff-panel">
      <h3 className="text-lg">DamIT plugins in QGIS</h3>
      <p className="mt-1 text-sm text-muted">
        Writes the dam folder the DamIT plugins read, including the LISFLOOD package and the flood strip. Get layers
        downloads a DEM and streams for this area (USGS, United States), or uses the DamIT data folder (DAMIT_DATA).
        Screening runs {algs.preflight} and starts {algs.runchain} only if the preflight is READY. Classify hands the
        folder, the jurisdiction choice, the model run&apos;s depth raster and the downstream receptors to {algs.classify}:
        the real structures, roads and rail lines for the depth raster&apos;s area (the DamIT data folder, else USACE NSI,
        FHWA HPMS and the national rail network online) plus the receptors you mapped. A layer it cannot check makes the
        class INCOMPLETE, shown as a lower bound. The flood model runs {algs.rundam} for this dam only. A missing
        algorithm, a missing DEM or depth raster, or a preflight FAIL stops there. Check QGIS hand-off tests the link to
        the plugins first, without running a dam. The log shows the plugin&apos;s output as it runs. Cancel stops QGIS
        and what it started, for every button; DAMIT_SCREENING_TIMEOUT_S limits screening and DAMIT_PLUGIN_TIMEOUT_S the
        Download layers, Atlas 14 and Find fills buttons (3 h, 15 min, 2 h by default). The result is a suggested class,
        not an official one.
      </p>
      <p className="mt-1 text-xs text-muted" data-testid="handoff-algorithms">
        Algorithms: {Object.entries(algs)
          .filter(([, id]) => id)
          .map(([role, id]) => `${role} ${id}`)
          .join(" · ")}
        {handoffInfo
          ? ""
          : profile === "nd"
            ? " (North Dakota profile: the DWR DamSafety plugins; set DAMIT_ND_ALG_* or the nd section of damit-handoff.json to point at other ids)"
            : " (DamIT defaults; set DAMIT_ALG_* or damit-handoff.json to point at other ids)"}
        {handoffInfo?.problems?.length ? ` — ${handoffInfo.problems.join("; ")}` : ""}
      </p>
      {serverNotices(handoffInfo?.notices).map((n) => (
        <p key={n} className="mt-1 text-xs text-ink [overflow-wrap:anywhere]" role="status" data-testid="storage-notice">
          Settings: {n}
        </p>
      ))}
      {handoff.autoNote ? (
        <p className="mt-3 flex flex-wrap items-baseline gap-2 text-xs text-muted" role="status" data-testid="handoff-autofill">
          <span>{handoff.autoNote}</span>
          <button type="button" className="rounded-sm border border-line bg-paper px-1.5 text-ink" onClick={() => void autofill()} disabled={handoff.busy}>
            Fill again
          </button>
        </p>
      ) : null}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-muted">
          Work folder
          <input
            className={field}
            value={handoff.work}
            placeholder={workFolderHint(handoffInfo?.work)}
            title={workFolderHint(handoffInfo?.work)}
            data-testid="handoff-work"
            onChange={(e) => {
              handoff.work = e.target.value;
              bump((n) => n + 1);
            }}
          />
          <span className="mt-0.5 block text-[11px] text-muted [overflow-wrap:anywhere]" data-testid="handoff-work-default">
            {(handoff.work ?? "").trim() ? "" : workFolderHint(handoffInfo?.work).replace(/^blank = /, "Used when blank: ")}
          </span>
        </label>
        <label className="text-xs text-muted">
          DEM <ChooseFile what="the DEM" onPick={(p) => ((handoff.dem = p), bump((n) => n + 1))} />
          <input
            className={field}
            value={handoff.dem}
            placeholder="blank = dem.tif, the data folder DEM, or DAMIT_DEM"
            onChange={(e) => {
              handoff.dem = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Depth raster (Classify) <ChooseFile what="the depth raster" onPick={(p) => ((handoff.depth = p), bump((n) => n + 1))} />
          <input
            className={field}
            value={handoff.depth}
            placeholder="maximum depth raster from a model run"
            onChange={(e) => {
              handoff.depth = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Velocity raster (Classify, optional) <ChooseFile what="the velocity raster" onPick={(p) => ((handoff.velocity = p), bump((n) => n + 1))} />
          <input
            className={field}
            value={handoff.velocity}
            placeholder="blank = none"
            onChange={(e) => {
              handoff.velocity = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Depth × velocity raster (Classify, optional)
          <input
            className={field}
            value={handoff.dv}
            placeholder="blank = none"
            onChange={(e) => {
              handoff.dv = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Water-surface elevation raster (Classify, optional)
          <input
            className={field}
            value={handoff.wse}
            placeholder="blank = none"
            onChange={(e) => {
              handoff.wse = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Non-breach depth raster (Classify, optional)
          <input
            className={field}
            value={handoff.nonbreach}
            placeholder="blank = none"
            onChange={(e) => {
              handoff.nonbreach = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Arrival time raster (hours) (Classify, optional) <ChooseFile what="the arrival raster" onPick={(p) => ((handoff.arrival = p), bump((n) => n + 1))} />
          <input
            className={field}
            value={handoff.arrival}
            placeholder="blank = none"
            onChange={(e) => {
              handoff.arrival = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Rail trains-per-day lookup (Classify, optional CSV){" "}
          <ChooseFile what="the rail trains-per-day lookup (CSV)" mode="csv" onPick={(p) => ((handoff.railLookup = p), bump((n) => n + 1))} />
          <input
            className={field}
            value={handoff.railLookup}
            placeholder="blank = none: an impacted rail line can only reach Medium"
            onChange={(e) => {
              handoff.railLookup = e.target.value;
              bump((n) => n + 1);
            }}
          />
        </label>
        <label className="text-xs text-muted">
          Flood model
          <select
            className={field}
            value={handoff.model}
            onChange={(e) => {
              handoff.model = e.target.value;
              bump((n) => n + 1);
            }}
          >
            <option value="lisflood">LISFLOOD-FP only</option>
            <option value="anuga">LISFLOOD-FP, then ANUGA</option>
            <option value="hecras">LISFLOOD-FP, then HEC-RAS 2D</option>
            <option value="builtin">Built-in screening engine (still needs a DEM)</option>
          </select>
        </label>
        <label className="text-xs text-muted">
          Layers
          <select
            className={field}
            value={handoff.source}
            onChange={(e) => {
              handoff.source = e.target.value;
              bump((n) => n + 1);
            }}
          >
            <option value="data">DamIT data folder (DAMIT_DATA)</option>
            <option value="download">Download DEM and streams for this area</option>
          </select>
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2" data-testid="handoff-actions">
        <button
          type="button"
          className="inline-flex h-10 items-center rounded-sm border border-water bg-paper px-3 text-sm text-water disabled:cursor-not-allowed disabled:opacity-50"
          disabled={handoff.busy}
          onClick={() => void start("/api/check")}
          title="Checks that qgis_process is found and that the preflight, chain, flood model and classify algorithms are in its QGIS profile. Runs no dam and writes nothing."
        >
          Check QGIS hand-off
        </button>
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/layers")}>
          Get layers
        </button>
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/folder")}>
          Write the dam folder
        </button>
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/screen")}>
          Write folder and run screening
        </button>
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/model")}>
          Run the flood model
        </button>
        <button type="button" className={btn} disabled={handoff.busy} data-fix="classify" onClick={() => void start("/api/classify")}>
          Classify ({algs.classify})
        </button>
        {algs.data ? (
          <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/data")}>
            Download layers ({algs.data})
          </button>
        ) : null}
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/pmp")}>
          Atlas 14 point ({algs.pmp})
        </button>
        <button type="button" className={btn} disabled={handoff.busy} onClick={() => void start("/api/finder")}>
          Find fills ({algs.finder})
        </button>
        {handoff.busy && handoff.job ? (
          <button
            type="button"
            className="inline-flex h-10 items-center rounded-sm border border-line bg-paper px-3 text-sm"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        ) : null}
      </div>
      <details className="mt-2 text-xs text-muted" data-testid="handoff-buttons-help">
        <summary className="cursor-pointer">What each button runs…</summary>
      <p className="mt-1">
        The flood button runs one dam ({algs.rundam}, or the {profile === "nd" ? "DWR runner CLI (ndbreach_cli.py)" : "DamIT runner CLI"} when both Point X and Point Y are filled in
        the DEM's coordinates). It does not start {algs.batch}. A failure mode that was not chosen is sent as piping.
        The drawn line stays longitude and latitude, so it is not sent as DAM_LINES. Download layers keeps the offline
        structure layers for the dam's state. Atlas 14 is a precipitation-frequency estimate, not a PMP study. Find
        fills looks for embankments on the DEM; a candidate is not a listed dam.
      </p>
      </details>
      <ExportsFolder />
      {handoff.warning ? (
        <p className="mt-2 rounded-sm border border-amber bg-amber/10 p-2 text-sm text-ink" role="status" data-testid="screening-partial">
          {handoff.warning}
        </p>
      ) : null}
      <LiveLog text={handoff.log} busy={handoff.busy} />
    </div>
  );
}

/** "Choose…" beside a path field, in a browser page served by the desk (the native window types or pastes paths). */
function ChooseFile({ what, onPick, mode = "dem" }: { what: string; onPick: (path: string) => void; mode?: "dem" | "csv" }) {
  if (isDesktop() || !hasDeskServer()) return null;
  return (
    <button
      type="button"
      className="ml-1 rounded-sm border border-line bg-paper px-1.5 text-xs text-ink"
      onClick={() => void pickOnServer({ mode, title: `Choose ${what}` }).then((p) => p && onPick(p))}
    >
      Choose…
    </button>
  );
}

/** Where Save writes in a browser page (the desk server writes exports; browser_io.py). */
function ExportsFolder() {
  const [dir, setDir] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const browser = !isDesktop() && hasDeskServer();
  useEffect(() => {
    if (!browser) return;
    getServer<{ dir: string }>("/api/export_dir")
      .then((r) => setDir(r.dir))
      .catch(() => setDir(null));
  }, [browser]);
  if (!browser) return null;
  const change = async () => {
    const p = await pickOnServer({ mode: "folder", title: "Folder for exports", start: dir });
    if (!p) return;
    try {
      setDir((await postServer<{ dir: string }>("/api/export_dir", { path: p })).dir);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <p className="mt-2 text-xs text-muted" data-testid="exports-folder">
      Exports (Save buttons) are written to <span className="break-all text-ink">{dir ?? "…"}</span>{" "}
      <button type="button" className="rounded-sm border border-line bg-paper px-1.5 text-xs text-ink" onClick={() => void change()}>
        Change…
      </button>
      {err ? <span className="ml-2 text-red-700">{err}</span> : null}
    </p>
  );
}

/** The job log, kept scrolled to the newest line while a plugin runs (the server streams its output). */
function LiveLog({ text, busy }: { text: string; busy: boolean }) {
  const ref = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (el && busy) el.scrollTop = el.scrollHeight;
  }, [text, busy]);
  return (
    <pre ref={ref} className="mt-3 max-h-72 overflow-auto rounded-sm bg-paper p-3 text-xs whitespace-pre-wrap" data-testid="plugin-log" aria-live="polite">
      {busy ? "● running — output appears as the plugin prints it\n" : ""}
      {text}
    </pre>
  );
}

function SourcesNote({ dam }: { dam: DamRecord }) {
  const prov = Object.entries(dam.provenance ?? {});
  return (
    <div className="rounded-md border border-line bg-card p-4 text-sm" data-testid="report-sources">
      <h3 className="text-lg">Sources</h3>
      <NidHazardLine dam={dam} />
      <ul className="mt-2 space-y-1">
        {prov.map(([field, p]) =>
          p ? (
            <li key={field}>
              {field}: {String(p.value)} from {p.src} {p.field} ({p.asOf}
              {p.confirmed ? ", confirmed by the user" : ""})
            </li>
          ) : null,
        )}
      </ul>
      {dam.nidRef ? <p className="mt-2 text-xs text-muted">{dam.nidRef.attribution}</p> : null}
    </div>
  );
}

function AoiNote({ flood }: { flood: ReturnType<typeof analyze>["flood"] }) {
  if (!flood.aoi) return null;
  return (
    <div className="rounded-md border border-line bg-sand p-3 text-sm">
      <p className="font-medium">{flood.aoi.label}</p>
      {flood.aoi.applied ? (
        <>
          <p className="mt-1 text-muted">
            {flood.aoi.areaBasis === "clipped"
              ? `Wet area of the schematic strip inside the drawn area: ${num(flood.acres, 0)} ac`
              : `Wet area of the schematic strip within the drawn area's reach (direction unknown, so cut by distance, not clipped to the outline): ${num(flood.acres, 0)} ac`}
            ; reach {num(flood.lengthM / 1000, 1)} km
            {flood.aoi.maxDepthInsideFt < flood.maxDepthFt - 0.005
              ? `; max depth ${num(flood.maxDepthFt, 1)} ft at the breach, ${num(flood.aoi.maxDepthInsideFt, 1)} ft inside the drawn area`
              : ""}
            .
          </p>
          {flood.aoi.direction ? <p className="mt-1 text-muted">{flood.aoi.direction}</p> : null}
        </>
      ) : null}
      {flood.warnings.length > 0 ? <FlagList flags={floodFlags({ flood })} className="mt-2 space-y-1 text-amber" testId="flood-flags" /> : null}
    </div>
  );
}

// Pipeline stage status for the rail: a step is done when its defining output exists on the
// record, blocked when a hard prerequisite is missing (nid-dams.ts), else pending/current.
const RAIL_MARK: Record<"done" | "current" | "blocked" | "todo", { glyph: string; cls: string; label: string }> = {
  done: { glyph: "✓", cls: "bg-water text-card border-water", label: "Complete" },
  current: { glyph: "▶", cls: "bg-card text-water border-water", label: "Current step" },
  blocked: { glyph: "!", cls: "bg-red-bg text-flag-red border-flag-red", label: "Blocked — missing required inputs" },
  todo: { glyph: "", cls: "bg-card text-muted border-line", label: "Not started" },
};

/**
 * The map-centric pipeline rail (V4+V7+V3 hybrid redesign): every step stays reachable at any
 * time — the old horizontal tab nav allowed jumping ahead, and jumping ahead is how a late,
 * confusing failure happened — but each step now shows its state before the jump, so the
 * prerequisite problem is visible in navigation instead of surfacing as an error later.
 * Non-colour marks keep the state readable in grayscale and field mode.
 */
function StepRail({
  dam,
  result,
  desk,
  step,
  setStep,
  onFix,
}: {
  dam: DamRecord;
  result: ReturnType<typeof analyze>;
  desk: ReturnType<typeof analyze>;
  step: StepId;
  setStep: (s: StepId) => void;
  onFix: (i: CheckItem) => void;
}) {
  // The checklist (2026-11-21): what holds each step, from missingForNext and the datum/flood flags of the desk
  // record, and the step-done rules of the record of analysis (the same rules as the marks and the status bar).
  const classifyAlg = useClassifyAlg();
  const checks = useMemo(() => stepChecklist(dam, desk, result, classifyAlg), [dam, desk, result, classifyAlg]);
  return (
    <nav className="flex min-w-0 flex-col gap-0.5" aria-label="Pipeline" data-testid="step-rail">
      {STEPS.map((s, i) => {
        const st = railState(s.id as StepId, dam, result, step);
        const m = RAIL_MARK[st];
        const on = step === s.id;
        const items = checks[s.id as StepId];
        return (
          <Fragment key={s.id}>
          <button
            type="button"
            onClick={() => setStep(s.id as StepId)}
            aria-current={on ? "step" : undefined}
            data-testid={`rail-${s.id}`}
            className={
              "group flex w-full items-start gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-smooth " +
              (on ? "bg-water/12 ring-1 ring-water" : "hover:bg-sand")
            }
          >
            <span
              aria-hidden="true"
              className={"mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-bold " + m.cls}
            >
              {m.glyph || String(i + 1)}
            </span>
            <span className="min-w-0 flex-1">
              <span className={"block font-medium " + (on ? "text-ink" : "text-ink")}>{s.label}</span>
              <span className={"block text-xs " + (on ? "text-muted" : "text-muted")}>{m.label}</span>
            </span>
          </button>
          <RailChecklist stepId={s.id as StepId} label={s.label} items={items} onFix={onFix} />
          </Fragment>
        );
      })}
    </nav>
  );
}

/** The persistent situation strip: the dam's key facts stay legible while the user works on any
 * step, the way RAS Mapper keeps the map present behind every pane. */
function SituationStrip({ dam, result }: { dam: DamRecord; result: ReturnType<typeof analyze> }) {
  const peak = result.breach.series.length ? Math.max(...result.breach.series.map((p) => p.qCfs)) : null;
  // Fresh install test 2026-11-21: the strip sat in the 210 px left rail of the three-pane layout but switched to four
  // columns on the window width (xl:), so "Swa… / PIPELINE 8 steps" ran into each other. The columns now follow the
  // strip's own width (a container query): two in the rail, four when it spans the page.
  const cell = "min-w-0";
  const label = "truncate text-xs uppercase tracking-wide text-muted";
  return (
    <div className="@container border-b border-line bg-card px-3 py-2.5 text-sm" data-testid="situation-strip">
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 @md:grid-cols-4">
        <div className={cell}>
          <p className={label}>Dam</p>
          <p className="truncate font-medium" title={dam.name}>
            {dam.name}
          </p>
        </div>
        <div className={cell}>
          <p className={label}>NID</p>
          <p className="truncate font-mono text-sm">{dam.nid || "—"}</p>
        </div>
        <div className={cell}>
          <p className={label}>Peak Q</p>
          <p className="truncate font-mono">{peak != null ? `${num(peak, 0)} cfs` : "—"}</p>
        </div>
        <div className={cell}>
          <p className={label}>Pipeline</p>
          <p className="truncate font-medium">8 steps</p>
        </div>
      </div>
    </div>
  );
}

/** The inspector panel: validation and provenance for the current step, reusing the same flag
 * machinery the screen and report rely on (warnings.ts), so nothing here is new truth. */
function InspectorPanel({ dam, result, step }: { dam: DamRecord; result: ReturnType<typeof analyze>; step: StepId }) {
  const warnings = [...datumFlags(result), ...floodFlags(result)];
  const stops = warnings.filter((w) => w.severity === "stop");
  const others = warnings.filter((w) => w.severity !== "stop");
  return (
    <aside className="flex min-w-0 flex-col gap-4" aria-label="Inspector" data-testid="inspector-panel">
      <div>
        <h2 className="text-base font-semibold">Validation</h2>
        <p className="text-xs text-muted">Live checks from the analysis; a stop holds the screen at Review, exactly as before.</p>
      </div>
      {stops.length === 0 && others.length === 0 ? (
        <p className="rounded-md border border-line bg-green-bg px-3 py-2 text-sm text-flag-green" data-testid="inspector-clear">
          ✓ No flags. Values used as entered.
        </p>
      ) : (
        <>
          {stops.length > 0 ? (
            <div className="rounded-md border border-flag-red bg-red-bg px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-flag-red">Holds the screen</p>
              <FlagList flags={stops} className="mt-1 list-disc space-y-1 pl-4 text-sm text-ink" />
            </div>
          ) : null}
          {others.length > 0 ? (
            <div className="rounded-md border border-flag-amber bg-amber-bg px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-flag-amber">Check before relying</p>
              <FlagList flags={others} className="mt-1 list-disc space-y-1 pl-4 text-sm text-ink" />
            </div>
          ) : null}
        </>
      )}
      <div className="rounded-md border border-line bg-sand px-3 py-2 text-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Step {STEPS.find((s) => s.id === step)?.label}</p>
        <p className="mt-1 text-muted">Required first: {missingForNext(dam).join(", ") || "nothing — the record is complete."}</p>
      </div>
      <div className="rounded-md border border-line bg-card px-3 py-2 text-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Provenance</p>
        <p className="mt-1 text-muted text-xs">{result.datum.rule}</p>
      </div>
      {dam.outline != null ? (
        <div className="rounded-md border border-line bg-card px-3 py-2 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Terrain</p>
          <p className="mt-1 text-muted text-xs">Terrain outline on record (built from the {terrainInfo(dam.outline?.source).local ? terrainInfo(dam.outline?.source).label : "3DEP terrain"}).</p>
        </div>
      ) : null}
    </aside>
  );
}

function StepNav({ step, setStep, blocked }: { step: StepId; setStep: (s: StepId) => void; blocked: string[] }) {
  const i = STEPS.findIndex((s) => s.id === step);
  const prev = i > 0 ? STEPS[i - 1] : null;
  const next = i >= 0 && i < STEPS.length - 1 ? STEPS[i + 1] : null;
  const btn = "inline-flex h-11 items-center gap-1 rounded-sm border px-4 text-sm";
  return (
    <nav className="mt-6 flex items-center justify-between gap-3" aria-label="Step navigation">
      {prev ? (
        <button type="button" onClick={() => setStep(prev.id)} className={`${btn} border-line bg-card text-ink`}>
          <ChevronLeft className="size-4" aria-hidden="true" />
          Back: {prev.label}
        </button>
      ) : (
        <span />
      )}
      {next ? (
        <span className="flex flex-col items-end gap-1">
          <button
            type="button"
            disabled={blocked.length > 0}
            onClick={() => setStep(next.id)}
            className={`${btn} border-water bg-water text-card disabled:cursor-not-allowed disabled:opacity-50`}
          >
            Next: {next.label}
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
          {blocked.length > 0 ? <span className="text-xs text-amber">Enter first: {blocked.join(", ")}</span> : null}
        </span>
      ) : null}
    </nav>
  );
}

function ExportPanel({ dam, result, desk }: { dam: DamRecord; result: ReturnType<typeof analyze>; desk: ReturnType<typeof analyze> }) {
  const update = useDesk((s) => s.update);
  const root = (dam.nid || dam.id).toLowerCase().replace(/[^a-z0-9]/g, "_");
  // UTM zone for the dam's longitude, so the grid hint matches the zone the export actually projects into
  // (western ND is 13N, central/eastern 14N) rather than always claiming 14N.
  const utmZone = dam.lon != null && Number.isFinite(dam.lon) ? Math.floor((dam.lon + 180) / 6) + 1 : null;
  const utmLabel = utmZone ? `UTM ${utmZone}N` : "UTM (zone for the dam's longitude)";
  const lisflood = useMemo(() => {
    try {
      return {
        pkg: generateLisfloodPackage(dam, result.breach.series, {
          cellSizeM: dam.lisflood?.cellSizeM,
          pointX: dam.lisflood?.pointX,
          pointY: dam.lisflood?.pointY,
        }),
        error: null,
      };
    } catch (e) {
      return { pkg: null, error: (e as Error).message };
    }
  }, [dam, result.breach.series]);
  // The strip of record (desk strip, or an imported run's raster strip), and the outline when it is built.
  const { online, strip, outline, ol, plss, nd911 } = useFloodAreas(dam, desk);
  // Lists against the outline when it is built (and in its exports); the strip's own exports keep the strip's lists.
  const plssTable = plss.state === "ready" ? plss.table : null;
  const nd911Table = nd911.state === "ready" ? nd911.table : null;
  const stripPlss = useMemo(() => (ol ? plssState(dam, strip.strip, online) : plss), [ol, dam, strip.strip, online, plss]);
  const stripNd911 = useMemo(() => (ol ? nd911State(dam, strip.strip, online) : nd911), [ol, dam, strip.strip, online, nd911]);
  const stripPlssTable = stripPlss.state === "ready" ? stripPlss.table : null;
  const stripNd911Table = stripNd911.state === "ready" ? stripNd911.table : null;
  const [saved, setSaved] = useState<string | null>(null);
  const save = useCallback(async (name: string, text: string, type?: string) => {
    const r = await saveText(name, text, type);
    if (r.status === "saved") setSaved(r.path ? `Saved ${r.path}` : null);
    else if (r.status === "cancelled") setSaved(null);
    else setSaved(`Could not save ${name}: ${r.message}`);
  }, []);
  const btn =
    "inline-flex h-10 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <div className="rounded-md border border-line bg-card p-4">
      <h3 className="text-lg">Export</h3>
      <p className="mt-1 text-sm text-muted">
        Hand-off files for the DamIT Runner and LISFLOOD-FP. The LISFLOOD package runs 72 h with the point source at the
        breach; you supply the DEM.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={btn} onClick={() => void save(`${root}_hydrograph.csv`, exportHydrographCsv(result.breach.series), "text/csv")}>
          Hydrograph CSV
        </button>
        <button type="button" className={btn} onClick={() => void save(`${root}_dam.json`, exportDamJson(dam, result, sharedNow()), "application/json")}>
          dam.json
        </button>
        {(["par", "bci", "bdy"] as const).map((ext) => (
          <button
            key={ext}
            type="button"
            className={btn}
            disabled={!lisflood.pkg}
            onClick={() => lisflood.pkg && void save(`${root}.${ext}`, lisflood.pkg[ext])}
          >
            LISFLOOD .{ext}
          </button>
        ))}
        <button
          type="button"
          className={btn}
          disabled={!strip.strip}
          title={strip.reason ?? undefined}
          onClick={() => strip.strip && void save(`${root}_flood_strip.geojson`, exportFloodGeoJson(strip.strip, stripPlssTable, stripNd911Table), "application/geo+json")}
        >
          Flood strip GeoJSON
        </button>
        <button
          type="button"
          className={btn}
          disabled={!strip.strip}
          title={strip.reason ?? undefined}
          onClick={() => strip.strip && void save(`${root}_flood_strip.kml`, exportFloodKml(strip.strip, stripPlssTable, stripNd911Table), "application/vnd.google-earth.kml+xml")}
        >
          Flood strip KML
        </button>
        <button
          type="button"
          className={btn}
          disabled={!ol}
          title={ol ? undefined : (outline.message ?? undefined)}
          onClick={() => ol && void save(`${root}_terrain_outline.geojson`, exportFloodGeoJson(ol, plssTable, nd911Table), "application/geo+json")}
        >
          Terrain outline GeoJSON
        </button>
        <button
          type="button"
          className={btn}
          disabled={!ol}
          title={ol ? undefined : (outline.message ?? undefined)}
          onClick={() => ol && void save(`${root}_terrain_outline.kml`, exportFloodKml(ol, plssTable, nd911Table), "application/vnd.google-earth.kml+xml")}
        >
          Terrain outline KML
        </button>
        <button
          type="button"
          className={btn}
          disabled={!plssTable}
          title={plssTable ? undefined : (plss.message ?? undefined)}
          onClick={() => plssTable && void save(`${root}_plss_sections.csv`, exportPlssCsv(plssTable), "text/csv")}
        >
          PLSS sections CSV
        </button>
        <button
          type="button"
          className={btn}
          disabled={!nd911Table || !dam.nd911}
          title={nd911Table ? undefined : (nd911.message ?? undefined)}
          onClick={() => nd911Table && dam.nd911 && void save(`${root}_911_address_points.csv`, exportNd911Csv(nd911Table, dam.nd911), "text/csv")}
        >
          911 address points CSV
        </button>
      </div>
      <p className="mt-2 text-xs text-muted">
        Flood strip (WGS 84): {strip.strip ? (dam.resultsOfRecord && !strip.basis.startsWith("the desk") ? `depth bands from ${strip.basis}.` : `dated last resort — an approximate screening strip, not a mapped flood extent; the schematic desk valley drawn as depth bands${dam.resultsOfRecord ? ` (${strip.basis})` : ""}. Build the terrain inundation layer for the current method.`) : strip.reason}
        {dam.resultsOfRecord ? ` dam.json names the source of record (${dam.resultsOfRecord.label}).` : ""}
      </p>
      <p className="mt-1 text-xs text-muted" data-testid="outline-export-note">
        {outline.state === "ready" && outline.layer === "routed" ? "Routed terrain flood" : "Terrain outline"} (WGS 84):{" "}
        {ol
          ? `${layerLabel(dam.outline, ROUTED_LABEL)}; ${num(ol.properties.outline_area_ac, 1)} ac, depth bands, with the PLSS and 911 lists against it. ${terrainInfo(dam.outline?.source).short}.`
          : outline.message}
      </p>
      <p className="mt-1 text-xs text-muted">
        PLSS sections:{" "}
        {plssTable
          ? `${plssTable.rows.length} touched${ol ? ` by the terrain outline (in its GeoJSON/KML and the CSV)${stripPlssTable ? `; ${stripPlssTable.rows.length} by the strip (in the strip files)` : ""}` : ", listed in the strip GeoJSON/KML and the CSV"}. ${PLSS_ATTRIBUTION}`
          : plss.message}
      </p>
      <p className="mt-1 text-xs text-muted" data-testid="nd911-export-note">
        911 address points:{" "}
        {nd911Table
          ? `${nd911Table.rows.length} inside the ${nd911Table.against}${ol ? ` (in its GeoJSON/KML and the CSV)${stripNd911Table ? `; ${stripNd911Table.rows.length} inside the flood strip (in the strip files)` : ""}` : ", as points in the strip GeoJSON/KML and in the CSV"}. ${ND911_ATTRIBUTION}`
          : nd911.message}
      </p>
      {saved ? (
        <p className="mt-2 text-xs text-muted" role="status">
          {saved}
        </p>
      ) : null}
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <OptNumField
          label="LISFLOOD cell size (m)"
          value={dam.lisflood?.cellSizeM}
          placeholder="10"
          onChange={(cellSizeM) => update({ lisflood: { ...dam.lisflood, cellSizeM } })}
        />
        <OptNumField
          label="Point X (DEM CRS, m)"
          value={dam.lisflood?.pointX}
          placeholder={`breach point in ${utmLabel}`}
          onChange={(pointX) => update({ lisflood: { ...dam.lisflood, pointX } })}
        />
        <OptNumField
          label="Point Y (DEM CRS, m)"
          value={dam.lisflood?.pointY}
          placeholder={`breach point in ${utmLabel}`}
          onChange={(pointY) => update({ lisflood: { ...dam.lisflood, pointY } })}
        />
      </div>
      <p className="mt-1 text-xs text-muted">
        Default grid: NAD83 / {utmLabel} at 10 m, point at the drawn breach point (else the record lat/lon). Leave blank for the
        default; enter both X and Y for another DEM (e.g. the Runner&apos;s EPSG:5070 30 m grid).
      </p>
      <p className="mt-2 text-xs whitespace-pre-line text-muted">{lisflood.pkg ? lisflood.pkg.notes : lisflood.error}</p>
    </div>
  );
}

function ReceptorTable({ result }: { result: ReturnType<typeof analyze> }) {
  const rows = [...result.flood.receptors].sort((a, b) => b.depthFt - a.depthFt);
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-card">
      <table className="w-full text-left text-sm">
        <thead className="text-xs tracking-wide text-muted uppercase">
          <tr>
            <th className="px-3 py-2 font-medium">Feature</th>
            <th className="px-3 py-2 font-medium">Kind</th>
            <th className="px-3 py-2 font-medium">km</th>
            <th className="px-3 py-2 font-medium">Depth ft</th>
            <th className="px-3 py-2 font-medium">Vel ft/s (est.)</th>
            <th className="px-3 py-2 font-medium">Arrival h</th>
            <th className="px-3 py-2 font-medium">D × V</th>
            <th className="px-3 py-2 font-medium">TM 11 zone</th>
            <th className="px-3 py-2 font-medium">ND class</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-line">
              <td className="px-3 py-2">{r.name}</td>
              <td className="px-3 py-2 capitalize">{r.kind}</td>
              <td className="px-3 py-2 tabular-nums">{num(r.distanceKm, 1)}</td>
              <td className="px-3 py-2 tabular-nums">{r.unresolved ? "unresolved" : r.flooded ? num(r.depthFt, 2) : "dry"}</td>
              <td className="px-3 py-2 tabular-nums">{r.flooded ? num(r.velocityFps, 2) : "—"}</td>
              <td className="px-3 py-2 tabular-nums">{r.arrivalHr == null ? "—" : num(r.arrivalHr, 2)}</td>
              <td className="px-3 py-2 tabular-nums">
                {r.flooded ? num(r.depthFt * r.velocityFps, 1) : "—"}
              </td>
              <td className="px-3 py-2">{r.flooded && r.zone ? r.zone : "—"}</td>
              <td className="px-3 py-2" title={r.rankReason}>
                {r.ndClass ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-xs text-muted">D × V is depth times velocity. It is not a pass or fail. Velocities are desk estimates. Unresolved receptors are past the desk reach and are not screened.</p>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="bg-card px-3 py-3">
      <p className="text-xs tracking-wide text-muted uppercase">{k}</p>
      <p className="text-lg tabular-nums">{v}</p>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted">{k}</dt>
      <dd className="tabular-nums">{v}</dd>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  tag,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  tag?: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 h-11 w-full rounded-sm border border-line bg-paper px-3 text-ink"
      />
      {tag}
    </label>
  );
}

/**
 * A number input with the desk's own limits on it. `min`/`max` (and `inputMode="decimal"`, the numeric keypad on a
 * phone) come from the caller; `warning` is the field's own out-of-range or clamp text, shown under the box in amber
 * (the engine still clamps, engine.ts bounded(); this just says so where the value is typed). The box itself is
 * marked invalid (aria-invalid) while the warning stands.
 */
function NumField({
  label,
  value,
  onChange,
  suffix,
  step = 1,
  min,
  max,
  warning,
  tag,
  fix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  suffix?: string;
  step?: number;
  min?: number;
  max?: number;
  warning?: string | null;
  tag?: ReactNode;
  /** The rail checklist's Fix… target (data-fix). */
  fix?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="text-muted">
        {label}
        {suffix ? ` (${suffix})` : ""}
      </span>
      <input
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        aria-invalid={warning ? true : undefined}
        data-fix={fix}
        // A missing value (NaN) shows blank, never 0; clearing the box makes it missing again.
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => onChange(e.target.value === "" ? Number.NaN : Number(e.target.value))}
        className={"mt-1 h-11 w-full rounded-sm border bg-paper px-3 tabular-nums text-ink " + (warning ? "border-amber" : "border-line")}
      />
      {warning ? (
        <span className="mt-1 block text-xs text-amber" role="status">
          {warning}
        </span>
      ) : null}
      {tag}
    </label>
  );
}

/** The field's own out-of-range text (W-V1), only once a value is typed: a blank field is "missing", said elsewhere. */
function inputRange(field: keyof typeof INPUT_RANGE, v: number): { min: number; max: number; warning: string | null } {
  const r = INPUT_RANGE[field];
  return { min: r.lo, max: r.hi, warning: Number.isFinite(v) ? inputRangeWarning(field, v) : null };
}

/** A latitude or longitude out of its range, or the pair swapped (guided.ts locationProblem), under both fields. */
function latLonWarning(dam: DamRecord, which: "lat" | "lon"): string | null {
  const v = which === "lat" ? dam.lat : dam.lon;
  if (v == null || !Number.isFinite(v)) return null;
  if (which === "lat" && Math.abs(v) > 90) return "Latitude must be between -90 and 90.";
  if (which === "lon" && Math.abs(v) > 180) return "Longitude must be between -180 and 180.";
  const p = locationProblem(dam);
  return p && /swapped/.test(p) ? p : null;
}

/** A number input that may be left blank (undefined = use the default). */
function OptNumField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: number | undefined;
  placeholder?: string;
  onChange: (v: number | undefined) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <input
        type="number"
        value={value != null && Number.isFinite(value) ? value : ""}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        className="mt-1 h-11 w-full rounded-sm border border-line bg-paper px-3 tabular-nums text-ink"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
  fix,
}: {
  label: string;
  value: string;
  options: (string | [string, string])[];
  onChange: (v: string) => void;
  fix?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <select
        value={value}
        data-fix={fix}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 h-11 w-full rounded-sm border border-line bg-paper px-3 text-ink"
      >
        {options.map((opt) => {
          const [id, text] = Array.isArray(opt) ? opt : [opt, opt];
          return (
            <option key={id} value={id}>
              {text}
            </option>
          );
        })}
      </select>
    </label>
  );
}
