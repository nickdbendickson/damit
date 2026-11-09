// @ts-check
/**
 * Regenerate src/lib/crest/data/jurisdictions.json, the desk's display index of the DamIT methods catalog
 * (US Dam Hazard Classification — Corrected Edition, Nov 9, 2026, Appendix A), from damit_hazard's catalog.json.
 *
 * The index carries ids, plain names, groups, preset bundles, label maps and verification status only. No threshold
 * or parameter is copied: those stay in the hazard catalog data file that damit:classify reads, so a rule change is a
 * data-file edit in one place (Appendix A.7).
 *
 *   node scripts/sync-jurisdictions.mjs [path/to/catalog.json]
 *
 * Default path: ../damit_hazard/data/catalog.json (the damit repo checkout). `--check` exits 1 when the committed index
 * differs from what the catalog would give (for CI once damit_hazard is on main).
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
export const INDEX = join(ROOT, "src/lib/crest/data/jurisdictions.json");
export const DEFAULT_CATALOG = resolve(ROOT, "../damit_hazard/data/catalog.json");

/** @param {Record<string, any>} section @param {string[]} keep */
function pick(section, keep) {
  /** @type {Record<string, any>} */
  const out = {};
  for (const [id, rec] of Object.entries(section || {})) {
    /** @type {Record<string, any>} */
    const row = {};
    for (const k of keep) if (rec && rec[k] !== undefined) row[k] = rec[k];
    out[id] = row;
  }
  return out;
}

/** @param {any} catalog */
export function buildIndex(catalog) {
  /** @type {Record<string, any>} */
  const presets = {};
  for (const [id, p] of Object.entries(catalog.presets || {})) {
    presets[id] = {
      label: p.label,
      scenarios: [...(p.scenarios || [])],
      methods: Object.keys(p.methods || {}),
      advisoryMethods: Object.entries(p.methods || {})
        .filter(([, v]) => v && v.strength === "advisory")
        .map(([k]) => k),
      modifiers: Object.keys(p.modifiers || {}),
      labels: { ...(p.labels || {}) },
      verification: p.verification || "unverified",
    };
  }
  return {
    generatedFrom: "damit_hazard/data/catalog.json",
    note: "Display index only (ids, names, label maps). Thresholds and parameters live in the hazard catalog that damit:classify reads; regenerate with `node scripts/sync-jurisdictions.mjs`.",
    catalogVersion: String(catalog.catalog_version ?? ""),
    sourceDocument: String(catalog.source_document ?? ""),
    disclaimer: String(catalog.disclaimer ?? ""),
    classes: { ...(catalog.classes || {}) },
    scenarios: pick(catalog.scenarios, ["name", "verification"]),
    domains: pick(catalog.domains, ["name", "verification"]),
    methods: pick(catalog.methods, ["name", "group", "verification"]),
    modifiers: pick(catalog.modifiers, ["name", "verification"]),
    presets,
  };
}

/** @param {string[]} argv */
function main(argv) {
  const check = argv.includes("--check");
  const path = resolve(argv.find((a) => !a.startsWith("--")) || DEFAULT_CATALOG);
  if (!existsSync(path)) {
    console.error(`No catalog at ${path}. Pass the path to damit_hazard/data/catalog.json.`);
    process.exit(2);
  }
  const text = JSON.stringify(buildIndex(JSON.parse(readFileSync(path, "utf8"))), null, 2) + "\n";
  if (check) {
    const now = existsSync(INDEX) ? readFileSync(INDEX, "utf8") : "";
    if (now !== text) {
      console.error(`${relative(ROOT, INDEX)} is out of date with ${path}; run node scripts/sync-jurisdictions.mjs`);
      process.exit(1);
    }
    console.log("jurisdictions.json matches the catalog.");
    return;
  }
  writeFileSync(INDEX, text);
  console.log(`Wrote ${relative(ROOT, INDEX)} from ${path}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
