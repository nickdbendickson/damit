# What changed (generated)

Generated 2026-11-22 from damit 0d9a163, DWR_Plugins 3f53622, the last 45 days. Newest first. Each line is one commit on the default branch (a merged pull request or a direct commit): repository, short id, title. Regenerate with `python3 heim/tools/what_changed.py --repo <checkout> ...` and re-index the pack.

## 2026-11-21

- damit `0d9a163` damit_crest: default Manning's n 0.05 (was 0.06), matching the suite (pairs with DWR_Plugins #460) (#165)
- damit `b20de29` GPU flood engine as a separate engine choice (Runner 0.6.8, Screener 0.3.6) - waits for DWR #399 (#125)
- damit `f1b068e` Engine version pins: ENGINES registry + LISFLOOD log pin + ANUGA check tie-in (audit 2026-11-19) (#137)
- damit `eca9c9d` Runner 0.7.14: port DamSafety pothole start fill (#162)
- damit `f069023` Runner 0.7.13: built-in engine point-source order (#161)
- damit `35e0e01` Runner 0.7.12 / Core 0.3.3: default Manning's n 0.06 to 0.05 (#160)
- damit `1171253` Runner 0.7.11 / Core 0.3.2: Xu & Zhang methods and peak-flow range (#159)
- damit `6d26c76` Runner 0.7.10: refuse a 3DEP refill that has no ground (#158)
- damit `7fdcb9b` Dead-code sweep: remove verified-unused functions and imports (#140)
- damit `70a5911` Installer from a git checkout: build the DamIT zips or fail clearly (#163)
- damit `53de765` lisfloodrain: atomic LISFLOOD-FP input writes (#135)
- damit `2b019a1` Runner 0.7.9: DamSafety port C1 - area-based spread rule (#157)
- damit `d153e59` Atlas 14 shared core: re-record pin at DWR_Plugins main 140030b (#164)
- DWR_Plugins `3f53622` Crest: default Manning's n 0.05 (was 0.06), matching the suite (changes results; review only) (#460)
- DWR_Plugins `b70c3aa` Bump react-dom from 19.3.0 to 19.3.1 in /dwr_crest (#426)
- DWR_Plugins `002fdce` Bump @vitejs/plugin-react from 5.2.0 to 6.3.0 in /dwr_crest (#427)
- DWR_Plugins `dfad3a9` Crest install-test fixes: Settings save on Linux, stopped screening reruns step 7, time-limit status, docs (review only, stacked on #447) (#456)
- DWR_Plugins `a3ffae8` Bump globals from 15.15.0 to 17.14.0 in /dwr_crest (#423)
- DWR_Plugins `63538d5` Crest desktop: screening uses the dam's own DEM for every clip (#447)
- DWR_Plugins `a32ef8e` CI: run the sub-grid FV kernel GPU==CPU gate on the Apple-GPU runner (#458)
- DWR_Plugins `6fdf6af` Runner 3.42.0: wire Boann sub-grid FV as the gpu-subfv engine (research) (#457)
- DWR_Plugins `1c32a01` Sub-grid FV solver: CPU table builder + reference (research, no wiring) (#453)
- DWR_Plugins `41fd858` cleanup(Data): drop pack_build.layer_names, never called since it was added (#454)
- DWR_Plugins `140030b` Atlas 14 core: copy DamIT GIS grid handle releases (#455)

## 2026-11-20

- damit `af11434` Runner 0.7.8: DamSafety port group B - report provenance and disclosure flags (DWR 6023cc1b, 07ab314c, 6dfd42cd); no computed result changes (#156)
- damit `76aaa76` GDAL handle releases + logged swallows (#149)
- damit `2af8976` Runner 0.7.7: DamSafety port group A - #394 cancel pid check, OMP #15 hint, #412 open-file limit (no number changes) (#153)
- damit `7046e81` Supply-chain golden fixtures: NOAA HDSC, StreamStats, 3DEP, ND GIS Hub (#155)
- damit `0946299` Runner 0.7.6 / Screener 0.3.8: no process-wide GDAL exception switch in the flood package (audit L-1) (#151)
- damit `c593667` Runner 0.7.5 / Hazard 0.4.8 / Hazard Lite 0.2.2: atomic writes from #134, rebased onto main (#150)
- damit `554a7e0` Crest desk: flag tokens — fix missing utilities + field-mode contrast (#154)
- damit `c41295e` DamIT Data: provider tests on small offline fixtures (audit 3-pack, lower priority) (#152)
- damit `e8874a0` DamIT Data 0.2.2: HPMS roads download again (lower-case field names) and get every page, not just the first 2,000 (#147)
- damit `b90ce14` Screener 0.3.7: a timed-out screening flood is PARTIAL, not a failed chain (+ Crest: partial result and the dam's DEM for every clip) (#146)
- damit `14f3ebd` Crest desk UI: pipeline rail + inspector, three-pane workflow (#148)
- damit `cc9a0e1` Numerics audit fixes: #416 port, feet DEMs in watershed, StreamStats state, logged errors (Runner 0.7.4 / PMP 0.4.9 / Hazard 0.4.7) - review only (#141)
- damit `b78d587` Atlas 14 shared core: re-record pin at DWR_Plugins main de361afb (DWR #443 squash merge; the old pin a75bc08 was on the deleted PR branch) (#145)
- damit `d0da1a7` Runner 0.7.1 / Screener 0.3.6: one driver per dam folder (runlock), unique temp names, ANUGA launch claims before it deletes the status (#144)
- damit `2179f79` PMP 0.4.8 / Hazard Lite 0.2.1: stop switching GDAL exceptions on process-wide (pairs with DWR_Plugins#443) (#143)
- damit `04fb828` PMP 0.4.7: re-sync temporal.py with DamSafety PMP (shared Atlas 14 check green again; overlaps #134) (#142)
- DWR_Plugins `08cbc14` Runner 3.41.0: make Boann gpu-sgc usable from a headless run (#452)
- DWR_Plugins `12aaec1` Runner 3.35.2: duplicate layers in the Runner window (audit 3-pack, lower priority) (#448)
- DWR_Plugins `243b9b1` Log two swallowed errors: extent clip transform, handoff.nid_for dam.json (Runner 3.35.1 / Hazard 2.25.7) - review only (#441)
- DWR_Plugins `3127809` Runner 3.40.0: BoannGrid below-water bed carve as a conditioner stage (research) (#451)
- DWR_Plugins `9947ef7` Runner 3.39.0: Boann CFL/theta run controls, fix gpu-sgc dropdown (#450)
- DWR_Plugins `e0ada74` Boann SGC: full-width floodplain flow area (faithful to LISFLOOD-FP SGC2) (#449)
- DWR_Plugins `2dd99d8` BoannGrid: add raise_levee, the high-ground breakline op (Runner 3.35.0) (#445)
- DWR_Plugins `9c44707` Boann: add the sub-grid-channel solver (SGC-through-Boann, Runner 3.36.0) (#446)
- DWR_Plugins `de2c93a` Runner 3.34.1: one driver per dam folder (runlock), unique temp names, ANUGA launch claims before it deletes the status (pairs with DamIT Runner 0.7.1) (#444)
- DWR_Plugins `de361af` PMP 0.6.2: shared Atlas 14 core no longer switches GDAL exceptions on process-wide (synced from DamIT PMP 0.4.8) (#443)
- DWR_Plugins `3f22450` Runner 3.35.0: potholes can start partly or fully full (#442)
- DWR_Plugins `d5808c7` PMP 0.7.0: Green-Ampt loss method in the inflow hydrograph tool (#440)
- DWR_Plugins `77b81cb` Add PolyForm Noncommercial coverage for damit_ai and clarify GPL scope (#439)
- DWR_Plugins `e3de8ff` Boann DG2: 2nd-order discontinuous-Galerkin solver as its own flood-engine choice (Runner 3.34.0 / Screening 0.25.0) (#438)
- DWR_Plugins `bbdb352` Sync temporal.py from DamIT (audit 2026-11-19): validated, size-capped zip extract (#414)
- DWR_Plugins `8a9d705` Add GPL-3.0-or-later LICENSE and SECURITY.md (#437)
- DWR_Plugins `b2bb2c6` Boann FV2: 2nd-order shock-capturing solver as its own flood-engine choice (Runner 3.33.0 / Screening 0.24.0) (#435)
- DWR_Plugins `7af04cc` Remove orphan shared/crest + fix stale shared/ docs (review only) (#436)
- DWR_Plugins `9ad82ea` Dead-code sweep 2026-11-19: remove verified-unused functions and imports (#434)
- DWR_Plugins `56da3c8` cleanup(Screening): drop Grid._dv_point, unused since dv became peak depth x peak velocity (#433)
- DWR_Plugins `f6fbd22` Shock-capturing GPU flood engine (HLLC finite volume; Runner 3.23.0) (#404)
- DWR_Plugins `8811373` Bump actions/upload-artifact from 4 to 7 (#421)

## 2026-11-19

- damit `73d7a97` suite install: --sandbox DIR puts the whole install in one folder; fix --qgis-profiles-path layout (#139)
- damit `823ae4d` Point at Crest's new home: DWR_Plugins dwr_crest/ (#138)
- damit `cba7874` Runner 0.7.0: LISFLOOD-FP sub-grid river channels (SGC), from DamSafety 3.26.0 (#136)
- damit `2e0be1b` Runner 0.6.8 / PMP 0.4.6: installer's LISFLOOD-FP before PATH (#131)
- DWR_Plugins `a93dc69` BoannGrid: freeze-refusal export gate, SGC from the D4 network (#431)
- DWR_Plugins `5d5b6df` Boann reference harness: diagnostic cases vs the serial oracle (#430)
- DWR_Plugins `005aa14` BoannHydro: add a breach's point source in LISFLOOD-FP's order by default (#432)
- DWR_Plugins `51f79a0` BoannGrid: terrain conditioner (flow, audit, reconnection, culverts) (#419)
- DWR_Plugins `1fa3661` BoannGrid: GPU depression-fill (Planchon-Darboux) reusing the metalflood backend (#417)
- DWR_Plugins `391cec4` GPU flood engine (Metal): LISFLOOD-FP's ACC scheme on the Apple GPU (#399)
- DWR_Plugins `a37e396` Require a CRS on every terrain read; no silent EPSG:5070 fallback (#416)
- DWR_Plugins `5477de4` validation: --sgc option for the gauge / Midland reach harness (#429:)
- DWR_Plugins `1529fba` Runner 3.27.0: default uniform Manning's n 0.06 → 0.05, prefer NLCD (#428:)
- DWR_Plugins `685735e` Move Crest into DWR_Plugins as dwr_crest/ (full history) (#420)
- DWR_Plugins `e4be555` Runner 3.26.0: LISFLOOD-FP sub-grid river channels (SGC), off by default (#418)
- DWR_Plugins `39b4f0f` Runner 3.24.2: installer's LISFLOOD-FP before PATH (replaces #407) (#415)
- DWR_Plugins `c573517` Lake Delhi validation: roughness study (NLCD n, n 0.05/0.035, panel-peak breach) (#388)
- DWR_Plugins `e272533` Runner 3.24.1: batch runs lift the open-file limit (no number changes) (#412)
- DWR_Plugins `73d5847` reach.run: apply the Runner stability cure on a mass-balance blowup (#413)
- DWR_Plugins `3a2d152` Runner 3.24.0: tests, records and display (batch 3 of Lumo clean adds) — no computed results change (#410)
- DWR_Plugins `a7f7464` nd-gauges: one sim per runner, drop two Little Missouri badlands gauges, gate non-converged runs (#411)
- DWR_Plugins `91f1323` Runner 3.23.0: disclosure and safety flags — crossings, tailwater, dam-cut, XZ method, burn width (no computed results change) (#409)

## 2026-11-18

- damit `5abe547` Security follow-ups (DamIT Crest desktop): one-time launch link for the browser fallback; printed-address docs (#132)
- damit `e2a168b` Finder 0.7.2: pond-outlet fills four score bands lower in review_order (DamSafety Finder 0.7.2 engine) (#129)
- damit `8071b77` DamIT Crest 0.1.2: official DaMiT wordmark in the header, favicon, and desktop icon (#133)
- damit `4faa778` Heim: Store.changed() also reads the SQLite file change counter (flaky index-reload test) (#130)
- damit `da0b560` Hazard 0.4.5 / Runner 0.6.6: bundle true-hole helper, WSE-test oversize (review only) (#115)
- damit `dfd6fac` Crest: breach peak check note, dashed "flood goes on" edge on routed layers (#122)
- damit `d577883` Docs audit 2026-11-18: E911 merge rule, Screener 0.3.4/0.3.5 + Runner 0.6.5 in REFERENCE, Crest network/hand-off check (review only) (#124)
- damit `f9d81e7` Runner 0.6.6: LISFLOOD-FP .bdy times strictly increase at the printed 4 decimals (#126)
- damit `42d3766` DamIT Crest hand-off: line_xy in EPSG:5070 for a proposed dam; no proposed-embankment block for an existing dam (#123)
- damit `1527f11` install-all: name the missing offline files, not only count them (#128)
- damit `f6022a8` Security: DamIT Crest desktop API token in the URL fragment, not in the served page (#127)
- damit `8c7e9b2` Install-test fixes: Screener 0.3.5 chain fails on a missing flood, Runner 0.6.5 finds the installer's LISFLOOD-FP, desk NID fixture, test-install options (#121)
- damit `4ba2601` PMP 0.4.5: share the Atlas 14 core with DamSafety PMP; Core 0.3.1 download fix (#119)
- damit `aab07dc` DamIT Crest accuracy: lakes as level pools, larger tiled terrain, 3DHP lake flowlines, taller recuts, scoring harness (#120)
- DWR_Plugins `9ac144d` Runner 3.22.0: report provenance — docx and run_report.md tell the truth about the run (no computed results change) (#408)
- DWR_Plugins `84fb7c5` Edenville-Sanford 2020: second real dam-failure validation (10 m reach + 30 m cascade) (#395)
- DWR_Plugins `2d246a9` Hazard evalcache: size-capped inflate of the saved evaluation (security follow-up, review only, do not merge) (#406)
- DWR_Plugins `5bf3f22` Finder 0.7.2: pond-outlet fills four score bands lower in the review order; statewide script 1.4 (#405)
- DWR_Plugins `70dd708` tools/mac: m24_area_diff.py — verify audit M24's real-inventory impact (#390)
- DWR_Plugins `75e71aa` Runner 3.21.0: Xu & Zhang (2009) breach methods and a peak-flow regression range (#401)
- DWR_Plugins `e4f1e14` Docs audit 2026-11-18: CHANGELOG for Runner 3.20.14 and #394 security, Screening 0.20.3/0.20.4 wording, PMP README identity (docs only) (#402)
- DWR_Plugins `45cc393` Security audit fixes 2026-11-18 (review only, do not merge) (#403)
- DWR_Plugins `0c313ac` PMP 0.6.1: pothole cascade contributing area per pothole, order-free (#400)
- DWR_Plugins `e389269` Screening 0.20.4 / Runner 3.20.15: install-test fixes (#398)
- DWR_Plugins `73e8a85` PMP 0.6.0: NOAA Atlas 14 tools on a core shared with DamIT PMP (#396)
- DWR_Plugins `0ca91de` Runner 3.20.14: two cascade fixes (repeated .bdy times; a 3DEP refill of no ground) (#397)

## 2026-11-17

- damit `3ff2886` Security: external-navigation guard for the DamIT Crest desktop window (#117)
- damit `64ee4e9` Security: escape map tooltips (XSS) in damit_crest; add SECURITY.md (#116)
- damit `cf1d6f0` Hazard 0.4.3: WSE-consistent NoData depth, size cap (review only) (#111)
- damit `a44b4fb` Hazard 0.4.2: load official ND E911 address points (review only) (#110)
- damit `4349ab8` Install-test fixes: NAVD88 units, DamIT Crest CSP, DAM_LINES, pack terrain (review only) (#109)
- damit `9512a9e` damit_pmp 0.4.2: VERTEX_ELEVATION (fixes ANUGA rain water stranding), stream refinement, principal outlet, stage probes (review only) (#72)
- damit `5fa42e6` Finder 0.7.1 (water years in the review order) and Runner 0.6.2 (ANUGA resume fix): engine sync to DamSafety 5d2ec3b (#107)
- damit `4034774` DamIT Hazard 0.4.1: depth-velocity chart lines drawn smooth (no number changes) (#108)
- DWR_Plugins `093fcc3` ND gauge roughness study: Manning's n vs measured flood stages (#391)
- DWR_Plugins `8a15369` Security hardening: solver-from-project RCE, pack zip-slip + bomb, cancel PID-reuse (#394)
- DWR_Plugins `cd6345c` Runner 3.20.13: batch dams use their DWR dam line, point at its centre (#392)
- DWR_Plugins `4726f52` Screening 0.20.3: default terrain and larger clips to the offline pack (review only) (#389)
- DWR_Plugins `30e12d6` Bump actions/checkout from 4 to 7 (#350)
- DWR_Plugins `6bbdb4f` Bump softprops/action-gh-release from 2 to 3 (#349)
- DWR_Plugins `47c5fc7` Finder 0.7.1: water years in the review order, work down to 0.5; statewide script 1.3 pack lookup (#381)
- DWR_Plugins `b6dd939` Bump actions/upload-artifact from 4 to 7 (#351)
- DWR_Plugins `e910fca` cleanup(tools): gui_lint drops two one-item loops that did nothing (B020) (#386)
- DWR_Plugins `3eec81e` cleanup(PMP tests): explicit imports in validate_hydro.py instead of a star import (#376)
- DWR_Plugins `4827715` cleanup(Screening tests): drop 21 unused imports in tests/ (#374)
- DWR_Plugins `0b36a17` cleanup(Screening): drop unused QgsProcessingAlgorithm import from 23 algorithm modules (#373)
- DWR_Plugins `9fa40a9` Runner 3.20.12: the breach inflow is no longer put on the reservoir when a dam line is given (#387)
- DWR_Plugins `21f575b` Lake Delhi 2010: ANUGA on the gmsh mesh with road breaklines and the crest burn (#371)
- DWR_Plugins `bd14874` Runner 3.20.11: check the dam point on the DEM before modelling (warn by default, move available) (#385)
- DWR_Plugins `9df8c7e` Smooth depth-velocity chart lines, drawing only (Hazard 2.25.6, Core 1.5.2; no number changes) (#384)
- DWR_Plugins `bd9f159` Runner 3.20.9: area-based rule for when a flood is still spreading (changes results) (#383)

## 2026-11-16

- damit `4945a9a` Suite installer: North Dakota Crest desk, Mac settings file, Crest Report profile, offline-pack launcher (#105)
- damit `9274ceb` dam_chain: a clean DamSafety preflight is OK; LISFLOOD-FP default from install-all (#106)
- damit `51b0e5c` install-all: LISFLOOD build broke on the macOS 'Application Support' path (#104)
- damit `0f4dc79` Suite download: reuse the saved Ollama for the model pull instead of downloading it every run (#103)
- damit `582f54f` Suite installer: find existing envs first, make and use every env by path (#102)
- damit `0d7dd4a` Suite download: retry on resets, resume partial files, 3 at a time, auto passes (#101)
- damit `f8fc9ba` Heim: run results in a database (heim runs) for exact depth / peak-flow answers (#100)
- damit `9f3c3d2` DamIT Data: download the offline layers from a terminal, without QGIS (#97)
- damit `96c3489` DamIT Finder 0.7.0: the DamSafety Finder 0.7.0 engine (#99)
- DWR_Plugins `facc89f` Runner 3.20.8, Hazard 2.25.5: batch-44 first-run fixes (inflow-depth warning, wizard DWR geometry, Overpass backups) (#382)
- DWR_Plugins `5d81793` DamSafety Data 1.11.2: Check for updates looks after the pack the plugins read (#380)
- DWR_Plugins `8d43bf6` Runner 3.20.7: Mac installers write the QGIS settings QGIS reads; self-test names engine sources; OMP #15 hint (#379)
- DWR_Plugins `4e05bd6` Mac LISFLOOD build: don't fail when Apple's Metal compiler is missing (#378)
- DWR_Plugins `7d0d592` Heim: run results in a database (heim runs) for exact depth / peak-flow answers (#377)
- DWR_Plugins `4cf0cb2` Runner 3.20.6: a resumed ANUGA run no longer computes its first pass again (#375)
- DWR_Plugins `b7f606b` Batch: get the offline pack without QGIS, and build it when a run finds none (#369)
- DWR_Plugins `bb1f18c` Release workflow: build the Mac LISFLOOD-FP on macos-latest (macos-14 is no longer offered) (#370)
- DWR_Plugins `f22f636` Finder 0.7.0: same fills whatever the run box, edge of the terrain data, evidence on review cards, statewide run (#372)

## 2026-11-13

- damit `6d819a7` Engine sync 3: flow sections, Windows fixes, and the keep-awake call that stopped model runs (Runner 0.6.1) (#98)
- damit `ec0960a` Vor 1.3.2 and Heim command words: stop the commands sending the reader in a circle (#96)
- damit `240f858` Runner 0.6.0: engine up to DamSafety 3.20.3 (batch workers, signed ANUGA checkpoints, QA map fix) (#95)
- damit `2e68fb9` Finder: ship the starter score model in the DamIT build (#94)
- damit `fb26351` Runner 0.5.0: scenario, starting pool and auxiliary spillway choices (#89)
- damit `2c9327e` Runner 0.4.1: engine up to DamSafety 3.17.13, the ported tools load, and a parity gate (#87)
- damit `2d53065` damit_crest: Content-Security-Policy and Subresource Integrity (port of crest #106) (#93)
- damit `40b7872` DamIT Crest: save the desk to a file and open it again (stacked on #91) (#92)
- damit `6fffb3e` DamIT Crest batch: fix the crash that stops every run on its first row; make it resumable (#91)
- damit `731084a` DamIT Crest: starting pool, Manning's n and the shared defaults Settings panel (paired with crest #109) (#90)
- damit `69bcf88` Rename the local AIs to Heim and Vor, and what they gained with it (#85)
- damit `a4f0567` damit_crest: engine sync check against crest, replacing the self-pin (#86)
- damit `c8b07bd` Shared defaults file in DamIT Core 0.3.0; DamIT Runner 0.4.0 reads it (#88)
- damit `6d6957d` rag_index: don't blame the PDFs when there is no PDF library (#82)
- damit `843e730` dam_chain 1.5.2: `run --set nd` exits 1 when a dam failed (#84)
- damit `014cbbf` damresearch 1.0.5: --doc / --per-doc, so a question can be scoped to one publication (#83)
- damit `1c161ff` first-run.zsh: name the winning model instead of printing "TAG" (#80)
- damit `7fb142a` DamIT Finder 0.6.0: lines out of each pond and brim-full ponds (mirror of DamSafety Finder 0.6.0) (#81)
- damit `3bad3d0` eval: fema333-temporary expects the wrong pages (#79)
- damit `d2d38ad` first-run.zsh: zip only the reports this run produced (#77)
- DWR_Plugins `6272760` Windows and macOS test runs before a release, and a start check for the Windows engine build (#362)
- DWR_Plugins `3e921a5` Validation: the Runner against the Lake Delhi Dam failure of 2010 (#368)
- DWR_Plugins `5ab7b52` User guide: pictures of the windows, and the tool that makes them (#365)
- DWR_Plugins `f36b965` Hazard 2.25.3: the hazard creep watch on a schedule, with a one-page list of changed dams (#364)
- DWR_Plugins `efe0c3a` Security: signed ANUGA checkpoints, bounded zips and downloads, checked NSI (Runner 3.20.3, Core 1.5.0, Screening 0.20.1, Hazard 2.25.2, Data 1.11.1) (#361)
- DWR_Plugins `c8b60ec` SI units in the result tables and the remaining reports (Core 1.4.0, Runner 3.20.2, Hazard 2.25.1) (#359)
- DWR_Plugins `1e62a1f` Vor 1.3.2 and Heim command words: stop the commands sending the reader in a circle (#367)
- DWR_Plugins `88cd933` Batch 44: a script that packs a finished batch into small zip files (#366)
- DWR_Plugins `5d12c12` Hazard 2.25.0: flag a class that rests on velocity (#358)
- DWR_Plugins `b84ae41` Core 1.3.0 / Data 1.11.0 / Runner 3.20.1: a sample dam to try the suite on (#357)
- DWR_Plugins `10b3cdb` Runner 3.20.0: several dams of a batch at the same time (#356)
- DWR_Plugins `7bd6a03` Runner 3.19.0: starting pool choice, flood with no breach, auxiliary spillway (#355)
- DWR_Plugins `e13cfd9` Batch: a study of whether the model settings change the hazard class, on the 44 dams (#363)
- DWR_Plugins `eca8129` Docs: an install route that works before the first release, the LISFLOOD-FP licence, a Finder review page (#360)
- DWR_Plugins `a892c26` Rename the local AIs: Pierre to Heim, damresearch to Vor, with a current domain context for both (#352)
- DWR_Plugins `504dc31` Batch scripts into the repository (tools/batch), with tests (#354)
- DWR_Plugins `9d9b256` Shared defaults file: one defaults.json every tool starts from (Core 1.2.0) (#353)
- DWR_Plugins `27db606` dam_chain 1.5.2: `run --set nd` exits 1 when a dam failed (#348)
- DWR_Plugins `58d5526` cleanup(PMP tests): drop unused imports (#344)
- DWR_Plugins `48ca4c8` damresearch 1.0.5: --doc / --per-doc, so a question can be scoped to one publication (#347)
- DWR_Plugins `4fe99f8` Run absaraka, nickreview and the 44-dam batches on a local terrain VRT (#346)
- DWR_Plugins `4ce1052` DamSafety Finder 0.6.0: lines out of each pond and brim-full ponds (Iowa pond-dam recall 41 % to 77 %) (#345)

## 2026-11-12

- damit `62d6790` DamIT Finder 0.5.0: all 15 small-dam research items (mirror of DamSafety Finder 0.5.0) (#78)
- damit `55b3cfd` Stop the install scripts dying silently under set -e (#76)
- damit `976ff0c` first-run.zsh: unload each model before scoring the next (#75)
- damit `94f977a` Index the Pierre knowledge pack on macOS (#74)
- damit `9d18b18` Make the suite installer work and be complete on a real macOS host (#73)
- damit `d676e30` Pierre pack: state Hazard 0.2.6's 20 m NoData receptor rule (#71)
- damit `f6d610d` Pierre Q&A persona: pin the sunny-day rule and the real tool ids (#70)
- damit `3097667` Hazard 0.4.0: only ND 911 points and reviewed structures are habitable; NSI occtype and USA Structures suggest (builds on #65) (#66)
- damit `399c551` DamIT Finder 0.4.3: pond pool from the LiDAR water surface; honest dam label (#63)
- damit `3f73185` Hazard 0.3.0 / Screener 0.3.2: depth-velocity chart of the habitable structures (review only) (#65)
- damit `90e71bf` Fix Tewaukon (DWR-2659) NoData receptors, unit-less 3DEP, and off-line dam points (review only) (#67)
- damit `85a6f38` Crest desk: public roads with no AADT are Medium; velocity can pass the chart axes (#68)
- damit `9724cc8` DamIT PMP 0.4.1: ANUGA discharge section positive downstream (review only) (#69)
- damit `6d6b274` DamIT PMP 0.4.0: watershed of a dam point, NRCS / Atlas 14 temporal patterns, losses, lisfloodrain (review only) (#64)
- damit `31a2958` Review only: Crest, Hazard 0.2.4 and Finder 0.4.3 fixes (#61)
- damit `291bfa0` Rewrite README as a one-page intro with logo, models and license notes (#62)
- damit `1888f18` M8a: a private road with AADT over 2,000 is High (#53)
- damit `c58765d` Add watershed delineation and PMF inflow helpers (#59)
- damit `7acd1f7` Finder 0.4.2: build the class-9 water mosaic from LiDAR tiles (#60)
- damit `c5a09d0` damit_ai: add macOS download-everything script + offline model seeding (#42)
- damit `8de8ae7` Runner 0.3.2 MultiLineString dam line; Lumo watcher 1.3.2: every pass says why, leaner late-pass memory (review only) (#57)
- damit `16d20d1` DamIT PMP 0.3.0: Atlas 14 GIS grids from NOAA + LISFLOOD-FP / ANUGA rain-on-grid export (review only) (#58)
- damit `c45e4ff` DamIT Finder: read open water from a classified LiDAR point cloud (0.4.1) (#56)
- damit `cbd65ba` DamIT Finder 0.4.0: dikes beside a channel, toe past a bench, water tool in town (#55)
- damit `1d98c57` Lumo watcher fixes from the DWR-2824 retest of #50 (run_digest 1.3.0, lumo_watch 1.3.0, Hazard 0.2.2, Runner 0.3.1) (#51)
- damit `f945a79` DamIT Finder 0.3.0: canal banks and highways off the road layers are not dams (#54)
- DWR_Plugins `f50681e` DamSafety Finder 0.5.0: all 15 small-dam research items, measured; boosted-tree default score (#343)
- DWR_Plugins `53ac5d1` Bump actions/cache from 4 to 6 (#333)
- DWR_Plugins `0becfb2` Hazard 2.24.8: 20 m NoData-receptor rule (review only) (#342)
- DWR_Plugins `a00cf49` Bump mamba-org/setup-micromamba from 2 to 3 (#332)
- DWR_Plugins `3c315ca` Bump actions/download-artifact from 4 to 8 (#335)
- DWR_Plugins `1a306ca` Bump conda-incubator/setup-miniconda from 3 to 4 (#336)
- DWR_Plugins `073b572` Bump actions/setup-python from 5 to 7 (#337)
- DWR_Plugins `2e9fa05` DamSafety Finder 0.4.3: pond pool from the LiDAR water surface; honest dam label (#338)
- DWR_Plugins `423f5e2` Hazard 2.24.7: public road with no AADT is Medium (#341)
- DWR_Plugins `22a2da4` Hazard 2.24.7: habitable-only ND depth-velocity chart (911 points until reviewed) — review only (#340)
- DWR_Plugins `c2d42af` Rename the Lumo local AI to Pierre (#339)
- DWR_Plugins `6d02036` Review only: Finder 0.4.3 and Screening 0.19.6 (dam-kind protect) (#334)
- DWR_Plugins `05ba457` DamSafety Runner 3.16.15: ANUGA option to keep fine-resolution maxima — review only (#300)
- DWR_Plugins `3d5d911` cleanup(Data): stop F811 redefinition of mocked in test_pack_refresh (#290)
- DWR_Plugins `26dd284` Finder 0.4.2: build the class-9 water mosaic from LiDAR tiles (#331)
- DWR_Plugins `9c4936e` Docs: Runner flat-plain grid default help — for Nick's review (#269)
- DWR_Plugins `73b191d` cleanup(Screening): drop four unused locals (#278)
- DWR_Plugins `c27f2ef` ci: security scans, Scorecard, Dependabot (#279)
- DWR_Plugins `e472335` cleanup(tools): drop unused imports in build_release, anuga_omp_bench and gui_lint (#309)
- DWR_Plugins `81f44d9` Finder: read open water from a classified LiDAR point cloud (0.4.1) (#330)
- DWR_Plugins `e075f39` DamSafety Finder 0.4.0: dikes beside a channel, height past a bench, water tool in town (#329)
- DWR_Plugins `31a9938` DamSafety Finder 0.3.0: long fills (canal banks, highways off the road layers) are not dams (#328)

## 2026-11-11

- damit `980bf63` Fix HEIGHT_MISMATCH severity: 5 ft OR 15%, not both (#52)
- damit `73805be` Stop a feet DEM and a substituted HEC-RAS breach from publishing a shallower flood (#48)
- damit `cdccb55` Lumo watcher follow-ups to #46: one flag per id, receptors same at every hook, INFO bullets, measured first-byte wait, toe source; Hazard 0.2.1 reads nested dam.json (#50)
- damit `1028c4d` New plugin DamIT Finder 0.2.0: dams, ponds and culverts not on the lists (#43)
- damit `67947eb` SI units in DamIT windows and reports (stacked on #47) (#49)
- damit `43011d7` DamIT Core: choose US or SI units for the tool windows (display only) (#47)
- damit `7c26bb0` Review only, do not merge: Lumo as a DamIT run watcher (deterministic run digest + streaming small-model explainer) (#46)
- damit `a3fac90` suite_install: one install-all package for Windows, Linux and macOS (#44)
- damit `63f7244` damit_ai: add download-everything offline-bundle scripts (Windows + Linux) (#41)
- damit `3c3ab4a` damit_ai: cross-platform local-AI installers + Lumo eval, refresh, auto-index (#40)
- damit `e3aa337` DamIT Runner: fix plugin failing to load (rundam core lost in merge) (#39)
- DWR_Plugins `6aa756b` HEC-RAS: keep a finished breach and refuse a too-shallow depth (#326)
- DWR_Plugins `cbd5c49` SI units in Screening, PMP, own windows and reports (stacked on #325) (#327)
- DWR_Plugins `4e50e4a` Core 1.1.0: choose US or SI units for the tool windows (display only) (#325)
- DWR_Plugins `bfdbe5e` DamSafety Finder 0.2.0: find unlisted dams, ponds, culverts and open water (6 tools) (#323)
- DWR_Plugins `09399fe` Screening 0.19.4: leave the Finder's candidate dams uncut (#324)

## 2026-11-10

- damit `9e3d23c` dam-research catalog: add 'software' group (LISFLOOD-FP, Gmsh, ANUGA, HEC-RAS docs) (#37)
- damit `7a0cf67` lumo: add knowledge pack (behaviours, findings, issues, tool-help helpers) (#38)
- damit `d8a1d40` dam-research catalog: add 'breach' group from Nick's dam-break source list (#36)
- damit `b7b2359` Bump plugins to 0.2.0 (#33)
- damit `eb4823b` dam-research: download-only library script + offline URL list (#35)
- damit `ff14208` dam-research: fixes from Nick's first run (damresearch 1.0.4, fetch_asdso 1.2, eval 1.1) (#34)
- damit `ea002de` Breach simulation, StreamStats, parity check, documentation (#32)
- damit `6a5935c` Review only, do not merge: DamIT Crest starts models like the original Crest (Screener 2D flood, Runner model run, ND judgment = Medium) (#16)
- damit `7e712af` End-to-end tests, ArcGIS download handlers, plugin packaging (#31)
- damit `c3f151d` dam_chain 1.5.1: use the suite's ndanuga env; gmsh only when it imports (#30)
- damit `8b9588c` damit_data: add Census TIGER counties, NBI bridges, HIFLD facilities (#29)
- damit `fa4a64d` Remove ND-specific modules, generalize to US-wide, add CI (#27)
- damit `a733e3c` damchain audit: local repo audit (repo_audit 1.0), dam_chain 1.5, Lumo installer 3.6 (#28)
- damit `0b155a9` Engine smoke tests, QGIS Processing algorithms, compat fixes (#26)
- damit `319340d` Lumo installer 3.5: no web downloads from the script (#24)
- damit `ee97487` Port full DWR Runner engine into damit_runner (Phases 1-5) (#25)
- damit `628fc6a` National generalization: VERTCON, HPMS roads, FRA rail, NSI receptor default (#23)
- damit `c379b0e` damit_ai: install Ollama and the ndresearch env from bundled files (#21)
- damit `3845c08` damit_crest: auto-select state preset when a NID dam is picked (#22)
- damit `8ecfd61` damit_crest: engine parity check (pin + script for cross-repo identity) (#20)
- damit `eb2d23e` damit_ai: local AI (Lumo code triage + dam-research literature assistant) (#10)
- DWR_Plugins `de50dd5` Runner 3.17.8: audit M16 [SAFETY-NUM, golden unchanged] Model.window scans the previous window (stacked on #318; review only, do not merge) (#322)
- DWR_Plugins `7968e7f` Runner 3.17.7: audit M18 - Cancel stops the HEC-RAS 2D stage (review only, do not merge) (#318)
- DWR_Plugins `e917ff6` Runner 3.17.7: save the model terrain for review (LISFLOOD grid GeoTIFF + ANUGA mesh GeoPackage) (#321)
- DWR_Plugins `452a0ba` Hazard 2.24.5: audit M02 interim - log parked worker-thread layers, batch help says WORKERS > 1 (stacked on #319; review only, do not merge) (#320)
- DWR_Plugins `1481f1d` Hazard 2.24.4: audit M04 [SAFETY-NUM, bit-identical] provider raster bulk read with strict dtype whitelist (review only, do not merge) (#319)
- DWR_Plugins `9c79a52` Screening test_popup: make the same-size, same-date input check deterministic (#311)
- DWR_Plugins `082deb5` damit_ai: dam_chain 1.5.1 (ANUGA env fix, mirror of damit #30) (#317)
- DWR_Plugins `6313f73` Runner 3.17.6: M15 TR-60 resolved to NRCS TR-210-60 (A = template section); correct disclosure note, no number change (#315)
- DWR_Plugins `9ed636b` damit_ai: damchain audit + dam_chain 1.5 (mirror of damit #28) (#316)
- DWR_Plugins `8d667f2` Screening 0.19.3: M24 tool-7b shallow-curve guard measures basin depth, not freeboard (signed off) (#314)
- DWR_Plugins `581d897` Add damit_ai: local Ollama assistants (Lumo + dam-research) (#307)
- DWR_Plugins `7fa560a` Release tools: ship DamSafety Core with the other plugins (#313)
- DWR_Plugins `47d37c1` Merge PR #312: Runner 3.17.5 — M21 follow-up velocity-missing defence (cascade/sensitivity/probabilistic)
- DWR_Plugins `6166516` Merge PR #310: Runner 3.17.4 — M21 velocity-missing product-write defence (signed off)

## 2026-11-09

- damit `74de38d` damit:classify: check parameters with GDAL PAM off too (#15)
- damit `aae7473` Review only, do not merge: classify PAM off, NID apply keeps elevations, ND preset default (#13)
- damit `5c178fa` [REVIEW ONLY – do not merge] DamIT Crest uses DamIT Catalog's NID-ID rule (no copy) (#11)
- damit `9e726a7` Review only, do not merge: DamIT Catalog 2026.11.09.4 follows the Nov 2026 Summaries (AL, NC, USACE, TVA; TX/AK/NY fixes) (#14)
- damit `06258ef` Review only, do not merge: DamIT Catalog 2026.11.09.3: USBR M1 via M5, M3 institution datums, preset status marks (#12)
- damit `c75bbdf` NID dams only: Catalog rule, Screener, Runner, hand-off and Hazard (lands #7 and #8 on main) (#9)
- damit `9cbfa90` Review only, do not merge: send downstream receptors to damit:classify with the selected method (#4)
- damit `7c390cb` Add damit_crest: DamIT Crest desktop app (adapted from Crest). (#3)
- damit `77f1a71` Review only, do not merge: DamIT Core, Setup, Data, Hazard Lite and PMP (Atlas 14 only) 0.1.0 (#6)
- damit `aae5c06` Review only, do not merge: point DamIT Hazard at DamIT Catalog (#5)
- damit `71f2cde` DamIT Catalog + Screener + Runner 0.1.0. (#2)
- damit `085e452` Add damit_hazard 0.1.0: catalog-driven dam hazard classification (#1)
- damit `36d0b49` Initial commit
- DWR_Plugins `591f48d` Merge PR #308: audit medium/low follow-up — M01, M25, M11 (no-number) + M15 MLM (signed-off)
- DWR_Plugins `080b791` Usability: window-simplification plan — Hazard 2.24.2 / Runner 3.17.2 / Screening 0.19.2 / Data 1.10.1 (#298)
- DWR_Plugins `3a754ef` Merge PR #304: audit medium/low backlog + sign-off batch (Core 1.0.1 / Hazard 2.24.1 / Runner 3.17.1 / Screening 0.19.1)
- DWR_Plugins `a8513b0` Use the DaMiT suite mark as the Plugin Manager icon (#306)
- DWR_Plugins `e12f35d` DamSafety Core 1.0.0: one shared damsuite (fresh consolidation on current main) (#305)
- DWR_Plugins `432f01f` Test-only: fix classification-parity fixtures (Float32 on_line, GEOS point_disc) after #295 (#303)
- DWR_Plugins `6cd5a84` H01: a cut-short ArcGIS download is written to _downloads/_partial/ (never reused as a complete day cache) and surfaced via INCOMPLETE_USED in the run log / sources. Plus a test-only fix to test_classification_parity.py (float32-boundary + documented GEOS arc/chord gap) that also un-reds main. Independently reviewed; all CI legs green. (#301:)
- DWR_Plugins `63e16ee` P1: Runner / Screening adopt Hazard's zone rule and sampling footprint (Runner 3.16.9 / Screening 0.18.17 / Hazard 2.23.13) (#295)

## 2026-11-08

- DWR_Plugins `4431882` Two audit sign-off correctness fixes in DamSafety Runner: H05 (preview no longer writes a nanmax crest onto the dam; uses the suite 98th-percentile rule on a copy) and H07 (cascade combine draws each run on its true ground at mixed cell sizes). Independently reviewed (0 correctness defects), CI green. (#299:)
- DWR_Plugins `2652d86` CI matrix: an LTR / Qt5 leg, numpy 2 legs, GUI lint on a 1080p display, Runner fast suite in the fast gate (audit CI matrix 2026-11-07) (#294)
- DWR_Plugins `a00dd85` Reliability and engine guards: numpy 2, failed structures, process-wide GDAL exceptions, unattended HEC-RAS limit, streamed Data downloads, Screening local mosaics, Runner shallow-outflow domain growth (audit R1 / R2 / R3 / R6 / R11; Grok audit 2026- (#292)
- DWR_Plugins `2ef646d` Usability, docs and release: README, metadata repository fields, changelog trim, GitHub Release + QGIS plugin repository, Setup dock build feedback (audit U6) (#293)
- DWR_Plugins `41a24a7` Hazard 2.23.15: every long job of the Hazard window runs in a QgsTask (imports, Check inputs, creep watch, self-test) (audit, GUI responsiveness) (#296)
- DWR_Plugins `7ee239f` Performance: LISFLOOD-FP wall-clock limits + tail progress read, DEM warp cache, float32 results, PMP vectorisation, HEC-RAS import float32 (audit P2 / P3 / P4 / P3-PMP / P6) — Runner 3.16.10 / Hazard 2.23.14 / PMP 0.4.3 (#291)

## 2026-11-07

- DWR_Plugins `5622547` Audit batch 2 (correctness): H06/H08/H09/H19/H10/H23 — Runner 3.16.7 / Hazard 2.23.11 / Screening 0.18.15 (#289)
- DWR_Plugins `16578f1` H07: Runner/Screening classify velocity over all wet cells, matching Hazard (Runner 3.16.6 / Screening 0.18.14) (#288)
- DWR_Plugins `4b0c53b` Audit fixes: loss-of-life warning band, storage leak guard, sensitivity pairing, triage road rule (#287)

## 2026-11-06

- DWR_Plugins `b146407` DamSafety Runner 3.16.4: sunny-day Vw = DWR max storage, PMF Vw = storage at the breach pool (#286)
- DWR_Plugins `1cd757b` Runner 3.16.3 / Hazard 2.23.9 / Screening 0.18.12 / Data 1.9.1: bounded xlsx reader and plain errors for bad input (#285)
- DWR_Plugins `dd0b849` DamSafety Runner 3.16.2: HEC-RAS breach always Froehlich (2008); breach equations use Vw = max storage (#284)
- DWR_Plugins `cdbf11b` DamSafety Runner 3.16.1: HEC-RAS breach defaults to piping, Froehlich (2008) — review only (#283)
- DWR_Plugins `682a0f3` Build OSM layers from Geofabrik when Overpass is down (DamSafety Data 1.9.0) (#282)
- DWR_Plugins `dc201c0` Get 3DHP from the national file when the web service is down (DamSafety Data 1.8.0) (#281)
- DWR_Plugins `8befccf` DamSafety Runner 3.16.0: selectable LISFLOOD-FP solver (ACC default, FV2, MWDG2) (#280)

## 2026-11-05

- DWR_Plugins `d03df4b` Merge #277: re-run LISFLOOD-FP with stable ACC settings when it makes water (DamSafety Runner 3.15.1)
- DWR_Plugins `792b793` Merge #270: crest burn + automatic finer grid as Runner defaults (DamSafety Runner 3.15.0)
- DWR_Plugins `182d9fb` Merge #276: DamSafety Data keeps its offline pack up to date (Data 1.7.0)
- DWR_Plugins `07ee4e1` Merge #275: one data updater for both suites (shared engine + source list, pin v6)
- DWR_Plugins `274d939` Merge #274: one pack layer list for both suites (shared ABI_* + ND DEQ layers, pin v5)
- DWR_Plugins `fdc129a` Merge #273: one offline pack builder for both suites (includes #272 Browser connections)
- DWR_Plugins `acdbb5e` feat(Data): USGS stream crossings in the offline pack (1.5.5) (#271)
- DWR_Plugins `4308a18` cleanup(Data): drop two dead locals (out_geojson in ArcGIS fetch, skipped in _run_file) (#267)
- DWR_Plugins `f85f409` feat(runner): terrain-aware 10 m grid default on flat plains (3.14.7) (#268)
- DWR_Plugins `e04ad83` fix(screening): DEM download works when the PROJ grid server is unreachable (0.18.7) (#266)
- DWR_Plugins `9c170fc` test: test_dem_z_once passes with a geoid grid (PROJ_NETWORK=ON) (#265)

## 2026-11-04

- DWR_Plugins `722338f` fix: GUI check 2026-11-04 - windows, docks and Processing panels fit 800 px (#264)
- DWR_Plugins `395c277` feat: GUI fit at 800x600 + 3DHP labels (#262)
- DWR_Plugins `2db2773` fix: Clear QGIS plugin upload security-scan blockers (#259)
- DWR_Plugins `65a1417` Screening 0.18.5: self-test takes the LISFLOOD-FP executable (parity with nd 0.17.0) (#263)

## 2026-11-03

- DWR_Plugins `d1895d8` Runner 3.14.1 / Hazard 2.23.0: OpenStreetMap culverts in the structures layer (#257)
- DWR_Plugins `39f8b83` Runner 3.14.0: cut unmatched culvert guesses into the DEM as guessed, unverified boxes (#256)
- DWR_Plugins `b512bd6` Audit fix E: Runner window min width (wizard button on its own row), lint cleanup, Screening storage conf simplified; Hazard 2.23.1, Runner 3.14.2, Screening 0.18.4, HazardLite 0.1.3 (#261)
- DWR_Plugins `72f9d0e` Wording sync + 3DHP flowlines (audit D) - review only (#260)
- DWR_Plugins `97e97a4` Hazard 2.22.5: DV = peak depth x peak wet-cell velocity; missing velocity filled with structure peak (audit fix C) (#258)
- DWR_Plugins `95016f2` HazardLite 0.1.2: judgment zone ND MEDIUM by rule by default; velocity_unknown column, nanmax vmax (audit 2026-11-03) (#255)
- DWR_Plugins `fd1b99c` PMP: drop two dead locals (pothole any_exit, algorithm sink/err) (#253)
- DWR_Plugins `21b92e4` Hazard 2.22.4: autodetect DSS-WISE rasters named Depth_ft / Velocity_ftps (#254)
- DWR_Plugins `38369dc` Runner 3.13.9: results dock shows the Hazard class and status (#247)
- DWR_Plugins `33a93c0` DamSafety Hazard: audit busy/setting widget names, drop dead run_all_btn (#252)

## 2026-11-02

- DWR_Plugins `80f0b33` damsuite cascade: a dam at the source location is the source, not downstream (#251)
- DWR_Plugins `501d008` Style A wizard polish: Setup 1.0.19 / Runner 3.13.8 (#249)
- DWR_Plugins `c1c44a2` Option C: classify structures on peak depth with peak wet-cell velocity (TM 11), all tools + parity test [review only] (#248)

## 2026-11-01

- DWR_Plugins `3af4328` Keep the hazard copy identical and do not open a download URL as a file.

## 2026-10-31

- DWR_Plugins `3208f53` Docs: toe-inflow rule, judgment-zone MEDIUM rule (#241), Oct 29 offline pack (#245)
- DWR_Plugins `7f14f93` Runner 3.13.5: DWR-6141 false CHECK THE DAM POINT; AADT join reads per-dam pack clips (#246)
- DWR_Plugins `db9c665` Harden pack paths and fix hazard classification.

## 2026-10-30

- DWR_Plugins `1e3e2f7` Full-test fixes and one-dam chain fixes: Hazard 2.21.2, Runner 3.12.11, Screening 0.17.59, Setup 1.0.18 (#242)
- DWR_Plugins `7fcbdb0` Runner 3.12.10: breach inflow placement on DWR-4031 (#237) (#238)
- DWR_Plugins `d53c11b` Hazard 2.22.1 / Runner 3.13.2: DWR-4031 toe10m report text + 5.3(f) moved-only count
- DWR_Plugins `6f63c4b` Hazard 2.22.0 / Runner 3.13.0 / Screening 0.18.0: judgment-zone house is ND MEDIUM by rule
- DWR_Plugins `de5c6be` Hazard 2.21.1: summary wording from the DWR-4031 review
- DWR_Plugins `a3e8a2f` Hazard 2.21.0: name a dam and add its model results
- DWR_Plugins `cc9adc2` Runner 3.12.9 / Hazard 2.20.4 / Screening 0.17.58 / damsuite 1.18.4: local datum band is 0-500 ft (#234)

## 2026-10-29

- DWR_Plugins `0a62e71` Hazard 2.20.3 / Runner 3.12.8 / Screening 0.17.57 / Data 1.5.2 / Setup 1.0.17 / damsuite 1.18.3: format-1 pack readers, HIFLD lifelines, flood zones (#235)
- DWR_Plugins `0396940` Runner 3.12.7 / Screening 0.17.56 / damsuite 1.18.2: 0-300 ft local by the DEM tie (#228)
- DWR_Plugins `ef6c2a1` Runner 3.12.6: ANUGA resume keeps its checkpoint key (#231)
- DWR_Plugins `8254271` Data 1.5.1 / Hazard 2.20.2: NHD fills only failed 3DHP areas; HIFLD credits; DWR dates (#232)
- DWR_Plugins `235cf06` PMP 0.4.0: StreamStats basin data, ND peak-flow check, PMF comparison (#229)
- DWR_Plugins `ca617bf` Add offline breach dashboard and QGIS results dock (#230)
- DWR_Plugins `06c8108` Runner 3.12.4: ANUGA host-pause check on PROGRESS lines; checkpoint timer on monotonic time

## 2026-10-28

- DWR_Plugins `5c5765f` Fix committed merge-conflict markers on main
- DWR_Plugins `36b2532` Runner 3.12.3: culvert prep - corrected copy of the structures layer, big changes flagged for review
- DWR_Plugins `44d3e7c` Runner 3.12.2: ANUGA worker detached from QGIS; finish a run after QGIS closed
- DWR_Plugins `fd670f7` Data 1.5.0: pack sources (#221 follow-up) + Download imagery + main CI fix
- DWR_Plugins `c2e24cf` Hazard 2.19.2: fix the ND DWR download (build_nd_pack --download-dwr)
- DWR_Plugins `1e74573` DamSafety_Data 1.5.0: Build offline pack (ND_Dam_Suite_Pack + nd_offline_pack.sqlite)
- DWR_Plugins `2c005c9` Runner 3.12.1 / Hazard 2.20.1: NGVD29 dam elevations to NAVD88 with VERTCON
- DWR_Plugins `9b2526f` 7b can download the runner DEM for the chosen dams (Screening 0.17.55)
- DWR_Plugins `71959f4` Docs: Runner 3.11.0 / Hazard 2.19.0 user guide; CHANGELOG, Hazard README and metadata changelog clean-up (#217)
- DWR_Plugins `b8e4bc1` Main clean-up + smoke-test fixes: Hazard 2.19.1 / Runner 3.11.1
- DWR_Plugins `7feee1f` Sync RELEASE, constants, and pin to metadata versions (2.19.0 / 3.11.0)
- DWR_Plugins `df22ad5` Fix configparser errors in Runner and Hazard metadata.txt
- DWR_Plugins `c7930e5` Hazard 2.19.0 / Runner 3.11.0: aerial basemap on report, map book and QA maps
- DWR_Plugins `ee20a3d` Hazard 2.18.69: crossing depth in the 1 m channel (DWR-3034 item 8)
- DWR_Plugins `ab8299b` Hazard 2.18.68: explain missing MS footprints in offline-only mode
- DWR_Plugins `9f8452d` Runner 3.10.96: culvert datum-shift check vs LiDAR channel bed; losses, opt-in bed floor, per-operator volume log
- DWR_Plugins `4fb24e7` Runner 3.10.95 / Hazard 2.18.67: G5 note, OSM ford dedupe, bridge-snap counts
- DWR_Plugins `fafc569` Runner 3.10.94: cap ANUGA's first dry-domain step at the hydrograph interval (DWR-3034 G5)
- DWR_Plugins `bac0046` DWR dugouts: Screening tool 1/16 + DWR GeoPackages in the offline pack
- DWR_Plugins `57b7e09` Screening 0.17.54: Tool 16 no longer stalls on a statewide water-body layer

## 2026-10-27

- DWR_Plugins `e20dac8` Runner: fix duplicate version/changelog lines in metadata.txt
- DWR_Plugins `72fcd59` Runner 3.10.85: tighter HEC-RAS solver/plan settings (40 iter, 3s step cap, cores by mesh size, IC ramp-up, sine breach, ANUGA-clipped outflow)
- DWR_Plugins `0b06cf4` Runner 3.10.92: HEC-RAS depth from actual terrain per pixel by default (reverses #189); add terrain_mean/terrain_max/fine bases
- DWR_Plugins `f58e088` Hazard 2.18.65 / Hazard Lite 0.1.1: roads and rail overtopped only over the 1 m centreline crown (DWR-2801)
- DWR_Plugins `407cbee` Runner 3.10.91: ANUGA gmsh mesh holds road/rail crests at 1 m DEM elevation (DWR-2801)
- DWR_Plugins `a122958` Screening 0.17.53: setHelp on key Breach Hydrograph parameters
- DWR_Plugins `bd77239` Screening 0.17.52: setHelp on key Download DEM parameters
- DWR_Plugins `a8d3a72` Runner 3.10.90: road overtopping over the road crown (cut trenches masked); NBI bridge cuts snapped to the crossing (DWR-3034) - DO NOT MERGE (#198)
- DWR_Plugins `c23d38a` Screening 0.17.51: runnerhandoff per-parameter help + DRY_RUN (issue #35)
- DWR_Plugins `2e19e91` Runner 3.10.89 / Screening 0.17.50: DEM units auto-detect (incl. Download DEM record) + explain the 729 1 m ImageServer requests, offer native 1 m tiles (Absaraka) (#197)
- DWR_Plugins `37fdfbe` Runner 3.10.87: HEC-RAS crest trace finds DWR-2801's embankment; dam line input (#195:)
- DWR_Plugins `ac39f87` tools/mac: Mac installer (QGIS 3.34, ANUGA, gmsh, LISFLOOD-FP 8.3) + NickReview run scripts (#196)

## 2026-10-26

- DWR_Plugins `a83ad04` Screening 0.17.49: 7b sends inventory max-pool area with no curve folder; inv_area_m2 no longer reads max_pool_area (follow-up to #188) (#194)
- DWR_Plugins `bafe2a8` Hazard 2.18.64, Runner 3.10.86, Screening 0.17.48, damsuite 1.17.6: packcheck never raises; a broken pack blocks where layers are required (#171 follow-up) (#192)
- DWR_Plugins `50a7fca` Screening 0.17.47: each inventory storage at its own elevation - max storage no longer used as normal (DWR-2865 / DWR-3034) (#190)
- DWR_Plugins `2f6fc4f` Runner 3.10.85: HEC-RAS export BC line just outside the 2D perimeter (#193)
- DWR_Plugins `b6cc5b9` Runner 3.10.84, Hazard 2.18.63: HEC-RAS depth = cell max WSE minus cell MINIMUM terrain by default (reverses #173's per-pixel default), and the chain and Hazard follow it (#189)
- DWR_Plugins `ca0ea17` Docs: CHANGELOG - #171 entry moved to 2026-10-25 (released) (#187)

## 2026-10-25

- DWR_Plugins `cc5892e` Screening 0.17.46: 7b surface-area fallback to DWR max_pool_area + optional Runner water-body mask (#188)
- DWR_Plugins `8e9b49f` Runner 3.10.83: real-Qt DEM-rows test finds DamSafety_Screening through a symlinked Runner (tests only) (#186)
- DWR_Plugins `69e4738` DamSafety_PMP 0.3.1: declare QGIS 4 / Qt6 support (metadata/compat, plus a fast-gate check) (#179)
- DWR_Plugins `7530579` Hazard 2.18.62: reproduce / data folder - every file of every role is loaded, or a loud warning (#183)
- DWR_Plugins `496db56` Seed thinning now drops band points closer than 0.7 x the band cell. Only a lone first row is protected. fix_faces drops the neighbour across an over-faced cell's shortest face and splits a big coarse cell ringed by band cells. Qhull runs on centred coordinates. Defaults are unchanged. (#185:)
- DWR_Plugins `06ff45a` Runner 3.10.81: self-test tests ignore a real LISFLOOD-FP/ANUGA set in the environment (tests only) (#181)
- DWR_Plugins `4756001` CI only. A new push to a PR cancels that PR's older run, while every push to main keeps its own run. Job timeouts: fast-checks 15 min, plugin-suites 60 min, model-tests 90 min. (#184:)
- DWR_Plugins `418cc6f` Runner 3.10.80: clip LISFLOOD-FP gauge sections to the grid (garbage gauge discharge) (#182)
- DWR_Plugins `e484bdf` Merge pull request #180 from nickdbendickson/fix/stale-runner-model-tests
- DWR_Plugins `f4b159e` Docs: HEC-RAS depth from the terrain (Runner 3.10.78) - why old results were too high, depth_basis, re-export (for #173) (#174)
- DWR_Plugins `e21925e` Hazard 2.18.61: HEC-RAS plan import - arrival on the same depth basis as the depth (terrain / Runner re-export / cell-min warning) (#177)
- DWR_Plugins `c837fdb` Runner 3.10.79: HEC-RAS depth from the terrain under each grid cell (not the cell minimum); re-export of a finished run (#173)
- DWR_Plugins `b758576` Runner 3.10.78: Windows HEC-RAS launcher correctness (#167 review) (#175)
- DWR_Plugins `c68a17d` Runner tests: stop two tests leaking state across the suite (#176)
- DWR_Plugins `97ef957` Docs: format-2 offline packs in Hazard and the pack check (for #171) (#172)
- DWR_Plugins `3547e0a` Hazard 2.18.60: format-2 offline packs + pack check against manifest.json (damsuite 1.17.5; Runner 3.10.77, Screening 0.17.45) (#171)
- DWR_Plugins `40d2140` HEC-RAS (Runner 3.10.76): 3 rows of 20 ft cells along roads, rail, structures and breaklines; optional ANUGA line band (depends on #169) (#170)
- DWR_Plugins `93c2ad0` HEC-RAS (Runner 3.10.75): RasUnsteady stack limit, structure lines on cell faces, connection names without '/' (DWR-2801) (#169)
- DWR_Plugins `812c827` Docs: ND_Dam_Suite_Pack NHD waterbody layer restored; fix 'no waterbody layer' claims (#168)

## 2026-10-24

- DWR_Plugins `8f84ee7` Batch-chain + Windows HEC-RAS launcher: correctness fixes from a static review (#167)
- DWR_Plugins `73ffe24` Runner 3.10.73: read-only ANUGA slowdown checker (host freeze vs time-step collapse) (#165)
- DWR_Plugins `27353b6` Runner 3.10.72: culvert pre-check before a run (ndbreach_cli.py culvert-precheck) (#166)
- DWR_Plugins `2b45b53` Runner 3.10.71: ANUGA culvert inverts from the fine ground; enquiry points past the inlet triangles (#164)
- DWR_Plugins `6a28452` Runner 3.10.70: ANUGA time-step diagnostic (opt-in) + wall clock on ANUGA progress lines (DWR-2801 slowdown) (#163)
- DWR_Plugins `b9e8e2b` Screening 0.17.43: tool 7b dam.json gets surface_area_ac and dam_length_ft (or a null with the reason) (#162)
- DWR_Plugins `1e5d0e2` Data: delete unused pack_sources.py and OVERTURE_NOTE (#161)

## 2026-10-23

- DWR_Plugins `5ee1c52` Runner 3.10.69: ANUGA gmsh far-field sizing (grading distance, line min area, wet footprint; defaults unchanged) (#160)
- DWR_Plugins `ac697d7` Screening: delete unused helpers (gpkg_sqlite.py, crop_box, is_line_source, step_of_tool) (#159)
- DWR_Plugins `b9bfec6` Windows HEC-RAS 6.6 launcher for the batch chain (Runner 3.10.68; untested on Windows) (#158)
- DWR_Plugins `9bd933a` Batch chain: a list of dams through Screening, Runner, HEC-RAS 2D and Hazard (Runner 3.10.67 / Hazard 2.18.59) (#157)
- DWR_Plugins `2e38109` Batch runs the HEC-RAS 2D stage (Runner 3.10.66); Hazard batch 2D-area model boundary (2.18.58) (#156)
- DWR_Plugins `93d580a` Runner 3.10.65: HEC-RAS structure connections 2 cells inside the 2D area (follow-up to #146, Absaraka KO-01) (#155)
- DWR_Plugins `e0b29eb` docs: results log - HEC-RAS v2e_gmsh_r_nf2 and the cv/cv2 failures (QA) (#154)

## 2026-10-21

- DWR_Plugins `d05dcd4` Fix stale window wording and two clipped layouts (#151)
- DWR_Plugins `c34d1df` Add optional downstream bearing to single-dam DEM download (#152)
- DWR_Plugins `45b3a80` DamSafety_Runner: optional "accept unpatched LISFLOOD-FP" setting (#153)
- DWR_Plugins `0a4f9e3` Tool dialogs stay in front of the window that opened them (Runner 3.10.63, Screening 0.17.41, Hazard 2.18.57) (#150)
- DWR_Plugins `4486f4f` Qt6 enum hygiene: fix 3 latent PyQt6 breakages + add a fast CI lint (Runner 3.10.62) (#149)
- DWR_Plugins `1c2758f` Hazard 2.18.50: restored 911 points (duplicates, non-dwelling evidence, Notes), model edge with a no-data ring, co-located snap, M3 near-limit (on #133) (#134)
- DWR_Plugins `86ac33c` Screening 0.17.33: Von Thun & Gillette Cb limits match the Runner (1,000 / 5,000 / 10,000 ac-ft) (#125)
- DWR_Plugins `82e8a17` Runner 3.10.41: gmsh-points timeout on the wall clock (core/wallclock), SIGTERM then SIGKILL to the group (#127)
- DWR_Plugins `e222070` Runner 3.10.43, Screening 0.17.35: gdal.Warp downsampling reads full-resolution data, not source overviews (-ovr NONE) (#128)
- DWR_Plugins `753b0df` Hazard 2.18.47: fill raster boxes when the same dam is handed over again (#112)
- DWR_Plugins `e2e57e7` Runner 3.10.56: HEC-RAS packages get the culverts and bridges ANUGA used; stop if the terrain loses its CRS (#146)
- DWR_Plugins `148e4b1` Runner 3.10.55: ANUGA outer edges outflow-only (a clipped edge no longer gains water; NDDOT culvert run 4.15x); volume balance check (#143)
- DWR_Plugins `6cc30a5` Runner 3.10.54: HEC-RAS compile errors show HEC-RAS's Compute Messages (no-limit TypeError fixed); check-only weir/notch-cell pre-flight (run queue QA c4) (#142)
- DWR_Plugins `02571a0` Runner 3.10.49: ANUGA thread count checks (inf/nan/decimals ignored with a note, clamped to the CPUs; CLI --threads help) - #132 follow-ups (#138)
- DWR_Plugins `1b5a63a` CI: fail on version / changelog bookkeeping regressions (RELEASE vs metadata vs PLUGIN_VERSION; lower than main; dropped changelog entries) (#147)
- DWR_Plugins `201e943` docs: flag anuga_structures_20261015 UNRELIABLE (transmissive-edge volume gain) (#148)
- DWR_Plugins `921456c` docs: USER_GUIDE tip for #126 zone colours (REG_05.2026) and zone-layer transparency (#145)
- DWR_Plugins `5e7fff7` Merge #136: CI suites report after failure
- DWR_Plugins `6aeec1d` Merge PR #133: Hazard 2.18.49 Microsoft footprints geometry
- DWR_Plugins `034e9d7` docs: arrival depth 0.1 ft (#131) and HEC-RAS no default time limit (#137) - user guide, results log, changelog (#144)
- DWR_Plugins `d0a3bc1` docs: ANUGA threads (#132, Runner 3.10.47) — user guide, results log, changelog (#135)
- DWR_Plugins `b210c6c` docs: results log for the 2026-10-21 run queue (QA) (#141)
- DWR_Plugins `2c19374` Docs: Hazard re-baselines on 2.18.44 and 2.18.45 (2026-10-20/21) in RESULTS_LOG, with H1 QA (#129)
- DWR_Plugins `732f597` Hazard 2.18.48, Runner 3.10.45, Screening 0.17.37: US / State highways at least Medium (REG_05.2026 5.2.1.2(b)); arrival depth 0.1 ft (after #126, #130) (#131)
- DWR_Plugins `ad4f31a` Hazard 2.18.47, Runner 3.10.44, Screening 0.17.36: hazard tables against REG_05.2026 Section 5 (on #126) (#130)
- DWR_Plugins `74a8e99` Hazard 2.18.46, Runner 3.10.42, Screening 0.17.34: hazard-zone colours from REG_05.2026 Fig. 5.1/5.2 (#126)
- DWR_Plugins `8d5493f` Setup: delete unused health.py (dead code, -46 lines) (#140)
- DWR_Plugins `5931cf2` Runner 3.10.50: real OpenMP thread count in the ANUGA report (omp_probe), Windows ANUGA env search, manual Windows/macOS scaling workflow - #132 follow-up (#139)
- DWR_Plugins `a3a1030` Runner 3.10.48: HEC-RAS 2D compute has no wall-clock limit unless NDBREACH_HECRAS_TIMEOUT_S is set (was 2-48 h) (#137)

## 2026-10-20

- DWR_Plugins `278db1f` Update README.md
- DWR_Plugins `caaf850` Runner 3.10.47: ANUGA uses several OpenMP threads (threads=0 → NDBREACH_ANUGA_THREADS or min(CPUs−2, 4)); bit-identical results (#132)
- DWR_Plugins `5b4ed05` Fix the DamSafety High findings of the 19 Oct audit (Setup 1.0.15, Hazard 2.18.45, Runner 3.10.40, Screening 0.17.32) (#113)
- DWR_Plugins `0a8344b` Runner 3.10.39: Download a DEM rows keep their height (fixes #107) (#118)
- DWR_Plugins `ec5c577` Runner 3.10.38: ANUGA checkpoints, partial results and resume (on for long runs) (#117)
- DWR_Plugins `8ae5487` Hazard 2.18.44: Classify no longer scrolls sideways (fixes #108) (#116)
- DWR_Plugins `18e9e27` Docs: DWR-3161 (#84, #93), Absaraka ANUGA 20x20/48 h results and refined-run setup, CHANGELOG through #114 (main b0c2ad5) (#99)
- DWR_Plugins `953c425` Cleanup: delete unused field and geometry helpers in Hazard helpers.py (#122)
- DWR_Plugins `b6b0420` DamSafety Hazard Lite 0.1.0: small hmax/vmax + REG_05.2026 5.2 classifier (#124)
- DWR_Plugins `d90e3c2` Runner 3.10.37: engine chips lead with their mark; missing ANUGA is amber (#123)
- DWR_Plugins `b27e2d8` GUI grammar part 3: Setup option A and the Runner dam wizard (#121)
- DWR_Plugins `c35748d` GUI grammar part 2: Runner and Screening main windows (#120)
- DWR_Plugins `7892d11` GUI grammar part 1: shared/ui canonical files, tokens, GUI lint, four window bugs (#115)

## 2026-10-19

- DWR_Plugins `b0c2ad5` Runner/CI: de-flake hecras_engine_write_project_hydrograph_inflow (green main) (#114)
- DWR_Plugins `186c926` Damsuite shared pin (fork-convergence slice 2) + recommendations round (dead-code, de-dup) (#111)
- DWR_Plugins `2df10f6` Screening 0.17.28: Download DEM source 'USGS 3DEP 1 m lidar tiles (native, TNM)' (#105)
- DWR_Plugins `478ad27` Claude's audit-fix campaign (H1–H14, M1–M24, L1–L3) with review follow-ups (Runner 3.10.32, Hazard 2.18.39, Screening 0.17.28, Data 1.4.2, Setup 1.0.11) (#94)
- DWR_Plugins `dca3275` Runner 3.10.31: ANUGA bed from the finest terrain (vertices), gmsh short-edge gate fix, gmsh culvert size, mesh_filename signature check (builds on #102) (#104)
- DWR_Plugins `84e411e` Runner 3.10.30: ANUGA default mesher - merge overlapping culvert-end octagons (Absaraka slivers 0.15 m2 -> 8.7 m2, dt x6.4) (#102)
- DWR_Plugins `4007e24` Runner 3.10.28: HEC-RAS breach timing, spillway, tolerances, plugin reference, optional gmsh points, crest dam line (Absaraka DWR-2801; includes #103) (#90)
- DWR_Plugins `0d04108` Cross-platform review: no console windows on Windows; Qt6-safe enum spellings (#100)
- DWR_Plugins `5c14aed` Setup 1.0.10: missing dam height/storage - NID fill, Estimate from DEM; hide not-a-dam records; dam point from the dam line (#88)
- DWR_Plugins `622b3c4` README: how to run the Setup tests (pytest in qgis334) (#98)
- DWR_Plugins `587dddf` Runner: remove 3 unused imports in plugin.py (#97)
- DWR_Plugins `b853ce7` Cleanup: delete unused FieldPlan, compare_result, extra_datasets, _fill_suite (Hazard, Data, Runner) (#95)
- DWR_Plugins `31d443f` Run report metrics: depth-threshold areas, P95/P99 velocity, max-velocity cell, receptor velocities, water-body mask (Runner 3.10.27, closes #91) (#92)
- DWR_Plugins `09660cf` Runner 3.10.26: HEC-RAS timeouts on the wall clock (SIGTERM, grace, SIGKILL; timeout logged before cleanup) (#96)
- DWR_Plugins `608c58b` Fix tests failing on main d217ec2; Screening tool 3 honours the storage choice (Runner 3.10.25, Screening 0.17.27) (#101)
- DWR_Plugins `d217ec2` Flagged structures: DWR-3161 is a road fill over backwater, hazard Low (DWR) (Runner 3.10.23, Hazard 2.18.38, Screening 0.17.26) (#93)

## 2026-10-18

- DWR_Plugins `a71e9e7` Screening: county download boxes from the county outlines (audit 1.22 #5) [HIGH-RISK: extents] (#78)
- DWR_Plugins `219594a` Screening: merge and Review writes work on GeoPackages QGIS wrote (audit #4) (#77)
- DWR_Plugins `8f1a41d` Suite UI polish: monitor-aware window sizing and one ellipsis character (Runner 3.10.21, Screening 0.17.25, Data 1.4.1, Setup 1.0.9, Hazard 2.18.37) (#89)
- DWR_Plugins `05d7235` Hazard 2.18.36: UI polish from Lumo's Hazard screens review (#87)
- DWR_Plugins `88a4877` RESULTS_LOG: re-baseline 2026-10-18 (TIER 0, main 8b0601c, culvert burn on) + HEC-RAS TIER 2 comparison (#83)
- DWR_Plugins `f2156ce` Runner 3.10.19: reservoir bottom carved from the storage curve (RESERVOIR_CARVE, opt-in) (#86)
- DWR_Plugins `50f891f` Runner 3.10.18: gmsh ANUGA mesh gate, strict/loud fallback, road and rail embankment lines (#85)
- DWR_Plugins `6886e7b` Runner 3.10.18: breach inflow on the downstream side (DWR-3161); side check; road-fill warning (#84)
- DWR_Plugins `5fbae0e` HEC-RAS TIER 2: report/polygons from HEC-RAS rasters; walk a rejected inflow point downstream (#76)
- DWR_Plugins `df4b354` Data: download into <suite data folder>/structures/, guard the pack, keep old downloads (audit 1.22 #7) (#80)
- DWR_Plugins `c9df884` Setup 1.0.8: wizard live checks - Next follows the page, reason in red (#82)
- DWR_Plugins `ae3f60a` Hazard 2.18.35: dam folder must be one dam's folder; rasters must belong to it (H-1, H-2) (#81)
- DWR_Plugins `e2cde8d` Runner 3.10.17: HEC-RAS site checks, breach invert vs toe ground, crest dam line, simulation window (#79)

## 2026-10-17

- DWR_Plugins `8b0601c` Runner TIER 2 + 7b ENGINE 2: LISFLOOD-FP then HEC-RAS 2D (PR 3 of #68, stacked on #72) (#73)
- DWR_Plugins `7cc6d9b` Runner: HEC-RAS 2D engine module (PR 2 of #68, off by default) (#72)
- DWR_Plugins `9744be8` Runner: optional gmsh ANUGA mesher (ANUGA_MESHER=gmsh, hidden, off by default) (#71)
- DWR_Plugins `fd80838` Design: optional gmsh breakline-graded ANUGA mesh (doc + mesh-only prototype) (#70)
- DWR_Plugins `2a9ae1a` Design: HEC-RAS 2D as a third engine (doc only) (#68)
- DWR_Plugins `06989ca` Runner window: grid size (CELL) follows project state, then the settings file, then 10 (#51)
- DWR_Plugins `a73db0e` Runner: no per-pass rasters in Monte Carlo run folders when per-run rasters are off (#50)
- DWR_Plugins `6dc1b70` Test: suite home 'Opened from' uses the DamSafety Runner name (#49)
- DWR_Plugins `a83af0f` Test: Runner window passes and saves its run fields (#48)
- DWR_Plugins `2ca1045` Test: nd_hazard chart sign-off matches the one-signer rule from #24 (#47)
- DWR_Plugins `e3dfa43` Runner 3.10.16: HEC-RAS export builds the 2D model package; inflow fix; dam-line trim (review only) (#75)
- DWR_Plugins `a8f3b2e` Hazard 2.18.34: window redesign — Classify / Results / Review + ⚙ menu (depends on #69, do not merge yet) (#74)
- DWR_Plugins `b414ee4` Runner 3.10.15: window redesign (review only) (#69)

## 2026-10-16

- DWR_Plugins `383ca26` Docs: 7b engine/culverts (#22), culvert matching (#30), cross-platform (#32), results log update (#34)
- DWR_Plugins `52875e2` Add DamSafety_PMP (nd_pmp v0.3.0 prototype): INTERNAL / EXPERIMENTAL, not validated against ArcGIS (#60)
- DWR_Plugins `89cb655` Hazard 2.18.32: show Check inputs results in a panel, ranked by severity (#67)
- DWR_Plugins `d1646a6` Screening 0.17.23: window layout (Run / Review / Results, pipeline strip, settings gear) — DO NOT MERGE yet (#66)

## 2026-10-15

- DWR_Plugins `9313ba9` Hazard 2.18.31: Lumo vReal.20 pack resume / extent transforms + vReal.21 submittal (#65)
- DWR_Plugins `36cbe88` Hazard 2.18.30: Lumo vReal.18b submittal / watch / history fixes (#64)
- DWR_Plugins `300c36b` Hazard 2.18.29: Lumo vReal.18 offline pack / OSM / evacuation fixes (#63)
- DWR_Plugins `867291a` Hazard 2.18.28: Lumo vReal.17 download robustness / eval key / roads (#62)
- DWR_Plugins `b0268e8` Hazard 2.18.27: Lumo vReal.16 evacuation dry-safe / EAP fixes (#61)
- DWR_Plugins `2114f89` Hazard 2.18.26: Lumo vReal.15 datafolder / webexport robustness (#59)
- DWR_Plugins `d0de0b9` Hazard 2.18.25: Lumo vReal.14 form fill / parcel hints / temporal fixes (#58)
- DWR_Plugins `b3a9a8b` Hazard 2.18.24: Lumo vReal.13 portfolio/reproduce fixes (#57)
- DWR_Plugins `2b73602` Hazard 2.18.23: Lumo vReal.12 estimate/run download parity + profile apply warnings (#56)
- DWR_Plugins `f0c5a7d` Hazard 2.18.22: Lumo vReal fingerprint/sensitivity/scenarios/sampling fixes (#55)
- DWR_Plugins `f8ab334` Hazard 2.18.21: fix SyntaxError so the plugin loads (#54)
- DWR_Plugins `46df503` Hazard 2.18.20: Lumo structures ST.1–ST.8 (DamSafety only) (#53)
- DWR_Plugins `e5220ed` Remove old nd_ plugins (archived on archive/nd-plugins) (#45)
- DWR_Plugins `cfb533b` Runner ND 5.2.1.2: same AADT join as Hazard; preliminary label + defer to Hazard (DWR-3161) (#40)
- DWR_Plugins `ef06872` 7b engine follow-ups from #22 review (one engine choice, visible ANUGA, culvert warning, ANUGA check, help) (#38)
- DWR_Plugins `ad7f871` Hazard (DamSafety 2.18.19, ND 2.31.6): Lumo dialog/review_tab fixes (#52)
- DWR_Plugins `d994dd1` Hazard (DamSafety 2.18.17, ND 2.31.5): Lumo v1.7/v1.8 fixes (#46)
- DWR_Plugins `1a06cd4` Hazard (DamSafety 2.18.16, ND 2.31.4): Lumo v1.6 fixes (#44)
- DWR_Plugins `36cbed2` Hazard: Lumo v1.5 fixes (DamSafety 2.18.15, ND 2.31.3) — stacked on #42 (#43)
- DWR_Plugins `7e77b68` Hazard: Lumo audit round 2 (DamSafety 2.18.14, ND 2.31.2) — stacked on #41 (#42)
- DWR_Plugins `47b8b6b` Hazard: Lumo audit short list (DamSafety 2.18.13, ND 2.31.1) (#41)
- DWR_Plugins `18ae1f5` Plan-datum CLP inverts in run report + patch version bump (#32) (#37)
- DWR_Plugins `e97e59b` damsuite copies: cross-platform text I/O (follow-up to #32), FILES.json updated (#39)
- DWR_Plugins `0ade9ea` Setup wizard DEM check; 7b help text and culverts-unused warning (#36)
- DWR_Plugins `6ffd632` Runner: size culvert guesses from the NDDOT/NBI inventory (#30)
- DWR_Plugins `d608aa0` Cross-platform fixes: UTF-8 text I/O, CSV newline='', Windows conda env python, subprocess decoding (#32)
- DWR_Plugins `a428f99` Fix confirmed audit issues (crest cap, feet LiDAR, dry-dam ground, ND inflow, truncation warnings, LISFLOOD vetting) (#33)
- DWR_Plugins `10eebb2` Hazard chart sign-off: 'Install in plugins' off by default (#25)
- DWR_Plugins `f062e4c` Docs: user guide, changelog and results log (PRs #9-#21, #23, #27) (#29)
- DWR_Plugins `ed16653` Runner tests: stop early when scipy is missing (6 of the 10 failures) (#28)
- DWR_Plugins `e2acb76` Screening 7b: engine choice and culverts/bridges for the Runner (ANUGA with structures from the GUI) (#22)
- DWR_Plugins `c3d3d78` Spillway adequacy: fixes from #23 review (#27)
- DWR_Plugins `f1debf4` Runner: spillway adequacy tool (REG_05.2026 IDF pass/fail) (#23)
- DWR_Plugins `a5c4280` damsuite consolidation + single-engineer TM11 sign-off (Nicholas Bendickson) (#24)
- DWR_Plugins `6030cf4` Draft: simplify the plugin windows - first steps (YOUR values first, one home, Data plugin fixes) (#16)
- DWR_Plugins `c62de53` Remaining test failures: inflow point + 7b structure_points (real bugs), FILES.json, test isolation, harness (#14)
- DWR_Plugins `6b228a8` Runner: QA inflow and depth maps for every run (#21)
- DWR_Plugins `b5c05f7` Screening: shallow-basin storage guard (port of nd_ 0.28.3) + tests (#13)

## 2026-10-14

- DWR_Plugins `e343d70` Standard work-folder layout (QGIS Dev) (#18)
- DWR_Plugins `a28911f` rundam: fix ValueError with a culvert/bridge STRUCTURES layer (#20)
- DWR_Plugins `334ff32` Screening: fix pre-existing test failures on QGIS 3.34 (numpy trapz, test_runner import) (#19)
- DWR_Plugins `1665b50` Close os.scandir iterators (no ResourceWarning) (#17)
- DWR_Plugins `f927416` Tool 7b: unknown-like classes treated as blank; 'High, Medium, Low and unknown' mode + tests (#15)
- DWR_Plugins `2e70b61` damsuite settings: safe shared saves (merge, no clobber on open, atomic + .bak, lock) + tests (#12)
- DWR_Plugins `41f4a4e` Security, integrity and performance fixes (2026-10-14 review) (#11)
- DWR_Plugins `a4e64b9` Runner: DEM_RESAMPLE default bilinear -> average (precedence unchanged) (#10)
- DWR_Plugins `0ef590f` Crest breach: place only on this dam's line within 500 m (#8)
- DWR_Plugins `16734a1` Runner: restore NDBREACH_DEM_RESAMPLE (param > env > default), DEM_RESAMPLE setting, method in run_manifest.json (#9)
- DWR_Plugins `246d21b` Fix four real bugs: defaults() json shadowing, process-wide gdal.UseExceptions, Runner VERSION from metadata, selftest paths (#7)
- DWR_Plugins `c79277a` Tests: fix harness/environment failures; list real bugs left failing (#6)
- DWR_Plugins `2daff6e` Follow-ups: 20 mi max extent everywhere, DEM download named by dam ID and auto-picked, Run page grid text (#5)
- DWR_Plugins `7d710a5` Wizard: DEM lookup scoped to the selected dam; refuse '/' and root Dams folders + tests (#4)
- DWR_Plugins `719c3f6` Max extent visible in the main dialog, 20 mi default + tests (#3)
- DWR_Plugins `248dbc7` Never write into the read-only ND_Dam_Suite_Pack (safe Dams folder default + guards) + tests (#2)
- DWR_Plugins `b32e750` Setup: Metres stay metres in the Runner (DEM_Z by unit id) + tests (#1)
- DWR_Plugins `2a87916` Add Claude-built nd_ plugins release 1.23 for comparison audit
- DWR_Plugins `b03a010` Initial import: plugins + audit docs
