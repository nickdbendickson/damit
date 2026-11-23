import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { rootLabels } from "./server-picker.ts";

describe("server picker root shortcuts", () => {
  it("names each root by its folder, with the parent when two share a name", () => {
    assert.deepEqual(
      rootLabels(["/w/desk/work", "/w/desk/work/exports", "/w/a_20261120/inputs", "/w/b_20261120/inputs", "C:\\Data\\dem"]),
      ["work", "exports", "a_20261120/inputs", "b_20261120/inputs", "dem"],
    );
    assert.deepEqual(rootLabels(["/"]), ["/"]);
  });
});
