"""Call the installed DamIT QGIS plugins through qgis_process. Never start the chain after a preflight FAIL.

The algorithm ids come from damit_desktop.algorithms (DamIT defaults, overridable by environment or
damit-handoff.json). Nothing here starts a North Dakota suite id (nddam:*, ndbreach:*) or a batch algorithm."""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote

from damit_desktop.algorithms import HandoffConfig, find_damit_cli, load_config
from damit_desktop.hazard_class import class_ordinal
from damit_desktop import profile as desk_profile
from damit_desktop.handoff import (
    handoff_ids,
    nid_problem,
    HandoffError,
    _dem_point,
    classification_block,
    resolved_failure_mode,
    safe_name,
    write_classify_record,
    write_dam_folder,
    write_dam_point,
    write_named_files,
)
from damit_desktop.layers import data_dem, download_aoi, find_data_folder, use_data_folder, write_settings
from damit_desktop import localdem, real_receptors
from damit_desktop.receptors import LAYERS as RECEPTOR_LAYERS
from damit_desktop.receptors import structure_points, write_receptor_layers

# The runner's METHOD / TIER option text (DamIT Runner 0.2.0 and an ND-style port: the DamSafety Runner's labels). qgis_process
# (QGIS 3.34) rejects option text for these enums ("Incorrect parameter value for METHOD"), so enum_value() looks the
# text up in `qgis_process help <rundam id>` and sends its index;
# a hard-coded index would silently change if the plugin reordered its options.
METHOD_LABEL = {
    ("froehlich", "piping"): "Piping failure, Froehlich (2008) parameters, routed",
    ("froehlich", "overtopping"): "Overtopping failure, Froehlich (2008) parameters, routed",
    ("macdonald", "piping"): "MacDonald & Langridge-Monopolis (1984) earthfill parameters, routed",
    ("macdonald", "overtopping"): "MacDonald & Langridge-Monopolis (1984) earthfill parameters, routed",
    ("tr60", "piping"): "NRCS TR-60 peak breach discharge, triangular hydrograph",
    ("tr60", "overtopping"): "NRCS TR-60 peak breach discharge, triangular hydrograph",
}
CLI_METHOD = {
    ("froehlich", "piping"): "piping",
    ("froehlich", "overtopping"): "overtopping",
    ("macdonald", "piping"): "mlm1984",
    ("macdonald", "overtopping"): "mlm1984",
    ("tr60", "piping"): "tr60",
    ("tr60", "overtopping"): "tr60",
}

# qgis_process enum text, then the CLI model.tier value.
MODELS = {
    "lisflood": ("LISFLOOD-FP only", "lisflood", False),
    "anuga": (
        "LISFLOOD-FP for the extent, then ANUGA (final results from ANUGA)",
        "lisflood+anuga",
        False,
    ),
    "hecras": (
        "LISFLOOD-FP then HEC-RAS 2D (final results from HEC-RAS; needs HEC-RAS 6.6, see help)",
        "lisflood+hecras",
        False,
    ),
    "builtin": ("LISFLOOD-FP only", "lisflood", True),
}


def model_choice(name: str | None) -> tuple[str, str, bool]:
    return MODELS.get(str(name or "lisflood"), MODELS["lisflood"])


def suite_qgis_process() -> Path:
    """The DamIT qgis_process the suite installer writes (install-all.sh / install-all-windows.cmd): QGIS from its
    conda env with the DamIT plugins' profile. In DAMSUITE_PREFIX, else ~/dam-suite. A --sandbox install writes it in
    the sandbox folder instead; set QGIS_PROCESS to that one."""
    prefix = Path(os.environ.get("DAMSUITE_PREFIX") or Path.home() / "dam-suite").expanduser()
    return prefix / ("qgis-process-damit.cmd" if os.name == "nt" else "qgis-process-damit.sh")


def dwr_suite_prefix() -> Path:
    """The DWR DamSafety suite's install folder (tools/mac/install_dwr_suite_mac.sh): DAMSAFETY_PREFIX, else
    ~/dwr-dam-suite. It holds damsafety_env.sh, which names that install's qgis_process and its headless QGIS
    configuration (a profiles/default link to the "damsafety" QGIS profile, kept apart from the DamIT plugins)."""
    return Path(os.environ.get("DAMSAFETY_PREFIX") or Path.home() / "dwr-dam-suite").expanduser()


_EXPORT = re.compile(r"""^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"]*)"|'([^']*)'|(\S*))\s*(?:#.*)?$""")


def read_env_file(path: Path) -> dict[str, str]:
    """The plain ``export NAME="value"`` lines of a shell env file such as damsafety_env.sh. Read only, never run."""
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        m = _EXPORT.match(line)
        if m:
            out[m.group(1)] = next(v for v in m.group(2, 3, 4) if v is not None)
    return out


def nd_launcher(prefix: Path | None = None, settings_dir: Path | None = None) -> str | None:
    """A qgis_process launcher for the DWR suite, in the North Dakota profile.

    <prefix>/qgis-process-dwr.sh (.cmd on Windows) when the install has one. Else, from the DWR installer's
    damsafety_env.sh, the desk writes qgis-process-dwr.sh in its settings folder: it sources that env file, points
    QGIS_CUSTOM_CONFIG_PATH at the install's headless configuration (so qgis_process reads the "damsafety" profile
    with the DWR plugins) and runs the install's qgis_process. Rewritten only when the text changes. None when there
    is no DWR install to use."""
    prefix = prefix or dwr_suite_prefix()
    own = prefix / ("qgis-process-dwr.cmd" if os.name == "nt" else "qgis-process-dwr.sh")
    if own.is_file():
        return str(own)
    env_file = prefix / "damsafety_env.sh"
    if os.name == "nt" or not env_file.is_file():
        return None
    env = read_env_file(env_file)
    exe, headless = env.get("QGIS_PROCESS"), env.get("DAMSAFETY_HEADLESS_CONFIG")
    if not exe or not Path(exe).is_file():
        return None
    folder = settings_dir or SETTINGS_DIR
    if folder is None:
        return None
    lines = [
        "#!/bin/sh",
        f"# Written by DamIT Desk (North Dakota profile) from {env_file}. Rewritten when that changes; do not edit.",
        f". {shlex.quote(str(env_file))}",
    ]
    if headless:
        lines.append(f"export QGIS_CUSTOM_CONFIG_PATH={shlex.quote(headless)}")
    lines.append(f'exec {shlex.quote(exe)} "$@"')
    text = "\n".join(lines) + "\n"
    out = Path(folder) / "qgis-process-dwr.sh"
    try:
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            Path(folder).mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        out.chmod(0o755)
    except OSError:
        return None
    return str(out)


