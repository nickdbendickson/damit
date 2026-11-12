"""A synthetic UTM valley DEM with an embankment across it, and a stub flood engine (tests only; no DWR data,
no model run)."""
import os

import numpy as np


def make_dem(path, nx=240, ny=360, cell=10.0, x0=600000.0, y0=5210000.0, epsg=26914, dam_row=80):
    """Valley running south (rows increase southward), floor slope 0.002, a dam across it at dam_row with its top
    at 335 m. Returns the dam line and reservoir point in lon / lat and the elevations (m)."""
    from osgeo import gdal, osr
    gdal.UseExceptions()
    yy, xx = np.mgrid[0:ny, 0:nx]
    floor = 330.0 - yy * cell * 0.002
    z = floor + 0.004 * np.abs(xx - nx / 2) * cell
    top = 335.0
    emb = (yy >= dam_row - 1) & (yy <= dam_row + 1) & (np.abs(xx - nx / 2) < 40)
    z = np.where(emb, np.maximum(z, top), z)
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    ds.SetProjection(s.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.GetRasterBand(1).SetUnitType("m")
    ds = None
    w = osr.SpatialReference()
    w.ImportFromEPSG(4326)
    w.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    t = osr.CoordinateTransformation(s, w)
    yd = y0 - (dam_row + 0.5) * cell
    xa, xb = x0 + (nx / 2 - 35) * cell, x0 + (nx / 2 + 35) * cell
    line = [tuple(t.TransformPoint(xa, yd)[:2]), tuple(t.TransformPoint(xb, yd)[:2])]
    res = tuple(t.TransformPoint(x0 + nx / 2 * cell, y0 - (dam_row - 50) * cell)[:2])
    centre = tuple(t.TransformPoint(x0 + nx / 2 * cell, yd)[:2])
    floor_dam = 330.0 - dam_row * cell * 0.002
    return {"line": line, "reservoir": res, "centre": centre, "top_m": top, "floor_at_dam": floor_dam,
            "dam_xy": (x0 + nx / 2 * cell, yd), "x0": x0, "y0": y0, "cell": cell, "nx": nx, "ny": ny}


def stub_lisflood(LF, calls):
    """A stand-in for lisflood.run: writes a 0.8 m strip down the valley as the LISFLOOD-FP results."""
    def fake_run(workdir, par, exe, max_wall_s=0.0, threads=0, cancel=None, log=None):
        calls.append({"workdir": workdir, "exe": exe, "max_wall_s": max_wall_s})
        a = LF.read_asc(os.path.join(workdir, "run.dem.asc"))
        ny, nx = a.shape
        h = np.zeros(a.shape)
        h[:, nx // 2 - 5:nx // 2 + 5] = 0.8
        os.makedirs(os.path.join(workdir, "results"), exist_ok=True)
        for ext, arr in ((".max", h), (".maxVc", h * 2), (".inittm", np.where(h > 0, 1.0, -9999))):
            LF.write_asc(os.path.join(workdir, "results", "run" + ext), arr, 0, 0, 10.0)
        return {"engine": "stub", "wall_s": 0.1, "wall_limit_s": LF.wall_limit_s(max_wall_s), "unpatched": False}
    return fake_run


class FakeFV:
    """A stand-in for fv_engine.Engine (screen.simulate's engine_factory(grid, dem_m, cell, manning)): floods a strip
    of the valley below the source cells."""
    timeout = False
    rows = 30

    def __init__(self, grid, dem, cell, manning=0.05):
        self.dem = dem
        self.cell = cell
        self.t = 0.0
        shape = dem.shape
        self.hmax = np.zeros(shape)
        self.vmax = np.zeros(shape)
        self.dvmax = np.zeros(shape)
        self.arrive = np.full(shape, -9999.0)
        self.src = []

    def add_source(self, cells, t_s, q, z):
        self.src = list(cells)

    def run(self, sim_s, max_wall_s=None, cancel=None):
        r0 = min(r for r, _ in self.src)
        c0 = int(np.mean([c for _, c in self.src]))
        ny, nx = self.dem.shape
        rows = slice(r0, ny if self.rows is None else min(r0 + self.rows, ny))
        cols = slice(max(c0 - 3, 0), min(c0 + 4, nx))
        self.hmax[rows, cols] = 1.0
        self.vmax[rows, cols] = 1.5
        self.dvmax[rows, cols] = 1.5
        self.arrive[rows, cols] = 0.5
        self.t = sim_s / 2.0
        if self.timeout:
            raise TimeoutError("stub time limit")
        self.t = sim_s
        self.mass = {"error_pct": 0.0}
        return {"depth": self.hmax, "vel": self.vmax, "dv": self.dvmax, "arrive_h": self.arrive, "t": self.t,
                "mass": self.mass}


class TimeoutFV(FakeFV):
    timeout = True


class EdgeFV(FakeFV):
    """Floods the strip down to the bottom edge of every clip (so the clip always grows)."""
    rows = None


def write_tif(path, z, x0, y0, cell, epsg):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    ny, nx = z.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    ds.SetProjection(s.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.GetRasterBand(1).SetUnitType("m")
    ds = None
    return path


def tiff_bytes(w, h, bbox, epsg=5070, value=300.0):
    """The bytes of a float32 GeoTIFF of w x h cells over bbox (a stand-in for a 3DEP exportImage answer)."""
    import tempfile
    d = tempfile.mkdtemp(prefix="damit_3dep_fake_")
    try:
        xmin, ymin, xmax, ymax = bbox
        cell = (xmax - xmin) / w
        yy = np.mgrid[0:h, 0:w][0]
        p = write_tif(os.path.join(d, "t.tif"), value - 0.001 * yy * cell + np.zeros((h, w)), xmin, ymax, cell, epsg)
        with open(p, "rb") as fh:
            return fh.read()
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_3dep_opener(calls, value=300.0, body=None):
    """urlopen stand-in: answers each exportImage request with a GeoTIFF of the requested size and box."""
    from urllib.parse import urlparse, parse_qs

    def opener(url, timeout=None):
        q = parse_qs(urlparse(url).query)
        calls.append({"url": url, "q": {k: v[0] for k, v in q.items()}, "timeout": timeout})
        if body is not None:
            return FakeResponse(body)
        w, h = (int(v) for v in q["size"][0].split(","))
        bbox = tuple(float(v) for v in q["bbox"][0].split(","))
        return FakeResponse(tiff_bytes(w, h, bbox, int(q["imageSR"][0]), value))
    return opener
