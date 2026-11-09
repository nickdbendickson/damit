// @ts-check
/**
 * Regenerate src/lib/crest/data/jurisdictions.json, the desk's display index of the DamIT methods catalog
 * (US Dam Hazard Classification — Corrected Edition, Nov 9, 2026, Appendix A), from DamIT Catalog as DamIT Hazard
 * reads it (`python3 -m damit_hazard.engine.catalog --export`).
 *
 * The index carries ids, plain names, groups, preset bundles, label maps and verification status only. No threshold
 * or parameter is copied: those stay in the hazard catalog data file that damit:classify reads, so a rule change is a
 * data-file edit in one place (Appendix A.7).
 *
 *   node scripts/sync-jurisdictions.mjs [path/to/exported.json]
 *
 * With no path, the script runs `python3 -m damit_hazard.engine.catalog --export <tmp>` in the damit repo checkout
 * (DamIT Hazard's translation of damit_catalog/data/), so the index has the preset ids and labels damit:classify
 * lists. `--check` exits 1 when the committed index differs from what the catalog would give.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
export const INDEX = join(ROOT, "src/lib/crest/data/jurisdictions.json");
export const REPO = resolve(ROOT, "..");

/** DamIT Hazard's export of DamIT Catalog, written to a temp file. @returns {{ path: string, cleanup: () => void }} */
function exportCatalog() {
  const dir = mkdtempSync(join(tmpdir(), "damit-catalog-"));
  const path = join(dir, "catalog.json");
  execFileSync(process.env.PYTHON || "python3", ["-m", "damit_hazard.engine.catalog", "--export", path], {
    cwd: REPO,
    stdio: ["ignore", "ignore", "inherit"],
  });
  return { path, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

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
    generatedFrom: "damit_catalog/data (python3 -m damit_hazard.engine.catalog --export)",
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
  const given = argv.find((a) => !a.startsWith("--"));
  const exported = given ? null : exportCatalog();
  const path = given ? resolve(given) : /** @type {{ path: string }} */ (exported).path;
  if (!existsSync(path)) {
    console.error(`No catalog at ${path}. Pass a file from python3 -m damit_hazard.engine.catalog --export.`);
    process.exit(2);
  }
  const text = JSON.stringify(buildIndex(JSON.parse(readFileSync(path, "utf8"))), null, 2) + "\n";
  exported?.cleanup();
  if (check) {
    const now = existsSync(INDEX) ? readFileSync(INDEX, "utf8") : "";
    if (now !== text) {
      console.error(`${relative(ROOT, INDEX)} is out of date with DamIT Catalog; run node scripts/sync-jurisdictions.mjs`);
      process.exit(1);
    }
    console.log("jurisdictions.json matches the catalog.");
    return;
  }
  writeFileSync(INDEX, text);
  console.log(`Wrote ${relative(ROOT, INDEX)} from ${given ? path : "DamIT Catalog"}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