def find_qgis_process() -> str | None:
    """QGIS_PROCESS; else the suite installer's DamIT qgis_process (a bare qgis_process uses the default QGIS profile,
    where the DamIT algorithms are usually missing); else qgis_process on PATH; else the Mac QGIS apps.

    North Dakota profile: DAMIT_ND_QGIS_PROCESS; else the DWR suite's launcher (nd_launcher); else the DamIT suite
    installer's qgis-process-damsafety.sh (.cmd), which reads its "damsafety" profile; else QGIS_PROCESS,
    PATH and the Mac apps as the old dwr_crest desk did. Never the DamIT suite's launcher: its QGIS profile has the
    DamIT plugins, not the DWR ones."""
    if desk_profile.is_nd():
        chosen = os.environ.get("DAMIT_ND_QGIS_PROCESS")
        if chosen and Path(chosen).is_file():
            return chosen
        launcher = nd_launcher()
        if launcher:
            return launcher
        # The DamIT suite installer (suite_install/install-all.sh) also installs the DWR plugins, in profile
        # "damsafety", and writes this launcher for it beside qgis-process-damit.sh.
        suite_nd = suite_qgis_process().with_name("qgis-process-damsafety" + suite_qgis_process().suffix)
        if suite_nd.is_file():
            return str(suite_nd)
    chosen = os.environ.get("QGIS_PROCESS")
    if chosen and Path(chosen).is_file():
        return chosen
    if not desk_profile.is_nd():
        suite = suite_qgis_process()
        if suite.is_file():
            return str(suite)
    found = shutil.which("qgis_process")
    if found:
        return found
    for candidate in (
        "/Applications/QGIS.app/Contents/MacOS/bin/qgis_process",
        "/Applications/QGIS-LTR.app/Contents/MacOS/bin/qgis_process",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


#: The default work folder, in the home folder.
DEFAULT_WORK_NAME = "DamITDams"


class WorkFolderError(ValueError):
    """The requested work folder is outside the allowed roots."""


def allowed_work_roots() -> list[Path]:
    """Folders a job sent over the local API may write under: ~/DamITDams, DAMIT_WORK, and any folders listed in
    DAMIT_WORK_ROOTS (os.pathsep separated)."""
    raw = [str(Path.home() / DEFAULT_WORK_NAME), os.environ.get("DAMIT_WORK") or ""]
    raw += (os.environ.get("DAMIT_WORK_ROOTS") or "").split(os.pathsep)
    roots = []
    for r in raw:
        if r.strip():
            roots.append(Path(r.strip()).expanduser().resolve())
    return roots


def resolve_work(requested) -> str | None:
    """Validate a work folder from an API request. Empty means the default. The path is resolved (symlinks and
    '..' included) and must be one of the allowed roots or inside one; otherwise WorkFolderError."""
    if requested is None or (isinstance(requested, str) and not requested.strip()):
        return None
    if not isinstance(requested, str) or "\x00" in requested:
        raise WorkFolderError("the work folder is not a valid path")
    path = Path(requested.strip()).expanduser()
    if not path.is_absolute():
        path = Path.home() / DEFAULT_WORK_NAME / path
    resolved = path.resolve()
    for root in allowed_work_roots():
        if resolved == root or root in resolved.parents:
            return str(resolved)
    roots = ", ".join(str(r) for r in allowed_work_roots())
    raise WorkFolderError(f"the work folder must be inside {roots} (set DAMIT_WORK_ROOTS to allow others)")


def default_work_dir() -> Path:
    """The work folder a blank Work folder field means: DAMIT_WORK, else ~/DamITDams (not created here). The Report
    step shows it in the field's hint (2026-11-21: the hint said ~/DamITDams even with DAMIT_WORK set)."""
    raw = (os.environ.get("DAMIT_WORK") or "").strip()
    return (Path(raw).expanduser() if raw else Path.home() / DEFAULT_WORK_NAME).resolve()


def work_dir(requested: str | None) -> Path:
    raw = (requested or "").strip()
    path = Path(raw).expanduser() if raw else default_work_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


#: The desk's own settings file (set by __main__.main): the local DEM chosen with "Choose DEM" is read from it, so the
#: plugins get the same terrain the desk draws with.
DESK_SETTINGS_FILE: Path | None = None


def desk_dem() -> str | None:
    """The local DEM chosen in the desk (Flood step, "Choose DEM"), when that file still exists."""
    try:
        chosen = localdem.read_dem_path(DESK_SETTINGS_FILE) if DESK_SETTINGS_FILE else None
    except (OSError, ValueError):
        return None
    return chosen if chosen and Path(chosen).is_file() else None


def dem_path(work: Path, dam: dict, source: str = "data") -> str | None:
    """The DEM the plugins get: the Report step's DEM field, else DAMIT_DEM, else the DEM chosen in the desk, else
    <work>/dem.tif or dem.vrt (Get layers), else the DamIT data folder's DEM."""
    for raw in (dam.get("demPath"), os.environ.get("DAMIT_DEM"), desk_dem(), work / "dem.tif", work / "dem.vrt"):
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.is_file():
            return str(path.resolve())
    if source in ("data", "pack"):
        found = data_dem(find_data_folder())
        if found:
            return found
    return None


def _ready(text: str) -> bool | None:
    match = re.search(r"READY:\s*(true|false)\b", text, re.I)
    if match:
        return match.group(1).lower() == "true"
    fails = re.search(r"FAILS:\s*(\d+)", text, re.I)
    if fails:
        return int(fails.group(1)) == 0
    # The report's first line is "Preflight: ready", "Preflight: ready, N warning(s)",
    # or "Preflight: not ready: ...". Warnings still pass.
    report = re.search(r"Preflight:\s*(not ready|ready)\b", text, re.I)
    if report:
        return report.group(1).lower() == "ready"
    return None


# Internal sentinels for a run we stopped ourselves. Kept clear of the common real exit codes 124 (coreutils
# timeout) and 130 (SIGINT) so a plugin that genuinely exits 124/130 is not misread as a DamIT Desk timeout/cancel.
STOPPED_TIMEOUT = 224
STOPPED_CANCEL = 230


def screening_timeout(value=None) -> float | None:
    """Seconds the screening chain may run: the request's value, else DAMIT_SCREENING_TIMEOUT_S, else no limit.

    A one-dam chain on a statewide pack has run past 45 minutes (2026-10-30), so there is no default limit;
    0, blank or a bad value means no limit."""
    for raw in (value, os.environ.get("DAMIT_SCREENING_TIMEOUT_S")):
        if raw in (None, ""):
            continue
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            continue
        if seconds == seconds and seconds > 0:
            return seconds
        return None
    return None


def _taskkill_tree(pid: int) -> bool:
    """Force-kill a Windows process and its whole child tree. True if taskkill ran, False if it is unavailable.

    proc.terminate() on Windows posts WM_CLOSE/TerminateProcess to qgis_process alone, leaving the LISFLOOD-FP /
    ANUGA / HEC-RAS children it spawned running — they keep burning CPU and writing into the work folder after a
    cancel or timeout. taskkill /T walks the tree; /F forces it.
    """
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return True
    except OSError:
        return False


def _stop(proc: subprocess.Popen) -> None:
    """Stop qgis_process and what it started: its process group on POSIX, its whole tree on Windows."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        elif not _taskkill_tree(proc.pid):
            proc.terminate()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            elif not _taskkill_tree(proc.pid):
                proc.kill()
        except OSError:
            pass


# A 45-minute chain can emit tens of MB of progress text. The job manager holds every job's log in memory, so keep
# only the head and tail of a run's output and note how much was dropped from the middle.
_OUTPUT_HEAD_CHARS = 100_000
_OUTPUT_TAIL_CHARS = 100_000


def _collect_bounded(stream, head_cap: int = _OUTPUT_HEAD_CHARS, tail_cap: int = _OUTPUT_TAIL_CHARS, on_line=None) -> str:
    """Read all of stream but retain only the first head_cap and last tail_cap characters, with a count of the
    dropped middle. Reads in blocks so the full output is never held in memory at once."""
    head: list[str] = []
    head_len = 0
    tail: deque[str] = deque()
    tail_len = 0
    dropped = 0
    while True:
        try:
            # Line by line when the caller streams the log: a text pipe's read(8192) waits for 8192 characters,
            # so a quiet plugin showed nothing until it ended.
            block = stream.readline() if on_line is not None else stream.read(8192)
        except (ValueError, OSError):
            break  # stream closed while the process was being stopped
        if not block:
            break
        if on_line is not None:
            try:
                on_line(block)
            except Exception:
                pass  # a log callback never stops the run
        if head_len < head_cap:
            take = min(len(block), head_cap - head_len)
            head.append(block[:take])
            head_len += take
            block = block[take:]
            if not block:
                continue
        tail.append(block)
        tail_len += len(block)
        while tail_len > tail_cap and len(tail) > 1:
            removed = tail.popleft()
            tail_len -= len(removed)
            dropped += len(removed)
    text = "".join(head)
    if dropped:
        text += f"\n[... {dropped:,} characters of output omitted ...]\n"
    return text + "".join(tail)


def classify_env() -> dict[str, str]:
    """Environment for the classify qgis_process: GDAL PAM off. The depth / velocity / WSE / arrival rasters are a
    model run's (often a product-of-record folder) and are read only; with PAM on, GDAL and QGIS (layer statistics)
    write <raster>.aux.xml sidecars beside them. damit:classify writes only its OUTPUT folder (reports, GeoPackage)."""
    return {**os.environ, "GDAL_PAM_ENABLED": "NO"}


def _argv(cmd: list[str]) -> list[str]:
    """A .py is not a program. Run it with this Python so the argument list is not re-parsed.

    A real qgis_process is an executable and is left as given.
    """
    if cmd and cmd[0].lower().endswith(".py"):
        return [sys.executable, *cmd]
    return cmd


def _run(
    cmd: list[str], timeout: float | None, cancel: threading.Event | None = None, env: dict[str, str] | None = None,
    on_line=None,
) -> tuple[int, str]:
    """Run cmd and return (exit code, output). timeout (seconds) gives 124, cancel.set() gives 130;
    both stop the process (and its children) and keep the output so far. Very long output is kept head + tail only.
    env: the child's environment (None = this process's). on_line(line) gets each output line as it is printed
    (the live log); see _run_logged."""
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc = subprocess.Popen(_argv(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", env=env, **kwargs)
    except OSError as exc:
        return 127, f"Could not start {cmd[0]}: {exc}\n"
    captured: list[str] = []
    reader = threading.Thread(
        target=lambda: captured.append(_collect_bounded(proc.stdout, on_line=on_line) if proc.stdout else ""), daemon=True
    )
    reader.start()
    start = time.monotonic()
    stopped = None
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            stopped = STOPPED_CANCEL
        elif timeout is not None and time.monotonic() - start > timeout:
            stopped = STOPPED_TIMEOUT
        if stopped:
            _stop(proc)
            break
        time.sleep(0.2)
    reader.join(timeout=10)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    if proc.stdout is not None and not reader.is_alive():
        proc.stdout.close()
    out = "".join(captured)
    if stopped == STOPPED_TIMEOUT:
        return stopped, out + f"\nStopped: the command ran longer than {timeout:g} s.\n"
    if stopped == STOPPED_CANCEL:
        return stopped, out + "\nStopped: cancelled in DamIT Desk.\n"
    return proc.returncode, out


#: Live lines per run sent to the job log as they come; past this the rest is logged (head + tail) when it ends.
_LIVE_CHARS = _OUTPUT_HEAD_CHARS // 2


#: qgis_process start-up notices that say nothing about the run (Absaraka desk test 2026-11-21: a PDAL plugin library
#: error and GDAL's FutureWarning on every classify). Kept out of the job log; one line says how many were hidden.
_NOISE = re.compile(
    r"(Can't load library|cannot load library|Unable to load).*(pdal|libgflags)"
    r"|libgflags\.so"
    r"|FutureWarning: Neither gdal\.UseExceptions\(\) nor gdal\.DontUseExceptions\(\)"
    r"|^\s*warnings\.warn\(\s*$", re.I)


def is_noise(line: str) -> bool:
    return bool(_NOISE.search(line or ""))


def _run_logged(cmd: list[str], log, timeout: float | None, cancel: threading.Event | None = None,
                env: dict[str, str] | None = None) -> tuple[int, str]:
    """_run with its output in the job log while it runs (the desk polls the log every second). Whatever was not
    streamed (past _LIVE_CHARS, and the Stopped: note) is logged when the run ends. Returns _run's (code, text).
    Start-up notices (_NOISE) are not logged; the returned text keeps them."""
    state = {"n": 0, "live": True, "sent": [], "hidden": 0}

    def on_line(line: str) -> None:
        if is_noise(line):
            state["hidden"] += 1
            state["n"] += len(line)
            state["sent"].append(line)
            return
        if not state["live"]:
            return
        if state["n"] + len(line) > _LIVE_CHARS:
            state["live"] = False
            log("[… live output paused here; the rest of it is shown when the run ends …]")
            return
        state["n"] += len(line)
        state["sent"].append(line)
        log(line.rstrip("\r\n"))

    code, text = _run(cmd, timeout=timeout, cancel=cancel, env=env, on_line=on_line)
    sent = "".join(state["sent"])
    rest = text[len(sent):] if text.startswith(sent) else ("" if not sent else text)
    if rest.strip():
        kept = [ln for ln in rest.strip("\n").splitlines() if not is_noise(ln)]
        state["hidden"] += len(rest.strip("\n").splitlines()) - len(kept)
        if kept:
            log("\n".join(kept))
    if state["hidden"]:
        log(f"({state['hidden']} QGIS start-up notice line(s) hidden: plugin library warnings that do not affect the result.)")
    return code, text


def plugin_timeout(role: str, environ=None) -> float | None:
    """Seconds a Download layers / Atlas 14 / Find fills job may run: DAMIT_PLUGIN_TIMEOUT_S (0 = no limit), else
    PLUGIN_TIMEOUTS. A state download is the long one; a stuck one is stopped instead of running for ever."""
    env = os.environ if environ is None else environ
    raw = env.get("DAMIT_PLUGIN_TIMEOUT_S")
    if raw not in (None, ""):
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            seconds = None
        if seconds is not None and seconds == seconds:
            return seconds if seconds > 0 else None
    return PLUGIN_TIMEOUTS.get(role)


#: Default limits (seconds): Download layers 3 h, Atlas 14 point 15 min, Find fills 2 h.
PLUGIN_TIMEOUTS = {"data": 3 * 3600.0, "pmp": 15 * 60.0, "finder": 2 * 3600.0}


_ENUM_HELP: dict[tuple[str, str], str | None] = {}
_ENUM_ROW = re.compile(r"^\s*-\s*(\d+):\s*(.*?)\s*$")
_PARAM_ROW = re.compile(r"^([A-Z][A-Z0-9_]*):")


_HELP_FAIL: dict[tuple[str, str], str] = {}


def _help_fail_reason(exe: str, alg: str, out: subprocess.CompletedProcess | None, exc: BaseException | None) -> str:
    """Why `qgis_process help alg` did not succeed: a crash or exit code, or the algorithm is missing."""
    if exc is not None:
        if isinstance(exc, FileNotFoundError):
            return f"{exe} was not found, so {alg} could not be checked."
        if isinstance(exc, subprocess.TimeoutExpired):
            return f"qgis_process help {alg} timed out after {exc.timeout:g} s (the process may have hung or crashed)."
        return f"could not start qgis_process help {alg} ({type(exc).__name__}: {exc})."
    assert out is not None
    code = out.returncode
    err = (out.stderr or "").strip() or (out.stdout or "").strip()
    combined = f"{out.stdout or ''}\n{out.stderr or ''}"
    missing = re.search(r"not found|unknown algorithm|Algorithm .* not found", combined, re.I)
    if missing and code not in (None, 0) and (code is not None and 0 < code < 128):
        return f"{alg} is not installed in this QGIS (qgis_process help exited {code})."
    # A negative or large exit is usually a crash (SIGSEGV is -11, or 139 = 128+11).
    if code is None or (isinstance(code, int) and (code < 0 or code >= 128)):
        detail = f" {err[:400]}" if err else ""
        return f"qgis_process help {alg} crashed (exit {code}).{detail}"
    detail = f" {err[:400]}" if err else ""
    return f"qgis_process help {alg} failed (exit {code}).{detail}"


def help_text(exe: str, alg: str) -> str | None:
    """`qgis_process help alg` (cached per exe/alg), or None when help did not succeed.

    help_failure(exe, alg) is the reason (crash, exit code, or not installed) when this is None.
    """
    key = (exe, alg)
    if key not in _ENUM_HELP:
        try:
            out = subprocess.run(_argv([exe, "help", alg]), capture_output=True, text=True, timeout=180,
                                 stdin=subprocess.DEVNULL)
            if out.returncode == 0 and out.stdout.strip():
                _ENUM_HELP[key] = out.stdout
                _HELP_FAIL.pop(key, None)
            else:
                _ENUM_HELP[key] = None
                _HELP_FAIL[key] = _help_fail_reason(exe, alg, out, None)
        except (OSError, subprocess.SubprocessError) as exc:
            _ENUM_HELP[key] = None
            _HELP_FAIL[key] = _help_fail_reason(exe, alg, None, exc)
    return _ENUM_HELP[key]


def help_failure(exe: str, alg: str) -> str | None:
    """The reason help_text is None, else None. Populates the same cache as help_text."""
    help_text(exe, alg)
    return _HELP_FAIL.get((exe, alg))


def algorithm_available(exe: str, alg: str) -> bool:
    return help_text(exe, alg) is not None


def help_params(exe: str, alg: str) -> set[str]:
    """Parameter names `qgis_process help alg` lists (e.g. {"WORK", "REPORT"}); empty when help is unavailable."""
    text = help_text(exe, alg) or ""
    names = set()
    for line in text.splitlines():
        m = _PARAM_ROW.match(line)
        if m:
            names.add(m.group(1))
    return names


def enum_options(exe: str, alg: str, param: str) -> list[tuple[str, str]]:
    """[(index, option text)] of enum `param`, read from `qgis_process help alg`; empty when it is not an enum."""
    inside, out = False, []
    for line in (help_text(exe, alg) or "").splitlines():
        if _PARAM_ROW.match(line):
            inside = line.startswith(param + ":")
            continue
        if inside:
            m = _ENUM_ROW.match(line)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def enum_value(exe: str, alg: str, param: str, label: str) -> str:
    """The index of option `label` of enum `param`, read from `qgis_process help alg` (cached per exe/alg).
    Falls back to the label itself when help cannot be read or does not list it."""
    for index, text in enum_options(exe, alg, param):
        if text == label:
            return index
    return label


def enum_match(exe: str, alg: str, param: str, match) -> str | None:
    """The index of the first option of enum `param` for which match(option_text) is true, else None."""
    for index, text in enum_options(exe, alg, param):
        if match(text):
            return index
    return None


def _args(exe: str, alg: str, values: dict, log) -> list[str]:
    """--NAME=value for each non-empty value whose NAME the installed algorithm's help lists.

    The candidates cover DamIT Screener / Runner 0.2.0 (WORK, DAMS, HANDOFF, OUTPUT_FOLDER, DAMS_FOLDER, DEM...) and an ND-style port
    (DAM_ID, DAMS_FOLDER, DEM, METHOD...); an algorithm gets only the ones it declares, so a renamed or missing
    parameter is skipped, never guessed. When help lists no parameters at all, every candidate is sent."""
    accepted = help_params(exe, alg)
    if not accepted:
        log(f"Could not read the parameter list of {alg}; sending every DamIT argument.")
    out = []
    for name, value in values.items():
        if value in (None, "") or (accepted and name not in accepted):
            continue
        out.append(f"--{name}={value}")
    return out


def _outputs(text: str) -> dict[str, str]:
    """NAME: value lines qgis_process prints for the results (e.g. RUN_FOLDER, CLASS, ORDINAL)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*):\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _choice(dam: dict) -> dict:
    """The desk's jurisdiction choice split into the ids the DamIT algorithms take (Appendix A codes)."""
    cls = _classification(dam) or {}
    mode = "custom" if cls.get("mode") == "custom" else "preset"
    ids = [str(m) for m in (cls.get("methods") or []) if isinstance(m, str)] if mode == "custom" else []
    return {
        "mode": mode,
        "preset": str(cls.get("preset") or "") if mode == "preset" else "",
        "preset_label": str(cls.get("preset_label") or ""),
        "scenarios": ",".join(i for i in ids if i[:1] in ("S", "D")),
        "methods": ",".join(i for i in ids if i[:1] == "M"),
        "modifiers": ",".join(i for i in ids if i[:1] == "R"),
        "advisory": bool(cls.get("apply_advisory")),
    }


