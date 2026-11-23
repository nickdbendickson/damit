import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { deriveRecord, nearRequest, selectStructures } from "./batch.ts";
import { dwrElevationOffer } from "./nd-dams.ts";
import { ND_DEFAULT_STATUSES, ND_KINDS, loadNdStructures, ndInventory, ndStructureRecord } from "./nd-structures.ts";
import type { DemGrid, DemRequest } from "./outline.ts";

/** A valley running south with an 8 m embankment across it at (lon0, lat0); ground 500 m at the point. */
function valleyDem(lon0: number, lat0: number) {
  const kx = 111320 * Math.cos((lat0 * Math.PI) / 180);
  const z = (lon: number, lat: number) => {
    const e = (lon - lon0) * kx;
    const n = (lat - lat0) * 110574;
    let v = 500 + 0.01 * n + 0.03 * Math.abs(e);
    if (Math.abs(n) < 10 && Math.abs(e) < 150) v += 8;
    return v;
  };
  return async (req: DemRequest): Promise<DemGrid> => {
    const g = new Float32Array(req.width * req.height);
    for (let j = 0; j < req.height; j++)
      for (let i = 0; i < req.width; i++)
        g[j * req.width + i] = z(req.bbox[0] + ((i + 0.5) / req.width) * (req.bbox[2] - req.bbox[0]), req.bbox[3] - ((j + 0.5) / req.height) * (req.bbox[3] - req.bbox[1]));
    return { ...req, z: g };
  };
}

describe("North Dakota structure list (nd-structures.ts)", () => {
  it("loads NID dams, DWR dams, dugouts and unknown structures, each once, with HUC8 watersheds", async () => {
    const { structures } = await loadNdStructures();
    assert.deepEqual([...new Set(structures.map((s) => s.kind))].sort(), [...ND_KINDS].sort());
    assert.ok(structures.length > 10000);
    assert.equal(new Set(structures.map((s) => s.id)).size, structures.length, "ids are unique");
    const withHuc = structures.filter((s) => s.huc8 && /\(\d{8}\)$/.test(s.huc8)).length;
    assert.ok(withHuc / structures.length > 0.999);
    // ND00199 (Absaraka) is the NID entry, not a duplicate DWR one.
    assert.equal(structures.filter((s) => s.nid === "ND00199").length, 1);
    // UNK-2400 (Nordell) is DWR-16431 now: found by its old number, not listed twice.
    const nordell = selectStructures(structures, { by: "pick", ids: ["UNK-2400"], kinds: [], statuses: [] });
    assert.deepEqual(
      nordell.map((s) => s.id),
      ["DWR-16431"],
    );
    // The default selection keeps the ND statuses on and every kind listed.
    const county = selectStructures(structures, { by: "state", kinds: [...ND_KINDS], statuses: [...ND_DEFAULT_STATUSES] });
    assert.ok(county.some((s) => s.kind === "dugout") && county.some((s) => s.kind === "nid"));
  });

  it("a DWR dam's record carries DWR provenance; an NID dam's carries the NID prefill", async () => {
    const { nd, structures } = await loadNdStructures();
    const dwrDam = structures.find((s) => s.kind === "dam" && s.heightFt != null)!;
    const r = ndStructureRecord(dwrDam, nd, "x");
    assert.equal(r.provenance?.heightFt?.src, "DWR");
    assert.equal(r.provenance?.heightFt?.note, "DWR Dams layer");
    assert.ok(Number.isNaN(r.crestFt), "elevations blank");
    const nid = structures.find((s) => s.id === "ND00199")!;
    const n = ndStructureRecord(nid, nd, "y");
    assert.equal(n.nidId ?? n.nid, "ND00199");
  });

  it("the batch takes DWR's NAVD 88 crest where the bundle offers it, else the terrain", async () => {
    const { nd, structures } = await loadNdStructures();
    const inv = ndInventory(nd);
    const offered = structures.find((s) => s.kind === "nid" && s.lat != null && s.heightFt != null && s.storageAcFt != null && dwrElevationOffer(nd.dwr.get(s.id)).ok)!;
    assert.ok(offered, "the bundle offers NAVD 88 elevations for some NID dams");
    const g = await valleyDem(offered.lon!, offered.lat!)(nearRequest(offered.lon!, offered.lat!));
    const withDwr = deriveRecord(offered, g, nd, "3DEP", inv);
    assert.ok(withDwr.ok);
    if (!withDwr.ok) return;
    assert.equal(withDwr.derived.crestFrom, "DWR");
    assert.match(withDwr.dam.sampleNote ?? "", /from DWR \(NAVD 88\)/);
    // Without the hooks (US path) the same structure reads its crest from the terrain.
    const plain = deriveRecord(offered, g, nd, "3DEP");
    assert.ok(plain.ok && plain.derived.crestFrom === "3DEP");
    // A structure DWR gives no elevations for falls back to the terrain even with the hooks.
    const dugout = structures.find((s) => s.kind === "dugout" && s.lat != null && s.heightFt != null && s.storageAcFt != null)!;
    const g2 = await valleyDem(dugout.lon!, dugout.lat!)(nearRequest(dugout.lon!, dugout.lat!));
    const d = deriveRecord(dugout, g2, nd, "3DEP", inv);
    assert.ok(d.ok && d.derived.crestFrom === "3DEP");
    assert.equal(d.ok && d.dam.provenance?.heightFt?.src, "DWR");
  });
});
