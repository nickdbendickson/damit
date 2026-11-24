// The damit:classify receptor list for the Dashboard and Report (classify-list.ts). Absaraka desk test 2026-11-21.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { classColor, countsLine, filterClassify, needsRuling, parseClassifyList, parseRuling, rulingFlag, zoomBounds } from "./classify-list.ts";

const RAW = {
  receptors: [
    { rid: "rail:21", layer: "RAIL", kind: "rail", name: "BNSF KO Subdivision", ordinal: 3, label: "High", depthFt: 2.1, velFps: 1.2, methods: "rail_trains", flags: ["trains_lookup"], at: [-97.3, 46.9], bbox: [-97.31, 46.89, -97.29, 46.91] },
    { rid: "roads:4", layer: "ROADS", kind: "road", name: "I-94", ordinal: 3, label: "High", depthFt: 1.5, velFps: null, methods: "road_aadt", flags: [], at: [-97.2, 46.8], bbox: null },
    { rid: "structures:7", layer: "STRUCTURES", kind: "structure", name: "1203 Main St", ordinal: null, label: "", depthFt: 0.4, velFps: 0, methods: "", flags: [], at: [-97.1, 46.7], bbox: null },
    { rid: 12, layer: "STRUCTURES" },
    null,
    { rid: "structures:8", layer: "ODD", at: [1, "x"], bbox: [1, 2, 3] },
  ],
  total: 3,
  truncated: false,
  counts: { STRUCTURES: { total: 1670, wet: 252, hit: 0 }, ROADS: { total: 263, wet: 30, hit: 11 }, RAIL: { total: 34, wet: 9, hit: 6 } },
  gpkg: "/w/classify/damit_hazard_receptors.gpkg",
};

describe("classify receptor list", () => {
  it("keeps good rows and drops bad ones; a bad layer is a structure, a bad point is none", () => {
    const l = parseClassifyList(RAW)!;
    assert.deepEqual(l.receptors.map((r) => r.rid), ["rail:21", "roads:4", "structures:7", "structures:8"]);
    assert.equal(l.receptors[3].layer, "STRUCTURES");
    assert.equal(l.receptors[3].at, null);
    assert.equal(l.receptors[3].bbox, null);
    assert.equal(l.receptors[3].name, "structures:8", "no name: the id stands in");
    assert.equal("ruling" in l, false, "the server did not say: nothing to backfill");
    assert.equal(parseClassifyList({ ...RAW, ruling: null })!.ruling, null);
    assert.deepEqual(parseClassifyList({ ...RAW, ruling: { label: "High", hits: 6, unruled: 4, why: ["a", 2] } })!.ruling, { label: "High", hits: 6, unruled: 4, why: ["a", "2"] });
    assert.equal(parseRuling({ label: "High", hits: 6, unruled: 0 }), null);
    assert.equal(parseClassifyList({}), null);
    assert.equal(parseClassifyList("x"), null);
  });

  it("filters by layer chip, by 'needs ruling' and by a search over name, id, class and method", () => {
    const rs = parseClassifyList(RAW)!.receptors;
    assert.deepEqual(filterClassify(rs, "ROADS").map((r) => r.rid), ["roads:4"]);
    assert.deepEqual(filterClassify(rs, "ruling").map((r) => r.rid), ["rail:21"]);
    assert.deepEqual(filterClassify(rs, "all", " main ").map((r) => r.rid), ["structures:7"]);
    assert.deepEqual(filterClassify(rs, "all", "high").map((r) => r.rid), ["rail:21", "roads:4"]);
    assert.equal(needsRuling({ flags: ["trains_lookup"] }), true);
    assert.equal(needsRuling({ flags: ["nodata_wse_ground"] }), false);
  });

  it("says the counts in words", () => {
    assert.equal(countsLine(RAW.counts), "252 of 1,670 structures wet · 11 of 263 roads with a hit · 6 of 34 rail lines with a hit");
    assert.equal(countsLine({}), "");
  });

  it("colours by class and zooms to at least ~150 m around a receptor", () => {
    assert.equal(classColor(4), "#B91C1C");
    assert.equal(classColor(2), "#B45309");
    assert.equal(classColor(null), "#0E768A");
    const z = zoomBounds({ at: [-97.1, 46.7], bbox: null })!;
    assert.ok(Math.abs(z.east - z.west - 0.003) < 1e-9);
    const big = zoomBounds({ at: null, bbox: [-97.4, 46.8, -97.2, 46.9] })!;
    assert.deepEqual([big.west, big.east].map((v) => +v.toFixed(6)), [-97.4, -97.2]);
    assert.equal(zoomBounds({ at: null, bbox: null }), null);
  });

  it("the class badge's 'needs ruling' flag: partly, wholly, or none", () => {
    const part = rulingFlag({ ruling: { label: "High", hits: 6, unruled: 4, why: ["BNSF KO trains/day is a lookup."] } })!;
    assert.equal(part.short, "partly needs ruling");
    assert.match(part.text, /^4 of 6 High hits rest on values that still need a ruling; the other 2 are by rule\. BNSF/);
    assert.equal(rulingFlag({ ruling: { label: "High", hits: 2, unruled: 2, why: [] } })!.short, "needs ruling");
    assert.equal(rulingFlag({ ruling: { label: "High", hits: 2, unruled: 0, why: [] } }), null);
    assert.equal(rulingFlag(null), null);
  });
});
