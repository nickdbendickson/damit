// The rail checklist (checklist.ts): what holds each step, from missingForNext, the datum and flood flags and the
// step-done rules, and where Fix… goes.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { analyze } from "./engine.ts";
import { blocks, flagTarget, MISSING_FIELD, stepChecklist } from "./checklist.ts";
import { missingForNext } from "./nid-dams.ts";
import { STEP_ORDER } from "./pipeline.ts";
import { blankDam, SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord } from "./types.ts";

const sample = (): DamRecord => structuredClone(SAMPLE_DAMS[0]);
const empty = (): DamRecord => ({ ...blankDam(), heightFt: NaN, storageAcFt: NaN, crestFt: NaN, streambedFt: NaN, statedDatum: "" });
const check = (d: DamRecord) => {
  const a = analyze(d);
  return stepChecklist(d, a, a);
};

describe("rail checklist", () => {
  it("lists every missing input on the Record step with its field, and nothing invented", () => {
    const d = empty();
    const c = check(d);
    const missing = missingForNext(d);
    assert.ok(missing.length >= 5);
    const rec = c.record.filter((i) => i.kind === "missing");
    assert.deepEqual(rec.map((i) => i.target), missing.map((m) => MISSING_FIELD[m].target));
    for (const i of rec) assert.equal(i.step, "record");
    assert.ok(blocks(c.record));
    // W-D1 "Elevations missing" repeats the missing inputs, so it is not listed again.
    assert.ok(!c.record.some((i) => /Elevations missing/.test(i.text)));
  });

  it("puts the steps that wait on Record inputs under their own step, fixed on Record", () => {
    const c = check(empty());
    assert.equal(c.setup[0].step, "record");
    assert.equal(c.setup[0].target, '[data-fix="heightFt"]');
    assert.equal(c.breach[0].target, '[data-fix="streambedFt"]');
  });

  it("a complete sample has no missing inputs; its open steps are to-dos", () => {
    const c = check(sample());
    for (const id of STEP_ORDER) assert.ok(!c[id].some((i) => i.kind === "missing"), id);
    assert.equal(c.flood[0].kind, "todo");
    assert.equal(c.dashboard[0].step, "flood");
    assert.equal(c.report[0].target, '[data-fix="classify"]');
    assert.ok(!blocks(c.flood));
  });

  it("Results' Fix… points at the Files… control, not the import card (Absaraka desk test 2026-11-21)", () => {
    const c = check(sample());
    assert.equal(c.results[0].target, '[data-testid="import-lisflood-files"]');
  });

  it("a classified record has no Report to-do", () => {
    const d = sample();
    d.hazardResult = { suggestedClass: "Low" } as DamRecord["hazardResult"];
    assert.equal(check(d).report.length, 0);
  });

  it("an out-of-range height is a W-V1 check on the Height field", () => {
    const d = { ...sample(), heightFt: 500 };
    const v = check(d).record.find((i) => i.text.startsWith("W-V1"));
    assert.ok(v);
    assert.equal(v.kind, "warn");
    assert.equal(v.target, '[data-fix="heightFt"]');
    assert.match(v.detail, /outside the desk range/);
  });

  it("a DEM crest that disagrees is a W-D1 check on the DEM crest field", () => {
    const d = { ...sample(), demCrestFt: sample().crestFt + 30 };
    const v = check(d).record.find((i) => i.text.startsWith("W-D1"));
    assert.ok(v);
    assert.equal(v.target, '[data-fix="demCrestFt"]');
  });

  it("maps flags to their fields", () => {
    assert.deepEqual(flagTarget({ code: "W-H1", severity: "warn", text: "x" }, "datum"), { step: "record", target: '[data-fix="heightFt"]' });
    assert.equal(flagTarget({ code: "W-V1", severity: "warn", text: "Storage 0 ac-ft is outside the desk range" }, "datum").target, '[data-fix="storageAcFt"]');
    assert.equal(flagTarget({ code: "W-D1", severity: "stop", text: "No DEM tie: …" }, "datum").target, '[data-fix="demCrestFt"]');
    assert.equal(flagTarget({ code: "W-R1", severity: "warn", text: "Reach incomplete" }, "flood").step, "flood");
  });

  it("shortens long flag text with a real ellipsis", () => {
    const d = { ...sample(), demCrestFt: sample().crestFt + 30 };
    const v = check(d).record.find((i) => i.text.startsWith("W-D1"));
    assert.ok(v && v.text.endsWith("…") && !v.text.endsWith("..."));
  });
});
