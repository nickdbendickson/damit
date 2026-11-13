# damit_crest — DamIT Crest desktop app

DamIT Crest is the DamIT desktop desk: a pywebview window around a local web desk for dam breach screening —
breach hydrograph, schematic and terrain flood views, receptor ranking, results import, a printable report and
datum-aware exports — plus the hand-off of a dam to the DamIT QGIS plugins from the **Report** step.

It is adapted from **Crest** ([nickdbendickson/crest](https://github.com/nickdbendickson/crest), `main` at `633d352`),
the North Dakota DamSafety desk. The desk engine (`src/lib/crest/engine.ts`) and its tests are carried over unchanged;
what changed is the posture and the hand-off:

- **Multi-jurisdiction.** Classification is consequence-based and jurisdiction-specific (US Dam Hazard Classification —
  Corrected Edition, Nov 9, 2026, Appendix A). The Report step has a *Jurisdiction and classification methods* panel:
  **preset mode** (a state or agency preset: FEMA 333, USBR, BIA, NRCS, USACE, TVA, ND, NE, NY, VA, TX, ID, CO, RI, AZ, CA, AK, AL, NC) or
  **custom mode** (tick S/D/M/R method ids, no jurisdiction names shown). The default is the FEMA 333 national
  baseline, not a state. Thresholds live in the hazard catalog data file that `damit:classify` reads, never in this
  app; the desk carries only a display index (`src/lib/crest/data/jurisdictions.json`, generated from
  DamIT Catalog through DamIT Hazard's `--export` by `scripts/sync-jurisdictions.mjs`).
- **DamIT hand-off.** The buttons call the DamIT plugins' `qgis_process` algorithms — `damit:classify`
  (`damit_hazard`), `damit_screen:preflight`, `damit_screen:runchain` (`damit_screener`) and `damit_run:rundam`
  (`damit_runner`), the ids those plugins publish — and the DamIT runner CLI (`damit_cli.py`). Every id can be overridden by environment variable or
  `damit-handoff.json` without a code change. The North Dakota suite's ids (`nddam:*`, `ndbreach:*`,
  `ndbreach_cli.py`) are never used, not even as a fallback. See **[docs/HANDOFF.md](docs/HANDOFF.md)**.
- **Piping by default.** A failure mode that was not chosen is piping, never overtopping, everywhere one is filled in
  (desk, `dam.json`, the DAMS layer and breach hydrograph, the CLI's `runner_config.json`).
- **Local only.** No web deploy, server-side state, sign-in, OAuth or client secret: Crest's TanStack Start / Vercel
  web app, its CI and its secret-scanning allowlists were left out.

**The dam inventory is the NID only** (USACE National Inventory of Dams; Nick, 2026-11-09). The Record step's
*Fill from the NID* picker and the Batch screen list the NID main dams of one **state** the user picks: the desktop
server downloads that state's NID bulk CSV once (`GET /api/nid/state?state=XX`, `desktop/damit_desktop/nid.py`),
converts it and caches it in the settings folder (`<settings>/nid/nid_XX.json`; *Download latest from the NID*
refreshes it). One bulk CSV per state, no per-dam API calls, and the NID's owner columns are never read. North Dakota
(`src/lib/crest/data/nid_ND.json`, 948 main dams) is committed as the offline example, so the desk works without a
network for ND; no national bundle is committed. No state dam-safety inventory (the ND DWR dams file), no dugout or
unknown-structure layer and no state suite pack (`NDSUITE_DATA`, `~/.ndsuite`) is read or shipped. Receptors (ND 911
address points for ND dams, or the user's own), DEMs (3DEP or a local DEM) and NHD streams are separate inputs.

**A batch of any size can be left running in the desk.** Rows are written to browser storage (IndexedDB) as they
finish, and again when the window is hidden or closed. The state and the selection being run are saved too, so after
**Stop**, a closed window or a crash the Batch screen reopens on the same state and selection with a line saying how
many are left, and **Resume** carries on from there; closing mid-run asks first. If the terrain service stops
answering (six dams in a row fail to reach it), the batch **pauses** instead of failing everything left, and tries
again by itself after 1, 2, 5, 10, 15 and 30 minutes or as soon as the connection is back; the dams that failed that
way are retried, never kept as results. *Stop retrying* ends the waits, and so does choosing another state. Only the
300 most recent finished records are kept in memory for **Open in desk**; any other finished row is rebuilt from the
NID and the terrain when opened (a few seconds), including after a reload. Above 300 dams the screen still shows the
command line, which runs without a window and can read a local DEM.

The built-in samples are the NID dam ND00199 (Swan Buffalo Detention 12) and two fictional desk examples
(*Local-datum sample* `SAMPLE-4031`, *Prairie holding pond* `DESK-014`). Those two ids are **not** NID IDs: the hand-off
sends them as samples (`is_sample`, no `nid_id`), never as NID inventory records. A new dam (*+ New dam*) starts with an
empty NID ID; tick **New dam** for a proposed dam that is not in the NID yet (`is_new`). Nothing defaults to North
Dakota except that example state.

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
  scripts/                  tests, build-nid-dams.mjs (NID state extract), batch-dams.mjs, sync-jurisdictions.mjs
  desktop/                  the pywebview app (adapted from Crest's crest-desktop/)
    run.py, requirements.txt, INSTALL.txt, damit_crest.spec, build_mac.sh
    damit_desktop/          __main__ (window + local API), nid (NID by state), algorithms (hand-off ids), qgis_run, handoff, layers, localdem
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

## Settings: starting pool, roughness and the shared defaults

DamIT Crest's presets are the pool at the top of dam, a piping failure, Froehlich (2008) and Manning's n of 0.035 in
the channel and 0.06 on the floodplain. They can be changed in two places.

**On one record (Breach step, "Advanced: starting pool and roughness").**

- *Starting pool*: top of dam (the default), the record's normal pool, or an elevation you enter (in the same datum
  as the crest; it is tied to NAVD88 the same way). Below the top of dam the head on the breach is lower and the
  breach equations use the storage at that pool, so the peak and the released volume are smaller. A pool that cannot
  be used (no normal pool on the record, above the top of dam, not above the breach bottom) falls back to the top of
  dam and says why. Inflow cases (PMF, flow over the spillway with or without a breach) are DamIT Runner's.
- *Manning's n*, channel and floodplain (0.01 to 0.3). Used by the routed flood on the terrain: travel time, depth and
  spread. Changing either asks for the terrain layer to be built again; the LISFLOOD export's `fpfric` follows the
  floodplain value.

These belong to the record: they are saved with it and written to its `dam.json`.

**For every new record (header, Settings).** Settings holds the suite's *shared defaults*, the same `defaults.json`
DamIT Core ships and DamIT Runner reads (`damit_core/lib/shared_defaults.py`): the sunny-day starting pool, the
failure mode, the breach equation and Manning's n. A new record, a record made from the NID picker and every batch
row starts from them. Records you already have are not changed; the Breach step lists where a record differs from
the shared defaults and has a button to put it back on them.

| Where | Your values live in | How to change them |
| --- | --- | --- |
| Desktop app | `~/DamIT/defaults.json`, found the way DamIT Core finds it outside QGIS: the `defaults_file` key of the DamIT settings file (`DAMIT_SETTINGS`, else `~/.config/damit/settings.json`), else `DAMIT_DEFAULTS` | Settings > Save writes the file. Editing it by hand works too; DamIT Crest reads it when it opens. |
| `DamIT.html` in a browser | that browser | Settings > Save. *Open settings file* reads a `defaults.json`; *Save settings file* writes one to hand to the plugins. |
| Batch command line | a file you name | `npm run batch:dams -- --defaults ~/DamIT/defaults.json ...` |

A `defaults_file` chosen inside QGIS is kept in the QGIS profile, which the desktop app cannot read; set
`DAMIT_DEFAULTS` to the same path if you keep the file somewhere other than `~/DamIT`.

Your file holds only the keys you changed, so a key you never touched follows the suite's value when the suite is
updated. Unknown keys and out-of-range values are left out and named, never guessed. DamIT Crest has three of the
suite's breach equations (Froehlich 2008, MacDonald & Langridge-Monopolis, a TR-60 width); if the shared defaults ask
for another, new records start on Froehlich (2008) and Settings says so. `pmf_breach_volume` is kept in the file for
the Runner and not used here. A test compares the desk's copy of the suite values, choices and ranges with
`damit_core/data/defaults.json` and DamIT Core's schema, so the two cannot drift apart.

Every `dam.json` DamIT Crest writes (Report step, and the dam folder) carries an `assumptions` entry in the form
`shared_defaults.assumptions()` writes: what the record used, in the shared file's own names, the shared values at the
time, and `differs`, the keys where the two are not the same. `starting_pool_ft` and `starting_pool_rule` give the pool
the breach really started from. An `assumptions` entry another tool already wrote in the dam folder's `dam.json` is
kept; DamIT Crest's own is then on its screened status entry.

## Saving and moving your work

The desk's dams live in the desktop app's own storage (or the browser `DamIT.html` is open in), not in a file you can
see. Under the dam list:

- **Save desk to file** writes every dam on the desk to one file, `damit-crest-desk-<date>.json`: inputs, receptors,
  drawn lines and areas, saved 911 / PLSS lookups, the terrain layer, the jurisdiction choice and the last classify
  result. This is the backup, and the way to move a desk to another computer or between `DamIT.html` and the desktop
  app.
- **Open desk file or dam.json** reads that file back. *Add to this desk* never changes a dam already on the desk: a
  dam that is already there and identical is left alone, and one with the same id but different content is added
  beside it as "(from file)". *Replace this desk* makes the desk exactly the file's dams.
- A **dam.json** opens too. One from the Report step carries the whole record (`crest_record`, without the terrain
  layer) and comes back as it was. The dam folder's `dam.json` (`damit/dam_record`, written by the hand-off) holds the
  engineering inputs only: it opens as a new record with those inputs and a note that receptors, drawn geometry and
  layers were not in the file.

A file is read as data only: each record is rebuilt field by field, and a value of the wrong type is dropped with a
note (`src/lib/crest/desk-file.ts`). The file format is the one Crest writes (`crest-desk`), so a desk saved from
either opens in the other; fields the other does not have are left out.

## Report step: DamIT plugins in QGIS

Needs QGIS 3.28–4.x with the DamIT plugins installed. The buttons do nothing in a page with no desktop server.

- **Get layers** — use the DamIT data folder (`DAMIT_DATA`, or `damit/data_folder` in `~/.damit/config.json`), or
  download a USGS 3DEP DEM and NHD streams and waterbodies for the drawn area (United States).
- **Write the dam folder** — `<work>/dams/<id>/` with `dam.json` (`damit/dam_record`, including the jurisdiction
  choice), the drawn geometries, both hydrographs, the LISFLOOD `.par` / `.bci` / `.bdy` and the flood strip. Starts
  nothing.
- **Write folder and run screening** — the preflight algorithm, then the screening chain **only if READY**, for this
  dam only (DamIT Screener 0.2.0 runs its 2D screening flood on the mapped structures and writes a preliminary
  class). A missing algorithm or a FAIL stops there. Cancel stops `qgis_process`; `DAMIT_SCREENING_TIMEOUT_S` sets a
  limit (default none); the screening flood keeps its maxima at 0.8 x that limit.
- **Run the flood model** — one dam: `damit_run:rundam` (with the screening's `damit_handoff.json` when there is
  one, `DRY_RUN=false`: DamIT Runner 0.2.0 launches LISFLOOD-FP, the built-in engine or LISFLOOD-FP then ANUGA with the
  DamSafety Runner's parameters and copies Depth (Max), hmax and the flood polygons into the dam folder), or a DamIT
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

## Security

The desk runs under a Content-Security-Policy built in one place, `src/lib/crest/csp.ts` (the same policy as Crest):

- **Scripts** run only from the app itself. The desktop app's local server sends the policy with every response
  from `web/security-headers.json`; `DamIT.html` carries it in a `<meta>` tag with the SHA-256 of its one inline
  script. No `unsafe-inline` or `unsafe-eval` for scripts. The per-launch token is a `<meta>` tag, not a script.
- **Network** from the page is limited to USGS basemap tiles and OpenStreetMap, USGS 3DEP, the ND GIS Hub 911 points
  and the BLM PLSS service (plus a tile server set with `VITE_CREST_TILE_URL` at build time). The NID state download
  is made by the Python server, not the page. A new service has to be added to `csp.ts`; `csp.test.ts` fails when
  the source names a host the policy does not.
- **Subresource Integrity**: the bundle's `index.html` carries a `sha384` hash for its script, preloads and
  stylesheet, so the window refuses a bundle file that does not match. The repo's `.gitattributes` stops git
  converting line endings in the bundle, which would break the hashes on Windows.
- Also sent: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `Referrer-Policy`,
  `Cross-Origin-Opener-Policy`, `Permissions-Policy`.

If a desktop webview ever needs something the policy blocks, start the app with `DAMIT_NO_CSP=1` to drop the policy
(the other headers stay) and report what was blocked.

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
from the hazard catalog (`--check` to verify). `npm run data:nid` refreshes the committed ND NID example
(`-- --state XX --out <file>` builds another state's extract; do not commit it), and `npm run batch:dams` runs the
batch screen from the command line (`--nid-state XX --nid-file <extract>` for a state other than ND). Tests use
fixtures and never download the NID.

Every export carries the build (`crest_version`, `<package version>+<git sha>`, labelled "DamIT Crest") and the engine
method version (`engine_version`); the field names are Crest's so existing readers keep working.
