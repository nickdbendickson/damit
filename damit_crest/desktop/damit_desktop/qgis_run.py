"""Call the installed DamIT QGIS plugins through qgis_process. Never start the chain after a preflight FAIL.

The algorithm ids come from damit_desktop.algorithms (DamIT defaults, overridable by environment or
damit-handoff.json). Nothing here starts a North Dakota suite id (nddam:*, ndbreach:*) or a batch algorithm."""

from __future__ import annotations

import csv
import json
import math
import os
import re
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

# An ND-style runner port's option text (damit_runner 0.1.0 has no METHOD / TIER; these are used only when a rundam override lists them). qgis_process
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


def find_qgis_process() -> str | None:
    chosen = os.environ.get("QGIS_PROCESS")
    if chosen and Path(chosen).is_file():
        return chosen
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


def work_dir(requested: str | None) -> Path:
    raw = (requested or os.environ.get("DAMIT_WORK") or "").strip()
    path = Path(raw).expanduser() if raw else Path.home() / DEFAULT_WORK_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def dem_path(work: Path, dam: dict, source: str = "data") -> str | None:
    for raw in (dam.get("demPath"), os.environ.get("DAMIT_DEM"), work / "dem.tif", work / "dem.vrt"):
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
# timeout) and 130 (SIGINT) so a plugin that genuinely exits 124/130 is not misread as a DamIT Crest timeout/cancel.
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


def _collect_bounded(stream, head_cap: int = _OUTPUT_HEAD_CHARS, tail_cap: int = _OUTPUT_TAIL_CHARS) -> str:
    """Read all of stream but retain only the first head_cap and last tail_cap characters, with a count of the
    dropped middle. Reads in blocks so the full output is never held in memory at once."""
    head: list[str] = []
    head_len = 0
    tail: deque[str] = deque()
    tail_len = 0
    dropped = 0
    while True:
        try:
            block = stream.read(8192)
        except (ValueError, OSError):
            break  # stream closed while the process was being stopped
        if not block:
            break
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


