"""HEC-RAS interchange algorithms: export a breach to HEC-RAS, import 2D results as rasters.

Register with `HECRAS_ALGORITHMS` (see the end of the file)."""
import os

import numpy as np
from qgis.core import (QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingOutputFolder, QgsProcessingOutputString,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString)

from .algorithms_tools import _ToolBase
from ..qgis_compat import SOURCE_LINE
from ..core import benchmark, gdal_io, hecras, hecras_model, hecras_package, workflow
from ..core.units import ARRIVAL_DEPTH_FT

STEPS = [(hecras.ras_interval_label(m), m) for m in hecras.RAS_INTERVALS_MIN]
STEP_DEFAULT = [m for _, m in STEPS].index(5)
IMPORT_NAMES = {"depth": "HECRAS Depth (Max).tif", "velocity": "HECRAS Velocity (Max).tif",
                "arrival": "HECRAS Arrival Time.tif", "wse": "HECRAS WSE (Max).tif",
                "time_of_max": "HECRAS Time of Max WSE.tif"}
# v3.10.22: computation points of the HEC-RAS 2D area (core/hecras_seeds.py)
MESH_SEEDS_LABELS = ["Regular grid (default)",
                     "gmsh layout, finer along the dam, breach and channel (needs gmsh; falls "
                     "back to the grid)"]
MESH_SEEDS_MODES = ["grid", "gmsh"]
# the HEC-RAS dam line (core/hecras_crest.py)
DAM_AXIS_LABELS = ["Along the embankment crest, traced from the DEM (default)",
                   "Straight line through the dam point, across the flow (the old line)"]
DAM_AXIS_MODES = ["crest", "straight"]
US_SI = ["Detect from the file (US customary when it says nothing)", "US customary (ft)",
         "SI metric (m)"]
# 3.10.84: what the imported HEC-RAS depth is measured from (core/hecras.depth_basis);
# 3.10.92: the actual terrain per pixel is the default again (first), cell minimum second
DEPTH_BASIS_OPTIONS = ["Terrain per pixel: max WSE minus the actual terrain at the centre of "
                       "each grid cell (default; the Terrain, else the dam folder's run DEM)",
                       "Cell minimum: max WSE minus the HEC-RAS cell's minimum terrain "
                       "elevation",
                       # 3.10.92 review of #204: three more (core/hecras_fine.py)
                       "Terrain mean: max WSE minus the mean terrain over each grid cell",
                       "Terrain max (conservative): the deepest point of the fine terrain in "
                       "each grid cell (WSE of the nearest HEC-RAS cell)",
                       "Fine (approximates RAS Mapper's sloped surface): WSE interpolated "
                       "between wet cell centres minus the fine terrain; also writes "
                       "Depth_fine / WSE_fine (Max).tif at the terrain's resolution"]
DEPTH_BASIS_KEYS = [hecras.DEPTH_BASIS_TERRAIN, hecras.DEPTH_BASIS_CELL_MIN,
                    hecras.DEPTH_BASIS_TERRAIN_MEAN, hecras.DEPTH_BASIS_TERRAIN_MAX,
                    hecras.DEPTH_BASIS_FINE]
# 3.10.89 review round 3: the Terrain's elevation unit (hecras_engine.terrain_z_factor)
TERRAIN_Z_OPTIONS = ["Detect from the raster (else the Runner's record of its own terrain, else "
                     "the CRS's linear unit, with a warning)", "Feet", "US survey feet", "Meters"]
TERRAIN_Z_KEYS = [gdal_io.Z_AUTO, gdal_io.Z_FEET, gdal_io.Z_US_FEET, gdal_io.Z_METERS]


def _depth_basis_default():
    """Index of NDBREACH_HECRAS_DEPTH_BASIS (else terrain, 3.10.92) in DEPTH_BASIS_KEYS."""
    try:
        return DEPTH_BASIS_KEYS.index(hecras.depth_basis())
    except (hecras.HecRasError, ValueError):
        return 0


def dam_line_points(source):
    """3.10.87: the vertices of the first line feature of a layer (its first part), as
    [(x, y), ...] in the layer's CRS; [] when it has none."""
    if source is None:
        return []
    for f in source.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        if g.isMultipart():
            parts = g.asMultiPolyline()
            pts = parts[0] if parts else []
        else:
            pts = g.asPolyline()
        if len(pts) >= 2:
            return [(float(p.x()), float(p.y())) for p in pts]
    return []



