import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { PROFILE_KEY, profileFromAddress, startProfile } from "./profile.ts";

const mem = (v: string | null) => ({ getItem: (k: string) => (k === PROFILE_KEY ? v : null), setItem: () => {} });

describe("desk profile", () => {
  it("reads ?profile=nd from the query or the fragment, any case", () => {
    assert.equal(profileFromAddress("?profile=nd"), "nd");
    assert.equal(profileFromAddress("?a=1&profile=ND"), "nd");
    assert.equal(profileFromAddress("", "#damit-token=x&profile=nd"), "nd");
    assert.equal(profileFromAddress("?profile=us"), "us");
    assert.equal(profileFromAddress("?profile=texas"), null);
    assert.equal(profileFromAddress(""), null);
  });
  it("starts from the address, else the stored choice, else us", () => {
    assert.equal(startProfile({ search: "?profile=nd", hash: "" }, mem("us")), "nd");
    assert.equal(startProfile({ search: "", hash: "" }, mem("nd")), "nd");
    assert.equal(startProfile({ search: "", hash: "" }, mem("bogus")), "us");
    assert.equal(startProfile({ search: "", hash: "" }, null), "us");
    const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => {} };
    assert.equal(startProfile({ search: "", hash: "" }, throwing), "us");
  });
});

describe("the North Dakota profile's DWR values stay in the ND picker", () => {
  it("only nd-dams.ts / nd-structures.ts ask for the DWR bundles; the Record step shows the ND pickers only for profile nd", async () => {
    const { readFileSync, readdirSync } = await import("node:fs");
    const here = new URL("./", import.meta.url);
    const users = readdirSync(here)
      .filter((f: string) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts"))
      .filter((f: string) => /loadBundle<[^>]*>\("nd_dams_dwr"\)/.test(readFileSync(new URL(f, here), "utf8")));
    assert.deepEqual(users, ["nd-dams.ts"]);
    const structureUsers = readdirSync(here)
      .filter((f: string) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts"))
      .filter((f: string) => /loadBundle<[^>]*>\("nd_structures"\)/.test(readFileSync(new URL(f, here), "utf8")));
    assert.deepEqual(structureUsers, ["nd-structures.ts"]);
    const desk = readFileSync(new URL("../../components/crest/desk.tsx", import.meta.url), "utf8");
    assert.match(desk, /profile === "nd" \? \(\s*<>\s*<NdDamPicker dam=\{dam\} \/>\s*<StructurePicker \/>\s*<\/>\s*\) : \(\s*<NidDamPicker dam=\{dam\} \/>/);
  });
});