def _run(cmd: list[str], timeout: float | None, cancel: threading.Event | None = None) -> tuple[int, str]:
    """Run cmd and return (exit code, output). timeout (seconds) gives 124, cancel.set() gives 130;
    both stop the process (and its children) and keep the output so far. Very long output is kept head + tail only."""
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", **kwargs)
    except OSError as exc:
        return 127, f"Could not start {cmd[0]}: {exc}\n"
    captured: list[str] = []
    reader = threading.Thread(
        target=lambda: captured.append(_collect_bounded(proc.stdout) if proc.stdout else ""), daemon=True
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
        return stopped, out + "\nStopped: cancelled in DamIT Crest.\n"
    return proc.returncode, out


_ENUM_HELP: dict[tuple[str, str], str | None] = {}
_ENUM_ROW = re.compile(r"^\s*-\s*(\d+):\s*(.*?)\s*$")
_PARAM_ROW = re.compile(r"^([A-Z][A-Z0-9_]*):")


def help_text(exe: str, alg: str) -> str | None:
    """`qgis_process help alg` (cached per exe/alg), or None when the algorithm is not installed or help failed."""
    key = (exe, alg)
    if key not in _ENUM_HELP:
        try:
            out = subprocess.run([exe, "help", alg], capture_output=True, text=True, timeout=180,
                                 stdin=subprocess.DEVNULL)
            _ENUM_HELP[key] = out.stdout if out.returncode == 0 and out.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            _ENUM_HELP[key] = None
    return _ENUM_HELP[key]


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

    The candidates cover DamIT Screener / Runner 0.1.0 (WORK, DAMS, HANDOFF, OUTPUT_FOLDER...) and an ND-style port
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


def _missing_alg(log, cfg: HandoffConfig, role: str, what: str) -> None:
    alg = cfg.alg(role)
    log(f"{alg} is not installed in this QGIS (qgis_process help {alg} failed). {what} was not started.")
    log(
        f"Install the DamIT plugin that provides it, or point DamIT Crest at the published id with "
        f"{'DAMIT_ALG_' + role.upper()} or damit-handoff.json (docs/HANDOFF.md). ND suite ids are not used as a fallback."
    )


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


def handoff_config(config: HandoffConfig | None = None) -> HandoffConfig:
    """The resolved algorithm ids. Read for every job, so an edited damit-handoff.json applies without a restart."""
    return config if config is not None else load_config(SETTINGS_DIR)


def _log_config(log, cfg: HandoffConfig, roles: tuple[str, ...]) -> None:
    for problem in cfg.problems:
        log(f"Handoff config: {problem}")
    for role in roles:
        where = "" if cfg.sources[role] == "default" else f" (from {cfg.sources[role]})"
        log(f"{role}: {cfg.alg(role)}{where}")


def _settings_path(root: Path, log, only_ids: str | None = None, classification: dict | None = None) -> Path:
    """damit_settings.json for --SETTINGS (always written: it carries dam_ids, so the chain screens this dam only)."""
    data = find_data_folder()
    dem = data_dem(data)
    local_dem = str(root / "dem.tif") if (root / "dem.tif").is_file() else None
    path = write_settings(root, data, dem or local_dem, only_ids, classification)
    if data:
        log(f"Screening settings use the DamIT data folder: {data}")
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
        " decide. The DamIT Crest record is not changed."
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
        text += " Flags: " + "; ".join(str(f) for f in flags[:6]) + "."
    return text + " A screening suggestion, not an official hazard classification."


def run_screening(
    dam: dict,
    analysis: dict,
    work: str | None,
    log,
    files=None,
    timeout: float | None = None,
    cancel: threading.Event | None = None,
    config: HandoffConfig | None = None,
) -> dict:
    """The preflight algorithm, then the screening chain for this dam only if the preflight is READY.

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
        log("Install QGIS (3.28 or newer), or set QGIS_PROCESS to the qgis_process program.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, preflight_alg):
        _missing_alg(log, cfg, "preflight", "The screening")
        return {"ok": False, "stopped": True, "missingAlgorithm": preflight_alg, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, chain_alg):
        _missing_alg(log, cfg, "runchain", "The screening")
        return {"ok": False, "stopped": True, "missingAlgorithm": chain_alg, "folder": str(folder), "work": str(root)}
    report = root / "preflight.txt"
    has_id = bool(dam.get("nid") or dam.get("nidId") or dam.get("id"))
    # only_ids is the NID ID alone (or the record id of a new dam / sample): never another inventory's id for it.
    only = dam_id if has_id else None
    settings = _settings_path(root, log, only, _classification(dam))
    point = write_dam_point(folder, dam, analysis or {})
    if point:
        log(f"Wrote {point} (this dam as a point layer for DAMS; DamIT field names, EPSG:4326).")
    else:
        log("The dam has no position (breach point, reservoir point or lon/lat), so no DAMS layer was written.")
    choice = _choice(dam)
    dem = dem_path(root, dam, "data")

    def common(alg: str) -> dict:
        return {
            "WORK": str(root),
            "DAMS": str(point) if point else None,
            "MODE": _mode_index(exe, alg, choice["mode"]),
            "PRESET": choice["preset"],
            "SCENARIOS": choice["scenarios"],
            "METHODS": choice["methods"],
            "TERRAIN": dem,
            "APPLY_ADVISORIES": "true" if choice["advisory"] else None,
            "SETTINGS": str(settings),
        }

    limit = screening_timeout(timeout)
    log(f"Jurisdiction: {choice['mode']}" + (f" preset {choice['preset']}" if choice["preset"] else "")
        + (f", methods {choice['methods']}" if choice["methods"] else "") + ".")
    log(f"Preflight: {exe} run {preflight_alg}")
    code, text = _run(
        [exe, "run", preflight_alg, *_args(exe, preflight_alg, {**common(preflight_alg), "REPORT": str(report)}, log)],
        timeout=180,
        cancel=cancel,
    )
    if code == STOPPED_CANCEL:
        log(text.rstrip())
        log(f"Cancelled. {chain_alg} was not started.")
        return {"ok": False, "stopped": True, "cancelled": True, "folder": str(folder), "work": str(root)}
    report_text = ""
    if report.is_file():
        report_text = report.read_text(encoding="utf-8", errors="replace")
    log(text.rstrip())
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
    code, text = _run([exe, "run", chain_alg, *_args(exe, chain_alg, chain_values, log)], timeout=limit, cancel=cancel)
    log(text.rstrip())
    if chain_log.is_file():
        written = chain_log.read_text(encoding="utf-8", errors="replace").rstrip()
        if written and written not in text:
            log(written)
    found = chain_names(root, dam_id) if has_id else []
    names = [n for n in found if n.upper() == dam_id.upper()]
    other = [n for n in found if n.upper() != dam_id.upper()]
    if other:
        log(f"The screening outputs also name this dam {', '.join(other)}, which is not its NID ID {dam_id}. "
            "DamIT Crest reads results by the NID ID only; check the screener's dam inventory is the NID.")
    out = {"folder": str(folder), "work": str(root), "chainIds": names}
    if code in (STOPPED_TIMEOUT, STOPPED_CANCEL):
        log("The screening chain was stopped. Its outputs so far stay in the work folder; chain_log.txt has the steps that ran.")
        return {**out, "ok": False, "stopped": True, "cancelled": code == STOPPED_CANCEL, "timedOut": code == STOPPED_TIMEOUT}
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
    rows = chain_results(root, [dam_id])
    for row in rows:
        log(_result_line(row))
    if not rows and screening is None:
        log("No hand-off package and no 10_reports/summary.csv row for this dam (the chain plan may not include them).")
    log("Screening chain finished.")
    return {**out, "ok": True, "stopped": False, "chainResult": rows}


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
        if cls:
            config_json["classification"] = cls
        path = folder / "runner_config.json"
        path.write_text(json.dumps(config_json, indent=2) + "\n", encoding="utf-8")
        log(f"One dam, no QGIS window: {cli} run")
        log("The point is the DEM-coordinate pair from the export fields, not longitude and latitude.")
        code, text = _run([_python_for(cli), cli, "run", str(path)], timeout=None, cancel=cancel)
        log(text.rstrip())
        log("Runner finished." if code == 0 else "The runner failed.")
        return {"ok": code == 0, "stopped": code != 0, "folder": str(folder), "work": str(root)}
    if cli and not point:
        log(f"{Path(cli).name} needs the dam point in the DEM's coordinates. Longitude and latitude were not sent as that point.")
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The flood model was not started.")
        if not point:
            log("Enter both Point X and Point Y (DEM CRS) on the export panel to use the DamIT runner CLI instead.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, rundam):
        _missing_alg(log, cfg, "rundam", "The flood model")
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
    values = {
        # DamIT Runner 0.1.0 (damit_run:rundam): the screener's package when there is one, else the dam as parameters.
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
        "DRY_RUN": "true",
        # An ND-style runner port.
        "DAMS_FOLDER": str(dams),
        "DEM": dem,
        "METHOD": enum_value(exe, rundam, "METHOD", METHOD_LABEL[key]) if "METHOD" in accepted else None,
        "TIER": enum_value(exe, rundam, "TIER", label) if "TIER" in accepted else None,
        "LISFLOOD_EXE": "builtin" if builtin else None,
        "HEIGHT_FT": _finite(dam.get("heightFt")),
        "STORAGE_ACFT": _finite(dam.get("storageAcFt")),
        "TOP_FT": _finite(datum.get("crestNavdFt")),
        "AREA_AC": _finite(dam.get("surfaceAreaAc")),
    }
    if "OUTPUT_FOLDER" in accepted:
        (root / "runs").mkdir(exist_ok=True)
    if values["HANDOFF"]:
        log(f"Hand-off package: {package}")
    cmd = [exe, "run", rundam, *_args(exe, rundam, values, log)]
    log(f"This button runs {rundam} for one dam.")
    if "DRY_RUN" in accepted:
        log("DRY_RUN=true: the runner prepares and records the run; DamIT Crest never asks it to launch an engine.")
    code, text = _run(cmd, timeout=None, cancel=cancel)
    log(text.rstrip())
    results = _outputs(text)
    out = {"ok": code == 0, "stopped": code != 0, "folder": str(folder), "work": str(root)}
    if results.get("RUN_FOLDER"):
        out["runFolder"] = results["RUN_FOLDER"]
        log(f"Run folder: {results['RUN_FOLDER']} (status {results.get('STATUS') or 'unknown'}).")
    log("Runner finished." if code == 0 else "The runner failed.")
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


def run_classify(
    dam: dict,
    analysis: dict,
    work: str | None,
    log,
    files=None,
    cancel: threading.Event | None = None,
    config: HandoffConfig | None = None,
) -> dict:
    """Write the dam folder, then hand it to the hazard classification algorithm (damit:classify by default) with the
    desk's preset or custom method choice and the model's depth raster. It runs no breach model."""
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
    _log_config(log, cfg, ("classify",))
    exe = find_qgis_process()
    if not exe:
        log("qgis_process was not found. The classification was not started.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    if not algorithm_available(exe, alg):
        _missing_alg(log, cfg, "classify", "The classification")
        return {"ok": False, "stopped": True, "missingAlgorithm": alg, "folder": str(folder), "work": str(root)}
    accepted = help_params(exe, alg)
    choice = _choice(dam)
    depth, velocity = _raster(dam.get("depthRaster")), _raster(dam.get("velocityRaster"))
    if not depth and "DEPTH" in accepted:
        log(f"{alg} needs the maximum depth raster of a flood model run. Type its path under Depth raster; nothing was classified.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    preset = _preset_index(exe, alg, choice)
    if preset is None and "PRESET" in accepted:
        log(f"{alg} does not list the preset {choice['preset'] or 'custom'}; nothing was classified.")
        return {"ok": False, "stopped": True, "folder": str(folder), "work": str(root)}
    record = write_classify_record(folder, dam)
    values = {
        "PRESET": preset,
        "METHODS": choice["methods"],
        "MODIFIERS": choice["modifiers"],
        "SCENARIOS": choice["scenarios"],
        "APPLY_ADVISORY": "true" if choice["advisory"] else None,
        "DEPTH": depth,
        "VELOCITY": velocity,
        "DAM_JSON": str(record),
        "DAM_NAME": dam.get("name") or None,
        "OUTPUT": str(folder / "classify"),
    }
    cmd = [exe, "run", alg, *_args(exe, alg, values, log)]
    log(f"Classification ({choice['mode']}{': ' + choice['preset'] if choice['preset'] else ''}): {' '.join(cmd[1:3])}")
    log("The result is a suggested class; the engineer of record and the regulating agency make the determination.")
    code, text = _run(cmd, timeout=None, cancel=cancel)
    log(text.rstrip())
    if code == STOPPED_CANCEL:
        return {"ok": False, "stopped": True, "cancelled": True, "folder": str(folder), "work": str(root)}
    out = {"ok": code == 0, "stopped": code != 0, "folder": str(folder), "work": str(root)}
    results = _outputs(text)
    if code == 0 and results.get("CLASS"):
        out["suggestedClass"] = results["CLASS"]
        out["ordinal"] = results.get("ORDINAL")
        out["report"] = results.get("REPORT")
        log(f"Suggested class: {results['CLASS']} (ordinal {results.get('ORDINAL', '?')}). Not an official hazard classification.")
    log("Classification finished." if code == 0 else "The classification failed.")
    return out


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
    return "python3"
