# Boann: the suite's own flood engines (DamSafety Runner)

As of DamSafety Runner 3.42.x (2026-11-22). Boann lives in DWR_Plugins
`DamSafety_Runner/core/metalflood/`; a byte-identical copy of the shared files is in
`DamSafety_Screening/core/metalflood/` (Screening's tests check it). DamIT's Runner has the ACC engine
only (`damit_runner/core/metalflood/`). **Boann is not LISFLOOD-FP**: reports, the run manifest and
the classification record name the engine. Confirm a final hazard classification with LISFLOOD-FP.

Names: **BoannHydro** = the flood solvers below; **BoannGrid** = the terrain conditioner (channel and
ditch burns, culvert carve, levee raise, freeze mask that protects dam crests).

## The engines and how to choose one

Chosen with the Runner's "Flood engine" field, or the engine word wherever a LISFLOOD-FP executable
is asked for (also CLI `model.lisflood_exe`). `core/lisflood.resolve_exe` is the one map from word
to engine; a test checks every word.

| Word | Scheme | Use it for | Notes |
|---|---|---|---|
| `gpu` | ACC: LISFLOOD-FP 8.3's local-inertial scheme on the GPU | Same answer as LISFLOOD-FP ACC, much faster on a Mac | Matches LF 8.3 on the same deck (DWR-2801 30 m: CSI 1.000, depth MAE 0.001 ft) |
| `gpu-fv` (`shock`) | FV1: first-order HLLC finite volume, full shallow-water equations | Steep dam-break fronts, hydraulic jumps | CFL capped at 0.45 |
| `gpu-fv2` | FV2: MUSCL reconstruction + SSP-RK2 | Sharper fronts than FV1 | CFL capped at 0.45 |
| `gpu-dg2` | DG2: second-order RK discontinuous Galerkin (slope-decoupled, as LF 8.0) | Highest order | CFL capped at 1/3. Slope limiter ON by default (float32 round-off at a standing lake otherwise grows until the step collapses); `.par` keyword `nolimitslopes` turns it off, for dynamic flows only |
| `gpu-sgc` | ACC with LISFLOOD-FP-style sub-grid channels (SGC) | Rivers narrower than a cell | Lake Delhi 2010: mean +1.20 ft at 8 USGS marks, about LF 8.3 SGC (+1.07) and half the ACC bias (+2.06) |
| `gpu-subfv` | Sub-grid FV (Devi & Kuiry 2024): HLLC on a coarse grid of dx·r, each cell keeping its r×r LiDAR sub-cells as stage tables | Big domains at LiDAR detail: r² cheaper, outputs downscaled to the native grid | Runner only (not Screening). `.par` keyword `subgrid <r>`, run-tool `SUBGRID_R` 1-8, blank = 4 |

Where it runs: the Mac's Metal GPU when there is one, else the CPU build of the same kernels (needs a
C++ compiler; one core; for testing, not speed). `DAMSAFETY_MF_BACKEND=metal|cpu` forces one. The GPU
and CPU builds give the same numbers (tests, and on real Apple GPUs in CI). Speed-ups seen on an M2
Pro: about 18-30x over LISFLOOD-FP on the CPU. Metal kernels are limited to 31 buffers, which shapes
the FV2/DG2 layouts.

## Run controls

- **CFL and THETA** are advanced run-tool numbers (`.par` keywords `cfl`, `theta`; also
  `initial_tstep`). Blank = engine default, so a default run is unchanged. Each solver clamps CFL to
  its own ceiling (DG2 1/3, FV 0.45). Time step: `dt = cfl·dx/√(g·h_max)` (ACC), on `|u|+√(gh)` for
  the FV family.
- **Automatic damped re-run:** a run with more than 1 % volume error (`STABILITY_RETRY_PCT`) is run
  once more at theta 0.7 / CFL 0.5 (`STABLE_THETA`, `STABLE_CFL`), and later runs of the dam keep
  those settings (`lisflood/stable_settings.json`). It covers every Boann engine (they write a
  `.mass` file); the log names the engine.
- **Manning n default is 0.05** (was 0.06 until Runner 3.27.0, all entry points). A spatially varying
  NLCD table is preferred when available.
- **BoannGrid below-water channel carve** (`carve_channels`, Runner 3.40.0) is research-gated and is
  NOT part of a default run.
- `physicalinflow` in the `.par`: the breach cell counts the step's inflow as available water (mass-
  conserving, differs from LISFLOOD-FP at the breach cell by up to 0.2 m). Default follows LF order.

## Known behaviours and traps

- **Valley ponds flat behind an open edge (sub-grid FV):** on Runner 3.42.0 and earlier, `gpu-subfv`
  padded the grid up to a multiple of r with high ground and read the east and south open-edge
  profiles from the padding, so those edges had **zero outflow** whenever the deck's rows or columns
  were not a multiple of r. Lake Delhi (1982×2314 cells) was walled at r=3, 4 and 8: lower valley
  +17 ft at the high-water marks, outflow 0.1 % of inflow. The fix is Runner 3.42.1 (DWR_Plugins PR
  #462, open on 2026-11-22; check whether it has merged): at r=8 outflow 77 %, bridges within about 1 ft. **Tell:** the run's `.mass` Qout stays near
  zero while the stored volume keeps rising. Check outflow before roughness, conveyance or the
  boundary condition (three wrong diagnoses were written before anyone looked).
- An r-sweep on the unfixed code misleads: r=1 and r=2 can drain while r=3+ is walled, which looks
  like a resolution effect.
- **LISFLOOD-FP 8.3 SGC limit-cycles** on a steep prismatic channel (Qout oscillates, reads about
  7.6 cm below analytic Manning); Boann SGC is stable and within about 3 cm. A Boann-vs-LF in-channel
  gap of 5-9 cm there is LF reading low, not Boann high.
- **Breach inflow cell depth** follows LISFLOOD-FP's DryCheck order by default and so changes with
  CFL (3.32 m at 0.7, 2.65 m at 0.5 on DWR-2801); not an engine error.
- Arithmetic is float32 on the GPU (Apple GPUs have no float64); beds are stored relative to the
  lowest cell so depths keep about 1e-5 m resolution; volumes are summed in float64 on the host.
- Boann runs only on macOS for the GPU path; LISFLOOD-FP's GPU path is CUDA only; ANUGA is CPU/MPI.

## Mesh decision

Boann stays on a structured square grid (GPU lockstep). Unstructured or triangle meshes are ANUGA's
job. Channel and breakline detail comes from SGC, sub-grid FV and BoannGrid conditioning, not from
the mesh. BoannGrid conditioning is not baked into terrain exported to HEC-RAS (RAS uses breaklines).
