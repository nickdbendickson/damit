import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { analyze } from "./engine.ts";
import {
  affected,
  hydrographSvg,
  PAPER_DISCLAIMER,
  PAPER_NOTICE,
  PAPER_ROW_CAP,
  paperFlags,
  paperRows,
  receptorCsv,
  receptorMetrics,
  stampClass,
} from "./paper.ts";
import { SAMPLE_DAMS } from "./samples.ts";
import type { Analysis, HazardResult } from "./types.ts";

const dam = SAMPLE_DAMS.find((d) => d.nid === "ND00199")!;
const result = analyze(dam);

describe("Style 3 paper report", () => {
  it("keeps the brief's wording", () => {
    assert.equal(
      PAPER_DISCLAIMER,
      "Screening estimate — not an official hazard classification.",
    );
    assert.match(
      PAPER_NOTICE,
      /^This is a screening-level estimate produced by DamIT Desk\. It is not an official hazard classification by any state or federal agency\./,
    );
    assert.match(PAPER_NOTICE, /full hydraulic study \(Runner \/ LISFLOOD-FP\) results\.$/);
  });

  it("hydrograph is plain SVG with a labelled peak (value and time)", () => {
    const svg = hydrographSvg(result.breach.series);
    assert.ok(svg.startsWith("<svg") && !/<script/i.test(svg));
    const peak = Math.max(...result.breach.series.map((p) => p.qCfs));
    assert.ok(svg.includes(`peak ${Math.round(peak).toLocaleString("en-US")} cfs @ `), svg);
    assert.match(svg, /<circle /);
    assert.ok(hydrographSvg([]).startsWith("<svg"));
  });

  it("front arrival and routed peak stay two columns", () => {
    const { rows } = paperRows(result);
    assert.ok(rows.length > 0);
    for (const r of rows) {
      assert.ok("front" in r && "peak" in r);
      assert.equal(r.peak, "—");
    }
    const csv = receptorCsv(result).split("\n");
    assert.match(csv[0], /Front arrival hr,Routed peak hr/);
  });

  it("caps the printed rows but the CSV has every structure and the disclaimer", () => {
    const many: Analysis = {
      ...result,
      flood: {
        ...result.flood,
        receptors: Array.from({ length: PAPER_ROW_CAP + 7 }, (_, i) => ({
          ...result.flood.receptors[0],
          id: `r${i}`,
          name: `House ${i}`,
          flooded: true,
          unresolved: false,
          depthFt: i,
        })),
      },
    };
    const p = paperRows(many);
    assert.equal(p.shown, PAPER_ROW_CAP);
    assert.equal(p.total, PAPER_ROW_CAP + 7);
    assert.equal(p.rows[0].name, `House ${PAPER_ROW_CAP + 6}`); // deepest first
    const csv = receptorCsv(many).trim().split("\n");
    assert.equal(csv.length, 1 + PAPER_ROW_CAP + 7 + 1);
    assert.equal(csv.at(-1), PAPER_DISCLAIMER);
    assert.equal(affected(many).length, PAPER_ROW_CAP + 7);
  });

  it("flags section is empty when nothing is flagged", () => {
    const clean: Analysis = {
      ...result,
      datum: { ...result.datum, warnings: [] },
      flood: { ...result.flood, warnings: [] },
    };
    assert.deepEqual(paperFlags(clean), []);
    assert.deepEqual(paperFlags(clean, ["edge wet"]), ["edge wet"]);
  });

  it("stamp class follows the level and the stamp keeps its word", () => {
    assert.equal(stampClass("High (flagged: judgment zone)"), "high");
    assert.equal(stampClass("Medium"), "medium");
    assert.equal(stampClass("Low"), "low");
    assert.equal(stampClass("Review"), "none");
  });

  it("counts damit:classify's real receptors in the table, not the desk's list", () => {
    const hazard = {
      suggestedClass: "High", ordinal: "3", classifiedAt: "", choiceKey: "", receptorKey: "", choiceText: "",
      layers: { STRUCTURES: 1666, ROADS: 263, RAIL: 34 },
      impacted: { STRUCTURES: 228, ROADS: 2, RAIL: 4 },
      wetStructures: 229,
      layerSources: { STRUCTURES: "USACE NSI (online)", ROADS: "FHWA HPMS (online)" },
    } as HazardResult;
    const rows = receptorMetrics(result, hazard);
    assert.deepEqual(rows.map((r) => [r.metric, r.value]), [
      ["Structures affected", "229 of 1,666 wet"],
      ["Road segments impacted", "2 of 263"],
      ["Rail segments impacted", "4 of 34"],
    ]);
    assert.match(rows[0]!.note, /real structures from USACE NSI \(online\)/);
    assert.ok(!rows.some((r) => /mapped/.test(r.value)));
    // An older result without the counts says how many were checked, never a desk count.
    const old = receptorMetrics(result, { ...hazard, impacted: undefined, wetStructures: undefined });
    assert.equal(old[0]!.value, "1,666 checked");
  });

  it("says the desk's own receptors when damit:classify has not run", () => {
    const [row] = receptorMetrics(result, null);
    const wet = result.flood.receptors.filter((r) => r.flooded).length;
    assert.equal(row!.value, `${wet} of ${result.flood.receptors.length} desk receptors`);
    assert.match(row!.note, /run Classify/);
  });
});
