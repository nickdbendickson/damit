import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { analyze } from "./engine.ts";
import { floodStrip } from "./floodstrip.ts";
import { bandAt, fetchStructures, nd911Seed, nd911State, nd911Table, structureWords, wantsNd911Lookup } from "./nd911.ts";
import { fetchNsi, NSI_API, NSI_ATTRIBUTION, NSI_ID_PREFIX, nsiQueryUrl, readNsiPoints, structureSource } from "./nsi.ts";
import { cspDirectives } from "./csp.ts";
import { SAMPLE_DAMS } from "./samples.ts";
import type { DamRecord } from "./types.ts";

/** A real NSI answer (12 of 72 structures in a small box below Lake Delhi Dam, Iowa), saved 2026-11-22 with the
 * kept fields plus one the desk ignores (sqft). */
const FC = JSON.parse(readFileSync(new URL("./__fixtures__/nsi_delhi_ia.json", import.meta.url), "utf8"));

const fake = (body: unknown, ok = true, status = 200) => {
  const urls: string[] = [];
  const fn = async (url: string) => {
    urls.push(url);
    return { ok, status, json: async () => body };
  };
  return { fn, urls };
};

describe("NSI structures (nsi.ts)", () => {
  it("reads points with the kept fields, an NSI id, a plain description and the population estimates", () => {
    const pts = readNsiPoints(FC.features);
    assert.equal(pts.length, FC.features.length);
    for (const [i, p] of pts.entries()) {
      const src = FC.features[i].properties;
      assert.equal(p.nguid, `${NSI_ID_PREFIX}${src.fd_id}`);
      assert.equal(p.placeType, src.occtype);
      assert.equal(p.popNight, src.pop2amu65 + src.pop2amo65);
      assert.equal(p.popDay, src.pop2pmu65 + src.pop2pmo65);
      assert.equal(p.foundHtFt, src.found_ht);
      assert.match(p.address, new RegExp(`\\(NSI ${src.fd_id}\\)$`));
      assert.ok(!("sqft" in p), "fields the desk does not keep are not copied");
    }
    const house = pts.find((p) => p.placeType.startsWith("RES1"))!;
    assert.match(house.address, /^residential \(RES1/);
    assert.match(house.address, /about \d+ (person|people) at night, \d+ by day/);
  });

  it("asks the API for the box as a closed lon,lat ring in GeoJSON", () => {
    const u = new URL(nsiQueryUrl([-91.335, 42.43, -91.325, 42.436]));
    assert.equal(`${u.origin}${u.pathname}`, NSI_API);
    assert.equal(u.searchParams.get("fmt"), "fc");
    const ring = u.searchParams.get("bbox")!.split(",").map(Number);
    assert.equal(ring.length, 10);
    assert.deepEqual(ring.slice(0, 2), ring.slice(8));
  });

  it("fetches one box, de-duplicates, and refuses a box too big for one request", async () => {
    const { fn, urls } = fake({ type: "FeatureCollection", features: [...FC.features, FC.features[0]] });
    const c = await fetchNsi([-91.335, 42.43, -91.325, 42.436], fn, new Date("2026-11-22T00:00:00Z"));
    assert.equal(urls.length, 1);
    assert.equal(c.points.length, FC.features.length);
    assert.equal(c.source, NSI_API);
    assert.equal(c.attribution, NSI_ATTRIBUTION);
    await assert.rejects(fetchNsi([-92, 41, -90, 43], fn), /square degrees/);
    await assert.rejects(fetchNsi([-91.3, 42.4, -91.2, 42.5], fake({}, false, 503).fn), /HTTP 503/);
  });

  it("is the source for a picked non-ND dam; ND dams keep the 911 points", () => {
    assert.equal(structureSource({ receptorSource: "nsi" }), "nsi");
    assert.equal(structureSource({ receptorSource: "nd911" }), "nd911");
    assert.equal(structureSource({}), "nd911");
    assert.equal(structureWords({ receptorSource: "nsi" }).noun, "NSI structures");
  });
});

describe("NSI structures through the 911 list (nd911.ts)", () => {
  const ND = SAMPLE_DAMS.find((d) => d.nid === "ND00199")!;
  const RESULT = analyze(ND);
  const STRIP = floodStrip(ND, RESULT).strip!;
  // the fixture's points moved inside this strip so the list / seed path can be exercised: the 911 fixture's own
  // points that the strip holds give known inside positions
  const PAGE911 = JSON.parse(readFileSync(new URL("./__fixtures__/nd911_nd00199.json", import.meta.url), "utf8"));
  const inside = (PAGE911.features as { geometry: { coordinates: number[] } }[])
    .map((f) => f.geometry.coordinates)
    .filter(([lon, lat]) => bandAt(STRIP, lon, lat));

  it("looks up, lists and seeds NSI structures with NSI wording", async () => {
    const dam: DamRecord = { ...ND, receptorSource: "nsi", nd911: undefined, nd911AutoAdded: undefined, receptors: [] };
    const st0 = nd911State(dam, STRIP, true);
    assert.equal(st0.state, "lookup");
    assert.match(st0.message, /NSI structures are not looked up yet .*National Structure Inventory/);
    assert.ok(wantsNd911Lookup(dam, st0));
    assert.ok(inside.length >= 3);
    const near = FC.features.slice(0, 3).map((f: { properties: unknown }, i: number) => ({
      ...f,
      geometry: { type: "Point", coordinates: inside[i] },
    }));
    const { fn } = fake({ type: "FeatureCollection", features: near });
    const cache = await fetchStructures(dam, STRIP, fn);
    assert.equal(cache.source, NSI_API);
    const t = nd911Table({ ...dam, nd911: cache }, STRIP, cache);
    assert.equal(t.total, 3);
    assert.equal(t.rows.length, 3);
    for (const r of t.rows) {
      const seed = nd911Seed(r, RESULT);
      assert.match(seed.name, /^NSI: /);
    }
    const ready = nd911State({ ...dam, nd911: cache }, STRIP, false);
    assert.equal(ready.state, "ready");
  });

  it("the page may fetch the NSI host (CSP connect-src)", () => {
    assert.ok(cspDirectives()["connect-src"].includes("https://nsi.sec.usace.army.mil"));
  });
});
