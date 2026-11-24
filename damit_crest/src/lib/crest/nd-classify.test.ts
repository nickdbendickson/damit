// The North Dakota profile with the receptor list, map layer, report table and "needs ruling" flag (2026-11-22): the
// desk names the classify algorithm of the active profile (or of the result), and reads ndhazard:classify's layers.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { stepChecklist } from "./checklist.ts";
import { filterClassify, needsRuling, parseClassifyList, rulingFlag } from "./classify-list.ts";
import { choiceKey, choiceText, classifyReceptors, receptorKey, reportLead } from "./classify-receptors.ts";
import { classifyActionLabel, DESK_ACTIONS } from "./commands.ts";
import { analyze } from "./engine.ts";
import {
  algorithmsFor,
  classifyAlgorithm,
  DEFAULT_ALGORITHMS,
  ND_ALGORITHMS,
  ND_RECEPTOR_FILES,
  receptorFilesText,
  resultAlgorithm,
} from "./handoff.ts";
import { damChoice, screenAgainstChoice } from "./jurisdiction.ts";
import { receptorMetrics, receptorSection } from "./paper.ts";
import { stepDoneRule } from "./pipeline.ts";
import { classBadge, suggestedDisclaimer, SUGGESTED_DISCLAIMER, summaryTiles } from "./review-summary.ts";
import { SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord, HazardResult } from "./types.ts";

const nd199 = (): DamRecord => structuredClone(SAMPLE_DAMS.find((d) => d.nid === "ND00199")!);
const ND_GPKG = "/w/dams/ND00199/outputs/Classification/Habitable_Structures.gpkg";

/** What _run_classify_nd stores (a real Absaraka ND00199 ndhazard:classify 2.25.8 run, 2026-11-22). */
function ndClassified(d: DamRecord, extra: Partial<HazardResult> = {}): DamRecord {
  const a = analyze(d);
  d.hazardResult = {
    suggestedClass: "High",
    ordinal: "3",
    report: "/w/dams/ND00199/outputs/Hazard_Classification_Report.pdf",
    gpkg: ND_GPKG,
    source: "ndhazard:classify",
    tm11Class: "High",
    layers: { STRUCTURES: 2449, ROADS: 273, RAIL: 39 },
    impacted: { STRUCTURES: 329, ROADS: 128, RAIL: 39 },
    wetStructures: 618,
    complete: true,
    notChecked: {},
    ruling: { label: "High", hits: 39, unruled: 5, why: ["5 rail stretch(es) at High: 22 trains/day >= 10 - probable loss of life - crossing on this line not confirmed"] },
    classifiedAt: "2026-11-23T02:39:00Z",
    choiceKey: choiceKey(damChoice(d)),
    receptorKey: receptorKey(classifyReceptors(d, a)),
    choiceText: choiceText(damChoice(d)),
    ...extra,
  } as HazardResult;
  return d;
}

describe("the classify algorithm the desk names", () => {
  it("is the active profile's: damit:classify (us), ndhazard:classify (nd)", () => {
    assert.equal(algorithmsFor("us").classify, "damit:classify");
    assert.equal(algorithmsFor("nd").classify, "ndhazard:classify");
    assert.equal(classifyAlgorithm("nd"), ND_ALGORITHMS.classify);
    assert.equal(classifyAlgorithm("us", null), DEFAULT_ALGORITHMS.classify);
  });
  it("is the one a stored result came from, read from its source or its GeoPackage's name", () => {
    assert.equal(resultAlgorithm({ source: "ndhazard:classify" }), "ndhazard:classify");
    assert.equal(resultAlgorithm({ gpkg: "/w/classify/damit_hazard_receptors.gpkg" }), "damit:classify");
    assert.equal(resultAlgorithm({ gpkg: "C:\\w\\outputs\\Classification\\Roads_Inundated.gpkg" }), "ndhazard:classify");
    assert.equal(resultAlgorithm({ gpkg: "/w/other.gpkg" }), null);
    assert.equal(resultAlgorithm(null), null);
    // A DamIT result stays named damit:classify after switching the desk to North Dakota, and the other way round.
    assert.equal(classifyAlgorithm("nd", { gpkg: "/w/classify/damit_hazard_receptors.gpkg" }), "damit:classify");
    assert.equal(classifyAlgorithm("us", { gpkg: ND_GPKG }), "ndhazard:classify");
  });
  it("labels the palette's Classify command", () => {
    assert.equal(classifyActionLabel("ndhazard:classify"), "Classify (ndhazard:classify)");
    assert.equal(DESK_ACTIONS.find((a) => a.id === "classify")!.label, "Classify (damit:classify)");
  });
  it("is in the Report to-do, the step rule, the badge, the disclaimer and the screen note", () => {
    const d = nd199();
    const a = analyze(d);
    const todo = (alg?: string) => stepChecklist(d, a, a, alg).report.find((i) => i.key === "todo-report")?.text;
    assert.equal(todo(), "Not classified: run damit:classify");
    assert.equal(todo("ndhazard:classify"), "Not classified: run ndhazard:classify");
    assert.equal(stepDoneRule("report", "ndhazard:classify"), "ndhazard:classify returned a class");
    assert.equal(stepDoneRule("report"), "damit:classify returned a class");
    assert.equal(stepDoneRule("flood"), "terrain outline built or a model run of record");
    assert.match(classBadge(d, a, "ndhazard:classify").note, /^ndhazard:classify has not run for this dam/);
    assert.match(classBadge(d, a).note, /^damit:classify has not run/);
    assert.equal(SUGGESTED_DISCLAIMER, suggestedDisclaimer("damit:classify"));
    assert.match(suggestedDisclaimer("ndhazard:classify"), /^A suggested class from ndhazard:classify:/);
    assert.match(screenAgainstChoice("Medium", damChoice(d), "ndhazard:classify"), /the one ndhazard:classify returns/);
  });
});

