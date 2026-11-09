# damit_crest — DamIT Crest desktop app

DamIT Crest is the DamIT desktop desk: a pywebview window around a local web desk for dam breach screening —
breach hydrograph, schematic and terrain flood views, receptor ranking, results import, a printable report and
datum-aware exports — plus the hand-off of a dam to the DamIT QGIS plugins from the **Report** step.

It is adapted from **Crest** ([nickdbendickson/crest](https://github.com/nickdbendickson/crest), `main` at `633d352`),
the North Dakota DamSafety desk. The desk engine (`src/lib/crest/engine.ts`) and its tests are carried over unchanged;
what changed is the posture and the hand-off:

- **Multi-jurisdiction.** Classification is consequence-based and jurisdiction-specific (US Dam Hazard Classification —
  Corrected Edition, Nov 9, 2026, Appendix A). The Report step has a *Jurisdiction and classification methods* panel:
  **preset mode** (a state or agency preset: FEMA 333, USBR, BIA, NRCS, ND, NE, NY, VA, TX, ID, CO, RI, AZ, CA, AK) or
  **custom mode** (tick S/D/M/R method ids, no jurisdiction names shown). The default is the FEMA 333 national
  baseline, not a state. Thresholds live in the hazard catalog data file that `damit:classify` reads, never in this
  app; the desk carries only a display index (`src/lib/crest/data/jurisdictions.json`, generated from
  `damit_hazard/data/catalog.json` by `scripts/sync-jurisdictions.mjs`).
- **DamIT hand-off.** The buttons call the DamIT plugins' `qgis_process` algorithms — `damit:classify`
  (`damit_hazard`), `damit_screen:preflight`, `damit_screen:runchain` (`damit_screener`) and `damit_run:rundam`
  (`damit_runner`), the ids those plugins publish — and the DamIT runner CLI (`damit_cli.py`). Every id can be overridden by environment variable or
  `damit-handoff.json` without a code change. The North Dakota suite's ids (`nddam:*`, `ndbreach:*`,
  `ndbreach_cli.py`) are never used, not even as a fallback. See **[docs/HANDOFF.md](docs/HANDOFF.md)**.
- **Piping by default.** A failure mode that was not chosen is piping, never overtopping, everywhere one is filled in
  (desk, `dam.json`, the DAMS layer and breach hydrograph, the CLI's `runner_config.json`).
- **Local only.** No web deploy, server-side state, sign-in, OAuth or client secret: Crest's TanStack Start / Vercel
  web app, its CI and its secret-scanning allowlists were left out.

North Dakota stays available as **optional example data**: the bundled NID / ND DWR dam picker, the ND sample dams,
ND NG911 address points and the ND batch screen still work, and an ND suite data pack (`NDSUITE_DATA`) is read as an
example data folder when no DamIT data folder is set. Nothing defaults to North Dakota.

The desk is a screen, not the layer of record, and not an official class: the engineer of record and the regulating
agency make the determination. Where its flood footprint can be trusted is in
[docs/accuracy-envelope.md](docs/accuracy-envelope.md) (carried over from Crest).

## Layout

```
damit_crest/
  README.md                 this file
  docs/HANDOFF.md           algorithm ids, overrides, what each button sends
  docs/damit-handoff.example.json
  docs/accuracy-envelope.md trust map (from Crest)
  package.json, vite.desktop.config.ts, tsconfig.json, eslint.config.mjs
  src/                      the desk (React + Leaflet); engine and libraries in src/lib/crest/
    lib/crest/jurisdiction.ts  preset / custom mode, label maps (no thresholds)
    lib/crest/handoff.ts       what the Report step sends; DamIT default ids
    components/crest/ClassificationPanel.tsx
  scripts/                  tests, data refresh for the ND example bundles, sync-jurisdictions.mjs
  desktop/                  the pywebview app (adapted from Crest's crest-desktop/)
    run.py, requirements.txt, INSTALL.txt, damit_crest.spec, build_mac.sh
    damit_desktop/          __main__ (window + local API), algorithms (hand-off ids), qgis_run, handoff, layers, localdem
    damit_desktop/web/      the built desk (committed, so `python run.py` needs no Node)
    tests/                  headless tests; fake qgis_process, nothing real is started
```

## Run it

Needs **Python 3.10 or newer** (3.14 is fine). Node is not needed to run it.

```
cd damit_crest/desktop
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Windows uses WebView2 (built into Windows 11), macOS WebKit, Linux `pywebview[qt]`. If no window backend starts, the
desk opens in the system browser. Optional packages: `pyinstaller damit_crest.spec` (Windows / Linux) or
`sh build_mac.sh` (macOS, Python 3.10–3.12) give `DamIT Crest.exe` / `DamIT Crest.app`.

The local server listens on 127.0.0.1:47241 (Crest uses 47231, so both can run). Every `/api/` call needs the
per-launch token the server puts in the page (`X-DamIT-Token`), and a job may only write under `~/DamITDams`,
`DAMIT_WORK` or `DAMIT_WORK_ROOTS`.

## Report step: DamIT plugins in QGIS

Needs QGIS 3.28–4.x with the DamIT plugins installed. The buttons do nothing in a page with no desktop server.

- **Get layers** — use the DamIT data folder (`DAMIT_DATA`, or `damit/data_folder` in `~/.damit/config.json`), or
  download a USGS 3DEP DEM and NHD streams and waterbodies for the drawn area (United States).
- **Write the dam folder** — `<work>/dams/<id>/` with `dam.json` (`damit/dam_record`, including the jurisdiction
  choice), the drawn geometries, both hydrographs, the LISFLOOD `.par` / `.bci` / `.bdy` and the flood strip. Starts
  nothing.
- **Write folder and run screening** — the preflight algorithm, then the screening chain **only if READY**, for this
  dam only. A missing algorithm or a FAIL stops there. Cancel stops `qgis_process`; `DAMIT_SCREENING_TIMEOUT_S` sets a
  limit (default none).
- **Run the flood model** — one dam: `damit_run:rundam` (with the screening's `damit_handoff.json` when there is
  one, always `DRY_RUN=true`; DamIT Runner 0.1.0 prepares and records the run and launches no engine), or a DamIT
  runner CLI when Point X and Point Y (DEM CRS) are filled. It never starts a batch algorithm (none is published; the
  name `damit_run:batch` is reserved). The DEM comes from `dem.tif` in the work folder, the DEM field, the data folder
  DEM, or `DAMIT_DEM`.
- **Classify** — hands the preset / custom choice, the model run's depth raster (typed path) and a flat dam record
  to `damit:classify`.

Every call sends only the parameters the installed algorithm's `qgis_process help` lists (docs/HANDOFF.md).

Before every run the app checks `qgis_process help <id>`; an algorithm that is not installed stops the job with the
variable to set. The log is on the Report step. Environment: `QGIS_PROCESS` (path to `qgis_process`), `DAMIT_ALG_*`,
`DAMIT_CLI`, `DAMIT_HANDOFF_CONFIG`, `DAMIT_PYTHON`, `DAMIT_DATA`, `DAMIT_DEM`, `DAMIT_WORK`, `DAMIT_WORK_ROOTS`,
`DAMIT_SCREENING_TIMEOUT_S`.

## Develop

```
cd damit_crest
npm ci
npm test                 # node tests: scripts/**/*.test.mjs and src/lib/crest/*.test.ts (incl. bundle freshness)
npm run test:desktop     # Python desktop tests, headless (fake qgis_process; no model, QGIS or Wine)
npm run typecheck && npm run lint
npm run build:desktop    # rebuild desktop/damit_desktop/web/ after changing src/, then commit it
```

`npm test` fails while the committed bundle is older than `src/`. `npm run build:html` builds an optional one-file
`DamIT.html` (not committed). `node scripts/sync-jurisdictions.mjs [catalog.json]` regenerates the preset index
from the hazard catalog (`--check` to verify). The `data:nd-*` and `batch:dams` scripts refresh and run the North
Dakota example bundles, as in Crest.

Every export carries the build (`crest_version`, `<package version>+<git sha>`, labelled "DamIT Crest") and the engine
method version (`engine_version`); the field names are Crest's so existing readers keep working.
