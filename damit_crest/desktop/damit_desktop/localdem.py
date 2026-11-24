"""A local DEM (e.g. a state lidar mosaic such as ND_1m_EPSG26914.vrt) as the desk's terrain, instead of USGS 3DEP.

The desk asks for terrain the way it asks 3DEP (outline.ts fetchDem): a lon/lat box, a width and height in cells,
float32 metres, row-major from the north-west corner, NODATA -9999. This module answers that request from the DEM file
chosen in the app (saved in damit-desk-settings.json as "dem_path") by running gdalwarp on a window of it, so only the
cells asked for are read from the mosaic. The path always comes from the settings file, never from the request.

gdalwarp is looked for next to the PROJ / GDAL data the environment points at (PROJ_DATA, PROJ_LIB, GDAL_DATA or
CONDA_PREFIX: the QGIS env's own gdalwarp, so its proj.db matches), then on PATH, then inside QGIS on macOS / Windows
(QGIS ships it).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NODATA = -9999.0
#: Largest request answered (cells). The desk's own cap is OUTLINE_MAX_PX squared (3000 x 3000).
MAX_CELLS = 3000 * 3000
DEM_SUFFIXES = (".vrt", ".tif", ".tiff", ".img")

_QGIS_GDALWARP = (
    "/Applications/QGIS.app/Contents/MacOS/bin/gdalwarp",
    "/Applications/QGIS-LTR.app/Contents/MacOS/bin/gdalwarp",
)


def env_gdalwarp(env: dict | None = None) -> str | None:
    """The gdalwarp of the install the environment's data variables belong to (<prefix>/share/proj -> <prefix>/bin),
    or CONDA_PREFIX's: the system gdalwarp with another install's PROJ_DATA fails on proj.db (Absaraka desk test)."""
    env = os.environ if env is None else env
    name = "gdalwarp.exe" if sys.platform == "win32" else "gdalwarp"
    prefixes = []
    for k in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA"):
        v = env.get(k)
        if v:
            d = Path(v)
            # <prefix>/share/proj, <prefix>/share/gdal (conda, Linux, macOS) or <prefix>/Library/share/proj (conda, Windows)
            prefixes += [d.parent.parent, d.parent.parent.parent]
    if env.get("CONDA_PREFIX"):
        prefixes.append(Path(env["CONDA_PREFIX"]))
    for pre in prefixes:
        for b in (pre / "bin" / name, pre / "Library" / "bin" / name):
            if b.is_file() and os.access(b, os.X_OK):
                return str(b)
    return None


def find_gdalwarp() -> str | None:
    found = env_gdalwarp() or shutil.which("gdalwarp")
    if found:
        return found
    for p in _QGIS_GDALWARP:
        if Path(p).is_file():
            return p
    if sys.platform == "win32":
        for root in (Path("C:/Program Files"), Path("C:/OSGeo4W")):
            for hit in sorted(root.glob("QGIS*/bin/gdalwarp.exe")) + sorted(root.glob("bin/gdalwarp.exe")):
                return str(hit)
    return None


def read_dem_path(settings_file: Path | None) -> str | None:
    """The chosen DEM, or None when none is chosen or the file is gone."""
    if not settings_file:
        return None
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    p = data.get("dem_path") if isinstance(data, dict) else None
    return p if isinstance(p, str) and Path(p).is_file() else None


def write_dem_path(settings_file: Path, path: str | None) -> None:
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if path:
        data["dem_path"] = str(path)
    else:
        data.pop("dem_path", None)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def parse_request(query: dict) -> tuple[tuple[float, float, float, float], int, int, float]:
    """bbox=w,s,e,n&w=<cells>&h=<cells>&cell=<m> from a parsed query string; ValueError when it is not usable."""
    def one(k):
        v = query.get(k) or [""]
        return v[0]

    box = tuple(float(x) for x in one("bbox").split(","))
    if len(box) != 4:
        raise ValueError("bbox must be west,south,east,north")
    w, s, e, n = box
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bbox out of range")
    width, height = int(one("w")), int(one("h"))
    cell = float(one("cell") or 10)
    if width < 1 or height < 1 or width * height > MAX_CELLS:
        raise ValueError("size out of range")
    return (w, s, e, n), width, height, cell


def warp_args(src: str, bbox, width: int, height: int, cell_m: float, out: str, source_cell_m: float = 1.0) -> list[str]:
    w, s, e, n = bbox
    return [
        "-q", "-overwrite", "-t_srs", "EPSG:4326",
        "-te", repr(w), repr(s), repr(e), repr(n),
        "-ts", str(width), str(height),
        "-r", "average" if cell_m > source_cell_m * 1.5 else "bilinear",
        "-ot", "Float32", "-dstnodata", str(int(NODATA)),
        "-of", "ENVI", src, out,
    ]


#: Variables that point GDAL / PROJ at their data files. When they belong to another GDAL install (e.g. QGIS's conda
#: environment exported into the desk's shell while gdalwarp comes from the system), PROJ refuses the proj.db
#: ("DATABASE.LAYOUT.VERSION.MINOR = 3 whereas a number >= 5 is expected") and gdalwarp fails.
DATA_VARS = ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")
_PROJ_DB_ERROR = re.compile(r"proj\.db|PROJ: proj_create|DATABASE\.LAYOUT\.VERSION|Cannot find proj", re.I)


def own_data_env(env: dict | None = None) -> dict:
    """The environment without DATA_VARS, so gdalwarp uses the PROJ / GDAL data it was built with."""
    out = dict(os.environ if env is None else env)
    for k in DATA_VARS:
        out.pop(k, None)
    return out


def is_proj_db_error(text: str) -> bool:
    return bool(_PROJ_DB_ERROR.search(text or ""))


def read_window(src: str, bbox, width: int, height: int, cell_m: float, gdalwarp: str | None = None, timeout: float = 120) -> bytes:
    """The window as little-endian float32 bytes (width * height * 4).

    When gdalwarp fails on its PROJ database and PROJ_DATA / PROJ_LIB / GDAL_DATA are set (they point at another GDAL
    install), it is run once more without them, so it uses its own data files."""
    exe = gdalwarp or find_gdalwarp()
    if not exe:
        raise RuntimeError("gdalwarp was not found: install QGIS (it ships gdalwarp) or put GDAL on PATH.")
    with tempfile.TemporaryDirectory(prefix="damit-dem-") as tmp:
        out = str(Path(tmp) / "dem.bin")
        cmd = [exe, *warp_args(src, bbox, width, height, cell_m, out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode != 0 and is_proj_db_error(text) and any(os.environ.get(k) for k in DATA_VARS):
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=own_data_env())
            text = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode != 0:
            if is_proj_db_error(text):
                raise RuntimeError(
                    f"gdalwarp ({exe}) could not read its map-projection database (proj.db), so the local DEM cannot "
                    "be read. Its PROJ files do not match this gdalwarp: start the desk without PROJ_DATA / PROJ_LIB "
                    "pointing at another GDAL or QGIS install, or put QGIS's own gdalwarp first on PATH.")
            first = next((ln for ln in text.splitlines() if ln.strip() and not ln.lower().startswith("usage")), text)
            raise RuntimeError(f"gdalwarp could not read the local DEM: {first.strip()[:300]}")
        raw = Path(out).read_bytes()
        hdr = (Path(tmp) / "dem.hdr").read_text(encoding="utf-8", errors="replace")
    need = width * height * 4
    if len(raw) < need:
        raise RuntimeError(f"gdalwarp wrote {len(raw)} bytes, expected {need}")
    raw = raw[:need]
    if "byte order = 1" in hdr:  # big-endian output: swap to little-endian for the desk
        import array

        a = array.array("f")
        a.frombytes(raw)
        a.byteswap()
        raw = a.tobytes()
    return raw