describe("an ndhazard:classify result on the desk", () => {
  it("reads as current (it gathers every layer itself), with its tiles and badge flag", () => {
    const d = ndClassified(nd199());
    const a = analyze(d);
    const b = classBadge(d, a, "ndhazard:classify");
    assert.equal(b.state, "current");
    assert.equal(b.text, "High");
    const tiles = summaryTiles(d, a, "ndhazard:classify");
    assert.equal(tiles.find((t) => t.key === "structures")!.note, "checked by ndhazard:classify; 618 wet");
    assert.deepEqual(rulingFlag(d.hazardResult), {
      short: "partly needs ruling",
      text: "5 of 39 High hits rest on values that still need a ruling; the other 34 are by rule. 5 rail stretch(es) at High: 22 trains/day >= 10 - probable loss of life - crossing on this line not confirmed",
    });
  });
  it("is named on the paper report with its own files", () => {
    const d = ndClassified(nd199());
    const a = analyze(d);
    const s = receptorSection(a, d.hazardResult, "nd");
    assert.match(s.note!, /ndhazard:classify judged the real structures \(618 of 2,449 wet\)/);
    assert.match(s.note!, /Habitable_Structures\.gpkg, Roads_Inundated\.gpkg, Rail_Inundated\.gpkg in outputs\/Classification/);
    assert.equal(receptorMetrics(a, d.hazardResult, "nd")[0].note, "ndhazard:classify, real structures");
    assert.equal(receptorFilesText("damit:classify"), "damit_hazard_receptors.gpkg");
    assert.deepEqual([...ND_RECEPTOR_FILES], ["Habitable_Structures.gpkg", "Roads_Inundated.gpkg", "Rail_Inundated.gpkg"]);
  });
  it("leads the Report with the ND class and TM 11, without the preset it was never sent", () => {
    const d = ndClassified(nd199());
    const lead = reportLead(d, analyze(d), "nd");
    assert.equal(lead.kind, "hazard");
    assert.equal(lead.lines[0], "ndhazard:classify judged the downstream receptors: High (ordinal 3). A suggested class; the engineer of record and the regulating agency make the determination.");
    assert.ok(lead.lines.includes("ACER TM 11: High."));
    assert.ok(lead.lines.some((l) => l.startsWith("Receptors checked: STRUCTURES 2449")));
  });
  it("says ndhazard:classify finds the receptors itself before it has run", () => {
    const d = nd199();
    const lead = reportLead(d, analyze(d), "nd");
    assert.equal(lead.kind, "none");
    assert.match(lead.lines[0], /^Classify \(below\) runs ndhazard:classify on the dam folder: it finds the downstream structures/);
    assert.match(reportLead(d, analyze(d)).lines[0], /damit:classify/);
  });
});

describe("ndhazard:classify's receptor list", () => {
  const RAW = {
    receptors: [
      { rid: "structure:1086", layer: "STRUCTURES", kind: "House on foundation", name: "Structure 1086 · RES1-2SWB (single-family home)", ordinal: 3, label: "High", advisory: false, depthFt: 6.1, velFps: 4.08, methods: "Probable loss of life (ACER HIGH)", flags: [], at: [-97.357756, 46.955525], bbox: [-97.357757, 46.955525, -97.357656, 46.955584] },
      { rid: "rail:7", layer: "RAIL", kind: "rail", name: "BNSF · subdivision KO", ordinal: 3, label: "High", depthFt: 2.4, velFps: 3.3, methods: "22 trains/day >= 10 - probable loss of life - crossing on this line not confirmed", flags: ["crossing_unconfirmed"], at: [-97.2, 46.9], bbox: null },
      { rid: "road:2", layer: "ROADS", kind: "Local/County", name: "6TH AVE S", ordinal: 2, label: "Medium", depthFt: 1.6, velFps: 0.6, methods: "no AADT found - assumed Medium for a public road (verify traffic)", flags: ["aadt_assumed"], at: [-97.2, 46.89], bbox: null },
      { rid: "structure:2201", layer: "STRUCTURES", kind: "House on foundation", name: "Structure 2201", ordinal: 2, label: "Medium", advisory: true, depthFt: 4.8, velFps: 1, methods: "Judgment zone (ACER JUDGMENT)", flags: ["habitability_unverified"], at: [-97.3, 46.95], bbox: null },
    ],
    total: 4,
    truncated: false,
    counts: { STRUCTURES: { total: 2449, wet: 618, hit: 329 }, ROADS: { total: 273, wet: 273, hit: 128 }, RAIL: { total: 39, wet: 39, hit: 39 } },
    gpkg: ND_GPKG,
    files: [ND_GPKG, "/w/dams/ND00199/outputs/Classification/Roads_Inundated.gpkg"],
    ruling: { label: "High", hits: 39, unruled: 5, why: ["5 rail stretch(es) at High"] },
  };
  it("keeps the files read and the ruling", () => {
    const l = parseClassifyList(RAW)!;
    assert.equal(l.files!.length, 2);
    assert.equal(l.ruling!.unruled, 5);
    assert.equal(l.receptors[3].advisory, true);
  });
  it("the Needs ruling chip lists the ND values still to rule on", () => {
    const l = parseClassifyList(RAW)!;
    assert.deepEqual(filterClassify(l.receptors, "ruling").map((r) => r.rid), ["rail:7", "road:2", "structure:2201"]);
    assert.equal(needsRuling({ flags: ["trains_lookup"] }), true, "damit:classify's flag still counts");
    assert.equal(needsRuling({ flags: [] }), false);
  });
});
