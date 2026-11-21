"""Engine version registry and probes (audit follow-up 2026-11-19).

Why: the suite sha-pins its own shared code (RUNNER_FILES, SHARED_ATLAS14.json) but nothing
pins the *engine* assumptions. LISFLOOD-FP silently runs a different solver when asked for a
CUDA one on a CPU build (CUDA_NOTE in lisfloodrain.py); an old ANUGA or a HEC-RAS minor
upgrade can change results quietly. This module is the single source of truth for which
engine versions the suite is meant to run against, and how each is detected.

One ENGINES entry per engine:
  min          the minimum version the suite is developed against (semver-ish x.y[.z])
  probe        how to get a version string: 'banner' (run the exe with probe_argv and read
               its output), 'python' (run interpreter -c import-and-print), or 'none' (not
               automatically detectable; live check only)
Production launchers call require_minimum() / probe_and_require() at run start; CI runs the
offline legs (parsing + minimum logic); the live legs run only when the engine env vars
point at real binaries (opt-in, like DAMIT_PMP_LISFLOOD in the pmp tests).
"""
import os
import re
import subprocess

NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

ENGINES = {
    "lisflood_fp": {
        "min": "8.0",
        "probe": "banner",
        "probe_argv": ["-v"],
        "banner_re": r"LISFLOOD[\s-]?FP\s+v?([0-9]+(?:\.[0-9]+)*)",
        "where": "banner printed by the executable (lisflood -v; also first lines of lisflood.log)",
    },
    "anuga": {
        "min": "1.4",
        "probe": "python",
        "banner_re": r"([0-9]+(?:\.[0-9]+)*)",
        "where": "import anuga; anuga.__version__ in the ANUGA conda env",
    },
    "gmsh": {
        "min": None,                       # optional mesher; recorded, never enforced
        "probe": "python",
        "banner_re": r"([0-9]+(?:\.[0-9]+)*)",
        "where": "import gmsh; gmsh.__version__ in the ANUGA conda env",
    },
    "hec_ras": {
        "min": "6.0",
        "probe": "none",                   # Windows controller API only; live check skips off-Windows
        "banner_re": r"([0-9]+(?:\.[0-9]+)*)",
        "where": "HEC-RAS controller version on Windows; not probed automatically",
    },
}


class EngineVersionError(RuntimeError):
    """The engine's version could not be determined or is below the pinned minimum."""


def _tuple(ver):
    """Numeric prefix of a version string as a tuple: '8.0rc1' -> (8, 0);
    '8' -> (8,).  Suffix digits glued to the last number ('0rc1') are cut
    before splitting, so the suffix never truncates the tuple."""
    s = re.sub(r"(?<=[0-9])(?=[a-zA-Z])", ".", str(ver)).split(".")
    parts = []
    for tok in s:
        m = re.match(r"^[0-9]+", tok)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts) or (0,)


def parse_banner(text, engine):
    """Version string from an engine's banner/one-line output, or None when unrecognized.
    Raises EngineVersionError for an empty probe; returns None (caller decides) for
    output that parses as text but carries no recognizable version."""
    if not text or not text.strip():
        raise EngineVersionError("no output from the {} probe".format(engine))
    m = re.search(ENGINES[engine]["banner_re"], text, re.I)
    return m.group(1) if m else None


def require_minimum(engine, version_str):
    """Raise EngineVersionError when `version_str` is below ENGINES[engine]['min'].
    Engines with min=None always pass. Unknown version strings pass with the caller's
    warning duty (fail-open: refusing an undetectable build would brick every exotic
    local build; the pin's job is the *detectable* substitution)."""
    spec = ENGINES[engine]
    if spec.get("min") is None or version_str is None:
        return version_str
    have, need = _tuple(version_str), _tuple(spec["min"])
    if have < need:
        raise EngineVersionError(
            "{} version {} is below the suite's pinned minimum {} ({})".format(
                engine, version_str, spec["min"], spec.get("where", "")))
    return version_str


def probe_and_require(engine, exe=None, python=None, timeout=30.0):
    """Live probe: run the engine's own version query and enforce the minimum.
    lisflood_fp: run [exe, '-v'] and read the banner. anuga/gmsh: run [python, '-c', ...].
    Returns the detected version string. Raises EngineVersionError when the probe cannot
    run or the version is too old."""
    spec = ENGINES[engine]
    if spec["probe"] == "banner":
        if not exe or not os.path.isfile(exe):
            raise EngineVersionError("cannot probe {}: executable not found: {}".format(engine, exe))
        cmd = [exe] + list(spec["probe_argv"])
    elif spec["probe"] == "python":
        if not python or not os.path.isfile(python):
            raise EngineVersionError("cannot probe {}: interpreter not found: {}".format(engine, python))
        code = "import {}; print(getattr({}, '__version__', '?'))".format(engine, engine)
        cmd = [python, "-c", code]
    else:
        raise EngineVersionError("{} has no automatic probe ({}); check it by hand".format(
            engine, spec["where"]))
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "QGIS_PREFIX_PATH"):
        env.pop(k, None)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             errors="replace", env=env, **NO_WINDOW)
    except Exception as e:
        raise EngineVersionError("{} probe failed: {}".format(engine, e))
    ver = parse_banner(out.stdout + "\n" + out.stderr, engine)
    if ver is None:
        raise EngineVersionError("{} did not print a recognizable version (got: {!r:.200})".format(
            engine, (out.stdout + out.stderr).strip()))
    return require_minimum(engine, ver)


def report():
    """The engine x minimum x detection matrix, for docs/REFERENCE.md."""
    lines = []
    for name, spec in sorted(ENGINES.items()):
        lines.append("{}: minimum {} | detected via {} ({})".format(
            name, spec.get("min") or "none (recorded only)", spec["probe"], spec["where"]))
    return "\n".join(lines)
