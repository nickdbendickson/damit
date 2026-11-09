import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { gzipSync } from "node:zlib";

import { analyze } from "./engine.ts";
import { exportDamJson } from "./export.ts";
import {
  confirmText,
  countyOptions,
  damOptionLabel,
  demElevationsPatch,
  fieldTag,
  fold,
  heightFor,
  heightWarningOnElevations,
  heightWarningOnPick,
  isNidId,
  loadNidData,
  makeNidData,
  missingForNext,
  nidHazardLine,
  prefillPatch,
  revertPatch,
  searchDams,
  storageFor,
  unlinkPatch,
  type NidDam,
} from "./nid-dams.ts";
import { blankDam, SAMPLE_DAMS } from "./samples.ts";
import { migrateDesk } from "./store.ts";
import type { DamRecord } from "./types.ts";

const data = await loadNidData();
const dam = (nid: string): NidDam => {
  const d = data.byNid.get(nid);
  assert.ok(d, nid);
  return d;
};
const filled = (nid: string, current: DamRecord = blankDam()): DamRecord => ({
  ...current,
  ...prefillPatch(dam(nid), data, current).patch,
});

describe("the NID example extract (ND)", () => {
  it("loads offline: 948 NID main dams, NID IDs only, the NID pull date recorded", () => {
    assert.equal(data.dams.length, 948);
    assert.equal(data.state, "ND");
    assert.ok(data.dams.every((d) => isNidId(d.nid) && d.nid.startsWith("ND")), "NID IDs only");
    assert.equal(data.nidSource.fetchedUtc, "2026-10-29T21:56:00Z");
    assert.ok(!("dwr" in data) && !("dugouts" in data), "no state dam-safety or dugout inventory");
  });

  it("size budget: <= 250 KB raw / 70 KB gzipped; no DWR or structures bundle ships", () => {
    const nid = readFileSync(new URL("./data/nid_ND.json", import.meta.url));
    assert.ok(nid.length <= 250_000, `${nid.length}`);
    assert.ok(gzipSync(nid, { level: 9 }).length <= 70_000);
    for (const gone of ["nd_dams_dwr.json", "nd_structures.json", "nd_dams.json"])
      assert.throws(() => readFileSync(new URL(`./data/${gone}`, import.meta.url)), gone);
  });

  it("the picker modules never fetch the inventory themselves: the example by dynamic import, other states via the desktop server", () => {
    for (const f of ["./nid-dams.ts", "./data-bundle.ts", "../../components/crest/NidDamPicker.tsx"]) {
      const src = readFileSync(new URL(f, import.meta.url), "utf8").replace(/\/\/.*$|\/\*[\s\S]*?\*\//gm, "");
      assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|https?:\/\/[^"'\s]*\.json/, f);
    }
    assert.match(readFileSync(new URL("./nid-dams.ts", import.meta.url), "utf8"), /loadBundle<NidBundle>\("nid_example"\)/);
    assert.match(readFileSync(new URL("./data-bundle.ts", import.meta.url), "utf8"), /import\("\.\/data\/nid_ND\.json"/);
  });

  it("NID IDs: two letters and digits; DWR-, DUG-, SAMPLE- and NEW are not", () => {
    for (const ok of ["ND00199", "RI00001", "TX12345"]) assert.ok(isNidId(ok), ok);
    for (const bad of ["DWR-4031", "DUG-130", "UNK-9", "SAMPLE-4031", "DESK-014", "NEW", "", "nd00199x", null]) assert.ok(!isNidId(bad), String(bad));
  });

  it("makeNidData takes the state from the bundle, else from the NID IDs", () => {
    const b = { cols: ["nid", "name"], rows: [["RI00001", "Test"]], source: { url: "u", fetchedUtc: "2026-11-09T00:00:00Z", rows: 1, attribution: "a" } };
    assert.equal(makeNidData(b).state, "RI");
    assert.equal(makeNidData({ ...b, source: { ...b.source, state: "CT" } }).state, "CT");
  });
});

describe("search and labels", () => {
  it("finds ND00199 by NID ID, digits, name words and other name; case- and accent-insensitive", () => {
    for (const q of ["nd00199", "ND00199", "199", "swan buff", "SWAN  Buffalo 12", "absaraka", "Ábsaraká"])
      assert.ok(searchDams(data.dams, q).some((d) => d.nid === "ND00199"), q);
    assert.equal(fold("Lac Qui Parlé — Dam"), "lac qui parle dam");
    assert.ok(!searchDams(data.dams, "absaraka", "Barnes").length);
    assert.equal(searchDams(data.dams, "").length, 948);
    assert.ok(!searchDams(data.dams, "4031").some((d) => !isNidId(d.nid)), "no DWR-only entries");
  });

  it("option label: name · NID ID · NID hazard · H ft · V ac-ft", () => {
    assert.equal(
      damOptionLabel(dam("ND00199")),
      "Swan Buffalo Detention Dam 12 · ND00199 · NID hazard Significant · 28 ft · 1,616 ac-ft",
    );
  });

  it("an unnamed dam reads (unnamed) · NID ID, never an owner name", () => {
    const d = dam("ND00971");
    assert.equal(d.name, null);
    assert.ok(!("owner" in d));
    assert.match(damOptionLabel(d), /^\(unnamed\) · ND00971 · NID hazard/);
    const f = filled("ND00971");
    assert.equal(f.name, "Unnamed dam ND00971");
    assert.ok(f.nidRef && !("owner" in f.nidRef));
    const out = JSON.stringify(f) + exportDamJson(f, analyze(f));
    assert.ok(!/"owner/i.test(out));
  });

  it("counties with counts; Clay carries its county note", () => {
    const opts = countyOptions(data.dams);
    assert.equal(opts.reduce((s, o) => s + o.count, 0), 948);
    assert.equal(opts.find((o) => o.county === "Clay")?.label, "Clay (1) (see note)");
    assert.match(opts.find((o) => o.county === "Cass")!.label, /^Cass \(\d+\)$/);
  });

  it("ND00182 stays in Clay with a Cass Co. note", () => {
    const d = dam("ND00182");
    assert.equal(d.county, "Clay");
    assert.match(d.countyNote!, /Cass Co\., ND/);
  });
});

describe("prefill", () => {
  it("ND00199: H 28 NID Height, V 1615.5 NID Max Storage, L 1700; no elevations, no datum, no area", () => {
    const r = filled("ND00199");
    assert.equal(r.name, "Swan Buffalo Detention Dam 12");
    assert.equal(r.nidId, "ND00199");
    assert.equal(r.heightFt, 28);
    assert.equal(r.provenance?.heightFt?.src, "NID");
    assert.equal(r.receptorSource, "nd911", "ND dams take ND 911 address points");
    assert.equal(r.storageAcFt, 1615.5);
    assert.equal(r.lengthFt, 1700);
    assert.equal(r.year, 1960);
    assert.equal(r.drainageMi2, 13.7);
    assert.ok(Number.isNaN(r.crestFt) && Number.isNaN(r.streambedFt));
    assert.equal(r.statedDatum, "");
    assert.equal(r.surfaceAreaAc, undefined);
    assert.equal(r.classOfRecord, undefined);
    assert.equal(r.nidHazard, "Significant");
    assert.equal(r.nidRef?.surfaceAreaNormalAc, 29.8);
    assert.deepEqual(missingForNext(r), ["crest", "breach bottom", "datum"]);
  });

  it("H is the NID Height (whole ft)", () => {
    const nidOnly = [...data.dams].find((d) => d.nidHeightFt != null)!;
    assert.deepEqual(heightFor(nidOnly), {
      value: nidOnly.nidHeightFt,
      src: "NID",
      field: "NID Height (Ft)",
      rounded: true,
    });
  });

  it("confirm dialog lists what is replaced; applying another dam clears its geometry, class and area", () => {
    const cur: DamRecord = { ...SAMPLE_DAMS[0], surfaceAreaAc: 50, classOfRecord: "High" };
    const { patch, replaced } = prefillPatch(dam("ND00486"), data, cur);
    assert.ok(replaced.includes("surfaceAreaAc") && replaced.includes("classOfRecord"));
    assert.match(confirmText(replaced), /^Fill this record from the NID\? These fields will be replaced: .*crest \(cleared\).*class of record \(cleared\)/);
    assert.equal(patch.surfaceAreaAc, undefined);
    const fromNew = prefillPatch(dam("ND00486"), data, { ...cur, isNew: true });
    assert.equal(fromNew.patch.isNew, undefined, "another dam does not inherit the New dam box");
    assert.ok(fromNew.replaced.includes("isNew"));
    const again = prefillPatch(dam("ND00486"), data, { ...cur, ...patch, surfaceAreaAc: 40 });
    assert.ok(!("surfaceAreaAc" in again.patch), "re-applying the same dam leaves area as it was");
  });

  it("required values missing in the NID become NaN with a red tag; optional ones read not in NID", () => {
    const d: NidDam = { ...dam("ND00486"), nid: "ND99999", nidHeightFt: null, damHeightFt: null, lengthFt: null, yearCompleted: null, name: null, otherNames: null };
    const r = { ...blankDam(), ...prefillPatch(d, data).patch };
    assert.ok(Number.isNaN(r.heightFt) && Number.isNaN(r.lengthFt));
    assert.deepEqual(fieldTag(r, "heightFt"), { kind: "missing", text: "not in NID: enter a value" });
    assert.deepEqual(fieldTag(r, "year"), { kind: "missing-optional", text: "not in NID" });
    assert.ok(missingForNext(r).includes("height") && missingForNext(r).includes("length"));
    assert.equal(r.name, "Unnamed dam ND99999");
  });

  it("tags: from NID / edited (NID: x) / revert / unlink", () => {
    const r = filled("ND00486");
    assert.equal(fieldTag(r, "storageAcFt")?.kind, "from");
    const e = { ...r, storageAcFt: 99 };
    assert.equal(fieldTag(e, "storageAcFt")?.text, "edited (NID: 150)");
    assert.equal(revertPatch(e, "storageAcFt").storageAcFt, 150);
    const u = { ...e, ...unlinkPatch() };
    assert.equal(fieldTag(u, "storageAcFt"), null);
    assert.equal(u.storageAcFt, 99);
  });
});

describe("storage chip", () => {
  it("NID Max Storage normally; Normal Storage with a warning when no max is reported; range note over 500k", () => {
    assert.equal(storageFor(dam("ND00199")).chip, "NID Max Storage");
    const noMax = storageFor(dam("ND00182"));
    assert.equal(noMax.chip, "NID Normal Storage (no max reported)");
    assert.match(noMax.warning!, /no Max Storage/);
    assert.equal(noMax.value, 452);
    assert.match(storageFor(dam("ND00145")).rangeNote!, /Over 500,000 ac-ft/);
    assert.equal(storageFor(dam("ND00199")).rangeNote, null);
  });
});

describe("height warnings", () => {
  it("W-H1, NID-only: ND00001 NID Height 24 vs Dam Height 16 offers Use 16; ND00486 (23 vs blank) does not offer", () => {
    const w = heightWarningOnPick(dam("ND00001"));
    assert.equal(w?.id, "W-H1");
    assert.equal(w?.useHeightFt, 16);
    assert.equal(heightWarningOnPick(dam("ND00486"))?.useHeightFt, undefined);
  });

  it("W-H2: ND00199 with matching typed elevations gives no warning; a 5 ft mismatch warns (tol = max(1, 5% D) + 0.5 if rounded)", () => {
    const r = filled("ND00199");
    const withElev = { ...r, ...demElevationsPatch(r, 1071.09, 1043.09) };
    assert.equal(heightWarningOnElevations(withElev), null);
    const off = { ...withElev, streambedFt: 1038.59 };
    const w = heightWarningOnElevations(off);
    assert.equal(w?.id, "W-H2");
    assert.equal(w?.useHeightFt, 32.5);
    // H is the rounded NID Height, so the tolerance gets +0.5 ft.
    const only = data.dams.find((d) => d.nidHeightFt != null && d.nidHeightFt < 25)!;
    const nid = filled(only.nid);
    const H = nid.heightFt;
    const r14 = { ...nid, crestFt: 100 + H - 1.4, streambedFt: 100, statedDatum: "NAVD88" as const };
    assert.equal(heightWarningOnElevations(r14), null, "1.4 ft is within 1 + 0.5 for a rounded NID H");
    const typed = { ...r14, provenance: { ...r14.provenance, heightFt: undefined } };
    assert.equal(heightWarningOnElevations(typed)?.id, "W-H2", "1.4 ft is outside 1 ft for a typed H");
  });
});

describe("typed DEM elevations", () => {
  it("typed DEM entry is NAVD 88, tagged typed, and never copied into demCrestFt", () => {
    const r = filled("ND00199");
    assert.equal(r.surfaceAreaAc, undefined);
    const dem = demElevationsPatch(r, 1071.1, 1043.6);
    assert.equal(dem.statedDatum, "NAVD88");
    assert.equal(dem.provenance?.crestFt?.src, "DEM");
    assert.match(dem.provenance!.crestFt!.field, /typed from DEM/);
    assert.ok(!("demCrestFt" in dem));
  });

  it("M1: after typed DEM values the DEM-vs-crest check can still fire against a sampled DEM crest", () => {
    const r = { ...filled("ND00199"), demCrestFt: 1071.09 };
    const typedOk = { ...r, ...demElevationsPatch(r, 1071.1, 1043.6) };
    assert.equal(typedOk.demCrestFt, 1071.09);
    assert.ok(!analyze(typedOk).datum.warnings.some((w) => /^DEM crest/.test(w)));
    const typedNgvd = { ...r, ...demElevationsPatch(r, 1070.0, 1042.5) };
    assert.ok(analyze(typedNgvd).datum.warnings.some((w) => /^DEM crest 1071\.09 ft differs from the tied crest 1070\.00/.test(w)));
  });
});

describe("no state dam-safety or dugout inventory", () => {
  it("the inventory modules carry no DWR or dugout reader", () => {
    for (const f of ["./nid-dams.ts", "./batch.ts", "./data-bundle.ts", "./engine.ts", "./export.ts"])
      assert.doesNotMatch(readFileSync(new URL(f, import.meta.url), "utf8").replace(/DWR-\d+/g, ""), /dwrSource|nd_dams_dwr|nd_structures|dugouts\b/i, f);
  });
});

describe("engine guard and export", () => {
  it("no elevations: Review (elevations missing), no breach, no flood", () => {
    const a = analyze(filled("ND00199"));
    assert.equal(a.screen.level, "Review");
    assert.equal(a.screen.label, "Review (elevations missing)");
    assert.equal(a.flood.engineLabel, "not run (elevations missing)");
    assert.equal(a.breach.series.length, 0);
    assert.ok(Number.isNaN(a.breach.peakCfs));
  });

  it("NID hazard is never fed into the screen or the class of record", () => {
    const r = filled("ND00199");
    const p = { ...r, ...demElevationsPatch(r, 1071.09, 1043.59) };
    const a = analyze(p);
    const b = analyze({ ...p, nidHazard: "High" });
    assert.equal(a.screen.level, b.screen.level);
    assert.equal(a.screen.classOfRecord, null);
    assert.equal(nidHazardLine("Significant"), "NID hazard (as reported to the NID, FEMA class): Significant");
  });

  it("dam.json gets provenance, NID hazard and attribution only for NID-filled records", () => {
    const sample = SAMPLE_DAMS.find((d) => d.id === "nd00199")!;
    const plain = JSON.parse(exportDamJson(sample, analyze(sample)));
    assert.ok(!("provenance" in plain) && !("nid_hazard" in plain));
    const r = filled("ND00199");
    const p = { ...r, ...demElevationsPatch(r, 1071.09, 1043.59) };
    const j = JSON.parse(exportDamJson(p, analyze(p)));
    assert.equal(j.nid_id, "ND00199");
    assert.equal(j.nid_hazard, "Significant");
    assert.match(j.nid_hazard_note, /not the class of record/);
    assert.equal(j.provenance.crestFt.src, "DEM");
    assert.equal(j.crest_ft.toFixed(2), "1071.09");
    assert.ok(j.attribution.some((s: string) => /National Inventory of Dams/.test(s)));
    assert.ok(!j.attribution.some((s: string) => /Water Resources/.test(s)));
  });
});

describe("stored desk migration (crest-desk-v2, version 0 -> 1)", () => {
  it("moves an untouched ND00199 sample from 1072.24 / 1044.74 to 1071.09 / 1043.59; keeps edited ones", () => {
    const now = SAMPLE_DAMS.find((d) => d.id === "nd00199")!;
    const old = { ...now, crestFt: 1072.24, streambedFt: 1044.74 };
    const edited = { ...now, crestFt: 1080, streambedFt: 1044.74 };
    const m = migrateDesk({ dams: [old], activeId: "nd00199" }, 0);
    assert.equal(m.dams[0].crestFt, 1071.09);
    assert.equal(m.dams[0].streambedFt, 1043.59);
    assert.equal(migrateDesk({ dams: [edited] }, 0).dams[0].crestFt, 1080);
    assert.equal(now.crestFt, 1071.09);
  });
});

describe("a new record from NID with no dam line (full test 2026-10-30)", () => {
  it("has no flood strip and no looked-up 911 points, so the Screen step holds at Review, not High", () => {
    // A record filled from the NID takes its structures from ND 911 address points (receptorSource "nd911") and starts
    // with none; with no dam line there is also no flood strip. Either alone holds the screen at Review, so an empty
    // list never reads as a real class. (The full-test record once carried generic seeds and read "Not assessed"; a
    // picked NID record is nd911 now, so the 911-not-looked-up guard is what protects it.)
    const sample = SAMPLE_DAMS.find((d) => d.nid === "ND00199")!;
    const { crestFt, streambedFt, demCrestFt, statedDatum, heightFt, storageAcFt } = sample;
    const r = { ...filled("ND00199"), crestFt, streambedFt, demCrestFt, statedDatum, heightFt, storageAcFt };
    assert.equal(r.geometry?.damLine, undefined);
    assert.equal(r.receptorSource, "nd911");
    assert.equal(r.receptors.length, 0);
    const a = analyze(r);
    assert.equal(a.screen.level, "Review");
    assert.equal(a.screen.label, "Review (911 points not looked up)");
    assert.match(a.screen.reasons[0], /^Structures for this dam come from ND 911 address points/);
    // A record the engineer screens in full (real receptors, not nd911) is not forced to Review by this guard.
    const own = analyze({ ...r, receptorSource: undefined, receptors: sample.receptors.map((x) => ({ ...x, id: `my-${x.id}` })), geometry: sample.geometry });
    assert.notEqual(own.screen.label, "Review (911 points not looked up)");
  });

  it("the same record with the dam line drawn is screened as before", () => {
    const sample = SAMPLE_DAMS.find((d) => d.nid === "ND00199")!;
    const { crestFt, streambedFt, demCrestFt, statedDatum, heightFt, storageAcFt } = sample;
    const a = analyze({ ...filled("ND00199"), crestFt, streambedFt, demCrestFt, statedDatum, heightFt, storageAcFt, geometry: sample.geometry });
    assert.notEqual(a.screen.label, "Not assessed (downstream direction unknown)");
    assert.ok(!a.screen.reasons.some((x) => x.startsWith("Not assessed")));
  });
});

describe("saved desk, version 1 -> 2", () => {
  it("an unedited ND00199 sample loses the TM11 Significant claim; an edited class is kept", () => {
    const now = SAMPLE_DAMS.find((d) => d.id === "nd00199")!;
    const old = { ...now, classOfRecord: "ND MEDIUM / TM11 Significant (DWR-2801 benchmark)", sampleNote: "old" };
    const m = migrateDesk({ dams: [old] }, 1);
    assert.equal(m.dams[0].classOfRecord, "ND MEDIUM (NID hazard Significant)");
    assert.equal(m.dams[0].sampleNote, now.sampleNote);
    const mine = { ...now, classOfRecord: "High (my review)" };
    assert.equal(migrateDesk({ dams: [mine] }, 1).dams[0].classOfRecord, "High (my review)");
  });
});

describe("hand-off ids (NID IDs only)", () => {
  it("dam_id is the NID ID; samples and new dams keep their own record id and never get a made-up NID ID", async () => {
    const { handoffIds } = await import("./nid-dams.ts");
    const nd = SAMPLE_DAMS.find((d) => d.nid === "ND00199")!;
    assert.deepEqual(handoffIds(nd), { damId: "ND00199", nidId: "ND00199", isNew: false, isSample: false });
    for (const sample of SAMPLE_DAMS.filter((d) => d.nid !== "ND00199")) {
      const ids = handoffIds(sample);
      assert.equal(ids.nidId, null, sample.nid);
      assert.equal(ids.isSample, true, sample.nid);
      assert.equal(ids.damId, sample.id);
      const j = JSON.parse(exportDamJson(sample, analyze(sample)));
      assert.equal(j.dam_id, sample.id);
      assert.equal(j.is_sample, true);
      assert.ok(!("nid_id" in j));
    }
    const fresh = { ...blankDam(), isNew: true };
    assert.equal(fresh.nid, "", "a new record has no NID ID, not NEW");
    assert.deepEqual(handoffIds(fresh), { damId: fresh.id, nidId: null, isNew: true, isSample: false });
    assert.equal(handoffIds({ id: "x", nid: "DWR-4031" }).damId, "x");
    assert.equal(handoffIds({ id: "x", nid: "NEW" }).nidId, null);
  });
});
