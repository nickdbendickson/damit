# Changelog

## 2026-11-21 (default Manning's n 0.05)

- **Default floodplain Manning's n is 0.05 (was 0.06). This changes results for records without their own n.**
  damit_crest follows the suite: DamIT Core 0.3.3 (#160) moved the shared `manning_n` to 0.05, and DamIT Desk
  (damit-desk #8) and ND Crest (DWR_Plugins #460) moved with it. `SUITE_VALUES.manning_n` (the copy of the shared
  defaults file) and the built-in floodplain n (`DEFAULT_ROUGHNESS.nFloodplain`, `routing.ts`) are now 0.05.
  A record that sets its own n is unchanged. A record left on the default gets a different routed flood and needs
  its terrain layer built again. The LISFLOOD export writes `fpfric 0.0500`. The channel n stays 0.035.
  The engine files match ND Crest's again, so `scripts/engine-sync-allow.json` needs no entry for it.
