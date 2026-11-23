import { test } from "node:test";
import assert from "node:assert/strict";
import { crestApiHeaders, hasDesktopServer, serverNotices, splitTokenFragment, workFolderHint } from "./desktop-server.ts";

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

test("the Work folder hint names the folder the server says a blank field means", () => {
  assert.equal(workFolderHint("/workspace/damit_desk_20261121/work"), "blank = /workspace/damit_desk_20261121/work");
  assert.equal(workFolderHint("  C:\\Users\\nick\\DamITDams "), "blank = C:\\Users\\nick\\DamITDams");
  // no server (or not answered yet): the rule, never a claim that it is ~/DamITDams
  assert.equal(workFolderHint(undefined), "blank = DAMIT_WORK, else DamITDams in your home folder");
  assert.equal(workFolderHint(""), "blank = DAMIT_WORK, else DamITDams in your home folder");
});

test("server notices are plain strings, trimmed and capped", () => {
  assert.deepEqual(serverNotices(["first start: copied", "", 3, null, " x "]), ["first start: copied", "x"]);
  assert.deepEqual(serverNotices(undefined), []);
  assert.deepEqual(serverNotices({ a: 1 }), []);
  assert.equal(serverNotices(["y".repeat(900)])[0].length, 600);
  assert.equal(serverNotices(Array(9).fill("n")).length, 5);
});
