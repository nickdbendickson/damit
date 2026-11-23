/**
 * Auto-fill for the Export & Hand-off form (Absaraka desk test 2026-11-21: the DEM, the imported run's rasters and the
 * rail lookup were all typed by hand although the desk knew them). The desk server finds the files (GET
 * /api/handoff/autofill, browser_io.autofill); this decides which field each one fills. Only blank fields are filled,
 * so nothing typed is ever replaced.
 */
import { classifyFile } from "./raster-meta.ts";

export type FillField = "dem" | "depth" | "velocity" | "arrival" | "wse" | "dv" | "railLookup";
export type Autofill = {
  dem: string | null;
  rasters: Record<string, string | null>;
  ambiguous?: string[];
  railLookup: string | null;
  railLookups?: string[];
};

const VAR_FIELD: Record<string, FillField> = { depth: "depth", velocity: "velocity", arrival: "arrival", wse: "wse", dv: "dv" };

/** Imported run file names -> the hand-off field each one fills (the lowest-rank file per variable, as Results does). */
export function rasterRoles(files: readonly string[]): Partial<Record<FillField, string>> {
  const best: Partial<Record<FillField, { name: string; rank: number }>> = {};
  for (const f of files) {
    const role = classifyFile(f);
    if (role.kind !== "grid") continue;
    const field = VAR_FIELD[role.variable];
    if (!field) continue;
    const prev = best[field];
    if (!prev || role.rank < prev.rank) best[field] = { name: f, rank: role.rank };
  }
  return Object.fromEntries(Object.entries(best).map(([k, v]) => [k, v!.name])) as Partial<Record<FillField, string>>;
}

const WHAT: Record<FillField, string> = {
  dem: "DEM (the desk's local DEM)",
  depth: "depth",
  velocity: "velocity",
  arrival: "arrival",
  wse: "water surface",
  dv: "depth × velocity",
  railLookup: "rail lookup",
};

/**
 * What to put in each blank field, and a one-line note of what was filled from where. `current` is the form now;
 * `files` the imported run's file names (DamRecord.resultsOfRecord.files) and `label` its source in words.
 */
export function fillPlan(
  current: Partial<Record<FillField, string>>,
  files: readonly string[],
  auto: Autofill,
  label = "the imported run",
): { set: Partial<Record<FillField, string>>; note: string | null; unresolved: string[] } {
  const set: Partial<Record<FillField, string>> = {};
  const blank = (k: FillField) => !(current[k] ?? "").trim();
  if (auto.dem && blank("dem")) set.dem = auto.dem;
  const unresolved: string[] = [];
  for (const [field, name] of Object.entries(rasterRoles(files)) as [FillField, string][]) {
    const base = name.split(/[\\/]/).pop() ?? name;
    const path = auto.rasters[base];
    if (path && blank(field)) set[field] = path;
    else if (!path && blank(field)) unresolved.push(base);
  }
  if (auto.railLookup && blank("railLookup")) set.railLookup = auto.railLookup;
  const keys = Object.keys(set) as FillField[];
  const run = keys.filter((k) => k !== "dem" && k !== "railLookup");
  const parts = [
    set.dem ? WHAT.dem : "",
    run.length ? `${run.map((k) => WHAT[k]).join(", ")} from ${label}` : "",
    set.railLookup ? `rail lookup (${set.railLookup.split(/[\\/]/).pop()})` : "",
  ].filter(Boolean);
  return { set, note: parts.length ? `Filled from the desk: ${parts.join("; ")}. Edit any field to change it.` : null, unresolved };
}
