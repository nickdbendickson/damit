# Modeling findings and fix provenance

Empirical results from real dam runs and the reasoning behind results-changing fixes.
This is the "why" that the `metadata.txt` changelogs point at but don't fully explain —
feed it to Heim so a triage of engine / solver code starts from what has already been
measured, not from first principles.

The per-plugin fix log itself lives in each plugin's `metadata.txt` `changelog=` (and
`docs/CHANGELOG.md` for the archived entries); Heim already indexes those. This file adds
the run-analysis context that is not in the code.

---

## Grid convergence and over-spread (Absaraka / DWR-2801)

- Flood area **shrinks as the grid refines** — a grid artifact, not physics. Use >= 10 m on
  flat plains.
- Versus the DSS-WISE reference, every solver is 0-11% **wider** than ACC at matched sim
  time; none is tighter and none nears DSS-WISE. So the over-spread is **terrain and
  crest-resolution**, not the numerical solver. The fix was crest-burn plus a finer grid
  (auto 10 m record rerun when over-spread), not a solver change.
- CSI ~0.34-0.37 is **model-grade**: three independent 2-D models agree only ~0.3-0.5 at a
  0.1 ft threshold. Don't read a low CSI as a bug.
- The flood is often **still spreading at 12-24 h** on flat terrain (ACC 2899 -> 3550 ac,
  +22%, 12 h -> 24 h at one case). Don't cap max-extent runs short.

## Solver comparison (the solver is not the lever)

- Matched-time downstream area, 20 m 2801 (DSS-WISE = 2242 ac): at 12 h ACC 2899 / FV1 3084
  / FV2-LL 2974 / MWDG2-LL 2974. Every higher-order / shock solver is 0-11% wider than ACC;
  none tighter. Confirms the over-spread is terrain/crest, not numerics.
  **Caveat (QA 2026-11-06):** the FV2-LL and MWDG2-LL depth rasters behind these numbers
  are byte-identical (same SHA-256, every pixel), so those two solver labels are invalid.
  Keep the numbers as published, but don't cite them as FV2 or MWDG2 results.
- **FV2 / MWDG2 are CUDA-only.** LISFLOOD-FP has no CPU implementation of FV2+`limitslopes`
  or MWDG2+`limitslopes`: a CPU-only binary prints the solver banner, then silently runs
  IterateQ adaptive (the same as a no-keyword deck); adding `cuda` on a non-CUDA build
  aborts. A "FV2-LL" / "MWDG2-LL" raster from a CPU-only build is not a real run of
  those solvers.
- **Rerun 2026-11-06 (20 m 2801, CPU-only, crest 1071.09 ft NAVD88 — the DSS-WISE study
  crest, not suite A1 1072.24; not the product of record).** ACC, FV1 and DG2-LL completed;
  FV2-LL / MWDG2-LL could not run (no CUDA). Wet area at >= 0.1 / 0.5 / 1 ft, max depth,
  wall time: ACC 7253 / 3897 / 2148 ac, 10.68 ft, 7.8 min; FV1 7467 / 4100 / 2235 ac,
  10.77 ft, 15.3 min; DG2-LL 9614 / 5078 / 2553 ac, 9.64 ft, 955 min. CSI vs ACC: FV1
  0.82 / 0.86 / 0.88; DG2-LL 0.70 / 0.67 / 0.68. DG2-LL wets ~30% more area at 0.5 ft
  for ~120x the run time, so it isn't worth it for screening.
- **Velocity is solver-sensitive (unlike depth).** In the DSS-WISE wet footprint (ft/s):
  reference mean ~1.1 / p95 ~3.3; ACC mean ~1.5 / p95 ~4.4 with a spurious ~27 ft/s
  wet-dry-front spike. The earlier "FV2-LL and MWDG2-LL damp the mean below the reference"
  result comes from the invalidated runs above (their Vmax files also differ while their
  Hmax files match, which is a provenance red flag). Velocity deserves a dedicated
  like-for-like study (consistent `maxVc`, spike filtering, a real CUDA build for FV2 or
  MWDG2) before its numbers are trusted.
- **FV1 and plain `dg2` write no max-velocity field** (`run.maxVc`) in the bundled 8.1
  binary; ACC / FV2 / MWDG2 do. This is why the Runner refuses FV1 / plain DG2 for a main
  run and why the velocity-missing guards (Runner 3.17.4/3.17.5) exist — a build with no
  `.maxVc` must not be read as velocity 0 off the v=0 danger curves.

## Mass balance and outflow accounting

- **ACC mass-balance auto-rerun:** volume error > 1% -> automatic damped rerun (theta 0.7,
  CFL 0.5). One case went 365% -> 0%; another 36% / 8.3 ft -> 0% / 2.7 ft.
- **Boundary outflow:** LISFLOOD-FP `.mass` Qout is surfaced as `boundary_outflow_acft/_pct`;
  at >= 5% of the breach volume the run warns that area and consequences are minimums. Once
  a configurable share has left, edges carrying >= 10% of the leaving water (depth^(5/3)
  weighted) and wet past the arrival depth are extended outward (the Grok-audit 3.1 fix).

## FV1 blow-up cause

The near-dam refine box's FREE south edge sits in the reservoir basin where back-flowed
breach water ponds; LISFLOOD-FP 8.1 FV1 imports water across a FREE edge and grows
exponentially (depth reached tens of thousands of ft). ACC is stable; closing that edge
fixes it. The `FREE <slope>` value has no effect with FV1. Mitigation: `REFINE_NEAR=false`.

## Crest burn and terrain

- **Crest burn ON** (road / rail raised <= 1 m) plus the auto 10 m record rerun when
  over-spread; the 5 m check is off. This is the lever for the 2801 over-spread, not the
  solver.
- **ANUGA terrain cell** (off by default): reads the fine DEM over the dam footprint only
  (1-2 m), to resolve the crest without a statewide fine grid.
- Statewide ND 1 m terrain is a VRT (EPSG:26914, NAVD88); DWR `local_dem()` auto-picks and
  clips per dam. USGS 1 m has no coverage at Fort Berthold and Spirit/Devils Lake; DWR https
  tiles fill the gaps. Gaps read as NoData = high ground; the Runner warns if the flood
  touches a gap.
- To check the grid a run actually used, open `Model Terrain (LISFLOOD).tif` (Runner
  3.17.7+), not `run.dem.asc`, which has no georeferencing.

## Hazard classification parity

The Runner, Screening and Hazard classify against the **same** digitized REG_05.2026 /
ACER TM-11 curve table (`damsuite.tm11_curves`): a depth on a boundary takes the higher
zone; beyond the axes is high danger. A structure outline is read over cells whose centre is
in the outline or within the 5 ft edge ring; a point structure over cells within 20 ft plus
the ring. Peak velocity is taken over all wet (depth > 0) cells. These choices only ever
raise a zone against the older rules, never lower it (the parity fixes in Runner 3.16.x).

## Safety-number audit changes (2026-11-10)

Hazard 2.24.4 (M04 bulk read) and Runner 3.17.9 (M16 window scan) were required to be
bit-identical to the old code: M04 was checked across 302 cases including the Population
path, and the M16 golden baseline passes unchanged. A results difference traced to either
change is a bug, not an expected shift.

---

_Values are point-in-time from specific runs; treat them as orders of magnitude, not fixed
constants, and re-measure before quoting a number in a deliverable._
