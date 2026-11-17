// The starting pool (engine.ts startingPool) and per-record Manning's n (routing.ts roughnessOf): the same engine
// behaviour as crest's settings.test.ts. The desk controls for them are not in DamIT Crest yet.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { analyze } from "./engine.ts";
import { generateLisfloodPackage } from "./export.ts";
import { dwr2801 } from "./fixtures.ts";
import { outlineInputs } from "./outline.ts";
import { DEFAULT_ROUGHNESS, roughnessOf } from "./routing.ts";
import { blankDam } from "./samples.ts";

const fp = (dam: ReturnType<typeof dwr2801>) => {
  const io = outlineInputs(dam, analyze(dam));
  assert.ok(io.ok);
  return io.inputs.fingerprint;
};

describe("starting pool", () => {
  const top = analyze(dwr2801());

  it("is the top of dam by default, with the numbers unchanged", () => {
    assert.equal(top.breach.startPool, "top");
    assert.equal(top.breach.startPoolNavdFt, 1071.09);
    assert.ok(Math.abs(top.breach.widthFt - 100) < 1);
    assert.ok(Math.abs(top.breach.headFt - 27.5) < 1e-9);
    assert.deepEqual(analyze(dwr2801({ startPool: "top" })).breach, top.breach);
  });

  it("normal pool: a lower head, the storage at that pool in the equations, a smaller peak and release", () => {
    const a = analyze(dwr2801({ startPool: "normal", normalPoolFt: 1061.09 }));
    assert.equal(a.breach.startPool, "normal");
    assert.equal(a.breach.startPoolNavdFt, 1061.09);
    assert.ok(Math.abs(a.breach.headFt - 17.5) < 1e-9, `head ${a.breach.headFt}`);
    // m = 2 without a surface area: storage at 17.5 of 27.5 ft is (17.5/27.5)^2 of the maximum.
    const vw = 1612.59 * (17.5 / 27.5) ** 2;
    assert.ok(Math.abs(a.breach.volumeAcFt - vw) < 0.01 * vw, `released ${a.breach.volumeAcFt} vs ${vw}`);
    assert.ok(a.breach.peakCfs < 0.6 * top.breach.peakCfs, `${a.breach.peakCfs} vs ${top.breach.peakCfs}`);
    assert.ok(a.breach.widthFt < top.breach.widthFt, "Froehlich width on the smaller Vw");
    assert.match(a.breach.notes.join("\n"), /Starting pool 1,061\.1 ft NAVD88 \(normal pool\), 10\.0 ft below the top of dam/);
    assert.equal(a.datum.warnings.filter((w) => w.startsWith("Starting pool")).length, 0);
  });

  it("an entered elevation is tied like the other stated elevations", () => {
    const a = analyze(dwr2801({ startPool: "elevation", startPoolFt: 1066.09 }));
    assert.equal(a.breach.startPool, "elevation");
    assert.ok(Math.abs(a.breach.headFt - 22.5) < 1e-9);
    // A local (0-300 ft) record: the typed value moves with the record's offset.
    const local = { ...blankDam(), startPool: "elevation" as const, startPoolFt: 95 };
    const b = analyze(local);
    assert.equal(b.breach.startPool, "elevation");
    assert.ok(Math.abs(b.breach.startPoolNavdFt - (95 + 1550 - 100)) < 1e-9, String(b.breach.startPoolNavdFt));
    assert.ok(Math.abs(b.breach.headFt - 13) < 1e-9);
  });

  it("a pool that cannot be used falls back to the top of dam and says why", () => {
    for (const [over, why] of [
      [{ startPool: "normal", normalPoolFt: Number.NaN }, /no normal pool elevation/],
      [{ startPool: "elevation" }, /no elevation is entered/],
      [{ startPool: "elevation", startPoolFt: 1080 }, /above the top of dam/],
      [{ startPool: "elevation", startPoolFt: 1043.7 }, /not above the breach bottom/],
      [{ startPool: "normal", normalPoolFt: 120 }, /could not be tied to NAVD88/],
    ] as const) {
      const a = analyze(dwr2801(over));
      assert.equal(a.breach.startPool, "top", JSON.stringify(over));
      assert.equal(a.breach.peakCfs, top.breach.peakCfs);
      const w = a.datum.warnings.filter((x) => x.startsWith("Starting pool:"));
      assert.equal(w.length, 1, JSON.stringify(over));
      assert.match(w[0], why);
      assert.match(w[0], /starts at the top of dam instead/);
      assert.ok(a.datum.flags?.some((f) => f.code === "W-V1" && f.text === w[0]));
    }
    // A pool typed at the top of dam is the default case, not a warning.
    const same = analyze(dwr2801({ startPool: "elevation", startPoolFt: 1071.09 }));
    assert.equal(same.breach.startPool, "top");
    assert.equal(same.datum.warnings.filter((x) => x.startsWith("Starting pool")).length, 0);
  });
});

describe("Manning's n on a record", () => {
  it("nothing set is the built-in roughness itself; a set value is held to 0.01 - 0.3", () => {
    assert.equal(roughnessOf(undefined), DEFAULT_ROUGHNESS);
    assert.equal(roughnessOf({}), DEFAULT_ROUGHNESS);
    assert.equal(roughnessOf({ nChannel: 0.035, nFloodplain: 0.06 }), DEFAULT_ROUGHNESS);
    assert.equal(roughnessOf({ nFloodplain: Number.NaN, nChannel: 0 }), DEFAULT_ROUGHNESS);
    assert.deepEqual(roughnessOf({ nFloodplain: 0.08 }), { nChannel: 0.035, nFloodplain: 0.08, bankfullM: 1.5 });
    assert.deepEqual(roughnessOf({ nChannel: 5, nFloodplain: 0.001 }), { nChannel: 0.3, nFloodplain: 0.01, bankfullM: 1.5 });
  });

  it("the terrain layer's fingerprint moves only when the record leaves the defaults", () => {
    const base = fp(dwr2801());
    assert.equal(fp(dwr2801({ startPool: "top", roughness: {} })), base, "defaults spelled out: the saved layer still matches");
    assert.equal(fp(dwr2801({ roughness: { nFloodplain: 0.06 } })), base);
    assert.notEqual(fp(dwr2801({ roughness: { nFloodplain: 0.08 } })), base);
    assert.notEqual(fp(dwr2801({ roughness: { nChannel: 0.05 } })), base);
    assert.notEqual(fp(dwr2801({ startPool: "normal", normalPoolFt: 1061.09 })), base);
    assert.equal(fp(dwr2801({ startPool: "normal" })), base, "a pool that fell back to the top of dam is the default layer");
  });

  it("the LISFLOOD export carries the record's floodplain n", () => {
    const series = analyze(dwr2801()).breach.series;
    assert.match(generateLisfloodPackage(dwr2801({ lisflood: { pointX: 1, pointY: 2 } }), series).par, /^fpfric 0\.0600$/m);
    assert.match(generateLisfloodPackage(dwr2801({ lisflood: { pointX: 1, pointY: 2 }, roughness: { nFloodplain: 0.045 } }), series).par, /^fpfric 0\.0450$/m);
  });
});
