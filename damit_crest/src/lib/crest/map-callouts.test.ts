// The Workflow map's figures (map-callouts.ts) come from the analysis, never invented.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { analyze } from "./engine.ts";
import { mapCallouts } from "./map-callouts.ts";
import { SAMPLE_DAMS } from "./samples.ts";

describe("mapCallouts", () => {
  it("reads max depth, velocity, peak and area from the analysis, and the earliest wet structure's arrival", () => {
    const a = analyze(structuredClone(SAMPLE_DAMS[0]));
    const c = Object.fromEntries(mapCallouts(a, "Desk estimate").map((x) => [x.key, x]));
    assert.equal(c.depth.value, `${a.flood.maxDepthFt.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ft`);
    assert.match(c.velocity.value, / ft\/s$/);
    assert.match(c.peak.value, / cfs$/);
    assert.match(c.area.value, / ac$/);
    const wet = a.flood.receptors.filter((r) => r.flooded && r.arrivalHr != null);
    if (wet.length) {
      const first = wet.reduce((m, r) => ((r.arrivalHr as number) < (m.arrivalHr as number) ? r : m));
      assert.equal(c.arrival.note, `at ${first.name}`);
      assert.match(c.arrival.value, / hr$/);
    } else assert.equal(c.arrival.value, "—");
  });

  it("shows — with the reason when there is no wet structure or no number", () => {
    const a = analyze(structuredClone(SAMPLE_DAMS[0]));
    const dry = { ...a, flood: { ...a.flood, maxVelocityFps: NaN, receptors: a.flood.receptors.map((r) => ({ ...r, flooded: false })) } };
    const c = Object.fromEntries(mapCallouts(dry, "x").map((x) => [x.key, x]));
    assert.equal(c.arrival.value, "—");
    assert.equal(c.arrival.note, "no wet structure with an arrival time");
    assert.equal(c.velocity.value, "—");
  });
});
