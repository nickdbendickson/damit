// The downstream receptors damit:classify judges with the chosen preset or custom methods, and how the Report leads.
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { readFileSync } from "node:fs";

import {
  choiceKey,
  classifyReceptors,
  hazardStatus,
  hazardType,
  paperStamp,
  receptorCount,
  receptorKey,
  reportLead,
} from "./classify-receptors.ts";
import { analyze } from "./engine.ts";
import { handoffDam } from "./handoff.ts";
import { toLocal } from "./aoi.ts";
import { SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord, HazardResult } from "./types.ts";

const dam = (): DamRecord => structuredClone(SAMPLE_DAMS.find((d) => d.id === "nd00199")!);

function classified(d: DamRecord, extra: Partial<HazardResult> = {}): DamRecord {
  const exp = classifyReceptors(d, analyze(d));
  return {
    ...d,
    hazardResult: {
      suggestedClass: "Significant",
      ordinal: "2",
      genericLabel: "Significant",
      report: "/w/dams/ND00199/classify/damit_hazard_report.md",
      gpkg: "/w/dams/ND00199/classify/damit_hazard_receptors.gpkg",
      driving: [{ method: "M2", label: "Significant", reason: "home wet 2 ft", receptors: 1 }],
      layers: { STRUCTURES: 3, ROADS: 2 },
      skipped: 0,
      classifiedAt: "2026-11-09T20:00:00Z",
      choiceKey: choiceKey(d.classification),
      receptorKey: receptorKey(exp),
      choiceText: "x",
      ...extra,
    },
  };
}

describe("classifyReceptors", () => {
  it("maps houses, mobile homes and barns to STRUCTURES points and roads to ROADS lines", () => {
    const d = dam();
    const exp = classifyReceptors(d, analyze(d));
    assert.equal(exp.format, "damit_crest/classify_receptors");
    assert.equal(exp.crs, "EPSG:4326");
    assert.deepEqual(Object.keys(exp.layers).sort(), ["ROADS", "STRUCTURES"]);
    assert.equal(exp.layers.STRUCTURES!.features.length, 3);
    assert.equal(exp.layers.ROADS!.features.length, 2);
    assert.ok(exp.layers.STRUCTURES!.features.every((f) => f.geometry.type === "Point"));
    assert.ok(exp.layers.ROADS!.features.every((f) => f.geometry.type === "LineString" && f.geometry.coordinates.length === 2));
    const p = exp.layers.STRUCTURES!.features[0].properties;
    for (const k of ["crest_id", "name", "kind", "type", "placed", "habitable", "pad_ft", "distance_km", "source"]) assert.ok(k in p, k);
    assert.equal(exp.layers.ROADS!.features[1].properties.aadt, 320);
    assert.equal(receptorCount(exp), 5);
    assert.equal(exp.placement["desk valley"], 5);
    assert.equal(exp.skipped.length, 0);
    assert.equal(exp.domain, null);
  });

  it("puts desk-valley receptors downstream of the breach along the drawn direction", () => {
    const d = dam();
    const result = analyze(d);
    const exp = classifyReceptors(d, result);
    const origin = { lon: d.lon!, lat: d.lat! };
    const res = d.geometry!.reservoirPoint!.geometry.coordinates as number[];
    const r = toLocal(res[0], res[1], origin);
    for (const f of exp.layers.STRUCTURES!.features) {
      const [lon, lat] = f.geometry.coordinates as [number, number];
      const q = toLocal(lon, lat, origin);
      // Downstream = away from the reservoir point.
      assert.ok(q[0] * r[0] + q[1] * r[1] < 0, `${f.properties.crest_id} is upstream`);
    }
  });

  it("uses a mapped lon/lat or the 911 address point before the desk valley", () => {
    const d = dam();
    d.receptors[1] = { ...d.receptors[1], lon: -97.38, lat: 46.98 };
    d.receptors[4] = { ...d.receptors[4], source: "nd911", sourceRef: "{G1}" };
    d.nd911 = { points: [{ nguid: "{G1}", lon: -97.37, lat: 46.975 }] } as unknown as DamRecord["nd911"];
    const exp = classifyReceptors(d, analyze(d));
    const byId = new Map(exp.layers.STRUCTURES!.features.map((f) => [f.properties.crest_id, f]));
    assert.deepEqual(byId.get("abs-farm")!.geometry.coordinates, [-97.38, 46.98]);
    assert.equal(byId.get("abs-farm")!.properties.placed, "mapped");
    assert.deepEqual(byId.get("abs-house")!.geometry.coordinates, [-97.37, 46.975]);
    assert.equal(byId.get("abs-house")!.properties.placed, "911 address point");
  });

  it("skips and explains receptors it cannot place, and sends the drawn area as DOMAIN", () => {
    const d = dam();
    d.geometry = {
      aoi: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[-97.4, 46.9], [-97.3, 46.9], [-97.3, 47], [-97.4, 46.9]]] } },
    };
    d.lat = undefined;
    d.lon = undefined;
    d.receptors[0] = { ...d.receptors[0], kind: "road" };
    d.receptors[2] = { ...d.receptors[2], lon: -97.35, lat: 46.95 };
    const exp = classifyReceptors(d, analyze(d));
    assert.equal(exp.domain?.geometry.type, "Polygon");
    assert.deepEqual(Object.keys(exp.layers), ["STRUCTURES"]);
    assert.equal(exp.layers.STRUCTURES!.features.length, 1); // the mapped barn
    assert.equal(exp.skipped.length, 4);
    assert.ok(exp.skipped.every((s) => /no position|downstream direction/.test(s.reason)));
  });

  it("uses Hazard's receptor type names", () => {
    assert.equal(hazardType({ kind: "house" }), "home");
    assert.equal(hazardType({ kind: "house", habitable: false }), "outbuilding");
    assert.equal(hazardType({ kind: "mobile" }), "mobile_home");
    assert.equal(hazardType({ kind: "barn" }), "farm_unoccupied");
    assert.equal(hazardType({ kind: "barn", habitable: true }), "farm_occupied");
  });
});

