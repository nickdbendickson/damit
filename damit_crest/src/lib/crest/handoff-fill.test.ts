// Auto-fill of the Export & Hand-off form (handoff-fill.ts). Absaraka desk test 2026-11-21.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fillPlan, rasterRoles } from "./handoff-fill.ts";

const FILES = ["lisflood_hmax_ft.tif", "lisflood_vmax_fps.tif", "lisflood_wsemax_ft.tif", "dvmax.tif", "notes.txt"];
const AUTO = {
  dem: "/w/dem/cass_10m_3dep.vrt",
  rasters: { "lisflood_hmax_ft.tif": "/w/run/lisflood_hmax_ft.tif", "lisflood_vmax_fps.tif": "/w/run/lisflood_vmax_fps.tif", "lisflood_wsemax_ft.tif": null },
  railLookup: "/w/rail_trains_lookup.csv",
};

describe("hand-off auto-fill", () => {
  it("maps run files to the fields they fill, skipping what is not a max grid", () => {
    assert.deepEqual(rasterRoles(FILES), { depth: "lisflood_hmax_ft.tif", velocity: "lisflood_vmax_fps.tif", wse: "lisflood_wsemax_ft.tif" });
  });

  it("fills blank fields only, says what it filled, and names a file it could not find", () => {
    const p = fillPlan({ velocity: "/mine/v.tif" }, FILES, AUTO, "the LISFLOOD run");
    assert.deepEqual(p.set, { dem: AUTO.dem, depth: "/w/run/lisflood_hmax_ft.tif", railLookup: AUTO.railLookup });
    assert.equal(p.note, "Filled from the desk: DEM (the desk's local DEM); depth from the LISFLOOD run; rail lookup (rail_trains_lookup.csv). Edit any field to change it.");
    assert.deepEqual(p.unresolved, ["lisflood_wsemax_ft.tif"]);
  });

  it("with everything typed, nothing changes and there is no note", () => {
    const all = { dem: "a", depth: "b", velocity: "c", wse: "d", railLookup: "e" };
    const p = fillPlan(all, FILES, AUTO);
    assert.deepEqual(p.set, {});
    assert.equal(p.note, null);
  });
});
