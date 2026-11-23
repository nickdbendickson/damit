/**
 * What the status bar shows about the DamIT plugins (DamIT Desk UI, 2026-11-21): whether a plugin job is running, how
 * the last one ended, and the last "Check QGIS hand-off" result. The Report step's plugin panel writes it; nothing here
 * starts QGIS by itself. Also a small hand-off so the command palette can ask that panel to start a job once it is
 * on screen (the panel holds the work folder, DEM and raster fields the job needs).
 */
import { create } from "zustand";

export type CheckRow = { role: string; algorithm: string; found: boolean };

export type JobStatus = {
  busy: boolean;
  /** The running (or last) job, in words: "Check QGIS hand-off", "Run the flood model", … */
  label: string | null;
  last: { label: string; ok: boolean; cancelled: boolean; partial: boolean; at: string } | null;
  check: { ok: boolean; found: number; total: number; missing: string[]; at: string } | null;
  /** No desk server answered (a page opened without bin/damit-desk). */
  noServer: boolean;
};

export const useJobStatus = create<JobStatus>(() => ({ busy: false, label: null, last: null, check: null, noServer: false }));

export const JOB_LABEL: Record<string, string> = {
  "/api/check": "Check QGIS hand-off",
  "/api/layers": "Get layers",
  "/api/folder": "Write the dam folder",
  "/api/screen": "Write folder and run screening",
  "/api/model": "Run the flood model",
  "/api/classify": "Classify",
  "/api/data": "Download layers",
  "/api/pmp": "Atlas 14 point",
  "/api/finder": "Find fills",
};

export function jobStarted(path: string): void {
  useJobStatus.setState({ busy: true, label: JOB_LABEL[path] ?? path, noServer: false });
}

/** A finished job, from the server's job record (GET /api/job). */
export function jobFinished(
  path: string,
  found: { ok?: boolean; cancelled?: boolean; partial?: boolean; check?: CheckRow[] } | null,
  now = new Date(),
): void {
  const label = JOB_LABEL[path] ?? path;
  const at = now.toISOString();
  const patch: Partial<JobStatus> = {
    busy: false,
    label,
    last: { label, ok: Boolean(found?.ok), cancelled: Boolean(found?.cancelled), partial: Boolean(found?.partial), at },
  };
  if (path === "/api/check" && found && !found.cancelled) patch.check = checkSummary(found.check ?? [], Boolean(found.ok), at);
  useJobStatus.setState(patch);
}

export function jobNoServer(): void {
  useJobStatus.setState({ busy: false, noServer: true });
}

export function checkSummary(rows: CheckRow[], ok: boolean, at: string): NonNullable<JobStatus["check"]> {
  return { ok: ok && rows.length > 0 && rows.every((r) => r.found), found: rows.filter((r) => r.found).length, total: rows.length, missing: rows.filter((r) => !r.found).map((r) => r.algorithm), at };
}

/** The status bar's engine line. */
export function engineText(s: Pick<JobStatus, "check" | "noServer">, server: boolean): { text: string; tone: "ok" | "warn" | "muted" } {
  if (!server || s.noServer) return { text: "QGIS: no desk server (start bin/damit-desk)", tone: "warn" };
  if (!s.check) return { text: "QGIS hand-off: not checked yet", tone: "muted" };
  if (s.check.ok) return { text: `QGIS hand-off ✓ ${s.check.found}/${s.check.total} algorithms`, tone: "ok" };
  if (s.check.total === 0) return { text: "QGIS hand-off: qgis_process not found", tone: "warn" };
  return { text: `QGIS hand-off: ${s.check.missing.length} missing (${s.check.missing.join(", ")})`, tone: "warn" };
}

/** The status bar's run line. */
export function runText(s: Pick<JobStatus, "busy" | "label" | "last">): string {
  if (s.busy) return `Running: ${s.label ?? "a plugin job"}…`;
  if (!s.last) return "Idle";
  const end = s.last.cancelled ? "cancelled" : s.last.partial ? "partial result" : s.last.ok ? "done" : "stopped";
  return `Idle · last: ${s.last.label} ${end}`;
}

type Starter = (path: string) => void;
let starter: Starter | null = null;
let pending: string | null = null;

/** The plugin panel registers how to start a job; a job asked for before it was on screen starts now. */
export function setJobStarter(f: Starter): () => void {
  starter = f;
  if (pending) {
    const p = pending;
    pending = null;
    f(p);
  }
  return () => {
    if (starter === f) starter = null;
  };
}

/** Start a plugin job through the panel (now, or once the panel mounts). */
export function requestJob(path: string): void {
  if (starter) starter(path);
  else pending = path;
}

/** For tests. */
export function resetJobStarter(): void {
  starter = null;
  pending = null;
}
