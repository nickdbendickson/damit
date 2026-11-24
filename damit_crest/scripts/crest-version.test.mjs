import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { crestVersion, packageVersion } from "./crest-version.mjs";

describe("build version stamp", () => {
  it("uses DAMIT_BUILD_SHA in place of HEAD's SHA (CI rebuilds the committed bundle with it)", () => {
    assert.equal(crestVersion(undefined, { DAMIT_BUILD_SHA: "1a86158" }), `${packageVersion()}+1a86158`);
    assert.equal(crestVersion(undefined, { DAMIT_BUILD_SHA: "local" }), `${packageVersion()}+local`);
  });
  it("ignores a value that is not a SHA", () => {
    assert.match(crestVersion(undefined, { DAMIT_BUILD_SHA: "x; rm -rf" }), /\+([0-9a-f]{7,}|local)$/);
  });
});
