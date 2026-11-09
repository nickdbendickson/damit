/**
 * Jurisdiction context for the DamIT desk: preset mode vs custom mode (US Dam Hazard Classification — Corrected
 * Edition, Nov 9, 2026, Appendix A).
 *
 * - Preset mode: the user picks a state or agency preset; the hazard plugin (damit:classify) loads that preset's
 *   scenarios, method ids, parameters and class labels from its catalog data file.
 * - Custom mode: the user ticks method ids with no state or agency names shown; results use generic labels.
 *
 * This module only reads the display index data/jurisdictions.json (ids, names, label maps; generated from the
 * damit_hazard catalog by scripts/sync-jurisdictions.mjs). No threshold lives here or in any other desk code: the
 * classification itself is damit:classify's, and its thresholds live in its data file (Appendix A.7).
 *
 * The desk's own built-in screen (engine.ts) is the Crest screen it was adapted from, a North Dakota REG_05-style
 * rule set returning Low / Medium / High. It is shown here as a generic ordinal so it can be read against the chosen
 * preset's labels; it is never presented as that preset's class.
 */
import index from "./data/jurisdictions.json" with { type: "json" };
import type { ClassificationChoice, ScreenLevel } from "./types.ts";

export type { ClassificationChoice, ClassificationMode } from "./types.ts";

export type CatalogEntry = { name?: string; group?: string; verification?: string };
export type PresetEntry = {
  label: string;
  scenarios: string[];
  methods: string[];
  advisoryMethods: string[];
  modifiers: string[];
  labels: Record<string, string>;
  verification: string;
};

type Index = {
  catalogVersion: string;
  sourceDocument: string;
  disclaimer: string;
  classes: Record<string, string>;
  scenarios: Record<string, CatalogEntry>;
  domains: Record<string, CatalogEntry>;
  methods: Record<string, CatalogEntry>;
  modifiers: Record<string, CatalogEntry>;
  presets: Record<string, PresetEntry>;
};

export const CATALOG = index as unknown as Index;

/**
 * Default posture is multi-jurisdiction: the FEMA 333 national baseline preset, not any one state. Nothing about the
 * dam's location picks a preset for the user.
 */
export const DEFAULT_PRESET = "FEMA333";
export const DEFAULT_CLASSIFICATION: ClassificationChoice = { mode: "preset", preset: DEFAULT_PRESET };

/** Generic labels by ordinal (0 Minimal … 4 Extremely High). */
export function genericLabel(ordinal: number): string {
  return CATALOG.classes[String(ordinal)] ?? "Unclassified";
}

export function presetIds(): string[] {
  return Object.keys(CATALOG.presets);
}

export function preset(id: string | undefined): PresetEntry | undefined {
  return id ? CATALOG.presets[id] : undefined;
}

const ID_RE = /^[SDMR]\d{1,2}[a-z]?$/;

/** Every id custom mode can tick, by section, with its plain name only (no state or agency names). */
export function customOptions(): { section: "scenarios" | "domains" | "methods" | "modifiers"; id: string; name: string; group?: string }[] {
  const out: { section: "scenarios" | "domains" | "methods" | "modifiers"; id: string; name: string; group?: string }[] = [];
  for (const section of ["scenarios", "domains", "methods", "modifiers"] as const) {
    for (const [id, e] of Object.entries(CATALOG[section])) out.push({ section, id, name: e.name ?? id, group: e.group });
  }
  return out;
}

/** The record's choice made valid: unknown presets and ids dropped, a missing choice = DEFAULT_CLASSIFICATION. */
export function resolveChoice(choice: ClassificationChoice | undefined | null): ClassificationChoice {
  if (!choice || typeof choice !== "object") return { ...DEFAULT_CLASSIFICATION, catalogVersion: CATALOG.catalogVersion };
  if (choice.mode === "custom") {
    const known = new Set(customOptions().map((o) => o.id));
    const methods = [...new Set((choice.methods ?? []).filter((m) => typeof m === "string" && ID_RE.test(m) && known.has(m)))];
    return { mode: "custom", methods, advisory: choice.advisory === true, catalogVersion: CATALOG.catalogVersion };
  }
  const id = choice.preset && CATALOG.presets[choice.preset] ? choice.preset : DEFAULT_PRESET;
  return { mode: "preset", preset: id, advisory: choice.advisory === true, catalogVersion: CATALOG.catalogVersion };
}

/** The ids a choice enables: the preset's bundle, or the ticked ids. */
export function enabledIds(choice: ClassificationChoice): string[] {
  const c = resolveChoice(choice);
  if (c.mode === "custom") return c.methods ?? [];
  const p = CATALOG.presets[c.preset ?? DEFAULT_PRESET];
  return [...p.scenarios, ...p.methods, ...p.modifiers];
}

/** The label a choice shows for an ordinal: the preset's local label, or the generic one in custom mode. */
export function classLabel(choice: ClassificationChoice, ordinal: number): string {
  const c = resolveChoice(choice);
  if (c.mode === "preset") {
    const local = CATALOG.presets[c.preset ?? DEFAULT_PRESET]?.labels[String(ordinal)];
    if (local) return local;
  }
  return genericLabel(ordinal);
}

/** The desk screen's Low / Medium / High as a generic ordinal (Medium = Significant). Review has none. */
export function screenOrdinal(level: ScreenLevel): number | null {
  return level === "High" ? 3 : level === "Medium" ? 2 : level === "Low" ? 1 : null;
}

/** One line for the Report: the desk screen read against the chosen labels, never as the preset's class. */
export function screenAgainstChoice(level: ScreenLevel, choice: ClassificationChoice): string {
  const ord = screenOrdinal(level);
  if (ord == null) return "The desk screen is at Review, so it has no class to read against the chosen labels.";
  const c = resolveChoice(choice);
  const where = c.mode === "preset" ? `${CATALOG.presets[c.preset ?? DEFAULT_PRESET].label} labels` : "generic labels";
  return (
    `The desk screen's ${level} is ordinal ${ord} (${genericLabel(ord)}); in ${where} that reads "${classLabel(c, ord)}". ` +
    "The desk screen uses the Crest rule set it was adapted from, not this preset's methods: the suggested class for this choice comes from damit:classify."
  );
}

/** The block the desktop hand-off sends (dam.classification), already resolved. */
export function handoffChoice(choice: ClassificationChoice | undefined | null): ClassificationChoice {
  const c = resolveChoice(choice);
  const label = c.mode === "preset" ? CATALOG.presets[c.preset ?? DEFAULT_PRESET]?.label : undefined;
  return label ? { ...c, presetLabel: label } : c;
}
