"""DamIT PMP: damit_pmp:lisfloodrain, a LISFLOOD-FP rain-on-grid job (the counterpart of damit_pmp:anugarain).

The domain, the model DEM and the rain series are the ANUGA job's; the .par, .bci, gauge section, solver choice and
executable search are damit_runner's LISFLOOD-FP setup (damit_pmp/runner_shared holds its files verbatim; see
lisfloodrain.py). Nothing here launches a process: damit_pmp/launch.py does, and only when RUN_LISFLOOD (default off)
is switched on.
"""
import os
import sys
import time

import numpy as np

from qgis.core import (Qgis, QgsProcessing, QgsProcessingException, QgsProcessingOutputNumber, QgsProcessingOutputString,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum, QgsProcessingParameterExtent,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterFolderDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterPoint, QgsProcessingParameterRasterLayer, QgsProcessingParameterString)

from .. import _deps  # noqa: F401
from .. import anugarain as AR
from .. import launch
from .. import lisfloodrain as LR
from .anuga_algs import FLAG_ADV, AnugaRain
from .pf_algs import DOUBLE, INTEGER, NOTE, _Base
from ..runner_shared import lisflood as L


def _plugin_version():
    from ..provider import plugin_version
    return plugin_version()


class LisfloodRain(_Base):
    _domain = AnugaRain._domain
    _opt_num = AnugaRain._opt_num

    def name(self):
        return "lisfloodrain"

    def displayName(self):  # noqa: N802
        return "LISFLOOD-FP rain-on-grid job (damit_runner's setup)"

    def shortHelpString(self):  # noqa: N802
        return (
            "Builds a LISFLOOD-FP rain-on-grid job the way damit_runner sets up its LISFLOOD-FP run, on the same domain "
            "as damit_pmp:anugarain: the DEM resampled to the model cell and masked to the domain polygon (written as "
            "'Model Terrain (LISFLOOD).tif' and, in local coordinates, rain.dem.asc), rain.bci with FREE (outflow) "
            "domain edges, rain.rain (mm/hr from the *_anuga_rate.csv of damit_pmp:raingrid, the same breakpoints the "
            "ANUGA job interpolates) and rain.par with the runner's keywords: the solver (ACC, the local-inertial CPU "
            "solver, by default), simulation time, mass-balance interval, Manning n 0.06, outputs (max depth, mass "
            "balance) and an optional discharge gauge across the line GAUGE_A - GAUGE_B. The runner's own lisflood.py, "
            "data_conventions.py, grid.py and units.py are verbatim, sha-pinned copies (runner_shared); the breach "
            "inflow and the arrival-time patch keywords are left out (a rain run has no breach).\n\n"
            "Cells outside the domain polygon are NODATA, which LISFLOOD-FP treats as walls. The grid is cropped to the "
            "domain's valid cells so the FREE edges touch it: water leaves only where the domain reaches the grid "
            "edge (a downstream box that reaches the DEM edge does), at the bed slope. ANUGA's outer ring is an "
            "outflow boundary all round, so ANUGA also drains the basin rim: a difference documented in the "
            "manifest (edge_valid_cells counts the domain cells on each edge; all zero = a closed model). Rain is "
            "uniform: the .rain file is a single series.\n\n"
            "SOLVER: ACC (default) runs on any CPU build. " + LR.CUDA_NOTE + " FV1 and DG2 are refused, as in the "
            "runner.\n\n"
            "0.4.2: STAGE_PROBE writes the water level at a point (the pond) every MASSINT_S to "
            "lisflood_probe_stage.csv. OUTLET_* model a dam's principal outlet pipe as a point sink at its inlet and a point "
            "source at its outlet end (LISFLOOD-FP has no pipe element; the weir file is weir flow only), the discharge being "
            "the Boyd inlet-control rating of the pond stage series OUTLET_STAGE_CSV from an earlier run of the same model: "
            "one coupling iteration, labelled in the manifest (and assumed unless OUTLET_ASSUMED is off).\n\n"
            "Nothing is launched by default. RUN_LISFLOOD (off) runs the executable (LISFLOOD_EXE, or the runner's "
            "search: DAMIT_LISFLOOD, PATH, the usual build folders) and then reads results/rain.max, rain.mass and the "
            "gauge into lisflood_rain_results.json and lisflood_max_depth.tif. Otherwise run it yourself: `lisflood -v "
            "rain.par` in the output folder. " + NOTE)

    def initAlgorithm(self, config=None):  # noqa: N802
        def adv(p):
            p.setFlags(p.flags() | FLAG_ADV)
            return p

        add = self.addParameter
        add(QgsProcessingParameterRasterLayer("DEM", "DEM (projected CRS in metres)"))
        add(QgsProcessingParameterFeatureSource("BASIN", "Basin / domain polygon (the model domain; or use the extent)",
                                                [QgsProcessing.TypeVectorPolygon], optional=True))
        add(QgsProcessingParameterExtent("EXTENT", "... or a rectangular domain (used when no basin is given)",
                                         optional=True))
        add(QgsProcessingParameterFile("RATE_CSV", "Rain series (the *_anuga_rate.csv from damit_pmp:raingrid: "
                                       "time_s, rate_m_per_s)", extension="csv"))
        add(QgsProcessingParameterNumber("CELL_M", "Model cell size (m)", DOUBLE, defaultValue=LR.DEFAULTS["cell_m"],
                                         minValue=AR.MIN_CELL_M))
        add(QgsProcessingParameterNumber("SIM_TIME_H", "Simulation time (hours; 0 = end of the rain series + 6 h)", DOUBLE,
                                         defaultValue=0.0, minValue=0.0))
        add(QgsProcessingParameterEnum("SOLVER", "Solver (ACC = CPU default; FV2 / MWDG2 need a CUDA build)",
                                       list(LR.SOLVER_CHOICES), defaultValue=0))
        add(QgsProcessingParameterNumber("MANNING_N", "Manning n (runner default 0.06)", DOUBLE,
                                         defaultValue=LR.DEFAULTS["manning_n"], minValue=0.0001, maxValue=1.0))
        add(QgsProcessingParameterPoint("GAUGE_A", "Discharge section, first end (with GAUGE_B: LISFLOOD-FP records the "
                                        "flow through this section, e.g. just below a dam; it is run along the nearest grid "
                                        "axis; empty = none)", optional=True))
        add(QgsProcessingParameterPoint("GAUGE_B", "Discharge section, second end", optional=True))
        add(QgsProcessingParameterPoint("FLOW_PATH_START", "Dam / pour point (the same point as the ANUGA job's flow-path "
                                        "start: it seeds the domain's main piece and orients the gauge downstream)",
                                        optional=True))
        add(adv(QgsProcessingParameterPoint("STAGE_PROBE", "Record the water level at this point (e.g. the pond; LISFLOOD-FP "
                                             "stagefile -> lisflood_probe_stage.csv, to rate an outlet in a second run)",
                                             optional=True)))
        add(adv(QgsProcessingParameterPoint("OUTLET_INLET", "Principal outlet (pipe through the dam), inlet end on the pond "
                                             "side: a point sink here and a point source at OUTLET_OUTLET, each the pipe's "
                                             "discharge (empty = no outlet)", optional=True)))
        add(adv(QgsProcessingParameterPoint("OUTLET_OUTLET", "Principal outlet, outlet end downstream of the dam", optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_DIAMETER_M", "Outlet pipe diameter (m)", DOUBLE, optional=True, minValue=0.05)))
        add(adv(QgsProcessingParameterNumber("OUTLET_INVERT_IN_M", "Outlet inlet invert elevation (m, DEM datum)", DOUBLE, optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_INVERT_OUT_M", "Outlet outlet invert elevation (m, recorded only)", DOUBLE, optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_BARRELS", "Outlet number of barrels", DOUBLE, 1.0, minValue=1.0)))
        add(adv(QgsProcessingParameterBoolean("OUTLET_ASSUMED", "The outlet values are assumed (not from the as-built drawings)", True)))
        add(adv(QgsProcessingParameterFile("OUTLET_STAGE_CSV", "Pond stage at the inlet from an earlier run of this model "
                                            "(lisflood_probe_stage.csv: t_s,stage_m): the pipe flow is its Boyd inlet-control "
                                            "rating (one coupling iteration)", optional=True)))
        add(adv(QgsProcessingParameterNumber("SIMPLIFY_M", "Simplify the outer outline by this tolerance (m; empty = the "
                                             "runner's rule; use the ANUGA job's value for the same domain)", DOUBLE,
                                             optional=True, minValue=0.5)))
        add(adv(QgsProcessingParameterNumber("BUFFER_M", "Grow the domain by this much (m)", DOUBLE, defaultValue=0.0,
                                             minValue=0.0)))
        add(adv(QgsProcessingParameterNumber("MASSINT_S", "Mass-balance / gauge interval (s)", DOUBLE,
                                             defaultValue=LR.DEFAULTS["massint_s"], minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("INITIAL_TSTEP_S", "Initial time step (s; runner 10)", DOUBLE,
                                             defaultValue=LR.DEFAULTS["initial_tstep_s"], minValue=0.001)))
        add(adv(QgsProcessingParameterNumber("THETA", "ACC theta (1 = LISFLOOD-FP's own; the runner's stable value 0.7)",
                                             DOUBLE, defaultValue=1.0, minValue=0.01, maxValue=1.0)))
        add(adv(QgsProcessingParameterNumber("CFL", "ACC cfl (empty = LISFLOOD-FP's own 0.7; the runner's stable value "
                                             "0.5)", DOUBLE, optional=True, minValue=0.01, maxValue=1.0)))
        add(adv(QgsProcessingParameterString("CLOSED_EDGES", "Grid edges closed as walls instead of FREE (letters from "
                                             "N S E W; empty = all free)", optional=True)))
        add(adv(QgsProcessingParameterNumber("THREADS", "OpenMP threads for the run (0 = the solver's own)", INTEGER,
                                             defaultValue=LR.DEFAULTS["threads"], minValue=0, maxValue=512)))
        add(QgsProcessingParameterString("LISFLOOD_EXE", "LISFLOOD-FP executable (empty = the runner's search: "
                                         "DAMIT_LISFLOOD, PATH, the usual build folders)", optional=True))
        add(QgsProcessingParameterBoolean("RUN_LISFLOOD", "Also RUN LISFLOOD-FP now (default off)", defaultValue=False))
        add(adv(QgsProcessingParameterNumber("RUN_TIMEOUT_H", "LISFLOOD-FP wall-clock timeout (hours)", DOUBLE,
                                             defaultValue=24.0, minValue=0.01)))
        add(QgsProcessingParameterFolderDestination("OUTPUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputString("PAR", "LISFLOOD-FP parameter file (rain.par)"))
        self.addOutput(QgsProcessingOutputString("TERRAIN", "Model terrain GeoTIFF"))
        self.addOutput(QgsProcessingOutputString("MANIFEST", "Run manifest (JSON)"))
        self.addOutput(QgsProcessingOutputString("RESULTS", "Results summary (JSON; empty when not run)"))
        self.addOutput(QgsProcessingOutputNumber("CELLS", "Cells in the domain"))

    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        t_start = time.time()
        out_dir = os.path.abspath(self.parameterAsString(P, "OUTPUT_DIR", context))
        os.makedirs(out_dir, exist_ok=True)
        dem_layer = self.parameterAsRasterLayer(P, "DEM", context)
        if dem_layer is None or dem_layer.crs().isGeographic():
            raise QgsProcessingException("The DEM must be in a projected CRS in metres; reproject it first.")
        run_it = self.parameterAsBool(P, "RUN_LISFLOOD", context)
        exe_in = (self.parameterAsString(P, "LISFLOOD_EXE", context) or "").strip()
        try:
            exe = LR.find_exe(exe_in)
            if run_it and not exe:
                raise AR.JobError("RUN_LISFLOOD needs a LISFLOOD-FP executable: none was given or found "
                                  "(LISFLOOD_EXE, DAMIT_LISFLOOD, PATH).")
            edges = [c for c in (self.parameterAsString(P, "CLOSED_EDGES", context) or "").upper() if c.isalpha()]
            st = LR.check_settings(dict(
                cell_m=self.parameterAsDouble(P, "CELL_M", context), buffer_m=self.parameterAsDouble(P, "BUFFER_M", context),
                manning_n=self.parameterAsDouble(P, "MANNING_N", context),
                solver=LR.SOLVER_CHOICES[self.parameterAsEnum(P, "SOLVER", context)],
                initial_tstep_s=self.parameterAsDouble(P, "INITIAL_TSTEP_S", context),
                massint_s=self.parameterAsDouble(P, "MASSINT_S", context), threads=self.parameterAsInt(P, "THREADS", context),
                theta=self.parameterAsDouble(P, "THETA", context), cfl=self._opt_num(P, "CFL", context), closed_edges=edges))
            rings, bounds, what = self._domain(P, context, dem_layer.crs(), st["cell_m"])
            feedback.pushInfo("Domain: {}; reading the DEM at {:g} m".format(what, st["cell_m"]))
            grid, ginfo = AR.read_model_grid(dem_layer.source(), bounds, st["cell_m"])
            start = None
            if P.get("FLOW_PATH_START") not in (None, ""):
                pt = self.parameterAsPoint(P, "FLOW_PATH_START", context, dem_layer.crs())
                start = (pt.x(), pt.y())
            gauge = None
            if P.get("GAUGE_A") not in (None, "") or P.get("GAUGE_B") not in (None, ""):
                if P.get("GAUGE_A") in (None, "") or P.get("GAUGE_B") in (None, ""):
                    raise QgsProcessingException("A discharge section needs both GAUGE_A and GAUGE_B.")
                ga = self.parameterAsPoint(P, "GAUGE_A", context, dem_layer.crs())
                gb = self.parameterAsPoint(P, "GAUGE_B", context, dem_layer.crs())
                gauge = LR.gauge_from_ab((ga.x(), ga.y()), (gb.x(), gb.y()), start)
            terrain, tinfo = LR.model_terrain(grid, rings, st["buffer_m"], start, self._opt_num(P, "SIMPLIFY_M", context))
            outlet, outlet_q, probe = None, None, None
            if P.get("OUTLET_INLET") not in (None, "") or P.get("OUTLET_OUTLET") not in (None, ""):
                nums = [self._opt_num(P, k, context) for k in ("OUTLET_DIAMETER_M", "OUTLET_INVERT_IN_M", "OUTLET_INVERT_OUT_M")]
                if P.get("OUTLET_INLET") in (None, "") or P.get("OUTLET_OUTLET") in (None, "") or any(v is None for v in nums) \
                        or P.get("OUTLET_STAGE_CSV") in (None, ""):
                    raise QgsProcessingException("An outlet needs OUTLET_INLET, OUTLET_OUTLET, OUTLET_DIAMETER_M, OUTLET_INVERT_IN_M, "
                                                 "OUTLET_INVERT_OUT_M and OUTLET_STAGE_CSV (first run the model without the outlet "
                                                 "and a STAGE_PROBE at the pond, then give its lisflood_probe_stage.csv).")
                pi = self.parameterAsPoint(P, "OUTLET_INLET", context, dem_layer.crs())
                po = self.parameterAsPoint(P, "OUTLET_OUTLET", context, dem_layer.crs())
                outlet = AR.outlet_spec((pi.x(), pi.y()), (po.x(), po.y()), nums[0], nums[1], nums[2], barrels=self.parameterAsDouble(
                    P, "OUTLET_BARRELS", context), assumed=self.parameterAsBool(P, "OUTLET_ASSUMED", context))
                try:
                    sd = np.loadtxt(self.parameterAsFile(P, "OUTLET_STAGE_CSV", context), delimiter=",", skiprows=1, ndmin=2)
                except (OSError, ValueError) as e:
                    raise QgsProcessingException("Cannot read OUTLET_STAGE_CSV ({})".format(e))
                if sd.shape[1] < 2:
                    raise QgsProcessingException("OUTLET_STAGE_CSV needs the columns t_s,stage_m")
                outlet_q = LR.outlet_flow_series(sd[:, 0], sd[:, 1], outlet)
                feedback.pushInfo("Outlet: {:.2f} m pipe, inverts {:.2f} -> {:.2f} m{}; peak rated flow {:.2f} m3/s".format(
                    outlet["width_m"], *outlet["invert_elevations"], " (ASSUMED values)" if outlet["assumed"] else "",
                    float(outlet_q[1].max())))
            if P.get("STAGE_PROBE") not in (None, ""):
                pp = self.parameterAsPoint(P, "STAGE_PROBE", context, dem_layer.crs())
                probe = (pp.x(), pp.y())
            t, r = AR.read_rate_csv(self.parameterAsFile(P, "RATE_CSV", context))
            sim_h = self.parameterAsDouble(P, "SIM_TIME_H", context)
            sim_time = sim_h * 3600.0 if sim_h > 0 else float(t[-1]) + LR.DEFAULTS["extra_h"] * 3600.0
            if sim_time < float(t[-1]):
                feedback.pushInfo("Warning: the simulation ends before the rain series does.")
        except (AR.JobError, L.ModelError) as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("Domain: {:.2f} km2 ({:.2f} sq mi), {} valid cells of {} x {}".format(
            tinfo["domain_km2"], tinfo["domain_km2"] / 2.589988, tinfo["domain_cells"], terrain.ny, terrain.nx))
        free = [e for e in "NSEW" if e not in st["closed_edges"]]
        if not any(tinfo["edge_valid_cells"][e] for e in free):
            feedback.pushInfo("Warning: no domain cell touches a FREE grid edge, so this model is closed: all rain stays "
                              "in the domain (extend the domain to a DEM edge, e.g. a downstream box, to let water leave).")
        if st["solver"] != L.SOLVER_ACC:
            feedback.pushInfo("Warning: " + LR.CUDA_NOTE)
        tif = LR.write_tif(os.path.join(out_dir, LR.TERRAIN_NAME), terrain)
        rate_copy = os.path.join(out_dir, "rain_rate_m_per_s.csv")
        with open(self.parameterAsFile(P, "RATE_CSV", context), "rb") as a, open(rate_copy, "wb") as b:
            b.write(a.read())
        comment = "rainfall in mm/hr (time in s) from {}: damit_pmp:lisfloodrain".format(
            os.path.basename(self.parameterAsFile(P, "RATE_CSV", context)))
        par = LR.write_inputs(out_dir, terrain, t, r, st, sim_time, gauge, comment, outlet, outlet_q, probe)
        rain_mm = LR.depth_mm(t, r)

        run_rec, results = None, None
        if run_it:
            feedback.pushInfo("RUN_LISFLOOD is on: running {} (timeout {:g} h)".format(exe, self.parameterAsDouble(
                P, "RUN_TIMEOUT_H", context)))
            try:
                cp = launch.run_lisflood(exe, par, st["threads"], self.parameterAsDouble(P, "RUN_TIMEOUT_H", context) * 3600.0,
                                         log=feedback.pushInfo)
            except Exception as e:      # noqa: BLE001 - timeout or start failure: reported
                raise QgsProcessingException("The LISFLOOD-FP run did not finish: {}".format(e))
            run_rec = {"returncode": cp.returncode, "stdout_tail": (cp.stdout or "")[-600:]}
            if cp.returncode != 0:
                raise QgsProcessingException("LISFLOOD-FP stopped with code {}: {}".format(
                    cp.returncode, (cp.stdout or cp.stderr or "")[-300:]))
            try:
                results = LR.summarize(out_dir, terrain, sim_time, rain_mm)
            except AR.JobError as e:
                raise QgsProcessingException(str(e))
            feedback.pushInfo("Results: max depth {:.2f} m, wet > 5 cm {:.3f} km2".format(
                results["max_depth_m"], results["wet_area_km2"]["0.05 m"]))

        dem_path = dem_layer.source()
        manifest = {
            "tool": "damit_pmp:lisfloodrain", "damit_pmp_version": _plugin_version(),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "qgis": Qgis.version(), "python": sys.version.split()[0],
            "domain": {"source": what, "crs": dem_layer.crs().authid(), "area_km2": tinfo["domain_km2"],
                       "area_sq_mi": tinfo["domain_km2"] / 2.589988, "simplify_m": tinfo["simplify_m"],
                       "model_cell_m": st["cell_m"], "grid": [terrain.ny, terrain.nx], "valid_cells": tinfo["domain_cells"],
                       "x0": terrain.x0, "y0": terrain.y0, "pour_point": start,
                       "outside_domain": "NODATA (a wall in LISFLOOD-FP)", "edge_valid_cells": tinfo["edge_valid_cells"],
                       "cropped_from_grid": tinfo["cropped_from"], "edges": "FREE except " + ",".join(
                           st["closed_edges"]) if st["closed_edges"] else "FREE on all four edges"},
            "settings": dict(st, sim_time_s=sim_time, cuda_note=LR.CUDA_NOTE, par_lines=LR.par_lines(st, sim_time, gauge=bool(gauge), bdy=outlet is not None,
                                                    stage=probe is not None)),
            "outlet": None if outlet is None else dict(outlet, rated_peak_m3_s=float(outlet_q[1].max()), coupling="pipe flow rated from the stage series of an earlier run (Boyd inlet control): a point sink at the inlet and a point source at the outlet end"),
            "gauge": gauge, "rain": {"depth_mm": rain_mm, "peak_mm_hr": float(r.max()) * LR.MM_PER_HR,
                                     "spatial": "uniform", "file": LR.RAIN_NAME},
            "inputs": {"dem": {"path": dem_path, "sha256": AR.sha256_file(dem_path) if os.path.isfile(dem_path) else None,
                               "crs": dem_layer.crs().authid(), "native_cell_m": ginfo["native_cell_m"]},
                       "rate_csv": {"path": self.parameterAsFile(P, "RATE_CSV", context), "sha256": AR.sha256_file(rate_copy)}},
            "lisflood": {"executable": exe or None, "description": L.describe_exe(exe) if exe else None,
                         "launched": bool(run_it), "result": run_rec},
            "runner_shared_sha256": LR.runner_sources(),
            "runner_reuse": ("lisflood.py (LisfloodSettings, solver names and choice, local_grid, gauge section clipping, "
                             ".mass reader), data_conventions.py (executable search), grid.py (Grid, ESRI ASCII), units.py, "
                             "wallclock.py (launcher) as verbatim copies; the rain .par is checked against "
                             "lisflood.write_inputs by the tests"),
            "results": results,
            "files": AR.file_records(out_dir, [LR.TERRAIN_NAME, LR.NAME + ".dem.asc", LR.BCI_NAME, LR.RAIN_NAME, LR.PAR_NAME,
                                               LR.GAUGE_NAME, "rain_rate_m_per_s.csv", LR.MAX_DEPTH_NAME, LR.RESULTS_NAME]),
            "limitations": ["not a PMP; Atlas 14 only", "uniform rain: LISFLOOD-FP reads one .rain series here",
                            "no infiltration or losses unless the rain series is already excess rain",
                            "the arrival-time patch keywords of the runner (hazard, inittm_depth) are not written",
                            "NODATA outside the polygon is a wall and only the domain cells on the grid edge drain (FREE); ANUGA's ring is an "
                            "outflow boundary all round",
                            "the gauge runs along the nearest grid axis, not along the line itself",
                            "the runner's keep-awake wrapper is not used"],
            "elapsed_s": round(time.time() - t_start, 1),
        }
        mpath = os.path.join(out_dir, LR.MANIFEST_NAME)
        AR.write_json(mpath, manifest)
        feedback.pushInfo("Wrote {}".format(out_dir))
        if not run_it:
            feedback.pushInfo("Next: run `lisflood -v {}` in {}".format(LR.PAR_NAME, out_dir))
        return {"PAR": par, "TERRAIN": tif, "MANIFEST": mpath,
                "RESULTS": os.path.join(out_dir, LR.RESULTS_NAME) if results else "", "CELLS": tinfo["domain_cells"],
                "OUTPUT_DIR": out_dir}


ALGORITHMS = (LisfloodRain,)
