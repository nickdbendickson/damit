// The command palette's matching and keys (commands.ts).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { DESK_ACTIONS, filterCommands, isPaletteShortcut, moveActive, shortcutLabel, type PaletteCommand } from "./commands.ts";

const C: PaletteCommand[] = [
  { id: "tab-workflow", group: "Views", label: "Go to Workflow" },
  { id: "step-flood", group: "Steps", label: "Step 4: Flood" },
  { id: "run", group: "Run", label: "Run…", hint: "open the DamIT plugin run panel", keywords: ["screening"] },
  { id: "save", group: "Desk", label: "Save desk to file" },
  { id: "field", group: "Desk", label: "Field mode: turn on", keywords: ["dark"] },
  { id: "check", group: "Run", label: "Check QGIS hand-off", disabled: true },
];
const ids = (q: string) => filterCommands(C, q).map((c) => c.id);

describe("filterCommands", () => {
  it("keeps the given order for an empty query", () => assert.deepEqual(ids("  "), C.map((c) => c.id)));
  it("matches every word, in label, hint, group or keywords", () => {
    assert.deepEqual(ids("flood"), ["step-flood"]);
    assert.deepEqual(ids("dark"), ["field"]);
    assert.deepEqual(ids("screening"), ["run"]);
    assert.deepEqual(ids("desk file"), ["save"]);
    assert.deepEqual(ids("nothing like this"), []);
  });
  it("puts a label that starts with the text first, and ignores case and the ellipsis", () => {
    assert.deepEqual(ids("RUN"), ["run", "check"]); // "check" is in the Run group
    assert.equal(ids("ru")[0], "run");
    assert.equal(ids("run…")[0], "run");
  });
});

describe("keys", () => {
  const k = (key: string, o: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }> = {}) => ({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...o });
  it("Ctrl+K and Cmd+K open the palette; plain K, Ctrl+Shift+K and Ctrl+J do not", () => {
    assert.ok(isPaletteShortcut(k("k", { ctrlKey: true })));
    assert.ok(isPaletteShortcut(k("K", { metaKey: true })));
    assert.ok(!isPaletteShortcut(k("k")));
    assert.ok(!isPaletteShortcut(k("k", { ctrlKey: true, shiftKey: true })));
    assert.ok(!isPaletteShortcut(k("j", { ctrlKey: true })));
  });
  it("moveActive wraps and skips disabled commands", () => {
    assert.equal(moveActive(C, 4, 1), 0); // 5 is disabled
    assert.equal(moveActive(C, 0, -1), 4);
    assert.equal(moveActive(C, -1, 1), 0);
    assert.equal(moveActive([{ disabled: true }], 0, 1), -1);
    assert.equal(moveActive([], 0, 1), -1);
  });
  it("shows ⌘K on a Mac and Ctrl K elsewhere", () => {
    assert.equal(shortcutLabel("MacIntel"), "⌘K");
    assert.equal(shortcutLabel("Win32"), "Ctrl K");
    assert.equal(shortcutLabel("Linux x86_64"), "Ctrl K");
  });
});

describe("the new desk chrome's labels", () => {
  // UI labels use the Unicode ellipsis (…), never three dots; the palette is an accessible modal dialog.
  const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
  const files = ["../../components/crest/CommandPalette.tsx", "../../components/crest/DeskChrome.tsx", "../../components/crest/WorkflowMap.tsx"];
  it("use … not ...", () => {
    for (const f of files) {
      const jsx = read(f).replace(/\{?\.\.\.[A-Za-z[(]/g, ""); // spread syntax is not a label
      assert.ok(!/\.\.\./.test(jsx), `${f} has "..."`);
    }
  });
  it("the palette is a modal dialog with a combobox and a listbox", () => {
    const src = read(files[0]);
    for (const a of ['role="dialog"', 'aria-modal="true"', 'role="combobox"', 'role="listbox"', 'role="option"', "aria-activedescendant", '"Escape"'])
      assert.ok(src.includes(a), a);
  });
  it("the tabs are a tablist the arrow keys move along", () => {
    const src = read(files[1]);
    for (const a of ['role="tablist"', 'role="tab"', "aria-selected", '"ArrowRight"', '"ArrowLeft"', 'role="progressbar"']) assert.ok(src.includes(a), a);
  });
});

describe("desk actions in the palette (Absaraka desk test 2026-11-21)", () => {
  it("classify, dem and import run each find their command", () => {
    const all = [...C, ...DESK_ACTIONS];
    assert.equal(filterCommands(all, "classify")[0].id, "classify");
    assert.equal(filterCommands(all, "dem")[0].id, "choose-dem");
    assert.equal(filterCommands(all, "import run")[0].id, "import-run");
    assert.ok(filterCommands(all, "screening").some((c) => c.id === "screening"));
    assert.ok(filterCommands(all, "terrain layer").some((c) => c.id === "build-terrain"));
    for (const a of DESK_ACTIONS) assert.ok(!/\.\.\./.test(a.label), `${a.label} uses the Unicode …`);
  });
});