def _mode_index(exe: str, alg: str, mode: str) -> str:
    found = enum_match(exe, alg, "MODE", lambda t: t.strip().lower().startswith(mode))
    return found if found is not None else mode


def _missing_alg(log, exe: str, cfg: HandoffConfig, role: str, what: str) -> None:
    alg = cfg.alg(role)
    if not alg:
        log(f"The {cfg.suite} publish no algorithm for {role}. {what} was not started.")
        return
    reason = help_failure(exe, alg) or f"qgis_process help {alg} failed"
    log(f"{reason} {what} was not started.")
    if cfg.profile == "nd":
        log(
            f"Install or enable the DWR DamSafety plugin that provides it (tools/mac/install_dwr_suite_mac.sh), or point "
            f"DamIT Desk at the published id with DAMIT_ND_ALG_{role.upper()} or the \"nd\" section of damit-handoff.json "
            "(docs/HANDOFF.md). DamIT ids are not used as a fallback."
        )
        return
    log(
        f"Install the DamIT plugin that provides it, or point DamIT Desk at the published id with "
        f"{'DAMIT_ALG_' + role.upper()} or damit-handoff.json (docs/HANDOFF.md). ND suite ids are not used as a fallback."
    )


def _no_qgis_hint() -> str:
    """Where qgis_process comes from, for the profile's plugins."""
    if desk_profile.is_nd():
        return ("Install the DWR DamSafety suite (tools/mac/install_dwr_suite_mac.sh writes ~/dwr-dam-suite/"
                "damsafety_env.sh, which the desk reads), or set DAMIT_ND_QGIS_PROCESS to a qgis_process that reads the "
                "QGIS profile with the DWR plugins.")
    return ("Install the DamIT plugins with the suite installer (install-all.sh), or set QGIS_PROCESS to its "
            "qgis-process-damit.sh (.cmd on Windows).")


def _method_key(dam: dict) -> tuple[str, str]:
    """(breach method, failure mode). A missing or unknown failure mode is piping, never overtopping (Nick, 2026-11-05)."""
    method = str(dam.get("method") or "froehlich").lower()
    if method not in ("froehlich", "macdonald", "tr60"):
        method = "froehlich"
    return method, resolved_failure_mode(dam)


def _opt_num(cmd: list[str], flag: str, value) -> None:
    if value in (None, ""):
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        return
    if not math.isfinite(number):  # NaN or ±Infinity
        return
    cmd.append(f"--{flag}={number}")


def _prepare(dam: dict, analysis: dict, work: str | None, log, files=None, append_status: bool = True):
    root = work_dir(work)
    try:
        folder, notes = write_dam_folder(root, dam, analysis or {}, append_status=append_status)
    except HandoffError as exc:
        log(str(exc))
        return None
    for note in notes:
        log(note)
    extra = write_named_files(folder, files)
    if extra:
        log("Also wrote: " + ", ".join(extra))
    log(f"Wrote {folder / 'dam.json'}")
    log("Geometries: dam line, breach point, reservoir point, downstream area, when they were drawn.")
    log("Folder layout: <work>/dams/<id>/ with dam.json, the drawn geometries, hydrograph.csv, and inputs/.")
    return root, folder


#: The app's settings folder (damit-handoff.json lives there). Set by __main__.main(); tests may set it.
SETTINGS_DIR: Path | None = None


_CONFIG_SH = re.compile(r"^\s*(?:export\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*QGIS_CUSTOM_CONFIG_PATH=(.*)$")
_CONFIG_CMD = re.compile(r'^\s*set\s+"?QGIS_CUSTOM_CONFIG_PATH=([^"\r\n]*)"?\s*$', re.IGNORECASE)


def launcher_config_path(exe: str) -> str | None:
    """The QGIS_CUSTOM_CONFIG_PATH a qgis_process launcher script sets for QGIS: the suite installer's
    qgis-process-damit.sh (`export QGIS_CUSTOM_CONFIG_PATH=...`) or .cmd (`set "QGIS_CUSTOM_CONFIG_PATH=..."`).
    None for a real qgis_process (a binary) or a script that does not set it. Read only, never run."""
    path = Path(exe)
    try:
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            return None
        head = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in head[:4096]:
        return None                                   # a binary: QGIS's own qgis_process
    found = None
    for line in head.decode("utf-8", "replace").splitlines():
        if line.lstrip().startswith(("#", "rem ", "REM ", "::")):
            continue
        m = _CONFIG_CMD.match(line)
        if m:
            found = m.group(1).strip() or None
            continue
        m = _CONFIG_SH.match(line)
        if m:
            try:
                parts = shlex.split(m.group(1), comments=True)
            except ValueError:
                parts = m.group(1).split()
            found = (parts[0] if parts else "") or None
    return found


def qgis_config_path(exe: str) -> tuple[str | None, str]:
    """(QGIS_CUSTOM_CONFIG_PATH qgis_process runs with, where it comes from). The launcher's own setting wins over the
    desk's environment, because the launcher sets it last, just before QGIS starts."""
    from_launcher = launcher_config_path(exe)
    if from_launcher:
        return from_launcher, f"set by the launcher {Path(exe).name}"
    env = os.environ.get("QGIS_CUSTOM_CONFIG_PATH")
    if env:
        return env, "from the desk's environment"
    return None, ""


CHECK_ROLES = ("preflight", "runchain", "rundam", "classify")   # the roles the Report step's buttons call
CHECK_TIMEOUT_S = 180.0


def run_check(log, cancel: threading.Event | None = None, config: HandoffConfig | None = None) -> dict:
    """'Check QGIS hand-off' (install test 2026-11-18): qgis_process is found, which QGIS profile it reads, and every
    algorithm the buttons call (DamIT defaults or damit-handoff.json overrides) is registered there
    (`qgis_process help <id>`). Runs no dam and writes nothing."""
    cfg = handoff_config(config)
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. " + _no_qgis_hint())
        return {"ok": False, "check": []}
    log(f"Profile: {'North Dakota (DWR DamSafety plugins)' if cfg.profile == 'nd' else 'United States (DamIT plugins)'}.")
    log(f"qgis_process: {exe}")
    custom, where = qgis_config_path(exe)
    log("QGIS profile it reads: " + (f"default profile under {custom} (QGIS_CUSTOM_CONFIG_PATH, {where})" if custom else
                                     "QGIS's default profile (neither the desk nor its qgis_process launcher sets "
                                     "QGIS_CUSTOM_CONFIG_PATH)"))
    if custom:
        link = Path(custom) / "profiles" / "default"
        log(f"  -> {os.path.realpath(link)}" if link.exists() else
            f"  -> {link} does not exist: the launcher's link is missing")
    for problem in cfg.problems:
        log(f"Handoff config: {problem}")
    rows = []
    for role in CHECK_ROLES:
        if not cfg.alg(role):
            continue
        if cancel is not None and cancel.is_set():
            log("Cancelled.")
            return {"ok": False, "cancelled": True, "check": rows}
        alg = cfg.alg(role)
        code, out = _run([exe, "help", alg], CHECK_TIMEOUT_S, cancel)
        found = code == 0 and alg in out
        rows.append({"role": role, "algorithm": alg, "found": found})
        where = "" if cfg.sources.get(role, "default") == "default" else f", from {cfg.sources[role]}"
        log(f"{'OK     ' if found else 'MISSING'} {alg}  ({role}{where})")
        if not found:
            for ln in [x for x in out.strip().splitlines() if x.strip()][-2:]:
                log(f"        {ln}")
    ok = all(r["found"] for r in rows)
    if ok:
        log(f"The hand-off is ready: every algorithm the buttons call is in QGIS ({cfg.suite}).")
    elif cfg.profile == "nd":
        log("Not ready: install or enable the missing DWR DamSafety plugins in that profile (DamSafety Screening for "
            "nddam:, DamSafety Runner for ndbreach:, DamSafety Hazard for ndhazard:), then check again.")
    else:
        log("Not ready: install or enable the missing DamIT plugins in that profile (DamIT Screener for damit_screen:, "
            "DamIT Runner for damit_run:, DamIT Hazard for damit:), then check again.")
    return {"ok": ok, "check": rows}


def handoff_config(config: HandoffConfig | None = None) -> HandoffConfig:
    """The resolved algorithm ids. Read for every job, so an edited damit-handoff.json applies without a restart."""
    return config if config is not None else load_config(SETTINGS_DIR)


def _log_config(log, cfg: HandoffConfig, roles: tuple[str, ...]) -> None:
    for problem in cfg.problems:
        log(f"Handoff config: {problem}")
    for role in roles:
        where = "" if cfg.sources[role] == "default" else f" (from {cfg.sources[role]})"
        log(f"{role}: {cfg.alg(role)}{where}")


def _settings_path(root: Path, log, only_ids: str | None = None, classification: dict | None = None,
                   dem: str | None = None) -> Path:
    """damit_settings.json for --SETTINGS (always written: it carries dam_ids, so the chain screens this dam only).

    dem: the DEM this run hands the screener as TERRAIN (dem_path). It also goes into the settings (terrain,
    local_dem, larger_clips 2) so every larger clip of the screening flood reads it too. Before 2026-11-20 only the
    data folder's DEM or <work>/dem.tif went there, so with a DEM typed or chosen in the desk the first clip used it
    and every larger clip downloaded USGS 3DEP afresh (Absaraka: 3 -> 6 -> 12 km of downloads, then the time limit)."""
    data = find_data_folder()
    local_dem = str(root / "dem.tif") if (root / "dem.tif").is_file() else None
    terrain = dem or data_dem(data) or local_dem
    path = write_settings(root, data, terrain, only_ids, classification)
    if data:
        log(f"Screening settings use the DamIT data folder: {data}")
    if terrain:
        log(f"Screening terrain: {terrain} (the larger clips read it too, not a USGS 3DEP download).")
    else:
        log("Screening terrain: none given, so the screener downloads USGS 3DEP for each clip.")
    return path


def _nid_stop(dam: dict, log, folder: Path, root: Path, what: str) -> dict | None:
    """Stop before qgis_process when the plugins would refuse the record (no NID ID, not new, not a sample)."""
    problem = nid_problem(dam)
    if not problem:
        return None
    log(problem)
    log(f"{what} was not started. The dam folder is written.")
    return {"ok": False, "stopped": True, "nidProblem": problem, "folder": str(folder), "work": str(root)}


def _log_ids(dam: dict, log) -> None:
    ids = handoff_ids(dam)
    if ids["nid_id"]:
        return
    if ids["is_sample"]:
        log(f"{ids['dam_id']} is a built-in desk example, not an NID dam: handed off as a sample (is_sample) with no NID ID.")
    elif ids["is_new"]:
        log(f"{ids['dam_id']} is a new (proposed) dam with no NID ID: handed off with is_new.")


def run_folder(dam: dict, analysis: dict, work: str | None, log, files=None) -> dict:
    # A plain folder export does not run a screening, so it does not append a screened status entry;
    # repeated exports of the same dam would otherwise keep growing the status list.
    prepared = _prepare(dam or {}, analysis or {}, work, log, files, append_status=False)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    log("The dam folder is written. No model was started.")
    return {"ok": True, "stopped": False, "folder": str(folder), "work": str(root)}


def run_layers(dam: dict, work: str | None, source: str, log) -> dict:
    root = work_dir(work)
    if source == "download":
        result = download_aoi(root, dam or {}, log)
    else:
        result = use_data_folder(root, log)
    result["work"] = str(root)
    result.setdefault("folder", "")
    return result


def chain_names(root: Path, dam_id: str) -> list[str]:
    """The dam_id(s) the screening's dam step gave this dam in <work>/1_dams.gpkg, matched on its dam_id or nid_id.

    The desk sends the NID id (e.g. ND00199); a screening that joins a state inventory may name the dam by that
    inventory's id, and every later output uses that name. The DamIT plugins now take NID dams only (dam_id = NID
    ID), so a name other than the NID ID is reported, never used in its place. Empty before the first run, and empty
    when the screener writes no 1_dams.gpkg."""
    path = Path(root) / "1_dams.gpkg"
    want = str(dam_id or "").strip().upper()
    if not want or not path.is_file():
        return []
    found: list[str] = []
    try:
        # quote the path: a '?' or '#' in a work-folder name would otherwise be read as the URI's query/fragment.
        con = sqlite3.connect(f"file:{quote(path.as_posix())}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        tables = [r[0] for r in con.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")]
        for table in tables:
            quoted = '"' + str(table).replace('"', '""') + '"'
            cols = {str(r[1]).lower() for r in con.execute(f"PRAGMA table_info({quoted})")}
            if "dam_id" not in cols:
                continue
            where = "UPPER(TRIM(dam_id)) = ?" + (" OR UPPER(TRIM(nid_id)) = ?" if "nid_id" in cols else "")
            args = (want, want) if "nid_id" in cols else (want,)
            for (name,) in con.execute(f"SELECT dam_id FROM {quoted} WHERE {where}", args):
                if name and str(name) not in found:
                    found.append(str(name))
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return found


