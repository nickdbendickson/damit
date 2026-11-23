// The Review summary band (review-summary.ts): the class badge's honest states, the tiles from the receptors sent,
// and the hit table from the stored structured hits.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { choiceKey, choiceText, classifyReceptors, receptorKey } from "./classify-receptors.ts";
import { analyze } from "./engine.ts";
import { damChoice } from "./jurisdiction.ts";
import { classBadge, hitRows, parseHits, sortHits, SUGGESTED_DISCLAIMER, summaryTiles } from "./review-summary.ts";
import { SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord, HazardResult } from "./types.ts";

const sample = (): DamRecord => structuredClone(SAMPLE_DAMS[0]);

function classified(d: DamRecord, extra: Partial<HazardResult> = {}): DamRecord {
  const a = analyze(d);
  d.hazardResult = {
    suggestedClass: "High",
    ordinal: "3",
    genericLabel: "High",
    report: null,
    gpkg: null,
    warnings: 0,
    layers: { STRUCTURES: 240, ROADS: 12, RAIL: 6 },
    impacted: { STRUCTURES: 228, ROADS: 11, RAIL: 6 },
    wetStructures: 228,
    complete: true,
    classifiedAt: "2026-11-21T15:00:00Z",
    choiceKey: choiceKey(damChoice(d)),
    receptorKey: receptorKey(classifyReceptors(d, a)),
    choiceText: choiceText(damChoice(d)),
    hits: [
      { method: "M8a", ordinal: 3, label: "High", strength: "rule", reason: "Depth 3.1 ft at a home", scenario: "sunny", receptors: ["structure:28"], receptorCount: 1 },
      { method: "M2", ordinal: 1, label: "Low", strength: "advisory", reason: "Road overtopped", scenario: "", receptors: ["road:240", "road:9"], receptorCount: 7 },
      { method: "M5", ordinal: 2, label: "Medium", strength: "rule", reason: "Rail line wet", scenario: "", receptors: ["rail:3"], receptorCount: 1 },
    ],
    hitsTotal: 245,
    ...extra,
  } as HazardResult;
  return d;
}

describe("class badge", () => {
  it("says Not classified with no result", () => {
    const d = sample();
    const b = classBadge(d, analyze(d));
    assert.equal(b.state, "none");
    assert.equal(b.text, "Not classified");
    assert.match(SUGGESTED_DISCLAIMER, /engineer of record/);
  });
  it("shows the class of a current result", () => {
    const d = classified(sample());
    const b = classBadge(d, analyze(d));
    assert.equal(b.state, "current");
    assert.equal(b.text, "High");
    assert.equal(b.ordinal, 3);
  });
  it("says Partial: at least … for an incomplete result", () => {
    const d = classified(sample(), { complete: false, notChecked: { RAIL: "offline" } });
    const b = classBadge(d, analyze(d));
    assert.equal(b.state, "partial");
    assert.equal(b.text, "Partial: at least High");
    assert.match(b.note, /rail not checked/);
  });
  it("does not show a stale class as the class", () => {
    const d = classified(sample(), { choiceKey: "other" });
    const b = classBadge(d, analyze(d));
    assert.equal(b.state, "stale");
    assert.equal(b.text, "Out of date");
    assert.equal(b.ordinal, null);
  });
});

describe("summary tiles", () => {
  it("counts the receptors the run was sent, and its hits", () => {
    const d = classified(sample());
    const t = summaryTiles(d, analyze(d));
    assert.deepEqual(t.map((x) => x.key), ["peak", "structures", "roads", "rail"]);
    assert.match(t[0].value, /cfs$/);
    assert.equal(t[1].value, "240");
    assert.match(t[1].note, /228 wet/);
    assert.equal(t[2].value, "12");
    assert.match(t[3].note, /6 with a hit/);
  });
  it("with no result, counts what Classify would send and says so", () => {
    const d = sample();
    const a = analyze(d);
    const t = summaryTiles(d, a);
    assert.equal(t[1].value, String(classifyReceptors(d, a).layers.STRUCTURES?.features.length ?? 0));
    assert.match(t[1].note, /not run yet/);
  });
});

describe("hit table", () => {
  it("builds rows from the structured hits with the receptor type from the id", () => {
    const h = hitRows(classified(sample()).hazardResult);
    assert.equal(h.source, "hits");
    assert.equal(h.total, 245);
    assert.equal(h.rows[0].type, "Structure");
    assert.equal(h.rows[1].type, "Road");
    assert.equal(h.rows[1].receptor, "road:240, road:9 +5 more");
    assert.equal(h.rows[0].criterion, "M8a (sunny)");
  });
  it("falls back to the driving hits of an older result", () => {
    const h = hitRows({ suggestedClass: "Low", driving: [{ method: "M2", label: "Low", reason: "r", receptors: 2 }] } as HazardResult);
    assert.equal(h.source, "driving");
    assert.equal(h.rows[0].receptor, "2 receptors");
    assert.equal(hitRows(null).source, "none");
  });
  it("sorts by class ordinal and by text, both ways", () => {
    const rows = hitRows(classified(sample()).hazardResult).rows;
    assert.deepEqual(sortHits(rows, "class", true).map((r) => r.label), ["High", "Medium", "Low"]);
    assert.deepEqual(sortHits(rows, "class", false).map((r) => r.label), ["Low", "Medium", "High"]);
    assert.deepEqual(sortHits(rows, "type", false).map((r) => r.type), ["Rail", "Road", "Structure"]);
    assert.deepEqual(sortHits(rows, "criterion", false).map((r) => r.criterion), ["M2", "M5", "M8a (sunny)"]);
  });
  it("validates hits from the server", () => {
    assert.equal(parseHits("x"), undefined);
    const p = parseHits([{ method: "M1", ordinal: 2, label: "Medium", receptors: ["road:1", 5], reason: "x".repeat(500) }, null]);
    assert.ok(p);
    assert.equal(p.length, 1);
    assert.deepEqual(p[0].receptors, ["road:1"]);
    assert.equal(p[0].reason.length, 200);
    assert.equal(p[0].receptorCount, 1);
  });
});
