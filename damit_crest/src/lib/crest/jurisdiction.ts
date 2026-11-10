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
import { handoffIds } from "./nid-dams.ts";
import type { ClassificationChoice, DamRecord, ScreenLevel } from "./types.ts";

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
 * Default posture is multi-jurisdiction: the FEMA 333 national baseline preset, not any one state, for a record with
 * no state (no NID ID) or a state that has no preset of its own. A record whose NID ID names a state with a catalog
 * preset of that ID (ND -> "North Dakota (REG_05.2026)") starts on that preset instead (defaultPresetFor). The user's
 * explicit choice (DamRecord.classification) always wins.
 */
export const DEFAULT_PRESET = "FEMA333";
export const DEFAULT_CLASSIFICATION: ClassificationChoice = { mode: "preset", preset: DEFAULT_PRESET };

/**
 * The catalog preset whose ID is the state's postal code, else undefined. Same rule as DamIT Setup
 * (damit_core/lib/catalog_access.py preset_for_state): ND, NE, NY, VA, TX, ID, CO, RI, AZ, CA, AK have one; any
 * other state has none and keeps DEFAULT_PRESET. No other state-to-preset mapping is assumed.
 */
export function presetForState(state: string | undefined | null): string | undefined {
  const code = String(state ?? "").trim().toUpperCase();
  return /^[A-Z]{2}$/.test(code) && CATALOG.presets[code] ? code : undefined;
}

/**
 * The preset a record starts on when the user has not chosen one: its state's preset (the state is the first two
 * letters of its NID ID, the hand-off's own id rule), else FEMA 333. Nick, 2026-11-09: an ND dam (e.g. ND00199,
 * bundled North Dakota NID) starts on North Dakota REG_05.2026, not FEMA 333.
 */
export function defaultPresetFor(dam: Pick<DamRecord, "id"> & Partial<Pick<DamRecord, "nid" | "nidId" | "isNew">> | undefined | null): string {
  const nidId = dam ? handoffIds(dam).nidId : null;
  return presetForState(nidId?.slice(0, 2)) ?? DEFAULT_PRESET;
}

/** The record's jurisdiction choice, resolved: its own choice, else its state's default preset (defaultPresetFor). */
export function damChoice(dam: DamRecord): ClassificationChoice {
  return resolveChoice(dam.classification, defaultPresetFor(dam));
}

/**
 * The classification a new dam should start with: its state's preset in preset mode, already resolved. Use this when
 * building the record so the choice is explicit (written to dam.json) rather than resolved at display time.
 */
export function classificationForState(stateCode: string | undefined | null): ClassificationChoice {
  const pid = presetForState(stateCode) ?? DEFAULT_PRESET;
  return resolveChoice({ mode: "preset", preset: pid }, pid);
}

/**
 * One-line explanation of why this preset was chosen — for the UI to show beside the preset selector so the engineer
 * knows the reasoning. Returns null when the user made an explicit choice (nothing to explain).
 */
export function presetExplanation(dam: DamRecord): string | null {
  // If the user has explicitly chosen a classification, don't override their understanding.
  if (dam.classification && (dam.classification.preset || dam.classification.mode === "custom")) return null;
  const nidId = handoffIds(dam).nidId;
  if (!nidId) return "No NID ID — using FEMA 333 national baseline. Switch to custom mode for agency-specific rules.";
  const stateCode = nidId.slice(0, 2);
  const statePreset = presetForState(stateCode);
  if (statePreset) {
    const label = CATALOG.presets[statePreset]?.label ?? statePreset;
    return `Auto-selected: ${label} (from NID ID ${nidId}).`;
  }
  return `${stateCode} has no specific preset in the catalog — using FEMA 333 national baseline. Switch to custom mode for state-specific adjustments.`;
}

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

/**
 * The record's choice made valid: unknown presets and ids dropped, a missing choice (or preset) = `fallback`
 * (DEFAULT_PRESET unless the caller passes the record's defaultPresetFor).
 */
export function resolveChoice(choice: ClassificationChoice | undefined | null, fallback: string = DEFAULT_PRESET): ClassificationChoice {
  const dflt = CATALOG.presets[fallback] ? fallback : DEFAULT_PRESET;
  if (!choice || typeof choice !== "object") return { mode: "preset", preset: dflt, catalogVersion: CATALOG.catalogVersion };
  if (choice.mode === "custom") {
    const known = new Set(customOptions().map((o) => o.id));
    const methods = [...new Set((choice.methods ?? []).filter((m) => typeof m === "string" && ID_RE.test(m) && known.has(m)))];
    return { mode: "custom", methods, advisory: choice.advisory === true, catalogVersion: CATALOG.catalogVersion };
  }
  const id = choice.preset && CATALOG.presets[choice.preset] ? choice.preset : dflt;
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

/**
 * One line for the Report about the desk screen. It is a schematic preview on the ND / ACER TM 11 rules Crest was
 * adapted from, so it is never translated into the chosen preset's labels or offered as that preset's (or the custom
 * methods') determination: that class comes from damit:classify on the downstream receptors.
 */
export function screenAgainstChoice(level: ScreenLevel, choice: ClassificationChoice): string {
  const c = resolveChoice(choice);
  const chosen = c.mode === "preset" ? CATALOG.presets[c.preset ?? DEFAULT_PRESET].label : "the custom methods";
  const preview = level === "Review" ? "is at Review" : `reads ${level}`;
  return (
    `Schematic preview only: the desk screen ${preview} on the ND / ACER TM 11 desk rules, not on ${chosen}. ` +
    `It is not the DamIT classification. The class for ${chosen} is the one damit:classify returns for the downstream receptors (Classify below).`
  );
}

/** The block the desktop hand-off sends (dam.classification), already resolved (missing = `fallback`). */
export function handoffChoice(choice: ClassificationChoice | undefined | null, fallback: string = DEFAULT_PRESET): ClassificationChoice {
  const c = resolveChoice(choice, fallback);
  const label = c.mode === "preset" ? CATALOG.presets[c.preset ?? DEFAULT_PRESET]?.label : undefined;
  return label ? { ...c, presetLabel: label } : c;
}