def chain_results(root: Path, names: list[str]) -> list[dict]:
    """This dam's rows of <work>/10_reports/summary.csv (the screening's report step), by the chain's dam_id."""
    path = Path(root) / "10_reports" / "summary.csv"
    want = {str(n).strip().upper() for n in names if str(n).strip()}
    if not want or not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return [row for row in csv.DictReader(fh) if str(row.get("dam_id") or "").strip().upper() in want]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _result_line(row: dict) -> str:
    cls = row.get("hz_class") or "no class"
    existing = row.get("haz_existing") or "none on record"
    text = f"Screening result for {row.get('dam_id')}: {cls} (class of record: {existing}"
    if row.get("hz_vs_existing"):
        text += f"; {row['hz_vs_existing']}"
    if row.get("hz_conf"):
        text += f"; confidence {row['hz_conf']}"
    text += ")."
    if row.get("review"):
        text += f" Review: {row['review']}."
    return (
        text
        + " A suggested screening result, not an official class; the engineer of record and the regulating agency"
        " decide. The DamIT Desk record is not changed."
    )


def _classification(dam: dict) -> dict | None:
    """The desk's jurisdiction choice, checked and normalised as dam.json carries it (see classification_block)."""
    return classification_block(dam)


def handoff_package(root: Path, dam_id: str) -> Path:
    """Where DamIT Screener's runchain / handoff writes this dam's package: <work>/handoff/<dam>/damit_handoff.json."""
    return Path(root) / "handoff" / safe_name(dam_id) / "damit_handoff.json"


def read_package_screening(path: Path) -> dict | None:
    """The `screening` block of a damit_handoff.json (preliminary suggestion, flags), or None."""
    try:
        pkg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    block = pkg.get("screening") if isinstance(pkg, dict) else None
    return block if isinstance(block, dict) else None


def flag_text(flag) -> str:
    """One screening flag in words: its message (and receptor), never a raw Python dict."""
    if isinstance(flag, dict):
        msg = str(flag.get("message") or flag.get("detail") or flag.get("code") or "flag").strip().rstrip(".")
        rec = flag.get("receptor")
        return f"{msg} ({rec})" if rec and str(rec) not in msg else msg
    return str(flag)


def _package_line(dam_id: str, block: dict) -> str:
    label = block.get("suggested_label")
    if not label:
        text = f"Screening package for {dam_id}: no preliminary class ({block.get('status') or 'not computed'})."
    else:
        text = f"Screening package for {dam_id}: preliminary {label}"
        if block.get("suggested_ordinal") is not None:
            text += f" (ordinal {block['suggested_ordinal']})"
        text += "."
    flags = block.get("flags")
    if isinstance(flags, list) and flags:
        # The chain repeats a flag once per scenario (Absaraka: the same 3 receptors twice): each one once here.
        words = list(dict.fromkeys(flag_text(f) for f in flags))
        text += " Flags: " + "; ".join(words[:6]) + "."
        if len(words) > 6:
            text += f" (+{len(words) - 6} more in the package)"
    return text + " A screening suggestion, not an official hazard classification."


def screening_receptors(folder: Path, dam: dict, dam_id: str, receptors=None) -> tuple[Path | None, int]:
    """<dam folder>/screen_inputs/receptors.geojson: the desk's structures as one point layer (EPSG:4326) for the
    screening chain's RECEPTORS (dam_id, receptor_type, structure_type, habitable, occupants, source). (None, 0) when there
    are none. Roads, rail and the other layers are for damit:classify only."""
    pts = structure_points(dam, receptors)
    if not pts:
        return None, 0
    feats = []
    for i, (xy, props) in enumerate(pts):
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [xy[0], xy[1]]}, "properties": {
            "id": str(props.get("crest_id") or props.get("id") or f"s{i + 1}"), "dam_id": dam_id,
            "receptor_type": "structure", "structure_type": props.get("type") or "home",
            "habitable": props.get("habitable") if isinstance(props.get("habitable"), bool) else None,
            "occupants": props.get("occupants"), "name": props.get("name"),
            # where the structure came from ("nd911" = an ND 911 address point): DamIT Hazard's chart plots only 911
            # points and structures an engineer reviewed habitable
            "source": props.get("source"), "source_ref": props.get("source_ref")}})
    out = Path(folder) / "screen_inputs"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "receptors.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "name": "damit_screen_receptors",
                                "features": feats}) + "\n", encoding="utf-8")
    return path, len(feats)


