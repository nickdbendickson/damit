"""The DEM picker and Save for the desk in a browser (Linux, or anywhere pywebview cannot start).

In the native window (Mac, Windows) the pywebview bridge opens the system's Open and Save dialogs. A browser page
cannot read a file on the computer by its path, and its downloads go to the browser's Downloads folder. Here the
desk's own server does both, on this computer, for the page it served (the same token check as every /api/ call):

  list_dir(dir, mode)   the folders and files under a folder, for the desk's own file chooser
                        (mode "dem": DEM files .vrt .tif .tiff .img; mode "folder": folders only)
  choose_dem(path)      remember a DEM as the desk's terrain (the same setting the native picker writes)
  save_export(...)      write an export into the chosen exports folder and say where

Nothing here deletes or overwrites: a name already in the folder gets " (2)", " (3)"...

Confinement (security, 2026-11-20). The token keeps other programs out, and on top of that these calls only reach
folders the desk has a reason to touch, after every symlink and ".." is resolved:

  read (list, choose a DEM)  the work folders (~/DamITDams, DAMIT_WORK, DAMIT_WORK_ROOTS), the exports folder, the
                             DamIT data folder (DAMIT_DATA or ~/.damit/config.json), DAMIT_DEM's folder, the folder of
                             the DEM already chosen, and any folders in DAMIT_DEM_ROOTS (os.pathsep separated)
  write (exports folder, Save)  the work folders only (DAMIT_WORK_ROOTS adds more)

A path outside them, a symlink that leads outside them, or a file name with a folder in it is refused."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from damit_desktop import layers, localdem
from damit_desktop.qgis_run import allowed_work_roots

MAX_ENTRIES = 2000


class BrowserIOError(ValueError):
    pass


def _settings(settings_file: Path | None) -> dict:
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file and settings_file.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _write_settings(settings_file: Path | None, data: dict) -> None:
    if not settings_file:
        return
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _real(path) -> Path | None:
    """The canonical path (symlinks and '..' resolved), or None for an empty or unusable one."""
    raw = str(path or "").strip()
    if not raw or "\x00" in raw:
        return None
    try:
        return Path(os.path.realpath(Path(raw).expanduser()))
    except (OSError, ValueError):
        return None


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _dedupe(paths) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p is not None and p not in out:
            out.append(p)
    return out


def write_roots() -> list[Path]:
    """Folders Save and the exports folder may be in: the work folders (qgis_run.allowed_work_roots)."""
    return _dedupe(_real(r) for r in allowed_work_roots())


def read_roots(settings_file: Path | None) -> list[Path]:
    """Folders the desk's file chooser may show and a DEM may be chosen from (see the module docstring)."""
    raw: list = [*allowed_work_roots(), export_dir(settings_file), layers.find_data_folder()]
    env_dem = os.environ.get("DAMIT_DEM")
    if env_dem:
        raw.append(Path(env_dem).expanduser().parent)
    chosen = localdem.read_dem_path(settings_file)
    if chosen:
        raw.append(Path(chosen).expanduser().parent)
    raw += (os.environ.get("DAMIT_DEM_ROOTS") or "").split(os.pathsep)
    return _dedupe(r for r in (_real(x) for x in raw) if r is not None and r.is_dir())


def _roots_hint() -> str:
    return "put it under the work folder, or add its folder to DAMIT_DEM_ROOTS and restart the desk"


def default_export_dir() -> Path:
    """<work folder>/exports: DAMIT_WORK, else ~/DamITDams."""
    work = os.environ.get("DAMIT_WORK") or str(Path.home() / "DamITDams")
    return Path(work).expanduser() / "exports"


def export_dir(settings_file: Path | None) -> Path:
    """The chosen exports folder while it exists and is still inside a work folder, else <work>/exports."""
    chosen = _settings(settings_file).get("export_dir")
    real = _real(chosen) if isinstance(chosen, str) else None
    if real is not None and real.is_dir() and _inside(real, write_roots()):
        return real
    return default_export_dir()


