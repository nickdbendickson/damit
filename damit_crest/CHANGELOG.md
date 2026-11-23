# Changelog

## 2026-11-23 (0.1.6: refresh from DamIT Desk)

- **This folder is refreshed from [DamIT Desk 0.1.6](https://github.com/nickdbendickson/damit-desk) (`a0e588b`).**
  Packaging for the damit monorepo is unchanged: `desktop/damit_crest.ico`, `desktop/damit_crest.spec` (the packaged
  app is still named DamIT Crest), `desktop/build_mac.sh` and the `python3 run.py` install path. The live desktop app
  remains damit-desk; this is a kept-in-place snapshot.
- **US and North Dakota profiles** (Desk 0.1.4 / #12), including ND inventory, values and hand-off, and the ND
  profile reading `ndhazard:classify` receptor layers (Desk #14).
- **Absaraka desk-test fixes** (Desk #8 / #9): local-DEM terrain labels on the Flood panel, legend, map credit and
  inspector (`outline.ts`: `terrainInfo`, `stampTerrain`, `layerLabel`); real classify receptors; hand-off auto-fill;
  a needs-ruling flag; map attribution follows a re-stamped terrain layer.
- **Classify sends real structures, roads and rail** in the flood area (data folder, else NSI / HPMS / national rail).
  An unchecked layer makes the class incomplete. Rail is High only with a trains-per-day CSV.
- **Other Desk 0.1.5–0.1.6 work included:** height-multiple width is not handed off as NRCS TR-60 (Desk #11);
  cancel and time limits on plugin jobs; browser file I/O for Linux; per-profile launchers stay in the damit-desk
  repo (their tests are skipped here); desk lint cleanup (Desk #15).
- **Engine sync:** `outline.ts` now matches Desk, so it is temporarily listed as `pending` in
  `scripts/engine-sync-allow.json` until the paired DWR_Plugins `dwr_crest/outline.ts` update is on main. The other
  engine files still match `dwr_crest` (allow-listed `engine.ts` / `warnings.ts` wording aside).
- The committed desktop web bundle is rebuilt from this tree (`npm run build:desktop`).

## 2026-11-22 (desk TR-60 is not handed off as NRCS TR-60)

- **The desk's "TR-60 width" is now "Height-multiple width (2H piping, 3H overtopping; screening)", and the flood-model
  hand-off refuses it.** It was always a screening opening from the dam height; the Runner's TR-60 is the NRCS
  1,100·Br^1.35 peak, so a hand-off ran a different breach without saying so (Absaraka audit: at 110 ft and 5,000 ac-ft,
  388,588 cfs against the desk's 91,317). The run button now stops with a message naming the difference; choose
  Froehlich 2008 or MacDonald for the model run. A shared default of NRCS TR-60 starts new records on Froehlich (2008)
  with a note, instead of on the desk's width. Desk results are unchanged.

## 2026-11-22 (0.1.3: NSI structures for dams outside North Dakota)

- **A dam picked from the NID outside North Dakota now gets its structures from the USACE National Structure
  Inventory (NSI), the way ND dams get their 911 address points.** Before, the NID picker already marked those dams
  `receptorSource: "nsi"`, but nothing read it, so the desk ranked no structures outside ND unless you added your own.
  New `src/lib/crest/nsi.ts`: one on-request query of the public NSI API (`nsi.sec.usace.army.mil/nsiapi/structures`)
  for the strip's padded box, saved with the dam (the same cache as the 911 points, so the list, map, "Add for
  review", the pads and the exports work unchanged and offline afterwards). Each structure is listed as its occupancy,
  building type, stories and the NSI's day / night population ("about 2 people at night, 2 by day"), with its NSI id.
  The NSI holds no address or name. The 911 panel takes NSI wording for an NSI dam; ND dams are unchanged. The
  connect-src of the Content-Security-Policy names the NSI host; the desktop bundle is rebuilt. Tests: `nsi.test.ts`.
  Screen numbers are unchanged until structures are added for review, as with the 911 points.

## 2026-11-21 (default Manning's n 0.05)

- **Default floodplain Manning's n is 0.05 (was 0.06). This changes results for records without their own n.**
  damit_crest follows the suite: DamIT Core 0.3.3 (#160) moved the shared `manning_n` to 0.05, and DamIT Desk
  (damit-desk #8) and ND Crest (DWR_Plugins #460) moved with it. `SUITE_VALUES.manning_n` (the copy of the shared
  defaults file) and the built-in floodplain n (`DEFAULT_ROUGHNESS.nFloodplain`, `routing.ts`) are now 0.05.
  A record that sets its own n is unchanged. A record left on the default gets a different routed flood and needs
  its terrain layer built again. The LISFLOOD export writes `fpfric 0.0500`. The channel n stays 0.035.
  The engine files match ND Crest's again, so `scripts/engine-sync-allow.json` needs no entry for it.
