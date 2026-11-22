# Changelog

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
