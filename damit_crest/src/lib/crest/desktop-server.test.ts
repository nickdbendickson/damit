import { test } from "node:test";
import assert from "node:assert/strict";
import { crestApiHeaders, hasDesktopServer, splitTokenFragment } from "./desktop-server.ts";

test("token is read from the fragment and removed from it", () => {
  assert.deepEqual(splitTokenFragment("#damit-token=abc_DEF-123"), { token: "abc_DEF-123", rest: "" });
  assert.deepEqual(splitTokenFragment("#a=1&damit-token=xyz&b=2"), { token: "xyz", rest: "#a=1&b=2" });
});

test("no token in the fragment leaves it as it was", () => {
  assert.deepEqual(splitTokenFragment(""), { token: "", rest: "" });
  assert.deepEqual(splitTokenFragment("#view=map"), { token: "", rest: "#view=map" });
  assert.deepEqual(splitTokenFragment("#not-damit-token=1"), { token: "", rest: "#not-damit-token=1" });
});

test("outside a desktop page there is no server and an empty token header", () => {
  assert.equal(hasDesktopServer(), false);
  assert.equal(crestApiHeaders(true)["X-DamIT-Token"], "");
  assert.equal(crestApiHeaders(true)["Content-Type"], "application/json");
});
