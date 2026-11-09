import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import {
  CATALOG,
  classLabel,
  customOptions,
  damChoice,
  DEFAULT_CLASSIFICATION,
  defaultPresetFor,
  handoffChoice,
  presetForState,
  enabledIds,
  presetIds,
  resolveChoice,
  screenAgainstChoice,
  screenOrdinal,
} from "./jurisdiction.ts";
import { DEFAULT_ALGORITHMS, handoffDam, handoffFailureMode } from "./handoff.ts";
import { blankDam, SAMPLE_DAMS } from "./samples.ts";
import { exportDamJson } from "./export.ts";
import { analyze } from "./engine.ts";
import type { DamRecord } from "./types.ts";

describe("jurisdiction presets (Appendix A.6)", () => {
  it("lists the fifteen presets of the source document", () => {
    assert.deepEqual(presetIds().sort(), ["AK", "AZ", "BIA", "CA", "CO", "FEMA333", "ID", "NE", "ND", "NRCS", "NY", "RI", "TX", "USBR", "VA"].sort());
  });

  it("defaults to the FEMA 333 national baseline, not a state", () => {
    assert.deepEqual(DEFAULT_CLASSIFICATION, { mode: "preset", preset: "FEMA333" });
    const c = resolveChoice(undefined);
    assert.equal(c.mode, "preset");
    assert.equal(c.preset, "FEMA333");
    assert.equal(c.catalogVersion, CATALOG.catalogVersion);
  });

  it("maps ordinals to each preset's local labels (Medium in ND, Class B in NY, Extremely High only in CA)", () => {
    assert.equal(classLabel({ mode: "preset", preset: "ND" }, 2), "Medium");
    assert.equal(classLabel({ mode: "preset", preset: "NY" }, 3), "Class C");
    assert.equal(classLabel({ mode: "preset", preset: "AK" }, 3), "Class I");
    assert.equal(classLabel({ mode: "preset", preset: "CA" }, 4), "Extremely High");
    assert.equal(classLabel({ mode: "preset", preset: "NE" }, 0), "Minimal");
    // Custom mode uses generic labels.
    assert.equal(classLabel({ mode: "custom", methods: ["M2"] }, 2), "Significant");
  });

  it("carries the ND preset bundle (S3, S7; M1, M2, M6 advisory, M8a, M8b, M9a, M11a)", () => {
    const nd = CATALOG.presets.ND;
    assert.deepEqual(nd.scenarios, ["S3", "S7"]);
    assert.deepEqual(nd.methods, ["M1", "M2", "M6", "M8a", "M8b", "M9a", "M11a"]);
    assert.deepEqual(nd.advisoryMethods, ["M6"]);
  });

  it("drops an unknown preset back to the default and unknown ids from custom mode", () => {
    assert.equal(resolveChoice({ mode: "preset", preset: "XX" }).preset, "FEMA333");
    assert.deepEqual(resolveChoice({ mode: "custom", methods: ["M2", "M99", "nddam:preflight", "M2", "R7"] }).methods, ["M2", "R7"]);
  });

  it("enables the preset's ids, or exactly the ticked ids", () => {
    assert.deepEqual(enabledIds({ mode: "preset", preset: "TX" }), ["M4c", "R5"]);
    assert.deepEqual(enabledIds({ mode: "custom", methods: ["S1", "M13"] }), ["S1", "M13"]);
  });

  it("custom mode shows method names only, no state or agency names", () => {
    const names = customOptions().map((o) => o.name).join(" ");
    for (const label of ["North Dakota", "Nebraska", "New York", "Virginia", "FEMA", "USBR", "California"]) {
      assert.ok(!names.includes(label), `custom option names mention ${label}`);
    }
  });

  it("holds no thresholds: the index has no params (they live in the hazard catalog)", () => {
    const text = JSON.stringify(CATALOG);
    assert.doesNotMatch(text, /"params"|threshold_ft|high_min|aadt/i);
  });

  it("labels the desk screen a schematic preview, never the chosen preset's or custom methods' class", () => {
    assert.equal(screenOrdinal("Medium"), 2);
    assert.equal(screenOrdinal("Review"), null);
    const line = screenAgainstChoice("Medium", { mode: "preset", preset: "NY" });
    assert.match(line, /^Schematic preview only/);
    assert.match(line, /ND \/ ACER TM 11 desk rules, not on New York/);
    assert.match(line, /not the DamIT classification/);
    assert.match(line, /damit:classify/);
    // Not translated into the preset's labels (that would read as New York's determination).
    assert.doesNotMatch(line, /Class B|ordinal|Significant/);
    const custom = screenAgainstChoice("High", { mode: "custom", methods: ["M1"] });
    assert.match(custom, /not on the custom methods/);
    assert.match(screenAgainstChoice("Review", { mode: "preset", preset: "FEMA333" }), /is at Review/);
  });

  it("matches DamIT Catalog when it is in this checkout", () => {
    const url = new URL("../../../../damit_catalog/data/presets.json", import.meta.url);
    if (!existsSync(url)) return; // full check: scripts/sync-jurisdictions.mjs --check
    const cat = JSON.parse(readFileSync(url, "utf8"));
    assert.deepEqual(Object.keys(cat.presets).sort(), presetIds().sort());
    const methods = JSON.parse(readFileSync(new URL("methods.json", url), "utf8"));
    assert.deepEqual(Object.keys(methods.methods).sort(), Object.keys(CATALOG.methods).sort());
  });
});

