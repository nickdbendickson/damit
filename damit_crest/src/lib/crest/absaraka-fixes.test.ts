// Fixes from the Absaraka (ND00199) desk test of 2026-11-21: duplicate NID records, the two structure counts, the
// terrain the layer was built on, and the Workflow map's figures read from the layer drawn.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { batchDisclaimer, BATCH_DISCLAIMER } from "./batch.ts";
import { analyze } from "./engine.ts";
import { mapCallouts, mappedLayerOf } from "./map-callouts.ts";
import { duplicateNidRecords, duplicateNidText, recordNid } from "./nid-dams.ts";
import { DEM_ATTRIBUTION_SHORT, DEM_SERVICE, layerLabel, OUTLINE_LABEL, stampTerrain, terrainInfo, type OutlineCache } from "./outline.ts";
import { ROUTED_LABEL } from "./inundation.ts";
import { receptorSection, structureCounts } from "./paper.ts";
import { blankDam, SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord, HazardResult } from "./types.ts";

const nd199 = (): DamRecord => structuredClone(SAMPLE_DAMS.find((d) => d.nid === "ND00199")!);

describe("duplicate NID records", () => {
  it("finds another record filed under the same NID ID (case-insensitive), not the record itself", () => {
    const a = nd199();
    const b = { ...blankDam(), id: "nid-nd00199-x", name: "Swan Buffalo Detention Dam 12", nid: "nd00199" };
    const c = { ...blankDam(), id: "other", nid: "ND00182" };
    assert.equal(recordNid(b), "ND00199");
    assert.deepEqual(duplicateNidRecords([a, b, c], "ND00199", b.id).map((d) => d.id), [a.id]);
    assert.deepEqual(duplicateNidRecords([a, b, c], "ND00199").map((d) => d.id), [a.id, b.id]);
    assert.deepEqual(duplicateNidRecords([a, b, c], ""), []);
    assert.match(duplicateNidText("nd00199", a), /ND00199 is already on this desk as “.+”\. .*dams\/ND00199/);
  });
});

describe("structure counts: desk receptors vs damit:classify", () => {
  const hazard = { suggestedClass: "High", layers: { STRUCTURES: 1670, ROADS: 263, RAIL: 34 }, wetStructures: 230, impacted: { ROADS: 11, RAIL: 6 } } as unknown as HazardResult;

  it("keeps each count with its own source", () => {
    const a = analyze(nd199());
    const c = structureCounts(a, hazard);
    assert.equal(c.desk.total, a.flood.receptors.length);
    assert.deepEqual(c.classify, { wet: 230, total: 1670 });
    assert.equal(structureCounts(a, null).classify, null);
  });

  it("the Report's receptor table says it is the desk list and where the 230 wet are", () => {
    const a = analyze(nd199());
    const s = receptorSection(a, hazard);
    assert.match(s.title, /^Desk receptors: \d+ of \d+ wet \(911 address points and mapped structures\)$/);
    assert.match(s.note!, /damit:classify judged the real structures \(230 of 1,670 wet\)/);
    assert.equal(receptorSection(a, null).note, null);
  });
});

describe("the terrain a layer was built on", () => {
  const cache = (): OutlineCache =>
    ({
      fingerprint: "f",
      builtAt: "2026-11-21T18:00:00Z",
      source: DEM_SERVICE,
      attribution: "x",
      layer: "routed",
      stats: {} as never,
      outline: { type: "FeatureCollection", properties: { disclaimer: ROUTED_LABEL, dem_source: DEM_SERVICE, outline_area_ac: 10329 }, features: [] },
    }) as unknown as OutlineCache;

  it("3DEP stays 3DEP; a local DEM is named everywhere", () => {
    assert.equal(terrainInfo(DEM_SERVICE).short, DEM_ATTRIBUTION_SHORT);
    const t = terrainInfo("local DEM cass_10m_3dep.vrt");
    assert.ok(t.local);
    assert.equal(t.short, "Terrain: local DEM cass_10m_3dep.vrt");
    const c = stampTerrain(cache(), t);
    assert.equal(c.source, "local DEM cass_10m_3dep.vrt");
    assert.equal(c.outline.properties.dem_source, "local DEM cass_10m_3dep.vrt");
    assert.match(String(c.outline.properties.disclaimer), /^Routed terrain flood from the local DEM cass_10m_3dep\.vrt and the breach hydrograph/);
    assert.ok(!/3DEP terrain/.test(layerLabel(c, ROUTED_LABEL)));
    assert.equal(layerLabel(cache(), ROUTED_LABEL), ROUTED_LABEL);
    assert.equal(layerLabel({ source: c.source, layer: "outline" }, ROUTED_LABEL), OUTLINE_LABEL.replace("from 3DEP terrain", "from the local DEM cass_10m_3dep.vrt"));
    assert.equal(stampTerrain(cache(), terrainInfo(null)).source, DEM_SERVICE);
  });

  it("the batch footer names the local DEM", () => {
    assert.equal(batchDisclaimer(terrainInfo(null)), BATCH_DISCLAIMER);
    assert.match(batchDisclaimer(terrainInfo("local DEM cass_10m_3dep.vrt")), /inventories and the local DEM cass_10m_3dep\.vrt\.$/);
  });
});

describe("Workflow map figures read the layer drawn", () => {
  it("terrain layer area and depth, and no 0.0 ft/s velocity", () => {
    const a = analyze(nd199());
    const outline = { properties: { outline_area_ac: 10329.4 }, features: [{ properties: { depth_max_ft: 4.2 } }, { properties: { depth_max_ft: 11.7 } }] };
    const layer = mappedLayerOf(outline, "terrain layer");
    assert.deepEqual(layer, { areaAc: 10329.4, maxDepthFt: 11.7, label: "terrain layer" });
    const still = { ...a, flood: { ...a.flood, maxVelocityFps: 0 } };
    const c = Object.fromEntries(mapCallouts(still, "Desk estimate", layer).map((x) => [x.key, x]));
    assert.equal(c.area.value, "10,329 ac");
    assert.equal(c.depth.value, "11.7 ft");
    assert.equal(c.velocity.value, "—");
    assert.match(c.velocity.note, /no velocity estimate/);
  });
});