class HecRasImportAlgorithm(_ToolBase):
    def name(self):
        return "hecrasimport"

    def displayName(self):
        return "Import HEC-RAS 2D results as rasters"

    def shortHelpString(self):
        return ("Reads the maximum results of a HEC-RAS 2D plan HDF (.p##.hdf) and writes "
                "GeoTIFFs 'HECRAS Depth (Max).tif', 'HECRAS Velocity (Max).tif', 'HECRAS "
                "Arrival Time.tif' and 'HECRAS WSE (Max).tif' in ft, ft/s, hours and ft. The "
                "Depth basis decides what depth is measured from (3.10.92): 'Terrain per pixel', "
                "the default, is the cell's maximum water surface minus the actual terrain at "
                "the centre of each grid cell - the Terrain you give, else the dam folder's run "
                "DEM (the fine LiDAR) when it is finer than the HEC-RAS terrain, else the "
                "HEC-RAS terrain; 'Cell minimum' (the 3.10.84 default, conservative) is the "
                "cell's maximum water surface minus the cell's minimum terrain elevation, the "
                "same on every grid cell inside it (a ditch or channel in a cell deepens the "
                "whole cell). With the cell-minimum basis the terrain gives only a comparison. "
                "The terrain is checked against the model's cell minimum elevations: one on "
                "another vertical datum or unit stops the per-pixel basis "
                "(NDBREACH_HECRAS_DATUM_CHECK=warn keeps it with a warning). 'Terrain elevation units': Detect reads the unit the Terrain records, "
                "else the Runner's record of its own HEC-RAS terrain, else assumes its CRS's "
                "linear unit and says so; or choose Feet / US survey feet / Meters. The wet "
                "area and the arrival time follow the depth of the basis chosen. "
                "The Depth basis starts at NDBREACH_HECRAS_DEPTH_BASIS (else terrain per pixel). "
                "Velocity is the per-cell maximum when the file has one, else the maximum face "
                "velocities averaged onto the cells. Arrival is the first time the depth reaches "
                "the arrival depth, from the water surface time series, counted from the "
                "'time of breach initiation' you give (hours after the start of the HEC-RAS "
                "run). Cells are sampled by nearest cell centre onto the grid of the 'like' "
                "raster (or of the dam folder's Depth (Max).tif), else onto a grid you set, "
                "else onto one at the median cell spacing. Coordinates must be in the "
                "same system as the like raster. Needs h5py in QGIS's Python. Tick 'compare' "
                "to run the benchmark against the dam folder's rasters. The layout of HDF "
                "files varies between HEC-RAS versions and was not tested against real "
                "files: if it cannot find the datasets it lists what the file contains.")

    def initAlgorithm(self, config=None):
        self._file("HDF", "HEC-RAS 2D plan results (.p##.hdf)", "hdf", optional=False)
        self._file("DAM_FOLDER", "Dam folder (its Depth (Max).tif sets the grid; outputs "
                   "go to <dam folder>/_hecras)", folder=True)
        self.addParameter(QgsProcessingParameterRasterLayer(
            "TERRAIN", "Terrain to measure the depth from (empty = the dam folder's run DEM "
            "or HEC-RAS terrain; the cell-minimum basis uses it only to compare)",
            optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            "TERRAIN_Z", "Terrain elevation units", TERRAIN_Z_OPTIONS, defaultValue=0,
            optional=True))
        # 3.10.92: terrain per pixel is the default again; cell minimum stays selectable
        self.addParameter(QgsProcessingParameterEnum(
            "DEPTH_BASIS", "Depth basis (wet area and arrival follow it)", DEPTH_BASIS_OPTIONS,
            defaultValue=_depth_basis_default()))
        self.addParameter(QgsProcessingParameterRasterLayer(
            "LIKE", "Grid of this raster (empty = the dam folder's, else set below)",
            optional=True))
        self._num("CELL", "Cell size when there is no raster to match (in the plan's CRS "
                  "units, usually US ft or m; 0 = median cell spacing)", 0.0, minimum=0.0)
        self.addParameter(QgsProcessingParameterExtent(
            "EXTENT", "Extent when there is no raster to match (empty = the 2D area)",
            optional=True))
        self._text("AREA", "2D flow area name (empty = the largest)")
        self.addParameter(QgsProcessingParameterEnum("UNITS", "HEC-RAS model units", US_SI,
                                                     defaultValue=0))
        self._num("ARRIVAL_FT", "Arrival depth (ft; starting value 0.1 is the engineer's: the "
                  "flood arrival depth, so every wet structure gets an arrival time)",
                  ARRIVAL_DEPTH_FT,
                  minimum=0.01)
        self._num("T0_HR", "Time of breach initiation in the HEC-RAS run (hr after its start)",
                  0.0, minimum=0.0)
        self.addParameter(QgsProcessingParameterBoolean(
            "COMPARE", "Compare with the dam folder's rasters (benchmark)", False))
        self._num("THRESH_FT", "Benchmark: wet where the depth is at least (ft; starting "
                  "value 1 is the engineer's, a screening value you choose)", 1.0,
                  minimum=0.01)
        self._file("OUT_FOLDER", "Output folder (empty = <dam folder>/_hecras)", folder=True)
        self.addOutput(QgsProcessingOutputFolder("FOLDER", "Output folder"))
        self.addOutput(QgsProcessingOutputFile("DEPTH", "HECRAS Depth (Max)"))
        self.addOutput(QgsProcessingOutputFile("SUMMARY", "Benchmark_Summary.csv"))
        self.addOutput(QgsProcessingOutputString("RESULT", "Result"))
        self.addOutput(QgsProcessingOutputString("DEPTH_BASIS", "Depth basis used"))

    def processAlgorithm(self, parameters, context, feedback):
        self._need_gdal()
        hdf = self.parameterAsFile(parameters, "HDF", context)
        dam_folder = self._fileparam(parameters, "DAM_FOLDER", context)
        out_dir = self._fileparam(parameters, "OUT_FOLDER", context) or (
            os.path.join(dam_folder, "_hecras") if dam_folder else "")
        if not out_dir:
            raise QgsProcessingException("Give a dam folder or an output folder")
        like = self.parameterAsRasterLayer(parameters, "LIKE", context)
        depth_path = os.path.join(dam_folder, workflow.FINAL_NAMES["depth"]) if dam_folder \
            else ""
        compare = self.parameterAsBool(parameters, "COMPARE", context)
        if compare and not os.path.exists(depth_path):
            raise QgsProcessingException("To compare, the dam folder needs '{}'".format(
                workflow.FINAL_NAMES["depth"]))
        like_grid = None
        try:
            if like is not None:
                like_grid = gdal_io.read_grid(like.source())
            elif os.path.exists(depth_path):
                like_grid = gdal_io.read_grid(depth_path)
            kw = {"units": (None, "us", "si")[self.parameterAsEnum(parameters, "UNITS",
                                                                     context)],
                  "arrival_depth_ft": self.parameterAsDouble(parameters, "ARRIVAL_FT", context),
                  "t0_hr": self.parameterAsDouble(parameters, "T0_HR", context)}
            # M13: the import never reads mesh.fields (arrival), so skip computing it here; the
            # published Arrival raster is built later by terrain_depth (**kw, want_arrival default).
            mesh = hecras.read_mesh(hdf, area=self._str(parameters, "AREA", context) or None,
                                    want_arrival=False, **kw)
            if like_grid is not None:
                x0, ytop, dx, nx, ny = (like_grid.x0, like_grid.y0, like_grid.dx,
                                        like_grid.nx, like_grid.ny)
            else:
                ext = None
                if parameters.get("EXTENT"):
                    r = self.parameterAsExtent(parameters, "EXTENT", context)
                    if r is not None and not r.isNull():
                        ext = (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())
                x0, ytop, dx, nx, ny = hecras.grid_spec(
                    mesh, self._opt(parameters, "CELL", context) or None, ext)
            crs = (like_grid.crs_wkt if like_grid is not None else None) or mesh.crs_wkt
            if not crs:
                raise QgsProcessingException(
                    "The HDF file records no projection; give a raster to match so the "
                    "rasters can be georeferenced.")
            from ..core.grid import Grid
            grid = Grid(np.zeros((ny, nx)), x0, ytop, dx, crs_wkt=crs)
            terrain = self.parameterAsRasterLayer(parameters, "TERRAIN", context)
            basis = DEPTH_BASIS_KEYS[self.parameterAsEnum(parameters, "DEPTH_BASIS", context)]
            # 3.10.92: depth, wet area and arrival on the chosen basis (terrain default): the
            # Terrain given, else the dam folder's run DEM / HEC-RAS terrain, at cell centres
            from ..core import hecras_engine
            zi = self.parameterAsEnum(parameters, "TERRAIN_Z", context) \
                if parameters.get("TERRAIN_Z") is not None else 0
            stage = hecras_engine._read_json(os.path.join(
                dam_folder, "_hecras", "hecras_stage.json")) if dam_folder else {}
            tnotes, twarn = [], []
            t_ft, _trec, reader = None, {}, []
            if terrain is not None or dam_folder:
                t_ft, _trec = hecras_engine.fine_terrain_on_grid(
                    dam_folder, grid,
                    model_terrain=terrain.source() if terrain is not None else
                    stage.get("terrain_tif"),
                    z=TERRAIN_Z_KEYS[zi] if 0 <= zi < 4 else None, stage=stage,
                    notes=tnotes, warnings=twarn, given=terrain is not None,
                    sample=hecras_engine.terrain_sample(basis), reader=reader)
            if basis in hecras.TERRAIN_BASES and t_ft is None:
                # no terrain anywhere: the cell minimum, said loudly (as the Linux stage does)
                w = ("WARNING: no terrain for the per-pixel terrain depth basis (give the "
                     "Terrain the HEC-RAS model used, or a dam folder with its run DEM): the "
                     "depth is measured from the HEC-RAS cell minimum instead")
                feedback.reportError(w, fatalError=False)
                twarn.append(w)
                basis = hecras.DEPTH_BASIS_CELL_MIN
            for n in tnotes:
                feedback.pushInfo(n)
            arrays, tinfo = hecras.terrain_depth(
                hdf, x0, ytop, dx, nx, ny, t_ft,
                area=self._str(parameters, "AREA", context) or None, basis=basis,
                fine=hecras_engine.fine_options(basis, grid, _trec, reader, folder=out_dir),
                **kw)
            tinfo.pop("depth_cell_min", None)
            tinfo.pop("depth_terrain", None)
            tinfo["notes"] = list(tinfo.get("notes") or []) + twarn + \
                list(tinfo.get("datum_warnings") or []) + [
                    "Depth basis: " + hecras.DEPTH_BASIS_TEXT[basis] + "."]
            mesh.info = tinfo
        except (hecras.HecRasError, OSError, ValueError, RuntimeError) as e:
            raise QgsProcessingException(str(e))
        writer = gdal_io.GeoTiffWriter(crs)
        os.makedirs(out_dir, exist_ok=True)
        paths = {}
        for k, a in arrays.items():
            paths[k] = os.path.join(out_dir, IMPORT_NAMES[k])
            writer(grid.like(a, np.nan), paths[k])
            self.load(context, paths[k], IMPORT_NAMES[k][:-4])
        info = mesh.info
        feedback.pushInfo("Area '{}', {:,} cells, units read as {}; grid {} x {} at {:g}.".format(
            info["area"], info["n_cells"], info["units"], nx, ny, dx))
        feedback.pushInfo("Used: " + "; ".join("{}: {}".format(k, v) for k, v
                                               in info["used"].items()))
        for n in info["notes"]:
            feedback.reportError("Check: " + n, fatalError=False)
        summary, msg = "", "wrote {}".format(", ".join(sorted(arrays)))
        if compare:
            try:
                summary, verdict = self._compare(parameters, context, dam_folder, grid, arrays,
                                                 out_dir, writer, feedback)
            except (ValueError, RuntimeError, OSError) as e:
                raise QgsProcessingException(str(e))
            msg += "; " + verdict
        return {"FOLDER": out_dir, "DEPTH": paths.get("depth", ""), "SUMMARY": summary,
                "RESULT": msg + "; depth basis {}".format(info.get("depth_basis")),
                "DEPTH_BASIS": info.get("depth_basis") or ""}

    def _compare(self, parameters, context, dam_folder, grid, arrays, out_dir, writer,
                 feedback):
        """This tool's rasters in the dam folder against the imported ones (same grid)."""
        names = workflow.FINAL_NAMES
        ours, ref = {}, {}
        for kind in ("depth", "velocity", "arrival", "wse"):
            p = os.path.join(dam_folder, names[kind])
            if os.path.exists(p) and kind in arrays:
                ours[kind] = gdal_io.read_like(p, grid, "near")
                ref[kind] = arrays[kind]
        unit = gdal_io.linear_unit_m(grid.crs_wkt) or 1.0
        cell_ac = (grid.dx * unit) ** 2 / 4046.8564224
        thr = self.parameterAsDouble(parameters, "THRESH_FT", context)
        m = benchmark.compare_fields(ours, ref, cell_ac, thr)
        r = benchmark.write_outputs(os.path.join(out_dir, "benchmark"), m,
                                    benchmark.difference_arrays(ours, ref, thr), writer, grid,
                                    "Benchmark against HEC-RAS")
        feedback.pushInfo(m["verdict"])
        for p in r["rasters"].values():
            self.load(context, p, os.path.basename(p)[:-4])
        return r["csv"], m["verdict"]


HECRAS_ALGORITHMS = (HecRasImportAlgorithm,)
