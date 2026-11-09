// Bundle age (data-provenance.ts): the inventories' pull times compared to an injected "now".
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ageWords, BUNDLE_STALE_DAYS, bundleAge, bundleAgeLine, deskBundles, staleBundleBanner } from "./data-provenance.ts";
import { loadNidData } from "./nid-dams.ts";

const NID = "2026-10-29T21:56:00Z";

describe("bundleAge", () => {
  it("counts whole days and months from the pull to now, and never negative", () => {
    assert.deepEqual(bundleAge(NID, new Date("2026-11-07T00:00:00Z")), { pulledUtc: NID, days: 8, months: 0, stale: false });
    assert.deepEqual(bundleAge(NID, new Date("2027-06-01T00:00:00Z")), { pulledUtc: NID, days: 214, months: 7, stale: true });
    assert.equal(bundleAge(NID, new Date("2026-10-01T00:00:00Z"))!.days, 0);
    assert.equal(bundleAge(null, new Date()), null);
    assert.equal(bundleAge("not a date", new Date()), null);
  });

  it("is stale past 180 days, not before", () => {
    const pulled = "2026-01-01T00:00:00Z";
    assert.equal(bundleAge(pulled, new Date(`2026-01-01T00:00:00Z`))!.stale, false);
    assert.equal(bundleAge(pulled, new Date(Date.parse(pulled) + BUNDLE_STALE_DAYS * 86_400_000))!.stale, false);
    assert.equal(bundleAge(pulled, new Date(Date.parse(pulled) + (BUNDLE_STALE_DAYS + 1) * 86_400_000))!.stale, true);
    assert.equal(ageWords(bundleAge(pulled, new Date("2026-01-02T00:00:00Z"))!), "1 day");
    assert.equal(ageWords(bundleAge(pulled, new Date("2026-03-01T00:00:00Z"))!), "1 month");
  });
});

describe("banner and lines", () => {
  const bundles = deskBundles({ nidFetchedUtc: NID });

  it("no banner while the extract is fresh", () => {
    assert.equal(staleBundleBanner(bundles, new Date("2026-11-07T00:00:00Z")), null);
    assert.equal(bundleAgeLine(bundles[0], new Date("2026-11-07T00:00:00Z")), "NID inventory pulled 2026-10-29 (8 days old)");
  });

  it("names the stale extract, its state, its age and how to refresh it", () => {
    const one = staleBundleBanner(deskBundles({ nidFetchedUtc: NID }), new Date("2027-06-01T00:00:00Z"));
    assert.equal(one, 'NID inventory is 7 months old (pulled 2026-10-29); "Download latest" in the NID picker refreshes it.');
    const tx = deskBundles({ nidFetchedUtc: NID, state: "TX" });
    assert.match(bundleAgeLine(tx[0], new Date("2027-06-01T00:00:00Z"))!, /^NID inventory \(TX\) pulled 2026-10-29 \(7 months old; stale, past 180 days: "Download latest" in the NID picker refreshes it\)$/);
  });

  it("is the NID extract only (no DWR or structures lists), and nothing when its source is unknown", () => {
    assert.deepEqual(deskBundles({}).length, 0);
    assert.equal(deskBundles({ nidFetchedUtc: null }).length, 1);
    assert.equal(bundleAgeLine(deskBundles({ nidFetchedUtc: null })[0], new Date()), null);
  });

  it("the committed example extract is not stale as of the day it was pulled", async () => {
    const nd = await loadNidData();
    const b = deskBundles({ nidFetchedUtc: nd.nidSource.fetchedUtc, state: nd.state });
    assert.equal(staleBundleBanner(b, new Date("2026-11-07T00:00:00Z")), null);
    assert.equal(nd.state, "ND");
  });
});
