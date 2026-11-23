// Field mode (styles.css body.field-mode) passes WCAG AA for the text pairs the desk chrome uses.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { contrastRatio, cssVars } from "./contrast.ts";

const css = readFileSync(new URL("../../styles.css", import.meta.url), "utf8");
const field = { ...cssVars(css, ":root"), ...cssVars(css, "body.field-mode") };

describe("contrast", () => {
  it("computes WCAG ratios", () => {
    assert.equal(contrastRatio("#000000", "#ffffff").toFixed(1), "21.0");
    assert.equal(contrastRatio("#777", "#777"), 1);
  });

  it("field mode: text on the panel, page and sand pass AA (4.5:1)", () => {
    const pairs: [string, string][] = [
      ["ink", "panel"], ["ink", "bg"], ["ink", "sand"],
      ["muted", "panel"], ["muted", "bg"], ["muted", "sand"],
      ["teal", "panel"], ["panel", "teal"],
      ["flag-amber", "panel"], ["flag-amber", "amber-bg"], ["flag-green", "panel"], ["flag-green", "green-bg"], ["flag-red", "red-bg"],
      ["panel", "flag-amber"],
    ];
    for (const [fg, bg] of pairs) {
      assert.ok(field[fg] && field[bg], `${fg}/${bg} defined`);
      const r = contrastRatio(field[fg], field[bg]);
      assert.ok(r >= 4.5, `${fg} on ${bg}: ${r.toFixed(2)}`);
    }
  });

  it("field mode: class-tinted table rows, badges, pager and pills pass AA (Absaraka desk test 2026-11-21)", () => {
    const light = cssVars(css, ":root");
    // The Dashboard's wet-structure row: the row tint under the table text (ink), in both themes.
    for (const t of ["hl-high-bg", "hl-sig-bg", "hl-low-bg"]) {
      assert.ok(contrastRatio(field.ink, field[t]) >= 4.5, `field ink on ${t}: ${contrastRatio(field.ink, field[t]).toFixed(2)}`);
      assert.ok(contrastRatio(light.ink, light[t]) >= 4.5, `light ink on ${t}`);
      assert.ok(contrastRatio(field.muted, field[t]) >= 4.5, `field muted on ${t}`);
    }
    // Light theme muted text on the page and sand (was 4.42 / 3.98:1).
    for (const bg of ["panel", "bg", "sand"]) assert.ok(contrastRatio(light.muted, light[bg]) >= 4.5, `light muted on ${bg}: ${contrastRatio(light.muted, light[bg]).toFixed(2)}`);
    // Badges and pills: the light flag colours on their dark backgrounds.
    for (const [fg, bg] of [["flag-red", "red-bg"], ["flag-amber", "amber-bg"], ["flag-green", "green-bg"], ["teal", "teal-light"]])
      assert.ok(contrastRatio(field[fg], field[bg]) >= 4.5, `${fg} on ${bg}`);
    // The current page button: panel-coloured text on teal, both themes.
    assert.ok(contrastRatio(field.panel, field.teal) >= 4.5);
    assert.ok(contrastRatio(light.panel, light.teal) >= 4.5);
    for (const rule of [
      "body.field-mode .dash-root .badge.sig",
      "body.field-mode .text-red-700",
      "body.field-mode .dash-root .flag-pill.info",
    ])
      assert.ok(css.includes(rule), rule);
    assert.ok(/\.dash-root \.pg button\.cur \{[^}]*color: var\(--panel\)/.test(css), "pager uses var(--panel)");
    assert.ok(/tr\.hl-sig td, tr\.hl-sig th \{ background: var\(--hl-sig-bg\)/.test(css), "row tint is a variable");
  });

  it("field mode swaps the dark amber text, border and High badge for the light flag amber", () => {
    assert.ok(contrastRatio(field.amber, field.panel) < 4.5, "the reason for the override");
    for (const rule of ["body.field-mode .text-amber", "body.field-mode .bg-amber", "body.field-mode .border-amber", "body.field-mode .dash-root .chip.legacy"])
      assert.ok(css.includes(rule + " {"), rule);
  });
});
