"""DamIT PMP: damit_pmp:anugarain, an ANUGA rain-on-grid job on the runner's gmsh mesh.

The mesh, the outer ring, the flow-path refinement line, the sizing defaults and the domain build
are the damit_runner ANUGA gmsh pipeline (damit_pmp/runner_shared holds its files verbatim; see
anugarain.py). Nothing here launches a process: damit_pmp/launch.py does, and only when an ANUGA
Python is given (mesh build) or RUN_ANUGA is switched on (default off).
"""
import json
import os
import sys
import time

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProcessing,
                       QgsProcessingException, QgsProcessingOutputNumber, QgsProcessingOutputString,
                       QgsProcessingParameterBoolean, QgsProcessingParameterDefinition, QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFile, QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterNumber, QgsProcessingParameterPoint, QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterString, QgsProject)

from .. import _deps  # noqa: F401
from .. import anugarain as AR
from .. import launch
from .pf_algs import DOUBLE, INTEGER, NOTE, _Base
from ..runner_shared import gmsh_mesher as gmshmod

ALGOS = list(AR.ALGORITHMS)
EDGE = list(AR.EDGE_BCS)
FLAG_ADV = getattr(QgsProcessingParameterDefinition, "FlagAdvanced", None) or \
    QgsProcessingParameterDefinition.Flag.FlagAdvanced


def _rings(geom):
    """Exterior rings ((N, 2) arrays) of a (multi)polygon geometry."""
    if geom.isMultipart():
        polys = geom.asMultiPolygon()
    else:
        polys = [geom.asPolygon()]
    return [np.array([[p.x(), p.y()] for p in poly[0]], float) for poly in polys if poly and len(poly[0]) >= 4]


def _plugin_version():
    from ..provider import plugin_version
    return plugin_version()