describe("the Report leads with damit:classify's class for the chosen jurisdiction", () => {
  it("before classify runs, the lead is not the desk screen", () => {
    const d = { ...dam(), classification: { mode: "preset" as const, preset: "NE" } };
    const lead = reportLead(d, analyze(d));
    assert.equal(lead.kind, "none");
    assert.match(lead.title, /^DamIT classification \(Nebraska.*\): not run yet$/);
    assert.match(lead.lines[0], /sends 5 downstream receptors to damit:classify/);
    const level = analyze(d).screen.label;
    assert.ok(!lead.title.includes(level) && !lead.lines.join(" ").includes(level), "the desk screen is not the lead");
    assert.equal(paperStamp(level, lead), `SCHEMATIC PREVIEW: ${level}`.toUpperCase());
  });

  it("after classify, Hazard's class leads and the stamp is Hazard's", () => {
    const d = classified({ ...dam(), classification: { mode: "preset", preset: "NE" } });
    const st = hazardStatus(d, analyze(d));
    assert.equal(st.state, "current");
    const lead = reportLead(d, analyze(d));
    assert.equal(lead.kind, "hazard");
    assert.match(lead.title, /^DamIT classification \(Nebraska.*\): Significant$/);
    assert.match(lead.lines[0], /damit:classify judged the downstream receptors with Nebraska.*: Significant \(ordinal 2\)/);
    assert.ok(lead.lines.some((l) => l.startsWith("M2 Significant")));
    assert.ok(lead.lines.some((l) => l.includes("damit_hazard_receptors.gpkg")));
    assert.equal(paperStamp("High", lead, "Significant"), "DAMIT CLASSIFY: SIGNIFICANT");
  });

  it("a result for another preset, other methods or other receptors is out of date, never the new choice's class", () => {
    const base = classified({ ...dam(), classification: { mode: "preset", preset: "NE" } });
    const other = { ...base, classification: { mode: "preset" as const, preset: "ND" } };
    const lead = reportLead(other, analyze(other));
    assert.equal(lead.kind, "stale");
    assert.match(lead.lines[0], /not the current choice \(North Dakota/);
    assert.equal(paperStamp("High", lead, "Significant"), "SCHEMATIC PREVIEW: HIGH");
    const custom = classified({ ...dam(), classification: { mode: "custom", methods: ["M1", "S1"] } });
    const changed = { ...custom, classification: { mode: "custom" as const, methods: ["M1", "M2", "S1"] } };
    assert.equal(hazardStatus(changed, analyze(changed)).state, "stale");
    const moved = { ...base, receptors: base.receptors.slice(1) };
    const st = hazardStatus(moved, analyze(moved));
    assert.equal(st.state, "stale");
    assert.match(st.state === "stale" ? st.why : "", /receptors/);
  });

  it("the hand-off dam does not carry the last result into dam.json", () => {
    const d = classified(dam());
    assert.ok(!("hazardResult" in handoffDam(d)));
  });
});

describe("Report copy", () => {
  const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
  it("the paper sheet no longer stamps the desk screen as the jurisdiction's class", () => {
    const paper = read("../../components/crest/PaperReport.tsx");
    assert.doesNotMatch(paper, /DESK SCREEN:|NORTH DAKOTA DAM SAFETY SCREENING/);
    assert.match(paper, /paperStamp\(level, lead, hazardClass\)/);
    assert.match(paper, /Schematic preview only \(ND \/ ACER TM 11 desk rules, not \{chosen\}; not the DamIT classification\)/);
  });
  it("the Report step leads with damit:classify's result, above the paper sheet and the desk screen", () => {
    const desk = read("../../components/crest/desk.tsx");
    const report = desk.slice(desk.indexOf("function ReportStep("));
    assert.ok(report.indexOf("<HazardLead") > 0 && report.indexOf("<HazardLead") < report.indexOf("<PaperReport"));
    assert.match(desk, /Desk screen: schematic preview/);
    assert.match(desk, /receptors,\n/); // the Classify job sends the receptor layers
  });
});
