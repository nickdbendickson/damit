# Changelog

## 2026-11-22 (desk TR-60 is not handed off as NRCS TR-60)

- **The desk's "TR-60 width" is now "Height-multiple width (2H piping, 3H overtopping; screening)", and the flood-model
  hand-off refuses it.** It was always a screening opening from the dam height; the Runner's TR-60 is the NRCS
  1,100·Br^1.35 peak, so a hand-off ran a different breach without saying so (Absaraka audit: at 110 ft and 5,000 ac-ft,
  388,588 cfs against the desk's 91,317). The run button now stops with a message naming the difference; choose
  Froehlich 2008 or MacDonald for the model run. A shared default of NRCS TR-60 starts new records on Froehlich (2008)
  with a note, instead of on the desk's width. Desk results are unchanged.

## 2026-11-21 (default Manning's n 0.05)

- **Default floodplain Manning's n is 0.05 (was 0.06). This changes results for records without their own n.**
  damit_crest follows the suite: DamIT Core 0.3.3 (#160) moved the shared `manning_n` to 0.05, and DamIT Desk
  (damit-desk #8) and ND Crest (DWR_Plugins #460) moved with it. `SUITE_VALUES.manning_n` (the copy of the shared
  defaults file) and the built-in floodplain n (`DEFAULT_ROUGHNESS.nFloodplain`, `routing.ts`) are now 0.05.
  A record that sets its own n is unchanged. A record left on the default gets a different routed flood and needs
  its terrain layer built again. The LISFLOOD export writes `fpfric 0.0500`. The channel n stays 0.035.
  The engine files match ND Crest's again, so `scripts/engine-sync-allow.json` needs no entry for it.