class AnugaRain(_Base):
    def name(self):
        return "anugarain"

    def displayName(self):  # noqa: N802
        return "ANUGA rain-on-grid job on the runner's gmsh mesh"

    def shortHelpString(self):  # noqa: N802
        return (
            "Builds an ANUGA rain-on-grid job the way damit_runner builds its ANUGA gmsh model: the runner's own "
            "gmsh_mesher.py (a verbatim, sha-pinned copy) meshes a basin polygon or an extent over a DEM with the "
            "runner's sizing defaults (lines 100 m2, flow path 250 m2, far field 20000 m2, quality gate min angle 20 "
            "deg), the outer ring comes from the runner's terrain.mask_outline, the refinement line is the runner's "
            "steepest-descent flow path from an optional start point, and the generated script builds the ANUGA "
            "domain with the runner's worker helpers (local coordinates, zero Geo_reference, every outer edge tagged "
            "outflow, DE0, minimum storable height 0.001, Manning n 0.06, dry start, edge_bc outflow | transmissive, "
            "ground from the model DEM at the centroids or, for a finer DEM, the native DEM at the vertices). The "
            "rain is an anuga.Rate_operator (m/s) from the *_anuga_rate.csv of damit_pmp:raingrid, with an optional "
            "per-triangle factor sampled from the raingrid FACTOR_RASTER.\n\n"
            "Output folder: gmsh_mesh_in.json (mesher input), gmsh_mesh.npz + gmsh_mesh.msh + mesh_triangles.geojson "
            "(when the mesh is built), anuga_rain_job.npz, run_anuga_rain.py with the runner files it imports, and "
            "run_manifest.json (settings, versions, sha256 of every file). Run the script in the ANUGA Python: "
            "`python run_anuga_rain.py --dry` builds the domain and rate operator and checks the storm volume "
            "without evolving; `--run` simulates.\n\n"
            "Nothing is launched by default. Give an ANUGA Python to build the gmsh mesh here (BUILD_MESH; gmsh only, "
            "the runner's launcher with a timeout); RUN_ANUGA (off by default) also runs the full simulation. The "
            "runner's worker has no rain: only its mesher, outer ring, flow path, sizes and domain build are reused.\n\n"
            "0.4.2 options (all off by default): VERTEX_ELEVATION samples the model DEM at the triangle vertices (a "
            "continuous bed) instead of once per centroid; without a finer DEM the runner's centroid rule leaves a bed "
            "that jumps between neighbouring triangles, which strands rain water (DWR-2801: 4.8 vs 3.1 Mm3 stored at 36 "
            "h, 0.6 vs 65 m3/s at the dam). STREAM_AREA_KM2, CHANNEL_AREA_M2, CHANNEL_DIST_MIN_M / MAX_M refine the mesh "
            "along the D8 stream network; REFINE_LINES puts mesh edges along given lines (a dam crest); OUTLET_* add the "
            "dam's principal outlet as the runner's Boyd pipe culvert (the values are labelled assumed unless "
            "OUTLET_ASSUMED is off); STAGE_PROBE records the water level at a point (the pond) every yield step. "
            + NOTE)

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
        add(QgsProcessingParameterRasterLayer("FACTOR_RASTER", "Spatial rain factor raster (damit_pmp:raingrid "
                                              "FACTOR_RASTER; empty = uniform rain)", optional=True))
        add(QgsProcessingParameterPoint("GAUGE_A", "Discharge section, first end (with GAUGE_B: the script records the flow "
                                        "through this line every yield step, e.g. just below a dam; empty = none)",
                                        optional=True))
        add(QgsProcessingParameterPoint("GAUGE_B", "Discharge section, second end", optional=True))
        add(QgsProcessingParameterPoint("FLOW_PATH_START", "Flow-path start for the refinement line (like the runner's "
                                        "inflow point; empty = no refinement, a uniform mesh)", optional=True))
        add(QgsProcessingParameterNumber("CELL_M", "Model cell size of the DEM grid (m; the runner's CELL default is "
                                         "10)", DOUBLE, defaultValue=AR.DEFAULTS["cell_m"], minValue=AR.MIN_CELL_M))
        add(QgsProcessingParameterNumber("SIM_TIME_H", "Simulation time (hours; 0 = end of the rain series + 6 h)", DOUBLE,
                                         defaultValue=0.0, minValue=0.0))
        add(QgsProcessingParameterNumber("YIELDSTEP_S", "Yield step (s; runner default 300)", DOUBLE,
                                         defaultValue=AR.DEFAULTS["yieldstep_s"], minValue=1.0))
        add(QgsProcessingParameterEnum("EDGE_BC", "Outer boundary (runner edge_bc)", EDGE, defaultValue=0))
        add(QgsProcessingParameterNumber("MANNING_N", "Manning n (runner default 0.06)", DOUBLE,
                                         defaultValue=AR.DEFAULTS["manning_n"], minValue=0.0001, maxValue=1.0))
        add(adv(QgsProcessingParameterEnum("ALGORITHM", "ANUGA flow algorithm (runner default DE0)", ALGOS,
                                           defaultValue=0)))
        add(adv(QgsProcessingParameterNumber("MAX_AREA_M2", "Far-field triangle area (m2; empty = the runner's 20000)",
                                             DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("LINE_MIN_AREA_M2", "Smallest triangle on the flow path (m2; empty = the "
                                             "runner's 100)", DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("GRADE_DIST_M", "Distance over which the size grows to the far field (m; "
                                             "empty = the runner's 1500)", DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("STREAM_AREA_KM2", "Refine the mesh along the stream network: channels draining "
                                             "at least this area (km2) from the D8 accumulation of the model DEM get the "
                                             "mesher's channel sizing (empty = only the flow path, the runner's rule)",
                                             DOUBLE, optional=True, minValue=0.0001)))
        add(adv(QgsProcessingParameterNumber("CHANNEL_AREA_M2", "Triangle area on the flow path and stream lines (m2; empty = "
                                             "the runner's 250)", DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("CHANNEL_DIST_MIN_M", "Distance from a channel line kept at the channel "
                                             "size (m; empty = the runner's 250)", DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterNumber("CHANNEL_DIST_MAX_M", "Distance at which the size has grown to the far field "
                                             "(m; empty = the runner's 2500)", DOUBLE, optional=True, minValue=1.0)))
        add(adv(QgsProcessingParameterFeatureSource("REFINE_LINES", "Extra mesh refinement lines (embankment crests, a dam line: "
                                                     "mesh edges are put along them at the runner's line size)",
                                                     [QgsProcessing.TypeVectorLine], optional=True)))
        add(adv(QgsProcessingParameterBoolean("VERTEX_ELEVATION", "Sample the model DEM at the triangle vertices (a continuous "
                                              "bed) instead of once per centroid (the runner's rule without a finer DEM)", False)))
        add(adv(QgsProcessingParameterPoint("OUTLET_INLET", "Principal outlet (pipe through the dam), inlet end on the pond side "
                                             "(with the other OUTLET_* values: the runner's Boyd pipe culvert; empty = no outlet)",
                                             optional=True)))
        add(adv(QgsProcessingParameterPoint("OUTLET_OUTLET", "Principal outlet, outlet end downstream of the dam", optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_DIAMETER_M", "Outlet pipe diameter (m)", DOUBLE, optional=True, minValue=0.05)))
        add(adv(QgsProcessingParameterNumber("OUTLET_INVERT_IN_M", "Outlet inlet invert elevation (m, DEM datum)", DOUBLE, optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_INVERT_OUT_M", "Outlet outlet invert elevation (m, DEM datum)", DOUBLE, optional=True)))
        add(adv(QgsProcessingParameterNumber("OUTLET_MANNING", "Outlet pipe Manning n", DOUBLE, 0.013, minValue=0.005)))
        add(adv(QgsProcessingParameterNumber("OUTLET_LOSSES", "Outlet entrance/exit loss coefficient", DOUBLE, 0.5, minValue=0.0)))
        add(adv(QgsProcessingParameterNumber("OUTLET_BARRELS", "Outlet number of barrels", DOUBLE, 1.0, minValue=1.0)))
        add(adv(QgsProcessingParameterBoolean("OUTLET_ASSUMED", "The outlet values are assumed (not from the as-built drawings): "
                                              "the manifest and the maps say so", True)))
        add(adv(QgsProcessingParameterPoint("STAGE_PROBE", "Record the water level at this point every yield step (e.g. the "
                                             "pond; anuga_rain_result.npz probe_stage)", optional=True)))
        add(adv(QgsProcessingParameterNumber("BUFFER_M", "Grow the domain by this much (m; the runner buffers its "
                                             "flood footprint by 500, a basin needs none)", DOUBLE, defaultValue=0.0,
                                             minValue=0.0)))
        add(adv(QgsProcessingParameterNumber("SIMPLIFY_M", "Simplify the outer outline by this tolerance (m; empty = the "
                                             "runner's rule, one cell with no buffer). A jagged basin outline needs 30 - 50 "
                                             "to pass the mesher's 20 degree quality gate", DOUBLE, optional=True,
                                             minValue=0.5)))
        add(adv(QgsProcessingParameterBoolean("FINE_ELEVATION", "Sample the native DEM at the triangle vertices when it "
                                              "is finer than the cell (the runner's 'fine' elevation)",
                                              defaultValue=True)))
        add(adv(QgsProcessingParameterNumber("THREADS", "Mesher / ANUGA threads (0 = automatic)", INTEGER,
                                             defaultValue=AR.DEFAULTS["threads"], minValue=0, maxValue=512)))
        add(QgsProcessingParameterString("ANUGA_PYTHON", "ANUGA Python interpreter (a path, as in DamSafety Setup; empty = "
                                         "write the job only, launch nothing)", optional=True))
        add(QgsProcessingParameterBoolean("BUILD_MESH", "Build the gmsh mesh now with the runner's mesher (needs the "
                                          "ANUGA Python above)", defaultValue=True))
        add(QgsProcessingParameterBoolean("RUN_ANUGA", "Also RUN the ANUGA simulation (default off; needs the mesh)",
                                          defaultValue=False))
        add(adv(QgsProcessingParameterNumber("MESH_TIMEOUT_S", "Mesher wall-clock timeout (s; runner 600)", DOUBLE,
                                             defaultValue=AR.DEFAULTS["gmsh_timeout_s"], minValue=10.0)))
        add(adv(QgsProcessingParameterNumber("RUN_TIMEOUT_H", "ANUGA run wall-clock timeout (hours)", DOUBLE,
                                             defaultValue=24.0, minValue=0.01)))
        add(QgsProcessingParameterFolderDestination("OUTPUT_DIR", "Output folder"))
        self.addOutput(QgsProcessingOutputString("SCRIPT", "Generated ANUGA script"))
        self.addOutput(QgsProcessingOutputString("MESH", "gmsh mesh (npz; empty when not built)"))
        self.addOutput(QgsProcessingOutputString("MANIFEST", "Run manifest (JSON)"))
        self.addOutput(QgsProcessingOutputNumber("TRIANGLES", "Triangles (0 when no mesh)"))

    # ------------------------------------------------------------------ helpers
    def _opt_num(self, P, name, context):
        v = P.get(name)
        return None if v in (None, "") else self.parameterAsDouble(P, name, context)

    def _domain(self, P, context, dem_crs, cell):
        """(rings in the DEM CRS, bounds, description)."""
        basin = self.parameterAsSource(P, "BASIN", context) if P.get("BASIN") not in (None, "") else None
        if basin is not None:
            tr = QgsCoordinateTransform(basin.sourceCrs(), dem_crs, QgsProject.instance())
            geoms = []
            for f in basin.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isEmpty():
                    continue
                g.transform(tr)
                geoms.append(g)
            if not geoms:
                raise QgsProcessingException("The basin layer has no polygons.")
            rings = _rings(QgsGeometry.unaryUnion(geoms))
            what = "basin polygon ({} feature(s))".format(len(geoms))
        elif P.get("EXTENT") not in (None, ""):
            r = self.parameterAsExtent(P, "EXTENT", context, dem_crs)
            if r.isEmpty():
                raise QgsProcessingException("The extent is empty.")
            rings = [np.array([[r.xMinimum(), r.yMinimum()], [r.xMaximum(), r.yMinimum()], [r.xMaximum(), r.yMaximum()],
                               [r.xMinimum(), r.yMaximum()], [r.xMinimum(), r.yMinimum()]])]
            what = "extent"
        else:
            raise QgsProcessingException("Give a basin polygon or an extent for the model domain.")
        if not rings:
            raise QgsProcessingException("The basin has no polygon rings.")
        allp = np.vstack(rings)
        pad = 2.0 * cell
        b = (allp[:, 0].min() - pad, allp[:, 1].min() - pad, allp[:, 0].max() + pad, allp[:, 1].max() + pad)
        return rings, b, what

    # ------------------------------------------------------------------ run
    def processAlgorithm(self, P, context, feedback):  # noqa: N802
        t_start = time.time()
        out_dir = os.path.abspath(self.parameterAsString(P, "OUTPUT_DIR", context))
        os.makedirs(out_dir, exist_ok=True)
        dem_layer = self.parameterAsRasterLayer(P, "DEM", context)
        if dem_layer is None or dem_layer.crs().isGeographic():
            raise QgsProcessingException("The DEM must be in a projected CRS in metres; reproject it first.")
        python = (self.parameterAsString(P, "ANUGA_PYTHON", context) or "").strip()
        run_anuga = self.parameterAsBool(P, "RUN_ANUGA", context)
        if run_anuga and not python:
            raise QgsProcessingException("RUN_ANUGA needs the ANUGA Python interpreter.")
        if python:
            try:
                launch.check_python(python)               # a path check only; nothing runs yet
            except AR.JobError as e:
                raise QgsProcessingException(str(e))
        try:
            st = AR.check_settings(dict(
                cell_m=self.parameterAsDouble(P, "CELL_M", context), buffer_m=self.parameterAsDouble(P, "BUFFER_M", context),
                yieldstep_s=self.parameterAsDouble(P, "YIELDSTEP_S", context),
                manning_n=self.parameterAsDouble(P, "MANNING_N", context),
                algorithm=ALGOS[self.parameterAsEnum(P, "ALGORITHM", context)],
                edge_bc=EDGE[self.parameterAsEnum(P, "EDGE_BC", context)], threads=self.parameterAsInt(P, "THREADS", context),
                gmsh_timeout_s=self.parameterAsDouble(P, "MESH_TIMEOUT_S", context)))
            sizing = {k: self._opt_num(P, k.upper(), context) for k in AR.SIZING_NUMBERS}
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
                gauge = AR.orient_gauge([(ga.x(), ga.y()), (gb.x(), gb.y())], start)
            region = AR.domain_region(grid, rings)
            outer, oinfo = AR.outer_ring(grid, region, st["buffer_m"], start, self._opt_num(P, "SIMPLIFY_M", context))
            channel, points, plen = [], [], 0.0
            if start is not None:
                channel, plen = AR.flow_path(grid, outer, start)
                points = [start]
                feedback.pushInfo("Flow path: {:.0f} m traced, {} piece(s) inside the domain".format(plen, len(channel)))
            stream_info = None
            stream_km2 = self._opt_num(P, "STREAM_AREA_KM2", context)
            if stream_km2:
                slines, stream_info = AR.stream_refine_lines(grid, outer, stream_km2)
                channel = list(channel) + slines
                feedback.pushInfo("Stream network: {lines} line(s), {length_km_in_domain} km in the domain (threshold "
                                  "{threshold_km2} km2)".format(**stream_info))
            outlet, probes = None, None
            ref_lines = []
            if P.get("REFINE_LINES") not in (None, ""):
                src = self.parameterAsSource(P, "REFINE_LINES", context)
                tr = QgsCoordinateTransform(src.sourceCrs(), dem_layer.crs(), QgsProject.instance())
                for f in src.getFeatures():
                    g = QgsGeometry(f.geometry())
                    if g.isEmpty():
                        continue
                    g.transform(tr)
                    for part in (g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]):
                        if len(part) >= 2:
                            ref_lines.append([(q.x(), q.y()) for q in part])
                ref_lines = AR.clip_lines_to_polygon(ref_lines, outer)
                feedback.pushInfo("Refinement lines: {} piece(s) in the domain".format(len(ref_lines)))
            if P.get("OUTLET_INLET") not in (None, "") or P.get("OUTLET_OUTLET") not in (None, ""):
                nums = [self._opt_num(P, k, context) for k in ("OUTLET_DIAMETER_M", "OUTLET_INVERT_IN_M", "OUTLET_INVERT_OUT_M")]
                if P.get("OUTLET_INLET") in (None, "") or P.get("OUTLET_OUTLET") in (None, "") or any(v is None for v in nums):
                    raise QgsProcessingException("An outlet needs OUTLET_INLET, OUTLET_OUTLET, OUTLET_DIAMETER_M, "
                                                 "OUTLET_INVERT_IN_M and OUTLET_INVERT_OUT_M.")
                pi = self.parameterAsPoint(P, "OUTLET_INLET", context, dem_layer.crs())
                po = self.parameterAsPoint(P, "OUTLET_OUTLET", context, dem_layer.crs())
                outlet = AR.outlet_spec((pi.x(), pi.y()), (po.x(), po.y()), nums[0], nums[1], nums[2],
                                        self.parameterAsDouble(P, "OUTLET_MANNING", context),
                                        self.parameterAsDouble(P, "OUTLET_LOSSES", context),
                                        self.parameterAsDouble(P, "OUTLET_BARRELS", context),
                                        self.parameterAsBool(P, "OUTLET_ASSUMED", context))
                points = list(points) + [tuple(e) for e in outlet["end_points"]]
                feedback.pushInfo("Outlet: {:.2f} m pipe, {:.0f} m long, inverts {:.2f} -> {:.2f} m{}".format(
                    outlet["width_m"], outlet["length_m"], *outlet["invert_elevations"],
                    " (ASSUMED values)" if outlet["assumed"] else ""))
            if P.get("STAGE_PROBE") not in (None, ""):
                pp = self.parameterAsPoint(P, "STAGE_PROBE", context, dem_layer.crs())
                probes = [(pp.x(), pp.y())]
            spec = AR.mesh_spec(outer, channel, points, st["threads"], sizing,
                                lines=ref_lines + ([outlet["end_points"]] if outlet else []))
            t, r = AR.read_rate_csv(self.parameterAsFile(P, "RATE_CSV", context))
            storm_s = float(t[-1])
            sim_h = self.parameterAsDouble(P, "SIM_TIME_H", context)
            sim_time = sim_h * 3600.0 if sim_h > 0 else storm_s + AR.DEFAULTS["extra_h"] * 3600.0
            factor, fstats = None, None
            if P.get("FACTOR_RASTER") not in (None, ""):
                fl = self.parameterAsRasterLayer(P, "FACTOR_RASTER", context)
                factor, fstats = AR.read_factor_on_grid(fl.source(), grid)
                feedback.pushInfo("Factor raster: {}".format(fstats))
            fine = None
            if self.parameterAsBool(P, "FINE_ELEVATION", context):
                fine = AR.read_fine_elevation(dem_layer.source(), grid, ginfo["native_cell_m"],
                                              os.path.join(out_dir, AR.FINE_NAME))
        except AR.JobError as e:
            raise QgsProcessingException(str(e))
        area = float(oinfo["region_km2"]) * 1e6
        feedback.pushInfo("Outer ring: {} points, {:.2f} km2 ({:.2f} sq mi); at least about {} triangles".format(
            len(outer), area / 1e6, area / 2.589988e6, AR.expected_triangles(area, spec)))

        spec_path = os.path.join(out_dir, AR.SPEC_NAME)
        AR.write_json(spec_path, spec)
        AR.write_job(out_dir, grid, t, r, st, sim_time, factor, fine, gauge, outlet, probes,
                     self.parameterAsBool(P, "VERTEX_ELEVATION", context))
        files = AR.copy_script_files(out_dir)
        rate_copy = os.path.join(out_dir, AR.RATE_NAME)
        with open(self.parameterAsFile(P, "RATE_CSV", context), "rb") as a, open(rate_copy, "wb") as b:
            b.write(a.read())

        versions = {}
        mesh_stats, mesh_note, mesh_path, ntri = None, "not built (no ANUGA Python given or BUILD_MESH off)", "", 0
        if python:
            versions = launch.probe(python)
            feedback.pushInfo("ANUGA Python: {}".format(versions))
        if python and self.parameterAsBool(P, "BUILD_MESH", context):
            if not versions.get("gmsh"):
                raise QgsProcessingException("gmsh is not available in that Python ({}). Install it there "
                                             "(pip install gmsh) or leave BUILD_MESH off.".format(
                                                 "; ".join(versions.get("messages", []))))
            mesh_path = os.path.join(out_dir, AR.MESH_NAME)
            feedback.pushInfo("Building the gmsh mesh with the runner's mesher (timeout {:g} s)".format(st["gmsh_timeout_s"]))
            mesh_stats, mesh_note = launch.run_mesher(python, spec_path, mesh_path, st["gmsh_timeout_s"],
                                                      log=feedback.pushInfo)
            if mesh_stats is None:
                raise QgsProcessingException(mesh_note)
            pts, tris, _bnd, _ = AR.mesh_arrays(mesh_path)
            ntri = len(tris)
            AR.write_msh2(os.path.join(out_dir, AR.MSH_NAME), pts, tris, grid)
            tri_ok = AR.write_triangles_geojson(os.path.join(out_dir, "mesh_triangles.geojson"), pts, tris)
            feedback.pushInfo("Mesh: {} triangles, min angle {:.1f} deg, min area {:.1f} m2".format(
                ntri, mesh_stats.get("min_angle_deg", float("nan")), mesh_stats.get("min_area_m2", float("nan"))))
            if not tri_ok:
                feedback.pushInfo("mesh_triangles.geojson skipped: more than 400000 triangles")
        script = os.path.join(out_dir, AR.SCRIPT_NAME)
        run_rec = None
        if run_anuga:
            if not mesh_path:
                raise QgsProcessingException("RUN_ANUGA needs the mesh: switch BUILD_MESH on.")
            feedback.pushInfo("RUN_ANUGA is on: launching the generated script in the ANUGA Python")
            try:
                cp = launch.run_script(python, script, ["--run"], timeout_s=self.parameterAsDouble(
                    P, "RUN_TIMEOUT_H", context) * 3600.0, log=feedback.pushInfo)
            except Exception as e:      # noqa: BLE001 - timeout or start failure: reported with the manifest
                raise QgsProcessingException("The ANUGA run did not finish: {}".format(e))
            run_rec = {"returncode": cp.returncode, "stdout_tail": (cp.stdout or "")[-600:],
                       "stderr_tail": (cp.stderr or "")[-600:]}
            if cp.returncode != 0:
                raise QgsProcessingException("The ANUGA script failed ({}): {}".format(
                    cp.returncode, (cp.stderr or cp.stdout or "")[-300:]))

        inputs = {"dem": {"path": dem_layer.source(), "sha256": AR.sha256_file(dem_layer.source()) if os.path.isfile(
            dem_layer.source()) else None, "crs": dem_layer.crs().authid(), "native_cell_m": ginfo["native_cell_m"]},
                  "rate_csv": {"path": self.parameterAsFile(P, "RATE_CSV", context), "sha256": AR.sha256_file(rate_copy)}}
        if P.get("FACTOR_RASTER") not in (None, ""):
            fp = self.parameterAsRasterLayer(P, "FACTOR_RASTER", context).source()
            inputs["factor_raster"] = {"path": fp, "sha256": AR.sha256_file(fp) if os.path.isfile(fp) else None,
                                       "stats_on_model_grid": fstats}
        manifest = {
            "tool": "damit_pmp:anugarain", "damit_pmp_version": _plugin_version(),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "qgis": Qgis.version(), "python": sys.version.split()[0],
            "domain": {"source": what, "crs": dem_layer.crs().authid(), "outer_ring_points": len(outer),
                       "area_km2": oinfo["region_km2"], "area_sq_mi": oinfo["region_km2"] / 2.589988,
                       "simplify_m": oinfo["simplify_m"], "model_cell_m": st["cell_m"], "grid": [grid.ny, grid.nx],
                       "flow_path_start": start, "flow_path_length_m": plen, "stream_refinement": stream_info, "outlet": outlet},
            "settings": dict(st, sim_time_s=sim_time, storm_s=storm_s, sizing={k: v for k, v in sizing.items() if v},
                             elevation=("fine (native DEM at the vertices)" if fine else "model grid (centroids)"),
                             mesher_defaults=gmshmod.default_sizes(), run_anuga=run_anuga, build_mesh=bool(mesh_path)),
            "rain": {"depth_mm": AR.rain_depth_m(t, r) * 1000.0, "peak_mm_hr": float(r.max()) * 3.6e6,
                     "spatial": "uniform x per-triangle factor raster" if factor is not None else "uniform",
                     "units": "rate in m/s of water depth; Rate_operator (no other scaling)"},
            "inputs": inputs, "anuga_python": {"path": python or None, "versions": versions},
            "mesh": {"built": bool(mesh_path), "triangles": ntri, "stats": mesh_stats, "note": mesh_note},
            "runner_shared_sha256": AR.runner_sources(),
            "runner_reuse": ("gmsh_mesher.py (mesher, sizing defaults, quality gate), terrain.py (mask_outline, "
                             "trace_downstream, dilate, largest_component), grid.py (Grid), wallclock.py (launcher), "
                             "anuga_worker.py helpers (bilinear, sample_fine, fill_nan, make_outer_boundary, "
                             "apply_threads) as verbatim copies"),
            "launched": {"gmsh_mesher": bool(mesh_path), "anuga": bool(run_anuga), "result": run_rec},
            "files": AR.file_records(out_dir, files + [AR.SPEC_NAME, AR.JOB_NAME, AR.RATE_NAME, AR.FINE_NAME, AR.MESH_NAME,
                                                       AR.MSH_NAME, "mesh_triangles.geojson"]),
            "limitations": ["not a PMP; Atlas 14 only", "the rain is a rate, runoff comes from ANUGA's depth-based "
                            "flow: no infiltration or losses unless you add them", "the runner worker has no rain "
                            "operator: the domain build is the runner's, the operator is new",
                            "basin polygon is whatever you gave, not a delineated watershed"],
            "elapsed_s": round(time.time() - t_start, 1),
        }
        mpath = os.path.join(out_dir, AR.MANIFEST_NAME)
        AR.write_json(mpath, manifest)
        feedback.pushInfo("Wrote {}".format(out_dir))
        feedback.pushInfo("Next (ANUGA Python): python {} --dry".format(script))
        return {"SCRIPT": script, "MESH": mesh_path, "MANIFEST": mpath, "TRIANGLES": ntri, "OUTPUT_DIR": out_dir}


ALGORITHMS = (AnugaRain,)