def run_screening(
    dam: dict,
    analysis: dict,
    work: str | None,
    log,
    files=None,
    timeout: float | None = None,
    cancel: threading.Event | None = None,
    config: HandoffConfig | None = None,
    receptors=None,
) -> dict:
    """The preflight algorithm, then the screening chain for this dam only if the preflight is READY.

    receptors: the desk's classify-receptors payload (or None: the record's mapped seeds). The structures go to the
    chain as one point layer (RECEPTORS), so DamIT Screener's 2D screening flood can sample them and suggest a
    preliminary class.

    timeout: seconds for the chain (else DAMIT_SCREENING_TIMEOUT_S, else no limit). cancel: an Event;
    setting it stops qgis_process. After the chain the dam's hand-off package (DamIT Screener) or its
    10_reports/summary.csv row (an ND-style port) is read back into the log and the result."""
    cfg = handoff_config(config)
    preflight_alg, chain_alg = cfg.alg("preflight"), cfg.alg("runchain")
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    stop = _nid_stop(dam, log, folder, root, "The screening")
    if stop:
        return stop
    _log_ids(dam, log)
    dam_id = handoff_ids(dam)["dam_id"]
    _log_config(log, cfg, ("preflight", "runchain"))
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The screening chain was not started.")
        log(_no_qgis_hint())
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, preflight_alg):
        _missing_alg(log, exe, cfg, "preflight", "The screening")
        return {"ok": False, "stopped": True, "missingAlgorithm": preflight_alg, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, chain_alg):
        _missing_alg(log, exe, cfg, "runchain", "The screening")
        return {"ok": False, "stopped": True, "missingAlgorithm": chain_alg, "folder": str(folder), "work": str(root)}
    report = root / "preflight.txt"
    has_id = bool(dam.get("nid") or dam.get("nidId") or dam.get("id"))
    # only_ids is the NID ID alone (or the record id of a new dam / sample): never another inventory's id for it.
    only = dam_id if has_id else None
    if has_id and cfg.profile == "nd":
        # The DWR screening names a dam in the DWR layer by its DWR id (ND00199 is DWR-2801 in 1_dams.gpkg and every
        # later output). A work folder that already ran the chain knows that name, so it goes in only_ids too, as the
        # old dwr_crest desk did: a screening that filters later steps by dam_id alone keeps the dam.
        known = [n for n in chain_names(root, dam_id) if n.upper() != dam_id.upper()]
        only = ",".join([dam_id, *known])
    dem = dem_path(root, dam, "data")
    settings = _settings_path(root, log, only, _classification(dam), dem)
    point = write_dam_point(folder, dam, analysis or {})
    if point:
        log(f"Wrote {point} (this dam as a point layer for DAMS; DamIT field names, EPSG:4326).")
    else:
        log("The dam has no position (breach point, reservoir point or lon/lat), so no DAMS layer was written.")
    choice = _choice(dam)
    rec_layer, rec_count = screening_receptors(folder, dam, dam_id, receptors)
    if rec_layer:
        log(f"Wrote {rec_layer} ({rec_count} structure point(s) for RECEPTORS: the 2D screening flood samples them).")
    else:
        log("No structure receptors to send: the screening flood runs, but the preliminary class has no receptors.")

    def common(alg: str) -> dict:
        return {
            "WORK": str(root),
            "DAMS": str(point) if point else None,
            "MODE": _mode_index(exe, alg, choice["mode"]),
            "PRESET": choice["preset"],
            "SCENARIOS": choice["scenarios"],
            "METHODS": choice["methods"],
            "TERRAIN": dem,
            "RECEPTORS": str(rec_layer) if rec_layer else None,
            "APPLY_ADVISORIES": "true" if choice["advisory"] else None,
            "SETTINGS": str(settings),
        }

    limit = screening_timeout(timeout)
    jur = f"preset {choice['preset']}" if choice["preset"] else choice["mode"]
    log(f"Jurisdiction: {jur}"
        + (f", methods {choice['methods']}" if choice["methods"] else "") + ".")
    log(f"Preflight: {exe} run {preflight_alg}")
    code, text = _run_logged(
        [exe, "run", preflight_alg, *_args(exe, preflight_alg, {**common(preflight_alg), "REPORT": str(report)}, log)],
        log,
        timeout=180,
        cancel=cancel,
    )
    if code == STOPPED_CANCEL:
        log(f"Cancelled. {chain_alg} was not started.")
        return {"ok": False, "stopped": True, "cancelled": True, "folder": str(folder), "work": str(root)}
    report_text = ""
    if report.is_file():
        report_text = report.read_text(encoding="utf-8", errors="replace")
    if report_text.strip() and report_text.strip() not in text:
        log(report_text.rstrip())
    ready = _ready(text + "\n" + report_text)
    if code != 0 or ready is not True:
        if ready is None and code == 0:
            log("Could not read READY from the preflight output.")
        log(f"Preflight did not pass. {chain_alg} was not started.")
        log("A new DamITDams folder fails here until the screening has its catalog preset, DEM and layers. That stop is intended.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    chain_log = root / "chain_log.txt"
    log(f"Preflight passed. Starting {chain_alg} for {only or dam_id}.")
    if limit:
        log(f"The chain stops after {limit:g} s (DAMIT_SCREENING_TIMEOUT_S or the request's timeout).")
    chain_values = {
        **common(chain_alg),
        "DAM_ID": only or dam_id,
        "PREFLIGHT": "true",
        "FAIL_ON_ERROR": "true",
        "LOG": str(chain_log),
    }
    # DamIT Screener's 2D screening flood keeps its maxima (partial) at 0.8 x DAMIT_SCREENING_TIMEOUT_S, so the
    # chain finishes inside the limit with a preliminary class instead of being stopped
    chain_env = {**os.environ, "DAMIT_SCREENING_TIMEOUT_S": f"{limit:g}"} if limit else None
    started = time.time()
    code, text = _run_logged([exe, "run", chain_alg, *_args(exe, chain_alg, chain_values, log)], log, timeout=limit,
                             cancel=cancel, env=chain_env)
    if chain_log.is_file():
        written = chain_log.read_text(encoding="utf-8", errors="replace").rstrip()
        if written and written not in text:
            log(written)
    found = chain_names(root, dam_id) if has_id else []
    names = [n for n in found if n.upper() == dam_id.upper()]
    other = [n for n in found if n.upper() != dam_id.upper()]
    if other and cfg.profile == "nd":
        # The DWR suite's own name for the dam (its DWR id): read its results under that name.
        names = found
        log(f"The screening outputs name this dam {', '.join(other)} (desk: {dam_id}), the DWR layer's id for it.")
    elif other:
        log(f"The screening outputs also name this dam {', '.join(other)}, which is not its NID ID {dam_id}. "
            "DamIT Desk reads results by the NID ID only; check the screener's dam inventory is the NID.")
    out = {"folder": str(folder), "work": str(root), "chainIds": names}
    if code == STOPPED_CANCEL:
        log("The screening chain was stopped. Its outputs so far stay in the work folder; chain_log.txt has the steps that ran.")
        return {**out, "ok": False, "stopped": True, "cancelled": True, "timedOut": False}
    # A flood stopped by its time limit is a PARTIAL result. DamIT Screener 0.3.7 (damit #146) finishes the chain OK
    # and marks it partial (partial=true, partial_reason=time_limit); 0.3.5-0.3.6 failed the chain with "did not run".
    # Either way this run's package and steps.json say so, so this is checked after a successful chain too.
    partial = screening_partial(root, folder, dam_id, started, desk_timeout=code == STOPPED_TIMEOUT)
    if partial is not None:
        return _partial_result(out, partial, dam_id, log, chain_failed=code != 0)
    if code == STOPPED_TIMEOUT:
        log("The screening chain was stopped at its time limit before it wrote a preliminary result. Its outputs so "
            "far stay in the work folder; chain_log.txt has the steps that ran. Raise DAMIT_SCREENING_TIMEOUT_S, or "
            "give the screening a local DEM so its larger clips do not download USGS 3DEP.")
        return {**out, "ok": False, "stopped": True, "cancelled": False, "timedOut": True}
    if code != 0:
        log("The screening chain failed. The flood model was not started.")
        return {**out, "ok": False, "stopped": True}
    package = handoff_package(root, dam_id)
    screening = read_package_screening(package) if package.is_file() else None
    if screening is not None:
        out["handoff"] = str(package)
        out["screening"] = screening
        log(f"Hand-off package: {package}")
        log(_package_line(dam_id, screening))
    rows = chain_results(root, names if cfg.profile == "nd" and names else [dam_id])
    for row in rows:
        log(_result_line(row))
    if not rows and screening is None:
        log("No hand-off package and no 10_reports/summary.csv row for this dam (the chain plan may not include them).")
    log("Screening chain finished.")
    return {**out, "ok": True, "stopped": False, "chainResult": rows}



def _fresh_json(path: Path, since: float) -> dict | None:
    """A JSON object written at or after `since` (this run), else None: an older run's file is never read as this one's."""
    try:
        if not path.is_file() or path.stat().st_mtime < since - 2:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def screening_partial(root: Path, folder: Path, dam_id: str, since: float, desk_timeout: bool = False) -> dict | None:
    """A screening whose 2D flood stopped at its time limit but still wrote this run's hand-off package.

    DamIT Screener keeps its 2D flood's maxima when the flood reaches 0.8 x DAMIT_SCREENING_TIMEOUT_S and marks the
    engine2d step GAP ("partial: time limit"). Screener 0.3.7+ (damit #146) also sets partial=true /
    partial_reason=time_limit on the step and on the package's engine2d gap, and finishes the chain OK; 0.3.5-0.3.6
    failed the chain (FAIL_ON_ERROR) saying the flood "did not run". Its maxima so far are a lower bound. Returns
    {"screening", "handoff", "flood", "otherGaps"} when this run's package exists and the flood timed out (or the
    desk itself stopped the chain at its limit), else None. Same reading as DamIT Crest (damit #146)."""
    package = handoff_package(root, dam_id)
    pkg = _fresh_json(package, since)
    if pkg is None:
        return None
    # The package may have no preliminary class (no receptors were screened, so the suggestion was not computed):
    # the time-limited flood is still a partial result, with its figures and rasters, just no class.
    screening = pkg.get("screening") if isinstance(pkg.get("screening"), dict) else {}
    steps = _fresh_json(Path(folder) / "steps.json", since) or {}
    engine = steps.get("engine2d") if isinstance(steps.get("engine2d"), dict) else {}
    stats = engine.get("stats") if isinstance(engine.get("stats"), dict) else {}
    gaps = [g for g in (pkg.get("gaps") or []) if isinstance(g, dict)]
    flood_gap = next((g for g in gaps if g.get("step") == "engine2d"), None)
    timed_out = (bool(engine.get("partial")) or bool((flood_gap or {}).get("partial")) or bool(stats.get("timed_out"))
                 or "time limit" in str((flood_gap or {}).get("detail") or ""))
    if not (timed_out or desk_timeout):
        return None
    flood = {"timedOut": timed_out, "detail": engine.get("detail") or (flood_gap or {}).get("detail") or "",
             "acres": stats.get("flooded_acres"), "maxDepthFt": stats.get("max_depth_ft"),
             "simHours": stats.get("sim_time_hr"), "runSeconds": stats.get("run_s"), "edge": stats.get("edge_flag"),
             "rasters": {k: v for k, v in (engine.get("rasters") or {}).items() if isinstance(v, str) and Path(v).is_file()}
             if isinstance(engine.get("rasters"), dict) else {}}
    return {"screening": screening, "handoff": str(package), "flood": flood,
            "otherGaps": [g for g in gaps if g.get("step") != "engine2d"]}


def _partial_result(out: dict, partial: dict, dam_id: str, log, chain_failed: bool = True) -> dict:
    flood = partial["flood"]
    label = partial["screening"].get("suggested_label")
    bits = []
    if flood.get("acres") is not None:
        bits.append(f"{flood['acres']:,} ac")
    if flood.get("maxDepthFt") is not None:
        bits.append(f"max {flood['maxDepthFt']} ft")
    if flood.get("simHours") is not None:
        bits.append(f"{flood['simHours']} h of model time")
    if flood.get("runSeconds") is not None:
        bits.append(f"stopped after {float(flood['runSeconds']) / 60:.0f} min")
    if label:
        warning = (f"PARTIAL SCREENING: the screening flood reached its time limit ({', '.join(bits) or 'no figures'}), "
                   f"so the preliminary class {label} rests on a flood that had not finished spreading. It is a lower "
                   "bound for review, not a result to rely on.")
    else:
        warning = (f"PARTIAL SCREENING: the screening flood reached its time limit ({', '.join(bits) or 'no figures'}). "
                   "Its depths and wet area so far are a lower bound for review, and there is no preliminary class "
                   "(the screener computed no suggestion for this run). Use Classify on a finished flood for the class.")
    log("")
    log(warning)
    if chain_failed:
        log("The screener's chain says the flood \"did not run\" and fails because of the time limit (FAIL_ON_ERROR, "
            "DamIT Screener 0.3.5-0.3.6). The flood did run; its maxima so far are kept" +
            (", and the hand-off package below has the preliminary class." if label else "."))
    else:
        log("The screener marked the flood PARTIAL (time limit) and finished the chain; its maxima so far are kept" +
            (", and the hand-off package below has the preliminary class." if label else "."))
    for name, path in (flood.get("rasters") or {}).items():
        log(f"Partial screening raster ({name}): {path}")
    if flood.get("edge"):
        log("The flood also reached the edge of its terrain, so it is cut off there as well.")
    for gap in partial.get("otherGaps") or []:
        log(f"Also a gap in the {gap.get('step')} step: {gap.get('detail')}")
    log(f"Hand-off package: {partial['handoff']}")
    log(_package_line(dam_id, partial["screening"]))
    log("Raise DAMIT_SCREENING_TIMEOUT_S, or run the flood model (LISFLOOD-FP) for a finished flood.")
    log("Screening chain finished with a PARTIAL (preliminary) result.")
    return {**out, "ok": True, "partial": True, "stopped": False, "timedOut": True, "warning": warning,
            "handoff": partial["handoff"], "screening": partial["screening"], "flood": flood, "chainResult": []}


def _dam_line_layer(folder: Path) -> Path | None:
    """The drawn dam line write_dam_folder wrote (longitude / latitude GeoJSON), or None."""
    path = Path(folder) / "dam_line.geojson"
    return path if path.is_file() else None


def run_model(
    dam: dict,
    analysis: dict,
    work: str | None,
    log,
    model: str = "lisflood",
    files=None,
    source: str = "data",
    cancel: threading.Event | None = None,
    config: HandoffConfig | None = None,
) -> dict:
    """The flood model for ONE dam: the DamIT runner CLI when the DEM-coordinate point is filled, else the rundam
    algorithm through qgis_process (with this dam's hand-off package when the screening wrote one). Never batch."""
    cfg = handoff_config(config)
    rundam = cfg.alg("rundam")
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    stop = _nid_stop(dam, log, folder, root, "The flood model")
    if stop:
        return stop
    if _method_key(dam)[0] == "tr60":
        # Absaraka audit: the desk's height-multiple width (2H piping / 3H overtopping) is a screening opening; the
        # Runner's TR-60 is the NRCS 1,100*Br^1.35 peak (at 110 ft and 5,000 ac-ft about 4x the desk's peak). Handing
        # one off as the other would run a different breach without saying so, so the hand-off refuses it.
        log(
            "Not started: this record uses the desk's height-multiple width (2H piping, 3H overtopping), a screening "
            "opening. The Runner's TR-60 is the NRCS peak discharge, a different breach. Choose Froehlich 2008 or "
            "MacDonald for the flood model run."
        )
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    _log_ids(dam, log)
    dams = root / "dams"
    ids = handoff_ids(dam)
    dam_id = ids["dam_id"]
    label, cli_tier, builtin = model_choice(model)
    dem = dem_path(root, dam, source)
    point = _dem_point(dam)
    datum = (analysis or {}).get("datum") if isinstance((analysis or {}).get("datum"), dict) else {}
    key = _method_key(dam)
    _log_config(log, cfg, ("rundam",))
    log(f"Flood model: {label}" + (" with the built-in screening engine (not LISFLOOD-FP)." if builtin else "."))
    log(f"Failure mode: {key[1]}" + (" (the default; none was chosen)" if not dam.get("failureMode") else "") + ".")
    log(f"{cfg.alg('batch')} was not started. Batch runs many dams; this button runs one dam.")
    cli = find_damit_cli(cfg)
    if cli and point:
        if not dem:
            _no_dem(log)
            return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
        config_json = {
            "dem": {"path": dem, "z_units": "auto"},
            "dam": {
                "dam_id": dam_id,
                "name": dam.get("name"),
                "dam_height_ft": dam.get("heightFt"),
                "storage_top_acft": dam.get("storageAcFt"),
                "top_of_dam_ft": datum.get("crestNavdFt"),
                "point": point,
            },
            "breach": {"method": CLI_METHOD[key], "failure_mode": key[1]},
            "model": {"tier": cli_tier, **({"lisflood_exe": "builtin"} if builtin else {})},
            "output": {"folder": str(dams)},
        }
        cls = _classification(dam)
        if cls and cfg.profile != "nd":
            config_json["classification"] = cls
        if cfg.profile == "nd":
            # ndbreach_cli.py checks every key and knows neither (the old dwr_crest desk sent neither).
            config_json["breach"].pop("failure_mode", None)
        line = _dam_line_layer(folder)
        if line:
            config_json["dam"]["dam_line"] = str(line)
        path = folder / "runner_config.json"
        path.write_text(json.dumps(config_json, indent=2) + "\n", encoding="utf-8")
        log(f"One dam, no QGIS window: {cli} run")
        log("The point is the DEM-coordinate pair from the export fields, not longitude and latitude.")
        code, text = _run_logged([_python_for(cli), cli, "run", str(path)], log, timeout=None, cancel=cancel)
        log("Runner finished." if code == 0 else "The runner failed.")
        return {"ok": code == 0, "stopped": code != 0, "folder": str(folder), "work": str(root)}
    if cli and not point:
        log(f"{Path(cli).name} needs the dam point in the DEM's coordinates. Longitude and latitude were not sent as that point.")
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The flood model was not started.")
        if not point:
            log("Enter both Point X and Point Y (DEM CRS) on the export panel to use the "
                + ("DWR runner CLI (ndbreach_cli.py)" if cfg.profile == "nd" else "DamIT runner CLI") + " instead.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, rundam):
        _missing_alg(log, exe, cfg, "rundam", "The flood model")
        return {"ok": False, "stopped": True, "missingAlgorithm": rundam, "folder": str(folder), "work": str(root)}
    accepted = help_params(exe, rundam)
    if not dem and (not accepted or "DEM" in accepted):
        _no_dem(log)
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not dem:
        log(f"No DEM: {rundam} records the terrain as a gap in the run folder.")
    package = handoff_package(root, dam_id)
    hydro = folder / "inputs" / "breach_hydrograph.csv"
    choice = _choice(dam)
    lonlat = _lonlat(dam)
    if model == "hecras":
        log(f"HEC-RAS 2D is not run by {rundam} (DamIT never starts HEC-RAS or Wine). Choose LISFLOOD-FP, ANUGA or "
            "the built-in engine. The flood model was not started.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    model_settings = runner_settings(dam)
    log("Runner settings: CELL {CELL:g} m, MAX_RUNS {MAX_RUNS}, DURATION_HR {DURATION_HR:g} (0 = automatic), "
        "DURATION_MAX_HR {DURATION_MAX_HR:g} ({how}).".format(how=model_settings["how"], **{
            k: model_settings[k] for k in ("CELL", "MAX_RUNS", "DURATION_HR", "DURATION_MAX_HR")}))
    values = {
        # DamIT Runner 0.2.0 (damit_run:rundam): the screener's package when there is one, else the dam as parameters.
        "HANDOFF": str(package) if package.is_file() else None,
        "DAM_ID": dam_id,
        # Runner with the NID-ID rule: the NID ID, or why there is none (a new / proposed dam, a desk sample).
        "NID_ID": ids["nid_id"],
        "IS_NEW": "true" if ids["is_new"] else None,
        "IS_SAMPLE": "true" if ids["is_sample"] else None,
        "X": lonlat[0] if lonlat else None,
        "Y": lonlat[1] if lonlat else None,
        "CRS": "EPSG:4326" if lonlat else None,
        "MODE": _mode_index(exe, rundam, choice["mode"]) if "MODE" in accepted else None,
        "PRESET": choice["preset"],
        "SCENARIOS": choice["scenarios"],
        "METHODS": choice["methods"],
        "TERRAIN": dem,
        "HYDROGRAPH": str(hydro) if hydro.is_file() else None,
        "OUTPUT_FOLDER": str(root / "runs"),
        # 0.2.0: the Runner launches the model, as ndbreach:rundam did for the original Crest
        "DRY_RUN": "false",
        # the DamSafety Runner's parameters (DamIT Runner 0.2.0, or an ND-style port)
        "DAMS_FOLDER": str(dams),
        "DEM": dem,
        "METHOD": enum_value(exe, rundam, "METHOD", METHOD_LABEL[key]) if "METHOD" in accepted else None,
        "TIER": enum_value(exe, rundam, "TIER", label) if "TIER" in accepted else None,
        "LISFLOOD_EXE": "builtin" if builtin else model_settings["LISFLOOD_EXE"],
        # the DamSafety Runner's run knobs, with its defaults unless the dam record or the environment sets them
        "CELL": model_settings["CELL"],
        "MAX_RUNS": model_settings["MAX_RUNS"],
        "DURATION_HR": model_settings["DURATION_HR"],
        "DURATION_MAX_HR": model_settings["DURATION_MAX_HR"],
        "HEIGHT_FT": _finite(dam.get("heightFt")),
        "STORAGE_ACFT": _finite(dam.get("storageAcFt")),
        "TOP_FT": _finite(datum.get("crestNavdFt")),
        "AREA_AC": _finite(dam.get("surfaceAreaAc")),
        "DAM_LINES": str(line) if (line := _dam_line_layer(folder)) else None,
    }
    if "OUTPUT_FOLDER" in accepted:
        (root / "runs").mkdir(exist_ok=True)
    if values["HANDOFF"]:
        log(f"Hand-off package: {package}")
    cmd = [exe, "run", rundam, *_args(exe, rundam, values, log)]
    log(f"This button runs {rundam} for one dam.")
    if values.get("DAM_LINES"):
        log("Dam line sent as DAM_LINES (" + Path(values["DAM_LINES"]).name + "). It is longitude and latitude; "
            "the Runner reprojects it to the DEM so the toe band can be placed "
            "(5 m out to H×(slope+1), 3:1 when the slope is unknown, 150 m cap, with the side check).")
    else:
        log("No drawn dam line was written, so DAM_LINES was not sent. The Runner will look in the dam folder, "
            "or fall back to the lowest ground within 150 m of the dam point.")
    if builtin:
        log("LISFLOOD_EXE=builtin: the built-in numpy engine (a screening approximation, not LISFLOOD-FP).")
    elif model_settings["LISFLOOD_EXE"]:
        log(f"LISFLOOD_EXE={model_settings['LISFLOOD_EXE']} ({model_settings['exe_how']}).")
    else:
        log("LISFLOOD_EXE empty: the runner looks for an installed LISFLOOD-FP (its provider setting, PATH, the usual "
            "install places) and runs the built-in engine with a warning when there is none.")
    code, text = _run_logged(cmd, log, timeout=None, cancel=cancel)
    results = _outputs(text)
    out = {"ok": code == 0, "stopped": code != 0, "folder": str(folder), "work": str(root)}
    if results.get("RUN_FOLDER"):
        out["runFolder"] = results["RUN_FOLDER"]
        log(f"Run folder: {results['RUN_FOLDER']} (status {results.get('STATUS') or 'unknown'}).")
    launched = str(results.get("MODEL_LAUNCHED") or "").strip().lower() in ("true", "1")
    out["modelLaunched"] = launched
    for key, name in (("depthRaster", "Depth (Max).tif"), ("velocityRaster", "Velocity (Max).tif"),
                      ("hmaxRaster", "hmax_ft.tif"), ("floodPolygons", "Flood Polygons (Max Depth).geojson")):
        path = folder / name
        if code == 0 and path.is_file():
            out[key] = str(path)
    if results.get("ENGINE_USED"):
        out["engine"] = results["ENGINE_USED"]
    if code == 0 and launched:
        log(f"Model rasters in the dam folder: {', '.join(Path(out[k]).name for k in ('depthRaster', 'velocityRaster', 'hmaxRaster', 'floodPolygons') if k in out) or 'none'}.")
    elif code == 0:
        log(f"{rundam} did not launch a model (it prepared and recorded the run only).")
    log("Runner finished." if code == 0 else "The runner failed.")
    return out


# The DamSafety Runner's defaults (DWR_Plugins main, DamSafety Runner algorithms.py RunDamAlgorithm): CELL 10 m,
# MAX_RUNS 6, DURATION_HR 0 (automatic), DURATION_MAX_HR 96. A dam record's lisflood box (cellSizeM, maxRuns,
# durationHr, durationMaxHr, exe) wins, then the environment (DAMIT_RUN_CELL, DAMIT_RUN_MAX_RUNS,
# DAMIT_RUN_DURATION_HR, DAMIT_RUN_DURATION_MAX_HR, LISFLOOD_EXE / DAMIT_LISFLOOD_EXE).
RUNNER_DEFAULTS = {"CELL": 10.0, "MAX_RUNS": 6, "DURATION_HR": 0.0, "DURATION_MAX_HR": 96.0}
RUNNER_KEYS = {"CELL": ("cellSizeM", "DAMIT_RUN_CELL"), "MAX_RUNS": ("maxRuns", "DAMIT_RUN_MAX_RUNS"),
               "DURATION_HR": ("durationHr", "DAMIT_RUN_DURATION_HR"),
               "DURATION_MAX_HR": ("durationMaxHr", "DAMIT_RUN_DURATION_MAX_HR")}


def runner_settings(dam: dict, environ=None) -> dict:
    """CELL, MAX_RUNS, DURATION_HR, DURATION_MAX_HR and LISFLOOD_EXE for damit_run:rundam (see RUNNER_DEFAULTS)."""
    env = os.environ if environ is None else environ
    box = dam.get("lisflood") if isinstance(dam.get("lisflood"), dict) else {}
    out, how = {}, []
    for name, (field, var) in RUNNER_KEYS.items():
        v, src = _finite(box.get(field)), "dam record"
        if v is None or v < 0:
            v, src = _finite(env.get(var)), var
        if v is None or v < 0 or (name in ("CELL", "MAX_RUNS", "DURATION_MAX_HR") and v <= 0):
            v, src = RUNNER_DEFAULTS[name], "DamSafety default"
        out[name] = int(v) if name == "MAX_RUNS" else float(v)
        if src != "DamSafety default":
            how.append(f"{name} from {src}")
    exe, exe_how = None, ""
    for v, src in ((box.get("exe"), "dam record"), (env.get("DAMIT_LISFLOOD_EXE"), "DAMIT_LISFLOOD_EXE"),
                   (env.get("LISFLOOD_EXE"), "LISFLOOD_EXE")):
        if isinstance(v, str) and v.strip():
            exe, exe_how = v.strip(), f"from {src}"
            break
    out["LISFLOOD_EXE"] = exe
    out["exe_how"] = exe_how
    out["how"] = "; ".join(how) if how else "DamSafety Runner defaults"
    return out


def _no_dem(log) -> None:
    log("No DEM, so the flood model was not started. The dam folder above was still written.")
    log("Type a DEM path, choose Get layers (download for this area, or the DamIT data folder), or set DAMIT_DEM.")
    log("The built-in engine is still a raster model. It is not the desk's schematic flood, and it also needs a DEM.")


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _lonlat(dam: dict) -> tuple[float, float] | None:
    lon, lat = _finite(dam.get("lon")), _finite(dam.get("lat"))
    return (lon, lat) if lon is not None and lat is not None else None


def _file(value) -> str | None:
    """An existing file path (any kind), resolved, or None."""
    return _raster(value)


def _raster(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    return str(path.resolve()) if path.is_file() else None


def _preset_index(exe: str, alg: str, choice: dict) -> str | None:
    """damit:classify's PRESET is an enum (0 = custom, then the catalog presets by label)."""
    options = enum_options(exe, alg, "PRESET")
    if not options:
        return choice["preset"] or None
    if choice["mode"] == "custom":
        return next((i for i, t in options if t.strip().lower().startswith("custom")), None)
    label, pid = choice["preset_label"], choice["preset"]
    for index, text in options:
        if label and (text == label or text.startswith(label + " (")):
            return index
    for index, text in options:
        if text == pid or text.startswith(pid + " ") or text.startswith(pid + ":"):
            return index
    return None


#: damit:classify's optional rasters besides DEPTH (dam keys the server fills from the job's fields).
EXTRA_RASTERS = (("VELOCITY", "velocityRaster"), ("DV", "dvRaster"), ("WSE", "wseRaster"),
                 ("NONBREACH", "nonbreachRaster"), ("ARRIVAL", "arrivalRaster"))


#: ndhazard:classify's optional flood rasters, from the desk's raster fields (its names differ from damit:classify's).
ND_EXTRA_RASTERS = (("VELOCITY", "velocityRaster"), ("DXV", "dvRaster"), ("BASE_DEPTH", "nonbreachRaster"),
                    ("ARRIVAL", "arrivalRaster"))


def _run_classify_nd(dam: dict, folder: Path, cfg: HandoffConfig, log, base: dict,
                     cancel: threading.Event | None = None) -> dict:
    """North Dakota profile: DamSafety Hazard's ndhazard:classify on the dam folder and the flood model's rasters.

    It reads the dam project folder (DAM_FOLDER) and gathers the structures itself (NSI and the ND GIS Hub address
    points, roads, rail), so the desk's receptor layers and jurisdiction choice are not sent: it gives the ND class and
    the ACER TM 11 class. A suggested class, as with damit:classify.

    Its receptor layers (outputs/Classification: Habitable_Structures.gpkg, Roads_Inundated.gpkg, Rail_Inundated.gpkg)
    are read back (classify_receptors.nd_summary) so the receptor list, map layer, report table and "needs ruling"
    flag show the ND run the same way they show a damit:classify one."""
    alg = cfg.alg("classify")
    _log_config(log, cfg, ("classify",))
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The classification was not started. " + _no_qgis_hint())
        return {**base, "ok": False, "stopped": True}
    if not algorithm_available(exe, alg):
        _missing_alg(log, exe, cfg, "classify", "The classification")
        return {**base, "ok": False, "stopped": True, "missingAlgorithm": alg}
    depth = _raster(dam.get("depthRaster"))
    from_folder = False
    if not depth:
        depth = _raster(str(folder / "Depth (Max).tif"))
        from_folder = bool(depth)
    if not depth:
        log(f"{alg} needs the maximum depth raster of a flood model run. Run the flood model, or type its path under "
            "Depth raster; nothing was classified.")
        return {**base, "ok": False, "stopped": True, "noDepth": True}
    if from_folder:
        log(f"Depth raster: {depth} (the flood model's Depth (Max) in the dam folder).")
    values = {
        "DAM_FOLDER": str(folder),
        "DEPTH": depth,
        **{param: _raster(dam.get(key)) for param, key in ND_EXTRA_RASTERS},
    }
    if not values.get("VELOCITY") and from_folder:
        values["VELOCITY"] = _raster(str(folder / "Velocity (Max).tif"))
    cmd = [exe, "run", alg, *_args(exe, alg, values, log)]
    log(f"Classification: {' '.join(cmd[1:3])} (DamSafety Hazard). It finds the downstream structures itself (NSI, "
        "ND 911 address points, roads, rail); the desk's receptor list and jurisdiction choice are not sent.")
    log("The result is a suggested class; the engineer of record and the regulating agency make the determination.")
    code, text = _run_logged(cmd, log, timeout=None, cancel=cancel, env=classify_env())
    if code == STOPPED_CANCEL:
        return {**base, "ok": False, "stopped": True, "cancelled": True}
    out = {**base, "ok": code == 0, "stopped": code != 0}
    results = _outputs(text)
    cls = results.get("ND_CLASS")
    if code == 0 and cls:
        ordinal = class_ordinal(cls)
        report = results.get("REPORT_PDF") or results.get("SUMMARY")
        out["suggestedClass"] = cls
        out["ordinal"] = ordinal
        out["report"] = report
        out["classification"] = {
            "suggestedClass": cls,
            "ordinal": ordinal,
            "report": report,
            "tm11Class": results.get("TM11_CLASS"),
            "outputFolder": results.get("OUTPUT_FOLDER"),
            "mode": "nd",
            "source": alg,
            # ndhazard:classify gathers every layer itself (NSI, ND 911 points, roads, rail); a layer it could not get
            # is in its own summary. The desk sends it no receptor layer, so none is "not checked" here.
            "complete": True,
            "notChecked": {},
        }
        from damit_desktop import classify_receptors  # here: classify_receptors imports this module

        out_dir = Path(results.get("OUTPUT_FOLDER") or folder / "outputs")
        nd = classify_receptors.nd_summary(out_dir / "Classification")
        if nd:
            out["gpkg"] = nd["gpkg"]
            out["classification"].update({k: v for k, v in nd.items() if k != "files"})
            log("Receptors by class: " + ", ".join(nd["files"]))
            if nd["ruling"]:
                g = nd["ruling"]
                log(f"Needs a ruling: {g['unruled']} of the {g['hits']} {g['label']} receptor(s) rest on a value the "
                    "engineer still has to rule on (" + "; ".join(g["why"]) + ").")
        else:
            log(f"No receptor layer in {out_dir / 'Classification'}: the receptor list stays empty for this run.")
        log(f"Suggested ND hazard class: {cls}" + (f"; ACER TM 11: {results['TM11_CLASS']}" if results.get("TM11_CLASS")
                                                    else "") + ". A suggestion, not an official hazard classification.")
    elif code == 0:
        log(f"{alg} finished without an ND_CLASS output; see its summary in the dam folder.")
    else:
        log("The classification failed.")
    return out


#: The most criteria hits the desk keeps with a dam (the Review tab's table); the report and GeoPackage keep them all.
MAX_HITS = 300


def report_hits(res: dict, labels: dict | None = None) -> tuple[list[dict], int]:
    """damit:classify's criteria hits (damit_hazard_report.json "hits": method, class, strength, reason, scenario and
    the receptor ids it was scored for), for the Review tab's table: one row per hit, strongest class first, at most
    MAX_HITS, with the total. Read from the structured list, never from the report's text."""
    labels = labels or {}
    rows: list[dict] = []
    for h in res.get("hits") or []:
        if not isinstance(h, dict):
            continue
        cls = h.get("class")
        ordinal = cls if isinstance(cls, int) and not isinstance(cls, bool) else None
        recs = [str(r) for r in (h.get("receptors") or []) if isinstance(r, (str, int))]
        rows.append({
            "method": str(h.get("method") or "")[:40],
            "ordinal": ordinal,
            "label": str(labels.get(str(cls), labels.get(cls, cls)) if cls is not None else "")[:40],
            "strength": str(h.get("strength") or "")[:20],
            "reason": str(h.get("reason") or "")[:200],
            "scenario": str(h.get("scenario") or "")[:20],
            "receptors": recs[:5],
            "receptorCount": len(recs),
        })
    rows.sort(key=lambda r: (-(r["ordinal"] if r["ordinal"] is not None else -1), r["strength"] != "rule"))
    return rows[:MAX_HITS], len(rows)


#: Flag codes whose receptors carry a value that still needs the engineer's ruling (e.g. the BNSF KO 15 trains/day
#: from RAIL_TRAINS_LOOKUP); a flag message saying "needs ... ruling" counts too.
UNRULED_CODES = ("trains_lookup",)


def unruled_top(res: dict, labels: dict | None = None) -> dict | None:
    """How many of the hits at the top class rest only on receptors with an unruled value (Absaraka 2026-11-21: High
    came from 2 roads by rule and 4 BNSF lines at a looked-up 15 trains/day that "needs Nick's ruling").
    {"label", "hits", "unruled", "why"} or None when the top class does not rest on any unruled value."""
    labels = labels or {}
    unruled: set[str] = set()
    why: list[str] = []
    for f in res.get("flags") or []:
        if not isinstance(f, dict):
            continue
        msg = str(f.get("message") or "")
        if f.get("code") in UNRULED_CODES or re.search(r"needs\b.{0,40}\bruling", msg, re.I):
            recs = {str(r) for r in f.get("receptors") or [] if isinstance(r, (str, int))}
            if recs:
                unruled |= recs
                why.append(msg[:240])
    hits = [h for h in res.get("hits") or [] if isinstance(h, dict) and isinstance(h.get("class"), int)
            and not isinstance(h.get("class"), bool)]
    if not unruled or not hits:
        return None
    top = max(h["class"] for h in hits)
    top_hits = [h for h in hits if h["class"] == top]
    resting = [h for h in top_hits if (recs := {str(r) for r in h.get("receptors") or []}) and recs <= unruled]
    if not resting:
        return None
    return {"label": str(labels.get(str(top), labels.get(top, top))), "hits": len(top_hits), "unruled": len(resting),
            "why": why[:3]}


def read_hazard_report(out_dir: Path) -> dict | None:
    """The parts of damit:classify's damit_hazard_report.json the desk shows: which preset/mode it ran, the
    generic label, the hits that set the class and how many warnings it flagged. None when there is no report."""
    try:
        res = json.loads((Path(out_dir) / "damit_hazard_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(res, dict):
        return None
    cfg = res.get("config") if isinstance(res.get("config"), dict) else {}
    labels = cfg.get("labels") if isinstance(cfg.get("labels"), dict) else {}
    driving = []
    for h in (res.get("driving") or [])[:8]:
        if isinstance(h, dict):
            cls = h.get("class")
            driving.append({
                "method": str(h.get("method") or ""),
                "label": str(labels.get(str(cls), labels.get(cls, cls)) if cls is not None else ""),
                "reason": str(h.get("reason") or "")[:300],
                "receptors": len(h.get("receptors") or []),
            })
    flags = [f for f in res.get("flags") or [] if isinstance(f, dict) and f.get("level") in ("error", "warning")]
    # What the run found affected among the real receptors (for the printed report's table): receptors with a hit, by
    # layer (per_receptor keys look like "structure:39", "road:240"), and the wet structures it counted.
    layer_of = {"structure": "STRUCTURES", "road": "ROADS", "rail": "RAIL", "facility": "FACILITIES",
                "lifeline": "LIFELINES", "environment": "ENVIRONMENT"}
    impacted: dict[str, int] = {}
    per = res.get("per_receptor") if isinstance(res.get("per_receptor"), dict) else {}
    for key in per:
        layer = layer_of.get(str(key).split(":", 1)[0])
        if layer:
            impacted[layer] = impacted.get(layer, 0) + 1
    hab = res.get("habitability") if isinstance(res.get("habitability"), dict) else {}
    tally = hab.get("tally") if isinstance(hab.get("tally"), dict) else {}
    wet = tally.get("wet_structures")
    hits, hits_total = report_hits(res, labels)
    return {
        "ruling": unruled_top(res, labels),
        "hits": hits,
        "hitsTotal": hits_total,
        "impacted": impacted,
        "wetStructures": wet if isinstance(wet, int) and not isinstance(wet, bool) else None,
        "ranMode": cfg.get("mode"),
        "ranPreset": cfg.get("preset"),
        "ranPresetLabel": cfg.get("preset_label"),
        "genericLabel": res.get("generic_label"),
        "driving": driving,
        "warnings": len(flags),
    }


def real_receptor_layers(dam: dict, analysis: dict, depth: str, log, cancel: threading.Event | None = None) -> dict:
    """The real structures / roads / rail for the depth raster's area (real_receptors.py). Never raises: a layer it
    cannot get is listed under "missing", and run_classify marks the class incomplete."""
    bbox = real_receptors.raster_bbox(depth)
    if bbox is None:
        point = _lonlat(dam)
        bbox = real_receptors.dam_bbox({"lon": point[0], "lat": point[1]}, analysis) if point else None
        if bbox is not None:
            log("The depth raster's area could not be read from its GeoTIFF tags (a CRS this desk does not know); "
                "receptors are looked up round the dam point instead.")
    if bbox is None:
        why = "no area: the depth raster's CRS is not one the desk reads, and the dam has no point"
        return {"layers": {}, "sources": {}, "missing": {k: why for k in real_receptors.CORE_LAYERS}}
    log("Looking up the real receptors (structures, roads, rail) for "
        f"{bbox[0]:.4f}, {bbox[1]:.4f} to {bbox[2]:.4f}, {bbox[3]:.4f}: the DamIT data folder first, then the public services.")
    state = _state_code(dam) or (str(dam.get("state") or "").upper()[:2] or None)
    try:
        found = REAL_RECEPTORS(bbox, state, find_data_folder(), log, cancel=cancel)
    except Exception as exc:  # a lookup bug must not stop classify; it shows as NOT CHECKED
        why = f"the lookup failed: {exc}"
        return {"layers": {}, "sources": {}, "missing": {k: why for k in real_receptors.CORE_LAYERS}}
    for key in real_receptors.CORE_LAYERS:
        if key in found.get("sources", {}):
            log(f"{key.title()}: {len(found['layers'].get(key) or [])} from {found['sources'][key]}.")
    return found


#: The real-receptor lookup (tests replace it; DAMIT_OFFLINE=1 keeps it to the data folder).
REAL_RECEPTORS = real_receptors.find_receptors


def run_classify(
    dam: dict,
    analysis: dict,
    work: str | None,
    log,
    files=None,
    cancel: threading.Event | None = None,
    config: HandoffConfig | None = None,
    receptors=None,
) -> dict:
    """Write the dam folder and the downstream receptor layers, then hand them to the hazard classification algorithm
    (damit:classify by default) with the desk's preset or custom method choice and the model's depth raster, so the
    chosen jurisdiction judges the downstream consequences. It runs no breach model.

    receptors: the desk's "damit_crest/classify_receptors" payload (classify-receptors.ts); without it the record's
    mapped seeds are used. Classify is not started without a depth raster or without at least one receptor layer."""
    cfg = handoff_config(config)
    alg = cfg.alg("classify")
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    stop = _nid_stop(dam, log, folder, root, "The classification")
    if stop:
        return stop
    _log_ids(dam, log)
    base = {"folder": str(folder), "work": str(root)}
    if cfg.profile == "nd":
        return _run_classify_nd(dam, folder, cfg, log, base, cancel)
    _log_config(log, cfg, ("classify",))
    choice = _choice(dam)
    chosen = (f"preset {choice['preset_label'] or choice['preset']}" if choice["mode"] == "preset"
              else "custom methods " + ",".join(x for x in (choice["scenarios"], choice["methods"], choice["modifiers"]) if x))
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The classification was not started.")
        return {**base, "ok": False, "stopped": True}
    if not algorithm_available(exe, alg):
        _missing_alg(log, exe, cfg, "classify", "The classification")
        return {**base, "ok": False, "stopped": True, "missingAlgorithm": alg}
    depth = _raster(dam.get("depthRaster"))
    from_folder = False
    if not depth:
        # the Runner (damit_run:rundam, DRY_RUN off) copies the model's Depth (Max) / Velocity (Max) into the dam folder
        depth = _raster(str(folder / "Depth (Max).tif"))
        from_folder = bool(depth)
    if not depth:
        log(f"{alg} needs the maximum depth raster of a flood model run. Run the flood model, or type its path under "
            "Depth raster; nothing was classified.")
        return {**base, "ok": False, "stopped": True, "noDepth": True}
    if from_folder:
        log(f"Depth raster: {depth} (the flood model's Depth (Max) in the dam folder).")
    real = real_receptor_layers(dam, analysis or {}, depth, log, cancel)
    if cancel is not None and cancel.is_set():
        log("Cancelled while looking up the receptors. Nothing was classified.")
        return {**base, "ok": False, "stopped": True, "cancelled": True}
    written = write_receptor_layers(folder, dam, receptors, real=real)
    for s in written["skipped"]:
        log(f"Receptor not sent: {s.get('name') or s.get('id') or s.get('kind')} ({s.get('kind')}): {s.get('reason')}.")
    if not written["layers"]:
        log(f"No downstream receptor could be sent to {alg}, so it was not started: it judges the consequences from "
            "receptor layers (structures, roads, rail, facilities, lifelines or environment) and needs at least one.")
        log("Add or map receptors (Flood / Screen steps, or the 911 points), and draw the breach point, dam line and "
            "reservoir point so desk-valley receptors can be placed on the ground.")
        return {**base, "ok": False, "stopped": True, "noReceptors": True, "skipped": len(written["skipped"])}
    counts = ", ".join(f"{k} {n}" for k, n in written["counts"].items())
    placed = ", ".join(f"{n} {k}" for k, n in written["placement"].items() if n)
    log(f"Receptor layers for {alg} ({written['source']}): {counts}" + (f"; placed: {placed}" if placed else "") + ".")
    missing = dict(written.get("missing") or {})
    if missing:
        log("INCOMPLETE: " + "; ".join(f"{k.lower()} NOT CHECKED ({why})" for k, why in missing.items())
            + ". The class below can only be a lower bound until those layers are checked.")
    rail_lookup = _file(dam.get("railTrainsLookup") or os.environ.get("DAMIT_RAIL_TRAINS_LOOKUP"))
    if written["counts"].get("RAIL") and not rail_lookup:
        log(f"Rail: {written['counts']['RAIL']} line(s) in the area. The national rail network has no trains per day, so "
            "M9a can call an impacted line Medium at most. For the High test (10+ freight trains a day), give a "
            "trains-per-day lookup (the Rail trains lookup field, or DAMIT_RAIL_TRAINS_LOOKUP). DamIT ships no default.")
    if written["placement"].get("desk valley"):
        log("Desk-valley receptors sit where the desk's straight valley puts them from the breach (schematic); map "
            "them (lon/lat) for a placement the depth raster can be trusted at.")
    if written["domain"]:
        log(f"Routed domain: {written['domain']} (the drawn downstream area).")
    accepted = help_params(exe, alg)
    if accepted and not (set(written["layers"]) & accepted):
        log(f"{alg} lists none of the receptor layers {', '.join(written['layers'])}, so the chosen methods could not "
            "judge the downstream receptors; nothing was classified. Check that the id points at DamIT Hazard's classify.")
        return {**base, "ok": False, "stopped": True, "noReceptorParams": True}
    preset = _preset_index(exe, alg, choice)
    if preset is None and "PRESET" in accepted:
        log(f"{alg} does not list the preset {choice['preset'] or 'custom'}; nothing was classified.")
        return {**base, "ok": False, "stopped": True}
    record = write_classify_record(folder, dam)
    out_dir = folder / "classify"
    # The run DEM for WSE-consistent NoData depth (Absaraka desk test 2026-11-21: without it 219 structures on NoData
    # cells next to water were scored dry). The DEM the hand-off panel or the desk chose; never the data folder's
    # statewide DEM, which may not match the run.
    terrain = dem_path(root, dam, source="none")
    if terrain and "TERRAIN" in accepted:
        log(f"Run DEM / terrain for NoData depth: {terrain} (the DEM chosen in the desk; units detected by {alg}).")
    elif "TERRAIN" in accepted:
        log("No DEM chosen: structures on NoData cells next to water are scored without ground (choose a DEM in the "
            "desk or under DEM, the same one the flood model used).")
    values = {
        "PRESET": preset,
        "METHODS": choice["methods"],
        "MODIFIERS": choice["modifiers"],
        "SCENARIOS": choice["scenarios"],
        "APPLY_ADVISORY": "true" if choice["advisory"] else None,
        "DEPTH": depth,
        "TERRAIN": terrain,
        **{param: _raster(dam.get(key)) for param, key in EXTRA_RASTERS},
        **({"VELOCITY": _raster(str(folder / "Velocity (Max).tif"))} if from_folder and not _raster(dam.get("velocityRaster")) else {}),
        **{key: written["layers"].get(key) for key in RECEPTOR_LAYERS},
        "DOMAIN": written["domain"],
        "DAM_JSON": str(record),
        "DAM_NAME": dam.get("name") or None,
        # DamIT Hazard 0.1.2: trains per day for rail layers without the field (NARN); no default, user-given only
        "RAIL_TRAINS_LOOKUP": rail_lookup,
        "OUTPUT": str(out_dir),
    }
    if values["RAIL_TRAINS_LOOKUP"]:
        log(f"Rail trains per day lookup: {values['RAIL_TRAINS_LOOKUP']} (values from it are flagged as needing a ruling).")
    unsent = [k for k in written["layers"] if accepted and k not in accepted]
    if unsent:
        log(f"{alg} does not list {', '.join(unsent)}; those receptors were not sent.")
    cmd = [exe, "run", alg, *_args(exe, alg, values, log)]
    log(f"Classification for {chosen}: {' '.join(cmd[1:3])} judges the downstream receptors with these methods.")
    log("The result is a suggested class; the engineer of record and the regulating agency make the determination.")
    code, text = _run_logged(cmd, log, timeout=None, cancel=cancel, env=classify_env())
    if code == STOPPED_CANCEL:
        return {**base, "ok": False, "stopped": True, "cancelled": True}
    out = {**base, "ok": code == 0, "stopped": code != 0}
    results = _outputs(text)
    if code == 0 and results.get("CLASS"):
        report = read_hazard_report(Path(results.get("OUTPUT") or out_dir)) or {}
        out["suggestedClass"] = results["CLASS"]
        out["ordinal"] = results.get("ORDINAL")
        out["report"] = results.get("REPORT")
        out["gpkg"] = results.get("GPKG")
        out["classification"] = {
            "suggestedClass": results["CLASS"],
            "ordinal": results.get("ORDINAL"),
            "report": results.get("REPORT"),
            "gpkg": results.get("GPKG"),
            "source": alg,
            "layers": written["counts"],
            "skipped": len(written["skipped"]),
            "mode": choice["mode"],
            "preset": choice["preset"],
            **report,
            # Which layers were checked and from where. complete is False when structures, roads or rail could not
            # be checked: the desk then shows the class as a lower bound, not as the answer.
            "complete": not missing,
            "notChecked": missing,
            "layerSources": dict(written.get("sources") or {}),
            "railTrainsLookup": rail_lookup,
        }
        if missing:
            out["incomplete"] = True
        ran = report.get("ranPreset")
        if choice["mode"] == "preset" and report and ran != choice["preset"]:
            log(f"Note: the report says it ran {ran or 'custom mode'}, not {choice['preset']}; check the PRESET list of {alg}.")
            out["classification"]["presetMismatch"] = True
        log(f"Suggested class for {chosen}: {results['CLASS']} (ordinal {results.get('ORDINAL', '?')}). "
            "This is the DamIT classification for the chosen jurisdiction, a suggestion, not an official hazard classification.")
        if missing:
            log(f"INCOMPLETE: {results['CLASS']} is at least the class; {', '.join(k.lower() for k in missing)} "
                "were NOT CHECKED, and any of them can raise it.")
        if results.get("GPKG"):
            log(f"Receptors by class: {results['GPKG']}")
    log("Classification finished." if code == 0 else "The classification failed.")
    return out


def _state_code(dam: dict) -> str | None:
    """Postal code from an NID id (ND00199 -> ND). None when the id does not start with one."""
    nid = str(dam.get("nid") or dam.get("nidId") or "")
    found = re.match(r"^([A-Z]{2})\d", nid)
    return found.group(1) if found else None


def _extent(dam: dict) -> str | None:
    """The drawn area as a qgis_process extent, or None."""
    geom = ((dam.get("geometry") or {}).get("aoi") or {}).get("geometry") or {}
    rings = geom.get("coordinates") if geom.get("type") == "Polygon" else None
    if not rings or not rings[0]:
        return None
    xs = [p[0] for p in rings[0] if isinstance(p, (list, tuple)) and len(p) >= 2]
    ys = [p[1] for p in rings[0] if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not xs or not ys:
        return None
    return f"{min(xs)},{max(xs)},{min(ys)},{max(ys)} [EPSG:4326]"


def _plugin(
    role: str,
    what: str,
    log,
    config: HandoffConfig | None,
    work: str,
    values: dict,
    folder: str = "",
    cancel: threading.Event | None = None,
) -> dict:
    """One qgis_process run of a published DamIT algorithm. Stops with a message when it is not installed.
    Its output is in the log as it runs; Cancel (cancel.set()) and the time limit (plugin_timeout) stop
    qgis_process and everything it started."""
    cfg = handoff_config(config)
    alg = cfg.alg(role)
    _log_config(log, cfg, (role,))
    exe = find_qgis_process()
    if not exe:
        log(f"qgis_process was not found. {what} was not started.")
        log(_no_qgis_hint())
        return {"ok": False, "stopped": True, "folder": folder, "work": work}
    if not algorithm_available(exe, alg):
        _missing_alg(log, exe, cfg, role, what)
        return {"ok": False, "stopped": True, "missingAlgorithm": alg, "folder": folder, "work": work}
    limit = plugin_timeout(role)
    log(f"{what}: {alg}" + (f" (stops after {limit / 60:g} min; DAMIT_PLUGIN_TIMEOUT_S)" if limit else ""))
    code, text = _run_logged([exe, "run", alg, *_args(exe, alg, values, log)], log, timeout=limit, cancel=cancel)
    out = {"ok": code == 0, "folder": folder, "work": work, "outputs": _outputs(text)}
    if code == STOPPED_CANCEL:
        log(f"{what} was cancelled. Files it had started may be incomplete.")
        out.update(stopped=True, cancelled=True)
    elif code == STOPPED_TIMEOUT:
        log(f"{what} was stopped at its time limit ({limit:g} s). Set DAMIT_PLUGIN_TIMEOUT_S for a longer one.")
        out.update(stopped=True, timedOut=True)
    return out


def run_data(dam: dict, analysis: dict, work: str | None, log, files=None, config: HandoffConfig | None = None,
             cancel: threading.Event | None = None) -> dict:
    """damit_data:download for the dam's state, into the DamIT data folder (or <work>/data).

    STATE is the option whose text names the postal code from the NID id. An id with no code downloads by extent.
    The North Dakota profile has no download algorithm (data role empty): its layers are the ND offline pack.
    """
    if not handoff_config(config).alg("data"):
        log("The DWR DamSafety plugins publish no download algorithm. In the North Dakota profile the layers come from "
            "the ND offline pack (NDSUITE_DATA, or DamSafety Setup's data folder), or use Get layers for this area.")
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files, append_status=False)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    data = find_data_folder() or str(root / "data")
    Path(data).mkdir(parents=True, exist_ok=True)
    values: dict = {"FOLDER": data}
    state = _state_code(dam)
    if state:
        index = enum_match(find_qgis_process() or "", cfg_alg("data", config), "STATE",
                           lambda text: text.strip().upper().startswith(state))
        if index is not None:
            values["STATE"] = index
            log(f"Data download for {state}.")
        else:
            log(f"{state} was not in the STATE list; downloading by extent.")
    extent = _extent(dam)
    if extent:
        values["EXTENT"] = extent
    return _plugin("data", "The data download", log, config, str(root), values, str(folder), cancel=cancel)


def cfg_alg(role: str, config: HandoffConfig | None) -> str:
    return handoff_config(config).alg(role)


def run_pmp(dam: dict, analysis: dict, work: str | None, log, files=None, config: HandoffConfig | None = None,
             cancel: threading.Event | None = None) -> dict:
    """damit_pmp:pointpf at the dam point. Atlas 14 only; not a PMP study."""
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files, append_status=False)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    point = _lonlat(dam)
    if point is None:
        log("No dam point. Atlas 14 was not started.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    out = root / "pmp"
    out.mkdir(exist_ok=True)
    stem = safe_name(handoff_ids(dam)["dam_id"])
    log("Atlas 14 at the dam point. This is a precipitation-frequency estimate, not a PMP study.")
    return _plugin(
        "pmp",
        "The Atlas 14 point estimate",
        log,
        config,
        str(root),
        {
            "POINT": f"{point[0]},{point[1]} [EPSG:4326]",
            "OUTPUT_CSV": str(out / f"{stem}_atlas14.csv"),
            "OUTPUT_JSON": str(out / f"{stem}_atlas14.json"),
        },
        str(folder),
        cancel=cancel,
    )


def run_finder(dam: dict, analysis: dict, work: str | None, log, files=None, config: HandoffConfig | None = None,
             cancel: threading.Event | None = None) -> dict:
    """damit_find:embankments on the local DEM, limited to the drawn area when there is one."""
    dam = dam or {}
    prepared = _prepare(dam, analysis or {}, work, log, files, append_status=False)
    if prepared is None:
        return {"ok": False, "stopped": True, "folder": "", "work": ""}
    root, folder = prepared
    dem = _raster(dam.get("demPath")) or _raster(os.environ.get("DAMIT_DEM")) or desk_dem() or (
        str(root / "dem.tif") if (root / "dem.tif").is_file() else None
    )
    if not dem:
        log("No DEM. Finder was not started. Choose a DEM, or set DAMIT_DEM.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    out = root / "finder"
    out.mkdir(exist_ok=True)
    stem = safe_name(handoff_ids(dam)["dam_id"])
    values = {"DEM": dem, "OUT": str(out / f"{stem}_embankments.gpkg")}
    extent = _extent(dam)
    if extent:
        values["EXTENT"] = extent
    known = write_known_dams(out / f"{stem}_known_dams.geojson", dam, log)
    if known:
        values["KNOWN"] = known
    log("Finder looks for fills. A candidate is not a listed dam, and it has no NID ID.")
    return _plugin("finder", "The fill search", log, config, str(root), values, str(folder), cancel=cancel)


def write_known_dams(path: Path, dam: dict, log, load_state=None) -> str | None:
    """The listed dams Finder checks each candidate against (its KNOWN layer), as EPSG:4326 points: the state's NID
    main dams from the desk's NID cache (downloaded once per state), and always this dam itself. Without it every
    fill came back "not listed", even this dam. None when there is not one point to write."""
    feats: dict[str, dict] = {}
    state = _state_code(dam)
    if state:
        try:
            from damit_desktop import nid as nid_mod

            if load_state is None:
                offline = (os.environ.get("DAMIT_OFFLINE") or "").strip().lower() in ("1", "true", "yes")
                cached = nid_mod.NID_DIR is not None and nid_mod.cache_path(state).is_file()
                if offline and not cached:
                    raise RuntimeError("no cached NID list, and DAMIT_OFFLINE is set")
                load_state = nid_mod.load_state
            bundle = load_state(state)
            cols = bundle.get("cols") or []
            ix = {c: i for i, c in enumerate(cols)}
            for row in bundle.get("rows") or []:
                try:
                    lon, lat, nid_id = row[ix["lon"]], row[ix["lat"]], row[ix["nid"]]
                except (KeyError, IndexError, TypeError):
                    continue
                if _finite(lon) is None or _finite(lat) is None or not nid_id:
                    continue
                feats[str(nid_id)] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                      "properties": {"nid": str(nid_id), "name": str(row[ix["name"]] or "") if "name" in ix else "",
                                                     "source": "NID"}}
            log(f"Known dams for Finder: {len(feats)} {state} NID dams (desk NID cache).")
        except Exception as exc:  # no cache and no network: Finder still runs, with this dam only
            log(f"The {state} NID list could not be loaded ({exc}); Finder checks candidates against this dam only.")
    point = _lonlat(dam)
    ids = handoff_ids(dam)
    ident = ids.get("nid_id") or ids.get("dam_id") or "this dam"
    if point is not None and str(ident) not in feats:
        feats[str(ident)] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                             "properties": {"nid": str(ident), "name": str(dam.get("name") or ""), "source": "desk record"}}
    if not feats:
        log("No listed dam to check candidates against (no NID list, no dam point).")
        return None
    path.write_text(json.dumps({"type": "FeatureCollection", "name": "known_dams", "features": list(feats.values())}) + "\n",
                    encoding="utf-8")
    return str(path)


def _python_for(cli: str) -> str:
    chosen = os.environ.get("DAMIT_PYTHON")
    if chosen and Path(chosen).is_file():
        return chosen
    for candidate in (
        "/Applications/QGIS.app/Contents/MacOS/bin/python3",
        "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3",
    ):
        if Path(candidate).is_file():
            return candidate
    if os.name == "nt":
        return sys.executable
    return "python3"