def set_export_dir(settings_file: Path | None, path: str) -> Path:
    folder = Path(str(path or "")).expanduser()
    if not str(path or "").strip() or not folder.is_absolute():
        raise BrowserIOError("give a full folder path")
    if not folder.is_dir():
        raise BrowserIOError(f"no such folder: {folder}")
    real = _real(folder)
    if real is None or not _inside(real, write_roots()):
        roots = ", ".join(str(r) for r in write_roots())
        raise BrowserIOError(f"exports must go inside the work folder ({roots}); set DAMIT_WORK_ROOTS to allow others")
    if not os.access(real, os.W_OK):
        raise BrowserIOError(f"this folder cannot be written: {folder}")
    data = _settings(settings_file)
    data["export_dir"] = str(real)
    _write_settings(settings_file, data)
    return real


def list_dir(path: str | None, mode: str = "dem", settings_file: Path | None = None) -> dict:
    """{"dir", "parent", "roots", "entries": [{"name", "path", "dir"}]} for the desk's file chooser, inside the read
    roots only. No path means the first root (the work folder). Hidden entries are left out; in "dem" mode only DEM
    files are listed beside the folders, in "csv" mode only .csv files; an entry whose real path leaves the roots (a symlink) is not listed."""
    roots = read_roots(settings_file)
    if not roots:
        raise BrowserIOError("there is no work folder to show; set DAMIT_WORK")
    folder = _real(path) if path else roots[0]
    if folder is None or not folder.is_dir():
        raise BrowserIOError(f"no such folder: {path}")
    if not _inside(folder, roots):
        raise BrowserIOError(f"the desk only shows its own folders here; to use {folder}, {_roots_hint()}")
    entries = []
    try:
        items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise BrowserIOError(f"cannot read {folder}: {exc.strerror or exc}") from None
    for p in items:
        if p.name.startswith("."):
            continue
        real = _real(p)
        if real is None or not _inside(real, roots):
            continue
        try:
            is_dir = real.is_dir()
        except OSError:
            continue
        # "dem": DEM files; "csv": tables (the rail trains-per-day lookup); "folder": folders only
        wanted = localdem.DEM_SUFFIXES if mode == "dem" else (".csv",) if mode == "csv" else ()
        if not is_dir and p.suffix.lower() not in wanted:
            continue
        entries.append({"name": p.name, "path": str(folder / p.name), "dir": is_dir})
        if len(entries) >= MAX_ENTRIES:
            break
    parent = folder.parent if folder.parent != folder and _inside(folder.parent, roots) else None
    return {"dir": str(folder), "parent": str(parent) if parent else None, "home": str(roots[0]),
            "roots": [str(r) for r in roots], "entries": entries}


def dem_state(settings_file: Path | None) -> dict:
    return {"path": localdem.read_dem_path(settings_file), "gdalwarp": localdem.find_gdalwarp()}


def choose_dem(settings_file: Path | None, path: str) -> dict:
    p = Path(str(path or "")).expanduser()
    if not str(path or "").strip() or not p.is_absolute():
        raise BrowserIOError("give the full path of the DEM file")
    if not p.is_file():
        raise BrowserIOError(f"no such file: {p}")
    if p.suffix.lower() not in localdem.DEM_SUFFIXES:
        raise BrowserIOError(f"not a DEM file DamIT Desk reads ({', '.join(localdem.DEM_SUFFIXES)}): {p}")
    real = _real(p)
    if real is None or not _inside(real, read_roots(settings_file)):
        raise BrowserIOError(f"the desk only reads DEMs from its own folders; to use {p}, {_roots_hint()}")
    if settings_file:
        localdem.write_dem_path(settings_file, str(p))
    return {"path": str(p), "gdalwarp": localdem.find_gdalwarp()}


def clear_dem(settings_file: Path | None) -> dict:
    if settings_file:
        localdem.write_dem_path(settings_file, None)
    return {"path": None, "gdalwarp": localdem.find_gdalwarp()}


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    for n in range(2, 10000):
        target = folder / f"{stem} ({n}){suffix}"
        if not target.exists():
            return target
    raise BrowserIOError("too many files with that name")


#: Characters a saved file name may not have (folder separators, Windows-reserved, control characters).
_BAD_NAME = set('<>:"/\\|?*') | {chr(c) for c in range(32)} | {"\x7f"}


def safe_name(name: str) -> str:
    """The export's own file name, with no folder in it: separators, reserved and control characters become "_",
    and leading dots (hidden files, "..") are dropped."""
    base = str(name or "").replace("\\", "/").split("/")[-1]
    clean = "".join("_" if ch in _BAD_NAME else ch for ch in base).strip().lstrip(".").strip()
    if not clean:
        return "damit_export.txt"
    if len(clean) > 150:
        stem, suffix = os.path.splitext(clean)
        clean = stem[: 150 - len(suffix[:20])] + suffix[:20]
    return clean


