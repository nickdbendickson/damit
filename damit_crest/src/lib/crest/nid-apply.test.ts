/**
 * "Apply to this record" / "New record from NID" keep the record's elevations (GUI chain walk on ND00199, Absaraka,
 * 2026-11-09; Nick: Apply keeps the elevations unless the NID actually supplies replacements, and it has none).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  confirmText,
  ELEVATION_FIELDS,
  elevationNote,
  isSameNidDam,
  loadNidData,
  missingForNext,
  newRecordPatch,
  prefillPatch,
} from "./nid-dams.ts";
import { blankDam, SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord } from "./types.ts";

const data = await loadNidData();
const nd00199 = data.byNid.get("ND00199")!;

/** The existing ND00199 record of the walk: NID fields plus the DWR crest (NGVD29 1070.0 -> 1071.09 ft NAVD88). */
const existing = (): DamRecord => ({
  ...blankDam(),
  ...prefillPatch(nd00199, data).patch,
  crestFt: 1071.09,
  streambedFt: 1043.59,
  demCrestFt: 1071.2,
  statedDatum: "NAVD88",
  datumNote: "DWR crest NGVD29 1070.0 converted to NAVD88",
  spillwayFt: 1065.5,
  normalPoolFt: 1062.0,
});

describe("Apply to this record (same NID dam)", () => {
  it("keeps crest, breach bottom, DEM crest, datum, spillway and normal pool; the NID has none to replace them", () => {
    const cur = existing();
    const { patch, replaced } = prefillPatch(nd00199, data, cur);
    for (const f of ELEVATION_FIELDS) assert.ok(!(f in patch), `${f} is not in the patch`);
    const r: DamRecord = { ...cur, ...patch };
    assert.equal(r.crestFt, 1071.09);
    assert.equal(r.streambedFt, 1043.59);
    assert.equal(r.demCrestFt, 1071.2);
    assert.equal(r.statedDatum, "NAVD88");
    assert.equal(r.datumNote, "DWR crest NGVD29 1070.0 converted to NAVD88");
    assert.equal(r.spillwayFt, 1065.5);
    assert.equal(r.normalPoolFt, 1062.0);
    assert.deepEqual(missingForNext(r), []);
    // The NID fields are still refreshed.
    assert.equal(r.nidId, "ND00199");
    assert.equal(r.heightFt, 28);
    assert.doesNotMatch(confirmText(replaced), /cleared/);
    assert.match(elevationNote(replaced), /crest, breach bottom and datum are kept/);
  });

  it("matches on the typed NID field too (a record not yet linked)", () => {
    const cur: DamRecord = { ...existing(), nidId: undefined, nid: "ND00199" };
    assert.ok(isSameNidDam(nd00199, cur));
    const r = { ...cur, ...prefillPatch(nd00199, data, cur).patch };
    assert.equal(r.crestFt, 1071.09);
    assert.equal(r.statedDatum, "NAVD88");
  });

  it("a record of another dam, or a blank record, still has its elevations cleared (no carry-over, no placeholders)", () => {
    const other = SAMPLE_DAMS.find((d) => d.nid !== "ND00199")!;
    const a = prefillPatch(nd00199, data, other);
    assert.ok(Number.isNaN(a.patch.crestFt) && Number.isNaN(a.patch.streambedFt));
    assert.equal(a.patch.statedDatum, "");
    assert.match(confirmText(a.replaced), /crest \(cleared\)/);
    assert.match(elevationNote(a.replaced), /you enter them next/);
    const b = { ...blankDam(), ...prefillPatch(nd00199, data, blankDam()).patch };
    assert.deepEqual(missingForNext(b), ["crest", "breach bottom", "datum"]);
  });
});

describe("New record from NID", () => {
  it("from the same dam's record: the new record carries that record's elevations, so it is not flagged missing", () => {
    const cur = existing();
    const r: DamRecord = { ...blankDam(), ...newRecordPatch(nd00199, data, cur) };
    assert.equal(r.crestFt, 1071.09);
    assert.equal(r.streambedFt, 1043.59);
    assert.equal(r.statedDatum, "NAVD88");
    assert.deepEqual(missingForNext(r), []);
    assert.equal(r.nidId, "ND00199");
  });

  it("from another dam's record or none: blankDam's placeholders are cleared and nothing is invented", () => {
    const other = SAMPLE_DAMS.find((d) => d.nid !== "ND00199")!;
    for (const cur of [other, undefined]) {
      const r: DamRecord = { ...blankDam(), ...newRecordPatch(nd00199, data, cur) };
      assert.ok(Number.isNaN(r.crestFt) && Number.isNaN(r.streambedFt) && Number.isNaN(r.demCrestFt));
      assert.equal(r.statedDatum, "");
      assert.deepEqual(missingForNext(r), ["crest", "breach bottom", "datum"]);
    }
  });

  it("the same dam's record with no elevations gives a new record with none (still flagged, not made up)", () => {
    const cur: DamRecord = { ...blankDam(), ...prefillPatch(nd00199, data).patch };
    const r: DamRecord = { ...blankDam(), ...newRecordPatch(nd00199, data, cur) };
    assert.deepEqual(missingForNext(r), ["crest", "breach bottom", "datum"]);
  });
});
