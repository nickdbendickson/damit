# Suite Processing algorithm help

_Generated 2026-11-13 by dump-algorithm-help.zsh from `qgis_process` (QGIS 3.34.4-Prizren 'Prizren' (exported))._
_Do not edit: run the script again. Heim: for these providers, an algorithm id that is not in this table does not exist, and a parameter that is not in that algorithm's page does not exist. The DaMiT tools (damit_*) are in ALGORITHM-HELP-DAMIT.md._

Providers: ndbreach, nddam, ndfind, ndhazard, ndlite, ndpmp. Algorithms: 89.

| Algorithm id | What it is | Full help |
|---|---|---|
| `ndbreach:animation` | Flood animation (GIF / MP4 / time-enabled layers) | [algorithm-help/ndbreach.animation.md](algorithm-help/ndbreach.animation.md) |
| `ndbreach:batch` | Run breach models for a layer of dams (batch) | [algorithm-help/ndbreach.batch.md](algorithm-help/ndbreach.batch.md) |
| `ndbreach:benchmark` | Compare with a reference model (e.g. HEC-RAS) | [algorithm-help/ndbreach.benchmark.md](algorithm-help/ndbreach.benchmark.md) |
| `ndbreach:buildvrt` | Build a statewide LiDAR DEM mosaic (VRT) | [algorithm-help/ndbreach.buildvrt.md](algorithm-help/ndbreach.buildvrt.md) |
| `ndbreach:cascade` | Cascade failure of dams in a chain | [algorithm-help/ndbreach.cascade.md](algorithm-help/ndbreach.cascade.md) |
| `ndbreach:chainbatch` | Batch chain: Screening → Runner → HEC-RAS → Hazard, dam by dam | [algorithm-help/ndbreach.chainbatch.md](algorithm-help/ndbreach.chainbatch.md) |
| `ndbreach:check` | Check the model installation | [algorithm-help/ndbreach.check.md](algorithm-help/ndbreach.check.md) |
| `ndbreach:conditiondem` | Preview the DEM conditioning around a dam | [algorithm-help/ndbreach.conditiondem.md](algorithm-help/ndbreach.conditiondem.md) |
| `ndbreach:consequences` | Life-safety and damage estimate (incremental) | [algorithm-help/ndbreach.consequences.md](algorithm-help/ndbreach.consequences.md) |
| `ndbreach:culvertprep` | Culvert prep: corrected copy of the structures layer (review list) | [algorithm-help/ndbreach.culvertprep.md](algorithm-help/ndbreach.culvertprep.md) |
| `ndbreach:estimate` | Estimate the run time for one dam | [algorithm-help/ndbreach.estimate.md](algorithm-help/ndbreach.estimate.md) |
| `ndbreach:fillgaps` | Fill no-data gaps in a DEM | [algorithm-help/ndbreach.fillgaps.md](algorithm-help/ndbreach.fillgaps.md) |
| `ndbreach:finishanuga` | Finish an ANUGA run after QGIS closed | [algorithm-help/ndbreach.finishanuga.md](algorithm-help/ndbreach.finishanuga.md) |
| `ndbreach:hecrasexport` | Export the breach to HEC-RAS (2D model package, hydrograph and breach table) | [algorithm-help/ndbreach.hecrasexport.md](algorithm-help/ndbreach.hecrasexport.md) |
| `ndbreach:hecrasimport` | Import HEC-RAS 2D results as rasters | [algorithm-help/ndbreach.hecrasimport.md](algorithm-help/ndbreach.hecrasimport.md) |
| `ndbreach:hydrograph` | Breach hydrograph only | [algorithm-help/ndbreach.hydrograph.md](algorithm-help/ndbreach.hydrograph.md) |
| `ndbreach:ndhazardclass` | ND hazard classification (Section 5.2, ACER TM 11 charts) | [algorithm-help/ndbreach.ndhazardclass.md](algorithm-help/ndbreach.ndhazardclass.md) |
| `ndbreach:nested` | Nested run: fine grid near the dam, coarse grid downstream | [algorithm-help/ndbreach.nested.md](algorithm-help/ndbreach.nested.md) |
| `ndbreach:nlcdmanning` | Manning's n raster from NLCD land cover | [algorithm-help/ndbreach.nlcdmanning.md](algorithm-help/ndbreach.nlcdmanning.md) |
| `ndbreach:probabilistic` | Probabilistic breach runs (Monte Carlo) | [algorithm-help/ndbreach.probabilistic.md](algorithm-help/ndbreach.probabilistic.md) |
| `ndbreach:products` | Flood polygons and EAP map from a dam's rasters | [algorithm-help/ndbreach.products.md](algorithm-help/ndbreach.products.md) |
| `ndbreach:rainfallrunoff` | Rainfall to inflow (PMF) hydrograph | [algorithm-help/ndbreach.rainfallrunoff.md](algorithm-help/ndbreach.rainfallrunoff.md) |
| `ndbreach:rundam` | Run breach model for one dam | [algorithm-help/ndbreach.rundam.md](algorithm-help/ndbreach.rundam.md) |
| `ndbreach:selftest` | Self-test the installation in this QGIS | [algorithm-help/ndbreach.selftest.md](algorithm-help/ndbreach.selftest.md) |
| `ndbreach:sensitivity` | Sensitivity of the breach model for one dam | [algorithm-help/ndbreach.sensitivity.md](algorithm-help/ndbreach.sensitivity.md) |
| `ndbreach:spillwayadequacy` | Spillway adequacy (pass the Inflow Design Flood?) | [algorithm-help/ndbreach.spillwayadequacy.md](algorithm-help/ndbreach.spillwayadequacy.md) |
| `ndbreach:submittal` | Submittal report (Word) | [algorithm-help/ndbreach.submittal.md](algorithm-help/ndbreach.submittal.md) |
| `ndbreach:validationrecord` | Validation record from a benchmark comparison | [algorithm-help/ndbreach.validationrecord.md](algorithm-help/ndbreach.validationrecord.md) |
| `ndbreach:verifymanifest` | Verify a run manifest (inputs and results unchanged?) | [algorithm-help/ndbreach.verifymanifest.md](algorithm-help/ndbreach.verifymanifest.md) |
| `nddam:breachdirection` | 4 - Breach point and flow direction | [algorithm-help/nddam.breachdirection.md](algorithm-help/nddam.breachdirection.md) |
| `nddam:breachhydrograph` | 5 - Breach parameters and hydrograph | [algorithm-help/nddam.breachhydrograph.md](algorithm-help/nddam.breachhydrograph.md) |
| `nddam:comparereference` | 11 - Compare with a reference model | [algorithm-help/nddam.comparereference.md](algorithm-help/nddam.comparereference.md) |
| `nddam:datapackage` | 0 - Build offline data package | [algorithm-help/nddam.datapackage.md](algorithm-help/nddam.datapackage.md) |
| `nddam:downloaddem` | Download DEM (dam, county, or state) | [algorithm-help/nddam.downloaddem.md](algorithm-help/nddam.downloaddem.md) |
| `nddam:downloadlayers` | 0b - Download offline layers | [algorithm-help/nddam.downloadlayers.md](algorithm-help/nddam.downloadlayers.md) |
| `nddam:estimateruntime` | 12 - Estimate the run time of the simulations | [algorithm-help/nddam.estimateruntime.md](algorithm-help/nddam.estimateruntime.md) |
| `nddam:estimatestorage` | 3 - Estimate reservoir storage | [algorithm-help/nddam.estimatestorage.md](algorithm-help/nddam.estimatestorage.md) |
| `nddam:findponds` | 16 - Find ponds and dugouts | [algorithm-help/nddam.findponds.md](algorithm-help/nddam.findponds.md) |
| `nddam:hazardclassification` | 8 - Hazard classification | [algorithm-help/nddam.hazardclassification.md](algorithm-help/nddam.hazardclassification.md) |
| `nddam:inventorydiff` | 13 - Inventory diff (what changed since the last run) | [algorithm-help/nddam.inventorydiff.md](algorithm-help/nddam.inventorydiff.md) |
| `nddam:mergeponds` | 18 - Merge dams and ponds | [algorithm-help/nddam.mergeponds.md](algorithm-help/nddam.mergeponds.md) |
| `nddam:preparedams` | 1 - Prepare dam inventory | [algorithm-help/nddam.preparedams.md](algorithm-help/nddam.preparedams.md) |
| `nddam:proposedam` | 19 - Propose a dam | [algorithm-help/nddam.proposedam.md](algorithm-help/nddam.proposedam.md) |
| `nddam:reports` | 10 - Reports and statewide summary | [algorithm-help/nddam.reports.md](algorithm-help/nddam.reports.md) |
| `nddam:runbreachsim` | 7 - Run breach flood simulations | [algorithm-help/nddam.runbreachsim.md](algorithm-help/nddam.runbreachsim.md) |
| `nddam:runchain` | 15 - Run the steps in order (headless) | [algorithm-help/nddam.runchain.md](algorithm-help/nddam.runchain.md) |
| `nddam:runnerhandoff` | 7b - Detailed runs with DamSafety Runner | [algorithm-help/nddam.runnerhandoff.md](algorithm-help/nddam.runnerhandoff.md) |
| `nddam:selftest` | 14 - Self-test in this QGIS | [algorithm-help/nddam.selftest.md](algorithm-help/nddam.selftest.md) |
| `nddam:sensitivity` | 9 - Sensitivity of the class (borderline dams) | [algorithm-help/nddam.sensitivity.md](algorithm-help/nddam.sensitivity.md) |
| `nddam:terraincache` | 2 - Cache terrain per dam | [algorithm-help/nddam.terraincache.md](algorithm-help/nddam.terraincache.md) |
| `nddam:triage` | 6 - Quick screen (triage) | [algorithm-help/nddam.triage.md](algorithm-help/nddam.triage.md) |
| `ndfind:crossings` | Find road and rail crossings of streams (culverts) | [algorithm-help/ndfind.crossings.md](algorithm-help/ndfind.crossings.md) |
| `ndfind:embankments` | Find fills across streams and draws (dams, dry dams, road fills, dugouts) | [algorithm-help/ndfind.embankments.md](algorithm-help/ndfind.embankments.md) |
| `ndfind:evidence` | Add evidence to fills (water by year, NWI, LiDAR drop-out, what is below) | [algorithm-help/ndfind.evidence.md](algorithm-help/ndfind.evidence.md) |
| `ndfind:osm` | Extract dams, dikes and culverts from OpenStreetMap | [algorithm-help/ndfind.osm.md](algorithm-help/ndfind.osm.md) |
| `ndfind:ponds` | Find ponds and dugouts in a water-body layer | [algorithm-help/ndfind.ponds.md](algorithm-help/ndfind.ponds.md) |
| `ndfind:review_batch` | Pick a review batch (random control, top-ranked, near the cut) | [algorithm-help/ndfind.review_batch.md](algorithm-help/ndfind.review_batch.md) |
| `ndfind:score` | Score fills by how much they look like the listed dams | [algorithm-help/ndfind.score.md](algorithm-help/ndfind.score.md) |
| `ndfind:water` | Find open water in aerial imagery (pond outlines) | [algorithm-help/ndfind.water.md](algorithm-help/ndfind.water.md) |
| `ndfind:water_mosaic` | Build a class-9 water mosaic from LiDAR tiles | [algorithm-help/ndfind.water_mosaic.md](algorithm-help/ndfind.water_mosaic.md) |
| `ndhazard:acerzones` | ACER TM 11 hazard zone rasters | [algorithm-help/ndhazard.acerzones.md](algorithm-help/ndhazard.acerzones.md) |
| `ndhazard:adddamresults` | Add model results to a dam | [algorithm-help/ndhazard.adddamresults.md](algorithm-help/ndhazard.adddamresults.md) |
| `ndhazard:batch` | Batch hazard classification (folder of dams) | [algorithm-help/ndhazard.batch.md](algorithm-help/ndhazard.batch.md) |
| `ndhazard:chartsignoff` | ACER TM 11 chart sign-off (chart file for the Breach Runner / Screening) | [algorithm-help/ndhazard.chartsignoff.md](algorithm-help/ndhazard.chartsignoff.md) |
| `ndhazard:classify` | Dam hazard classification (ND REG_05.2026 / ACER TM 11) | [algorithm-help/ndhazard.classify.md](algorithm-help/ndhazard.classify.md) |
| `ndhazard:creepwatch` | Hazard creep watch (folder of dams, fresh data) | [algorithm-help/ndhazard.creepwatch.md](algorithm-help/ndhazard.creepwatch.md) |
| `ndhazard:damsinseries` | Dams in series screen (folder of dams) | [algorithm-help/ndhazard.damsinseries.md](algorithm-help/ndhazard.damsinseries.md) |
| `ndhazard:dsswise` | Import DSS-WISE Lite results | [algorithm-help/ndhazard.dsswise.md](algorithm-help/ndhazard.dsswise.md) |
| `ndhazard:ensemble` | Hazard class probability from an ensemble of breach runs | [algorithm-help/ndhazard.ensemble.md](algorithm-help/ndhazard.ensemble.md) |
| `ndhazard:fillform` | Fill a form template from a dam's results | [algorithm-help/ndhazard.fillform.md](algorithm-help/ndhazard.fillform.md) |
| `ndhazard:hecrasplan` | Import HEC-RAS plan results (2D, .hdf) | [algorithm-help/ndhazard.hecrasplan.md](algorithm-help/ndhazard.hecrasplan.md) |
| `ndhazard:markreviewed` | Mark the classification reviewed | [algorithm-help/ndhazard.markreviewed.md](algorithm-help/ndhazard.markreviewed.md) |
| `ndhazard:modelgate` | Model gate (checks of the breach model results) | [algorithm-help/ndhazard.modelgate.md](algorithm-help/ndhazard.modelgate.md) |
| `ndhazard:portfolio` | Dam portfolio dashboard (folder of dams) | [algorithm-help/ndhazard.portfolio.md](algorithm-help/ndhazard.portfolio.md) |
| `ndhazard:quickcreep` | Quick creep screen: new structures layer against every dam's flood | [algorithm-help/ndhazard.quickcreep.md](algorithm-help/ndhazard.quickcreep.md) |
| `ndhazard:reproduce` | Reproduce a past run from its package | [algorithm-help/ndhazard.reproduce.md](algorithm-help/ndhazard.reproduce.md) |
| `ndhazard:reviewhabitable` | Review habitable structures (engineer sign-off) | [algorithm-help/ndhazard.reviewhabitable.md](algorithm-help/ndhazard.reviewhabitable.md) |
| `ndhazard:reviewpackage` | Review a submittal package (checklist) | [algorithm-help/ndhazard.reviewpackage.md](algorithm-help/ndhazard.reviewpackage.md) |
| `ndhazard:reviewsummary` | Summarize a filled review checklist | [algorithm-help/ndhazard.reviewsummary.md](algorithm-help/ndhazard.reviewsummary.md) |
| `ndhazard:rulecompare` | Compare with the Breach Runner / Screening rules (nd_hazard) | [algorithm-help/ndhazard.rulecompare.md](algorithm-help/ndhazard.rulecompare.md) |
| `ndhazard:runnerculverts` | Culvert and bridge lines for DamSafety Runner | [algorithm-help/ndhazard.runnerculverts.md](algorithm-help/ndhazard.runnerculverts.md) |
| `ndhazard:suiteexport` | Export data package for ND Dam Breach Screening | [algorithm-help/ndhazard.suiteexport.md](algorithm-help/ndhazard.suiteexport.md) |
| `ndlite:classify` | Classify dam hazard (REG_05.2026 5.2) | [algorithm-help/ndlite.classify.md](algorithm-help/ndlite.classify.md) |
| `ndpmp:export_hms` | Export HEC-HMS project (optionally run it headless) | [algorithm-help/ndpmp.export_hms.md](algorithm-help/ndpmp.export_hms.md) |
| `ndpmp:inflow_hydrograph` | Inflow hydrograph from PMP hyetographs | [algorithm-help/ndpmp.inflow_hydrograph.md](algorithm-help/ndpmp.inflow_hydrograph.md) |
| `ndpmp:pmp` | PMP Evaluation (main tool) | [algorithm-help/ndpmp.pmp.md](algorithm-help/ndpmp.pmp.md) |
| `ndpmp:pothole_storage` | Pothole (depression) storage & contributing area | [algorithm-help/ndpmp.pothole_storage.md](algorithm-help/ndpmp.pothole_storage.md) |
| `ndpmp:snowmelt` | Snowmelt (100-yr SWE, degree-day, rain-on-snow) | [algorithm-help/ndpmp.snowmelt.md](algorithm-help/ndpmp.snowmelt.md) |
| `ndpmp:spatial_distribution` | PMP spatial distribution (SPAS storm patterns) | [algorithm-help/ndpmp.spatial_distribution.md](algorithm-help/ndpmp.spatial_distribution.md) |