def save_export(settings_file: Path | None, name: str, data: bytes) -> Path:
    """Write an export into the exports folder (made if missing) under its own name, never over another file, and
    never through a symlink out of the work folders."""
    clean = safe_name(name)
    folder = export_dir(settings_file)
    folder.mkdir(parents=True, exist_ok=True)
    real = _real(folder)
    if real is None or not _inside(real, write_roots()):
        raise BrowserIOError(f"the exports folder {folder} is outside the work folder; choose it again")
    target = _free_name(real, clean)
    if target.parent != real:
        raise BrowserIOError("not a plain file name")
    tmp = target.with_name(target.name + ".part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp, flags, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except FileExistsError:
        raise BrowserIOError(f"{tmp.name} is in the way in {real}; remove it and save again") from None
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return target


#: How deep and how many entries autofill looks through under each read root (a work folder can be large).
AUTOFILL_DEPTH = 4
AUTOFILL_MAX_SCAN = 20000
RASTER_SUFFIXES = (".tif", ".tiff", ".vrt", ".img", ".asc")


def _digest(path: Path, cap: int = 256 * 1024 * 1024) -> str:
    """The file's SHA-256 (size + path when larger than cap, so a big file is never read twice for this)."""
    try:
        size = path.stat().st_size
        if size > cap:
            return f"{size}:{path}"
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return f"?:{path}"


def _is_rail_lookup(name: str) -> bool:
    n = name.lower()
    return n.endswith(".csv") and "rail" in n and ("train" in n or "lookup" in n)


def autofill(settings_file: Path | None, names: list[str]) -> dict:
    """Paths the Report step's hand-off form can start from (Absaraka desk test 2026-11-21: every field was typed by
    hand): the DEM chosen in the desk, where the imported run's rasters are on this computer (the browser only knows
    their names, so they are looked for by name under the read roots) and a rail trains-per-day lookup CSV.
    {"dem", "rasters": {name: path | null}, "railLookup", "ambiguous": [name]}; only files inside the read roots."""
    wanted = {Path(n).name: [] for n in names[:12] if Path(n).name and Path(n).suffix.lower() in RASTER_SUFFIXES}
    rail: list[Path] = []
    roots = read_roots(settings_file)
    seen = 0
    for root in roots:
        stack = [(root, 0)]
        while stack and seen < AUTOFILL_MAX_SCAN:
            folder, depth = stack.pop()
            try:
                entries = sorted(folder.iterdir(), key=lambda p: p.name)
            except OSError:
                continue
            for p in entries:
                seen += 1
                if p.name.startswith(".") or p.name in ("node_modules", "chrome-profile"):
                    continue
                try:
                    if p.is_dir():
                        if depth < AUTOFILL_DEPTH and not p.is_symlink():
                            stack.append((p, depth + 1))
                        continue
                except OSError:
                    continue
                real = _real(p)
                if real is None or not _inside(real, roots):
                    continue
                if p.name in wanted and real not in wanted[p.name]:
                    wanted[p.name].append(real)
                elif _is_rail_lookup(p.name) and real not in rail:
                    rail.append(real)
    dem = localdem.read_dem_path(settings_file)
    # A run folder holding all of the names wins over stray copies; copies with the same bytes are the same raster.
    cover: dict[Path, int] = {}
    for hits in wanted.values():
        for h in hits:
            cover[h.parent] = cover.get(h.parent, 0) + 1
    rasters, ambiguous = {}, []
    for n, hits in wanted.items():
        if not hits:
            rasters[n] = None
            continue
        hits = sorted(hits, key=lambda h: (-cover[h.parent], len(h.parts), str(h)))
        if len(hits) > 1 and len({_digest(h) for h in hits}) > 1:
            rasters[n] = None
            ambiguous.append(n)
        else:
            rasters[n] = str(hits[0])
    return {"dem": dem if dem and Path(dem).is_file() else None, "rasters": rasters, "ambiguous": sorted(ambiguous),
            "railLookup": str(rail[0]) if len(rail) == 1 else None, "railLookups": [str(r) for r in rail[:10]]}
