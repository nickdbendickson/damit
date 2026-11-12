// The NID-by-state loader (nid-state.ts): the committed ND example offline, any other state from the desktop server.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { EXAMPLE_STATE, isNidState, loadNidState, NID_STATES, stateName } from "./nid-state.ts";

const bundle = (state: string, ids: string[]) => ({
  v: 2,
  source: { url: "u", state, fetchedUtc: "2026-11-09T00:00:00Z", rows: ids.length, attribution: "NID" },
  cols: ["nid", "name", "county", "lat", "lon"],
  rows: ids.map((id) => [id, `Dam ${id}`, "Kent", 41.7, -71.5]),
});
const fakeFetch = (calls: string[], body: unknown, status = 200) =>
  (async (url: string) => {
    calls.push(url);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;

describe("NID by state", () => {
  it("lists the 50 states, DC and the territories, ND marked as the example; same codes as the desktop server", () => {
    assert.equal(NID_STATES.length, 56);
    assert.equal(EXAMPLE_STATE, "ND");
    assert.equal(stateName("RI"), "Rhode Island");
    assert.ok(isNidState("PR") && !isNidState("ZZ") && !isNidState("North Dakota"));
    const py = readFileSync(new URL("../../../desktop/damit_desktop/nid.py", import.meta.url), "utf8");
    const block = py.slice(py.indexOf("STATES = frozenset("), py.indexOf(".split()", py.indexOf("STATES = frozenset(")));
    const pyCodes = block.match(/\b[A-Z]{2}\b/g)!.sort();
    assert.deepEqual(pyCodes, NID_STATES.map(([c]) => c).sort());
  });

  it("ND loads the committed extract with no network", async () => {
    const calls: string[] = [];
    const nd = await loadNidState("nd", { fetchImpl: fakeFetch(calls, {}) });
    assert.equal(nd.state, "ND");
    assert.equal(nd.dams.length, 948);
    assert.equal(calls.length, 0);
  });

  it("another state comes from /api/nid/state once, then from memory; refresh asks again", async () => {
    const calls: string[] = [];
    const f = fakeFetch(calls, bundle("RI", ["RI00001", "RI00002"]));
    const a = await loadNidState("RI", { fetchImpl: f });
    assert.equal(a.state, "RI");
    assert.deepEqual(a.dams.map((d) => d.nid), ["RI00001", "RI00002"]);
    await loadNidState("RI", { fetchImpl: f });
    assert.deepEqual(calls, ["/api/nid/state?state=RI"]);
    await loadNidState("RI", { fetchImpl: f, refresh: true });
    assert.deepEqual(calls, ["/api/nid/state?state=RI", "/api/nid/state?state=RI&refresh=1"]);
  });

  it("errors are messages: a bad code, the server's error, no server", async () => {
    await assert.rejects(loadNidState("ZZ"), /not an NID state/);
    await assert.rejects(loadNidState("CT", { fetchImpl: fakeFetch([], { error: "the NID returned HTTP 502 Bad Gateway for this state's extract." }, 502) }), /HTTP 502.*502 Bad Gateway/);
    await assert.rejects(loadNidState("ME", { fetchImpl: fakeFetch([], null, 502) }), /HTTP 502/);
    const down = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    await assert.rejects(loadNidState("VT", { fetchImpl: down }), /desktop server/);
  });
});