describe("hand-off to the DamIT plugins", () => {
  it("defaults to the DamIT algorithm ids, never the ND suite's", () => {
    assert.deepEqual(DEFAULT_ALGORITHMS, {
      classify: "damit:classify",
      preflight: "damit_screen:preflight",
      runchain: "damit_screen:runchain",
      rundam: "damit_run:rundam",
      batch: "damit_run:batch",
    });
    for (const id of Object.values(DEFAULT_ALGORITHMS)) assert.doesNotMatch(id, /^(nddam|ndbreach|nd_)/);
  });

  it("sends piping when no failure mode was chosen (or an unknown one)", () => {
    assert.equal(handoffFailureMode(undefined), "piping");
    assert.equal(handoffFailureMode(""), "piping");
    assert.equal(handoffFailureMode("sideways"), "piping");
    assert.equal(handoffFailureMode("overtopping"), "overtopping");
    const { failureMode: _drop, ...rest } = blankDam();
    assert.equal(handoffDam(rest as DamRecord).failureMode, "piping");
    assert.equal(blankDam().failureMode, "piping");
  });

  it("keeps a chosen overtopping and adds the resolved classification", () => {
    const d = { ...blankDam(), failureMode: "overtopping" as const, classification: { mode: "preset" as const, preset: "NE" } };
    const out = handoffDam(d);
    assert.equal(out.failureMode, "overtopping");
    assert.deepEqual({ mode: out.classification?.mode, preset: out.classification?.preset }, { mode: "preset", preset: "NE" });
    // The catalog label goes along so the server can pick damit:classify's PRESET enum option by its text.
    assert.equal(out.classification?.presetLabel, CATALOG.presets.NE.label);
  });

  it("dam.json export carries piping and the classification block", () => {
    const nd = SAMPLE_DAMS.find((x) => x.nid === "ND00199")!;
    const { failureMode: _f, ...noMode } = nd;
    const j = JSON.parse(exportDamJson(noMode as DamRecord, analyze(nd)));
    assert.equal(j.failure_mode, "piping");
    assert.equal(j.classification.mode, "preset");
    // No choice on the record: an ND dam goes out on its state's preset (Nick, 2026-11-09), a blank one on FEMA 333.
    assert.equal(j.classification.preset, "ND");
    const blank = blankDam();
    assert.equal(JSON.parse(exportDamJson(blank, analyze(blank))).classification.preset, "FEMA333");
  });

  it("is_new is false unless the New dam box is ticked, and never inferred from a missing class of record", () => {
    for (const d of SAMPLE_DAMS) assert.notEqual(d.isNew, true, `${d.nid} is a sample of an existing dam`);
    const blank = blankDam();
    assert.equal(blank.isNew, undefined);
    assert.equal(blank.classOfRecord, undefined);
    assert.equal(JSON.parse(exportDamJson(blank, analyze(blank))).is_new, false);
    const nd = SAMPLE_DAMS.find((x) => x.nid === "ND00199")!;
    assert.equal(JSON.parse(exportDamJson(nd, analyze(nd))).is_new, false);
    assert.equal(JSON.parse(exportDamJson({ ...nd, isNew: true }, analyze(nd))).is_new, true);
    assert.equal(handoffDam({ ...nd, isNew: true }).isNew, true);
  });
});

describe("default preset from the record's state (GUI chain walk, ND00199, 2026-11-09)", () => {
  const nd = SAMPLE_DAMS.find((x) => x.nid === "ND00199")!;

  it("an ND dam with no choice starts on North Dakota (REG_05.2026), not FEMA 333", () => {
    const rec: DamRecord = { ...blankDam(), nid: "ND00199", nidId: "ND00199", classification: undefined };
    assert.equal(defaultPresetFor(rec), "ND");
    const c = damChoice(rec);
    assert.equal(c.mode, "preset");
    assert.equal(c.preset, "ND");
    assert.equal(CATALOG.presets[c.preset!].label, "North Dakota (REG_05.2026)");
    assert.equal(handoffDam(rec).classification?.preset, "ND");
    assert.equal(handoffDam(rec).classification?.presetLabel, "North Dakota (REG_05.2026)");
    assert.equal(damChoice({ ...nd, classification: undefined }).preset, "ND");
  });

  it("the user's explicit choice wins over the state default", () => {
    const rec: DamRecord = { ...nd, classification: { mode: "preset", preset: "FEMA333" } };
    assert.equal(damChoice(rec).preset, "FEMA333");
    assert.equal(handoffDam(rec).classification?.preset, "FEMA333");
    assert.equal(damChoice({ ...nd, classification: { mode: "custom", methods: ["M2"] } }).mode, "custom");
    // An unknown preset id falls back to the state's preset, not to FEMA 333.
    assert.equal(damChoice({ ...nd, classification: { mode: "preset", preset: "XX" } }).preset, "ND");
  });

  it("no NID ID, or a state with no preset of its own, keeps FEMA 333; DamIT Setup's postal-code rule otherwise", () => {
    assert.equal(defaultPresetFor(blankDam()), "FEMA333");
    assert.equal(damChoice(blankDam()).preset, "FEMA333");
    assert.equal(defaultPresetFor({ id: "x", nid: "MN00123" }), "FEMA333");
    assert.equal(defaultPresetFor({ id: "x", nid: "NE01234" }), "NE");
    assert.equal(defaultPresetFor({ id: "x", nid: "DWR-2801" }), "FEMA333", "not an NID ID");
    assert.equal(presetForState("nd"), "ND");
    assert.equal(presetForState("MN"), undefined);
    assert.equal(presetForState("FEMA333"), undefined);
    assert.equal(presetForState(""), undefined);
    // resolveChoice / handoffChoice without a record keep the national baseline.
    assert.equal(resolveChoice(undefined).preset, "FEMA333");
    assert.equal(handoffChoice(undefined).preset, "FEMA333");
  });
});

