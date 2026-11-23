"""Which DamIT algorithms and CLI the desktop app hands off to, and how to point it at others.

DamIT Desk does not run a breach model, a screening chain or the hazard classification itself. From the Report step
it writes the dam folder and calls the DamIT QGIS plugins through ``qgis_process`` (or a DamIT runner CLI for one
dam). The defaults below are the ids the DamIT plugins publish: ``damit:classify`` (damit_hazard),
``damit_screen:preflight`` / ``damit_screen:runchain`` (damit_screener 0.2.0: the 2D screening flood) and
``damit_run:rundam`` (damit_runner 0.2.0: the model run). No batch algorithm is published; the ``batch`` role is a name only and nothing in the app starts it. Every id
stays overridable. See docs/HANDOFF.md.

Resolution order for every role (first hit wins):

1. an environment variable (``DAMIT_ALG_PREFLIGHT`` and so on, ``DAMIT_CLI`` for the CLI);
2. the JSON file named by ``DAMIT_HANDOFF_CONFIG``, else ``damit-handoff.json`` in the app's settings folder;
3. the compiled-in DamIT default.

There is deliberately no fallback to the North Dakota suite's ids (``nddam:*``, ``ndbreach:*``) or to
``ndbreach_cli.py``: a legacy id given as an override is refused with a message, never started.

The North Dakota profile (profile.py; Nick, 2026-11-22: damit-desk is the one desk, and the ND DWR desk dwr_crest
retires into it) hands off to the DWR DamSafety suite instead, as dwr_crest did: ``nddam:preflight`` /
``nddam:runchain`` (DamSafety Screening), ``ndbreach:rundam`` (DamSafety Runner, CLI ``ndbreach_cli.py``),
``ndhazard:classify`` (DamSafety Hazard), ``ndpmp:atlas14_point`` (DamSafety PMP) and ``ndfind:embankments``
(DamSafety Finder). Its overrides are ``DAMIT_ND_ALG_<ROLE>`` / ``DAMIT_ND_CLI`` and the ``"nd"`` section of
damit-handoff.json; there a DamIT id is refused instead, since the two suites live in separate QGIS profiles.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Compiled-in DamIT defaults. ``batch`` is documented only; no button starts it (one dam per run).
DEFAULT_ALGORITHMS: dict[str, str] = {
    "classify": "damit:classify",
    "preflight": "damit_screen:preflight",
    "runchain": "damit_screen:runchain",
    "rundam": "damit_run:rundam",
    "batch": "damit_run:batch",
    "data": "damit_data:download",
    "pmp": "damit_pmp:pointpf",
    "finder": "damit_find:embankments",
}

#: Which plugin is expected to publish each role, and whether that id is confirmed yet.
ROLE_INFO: dict[str, dict[str, str]] = {
    "classify": {"plugin": "damit_hazard", "status": "published", "analog": "(new in DamIT)"},
    "preflight": {"plugin": "damit_screener", "status": "published", "analog": "nddam:preflight"},
    "runchain": {"plugin": "damit_screener", "status": "published", "analog": "nddam:runchain"},
    "rundam": {"plugin": "damit_runner", "status": "published", "analog": "ndbreach:rundam"},
    "batch": {"plugin": "damit_runner", "status": "not published", "analog": "ndbreach:batch (never started by the app)"},
    "data": {"plugin": "damit_data", "status": "published", "analog": "damit_data:download"},
    "pmp": {"plugin": "damit_pmp", "status": "published", "analog": "damit_pmp:pointpf"},
    "finder": {"plugin": "damit_finder", "status": "published", "analog": "damit_find:embankments"},
}

ENV_VARS: dict[str, str] = {role: f"DAMIT_ALG_{role.upper()}" for role in DEFAULT_ALGORITHMS}

#: The North Dakota profile's defaults: the DWR DamSafety suite's published ids. DamSafety Data publishes no download
#: algorithm (its layers come from the ND offline pack), so ``data`` is empty there and its button says so.
ND_ALGORITHMS: dict[str, str] = {
    "classify": "ndhazard:classify",
    "preflight": "nddam:preflight",
    "runchain": "nddam:runchain",
    "rundam": "ndbreach:rundam",
    "batch": "ndbreach:batch",
    "data": "",
    "pmp": "ndpmp:atlas14_point",
    "finder": "ndfind:embankments",
}
ND_ROLE_INFO: dict[str, dict[str, str]] = {
    "classify": {"plugin": "DamSafety_Hazard", "status": "published", "analog": "damit:classify"},
    "preflight": {"plugin": "DamSafety_Screening", "status": "published", "analog": "damit_screen:preflight"},
    "runchain": {"plugin": "DamSafety_Screening", "status": "published", "analog": "damit_screen:runchain"},
    "rundam": {"plugin": "DamSafety_Runner", "status": "published", "analog": "damit_run:rundam"},
    "batch": {"plugin": "DamSafety_Runner", "status": "published", "analog": "(never started by the app)"},
    "data": {"plugin": "DamSafety_Data", "status": "not published", "analog": "damit_data:download (ND: the offline pack)"},
    "pmp": {"plugin": "DamSafety_PMP", "status": "published", "analog": "damit_pmp:pointpf"},
    "finder": {"plugin": "DamSafety_Finder", "status": "published", "analog": "damit_find:embankments"},
}
ND_ENV_VARS: dict[str, str] = {role: f"DAMIT_ND_ALG_{role.upper()}" for role in ND_ALGORITHMS}
ND_CLI_ENV = "DAMIT_ND_CLI"
ND_CLI_NAMES: tuple[str, ...] = ("ndbreach_cli.py",)
ND_CLI_PLUGIN_GLOBS: tuple[str, ...] = ("DamSafety_Runner", "*")


def defaults_for(profile: str) -> dict[str, str]:
    return ND_ALGORITHMS if profile == "nd" else DEFAULT_ALGORITHMS
CLI_ENV = "DAMIT_CLI"
CONFIG_ENV = "DAMIT_HANDOFF_CONFIG"
CONFIG_NAME = "damit-handoff.json"

#: File names searched for the one-dam runner CLI inside installed QGIS plugins (DamIT plugins only).
DEFAULT_CLI_NAMES: tuple[str, ...] = ("damit_cli.py", "damit_runner_cli.py")
#: Plugin folder name patterns the CLI search looks in.
CLI_PLUGIN_GLOBS: tuple[str, ...] = ("damit_runner", "damit_*", "damit")

_ALG_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:[A-Za-z][A-Za-z0-9_]*\Z")
#: Providers of the North Dakota suite. Never a DamIT default, and refused as an override.
LEGACY_PROVIDERS = ("nddam", "ndbreach", "ndhazard", "nd_hazard", "ndscreen")


class HandoffConfigError(ValueError):
    """An override is not usable. The message says which one and why."""


@dataclass
class HandoffConfig:
    algorithms: dict[str, str]
    sources: dict[str, str]
    cli: str | None = None
    cli_names: tuple[str, ...] = DEFAULT_CLI_NAMES
    problems: list[str] = field(default_factory=list)
    #: "us" (the DamIT plugins) or "nd" (the DWR DamSafety suite).
    profile: str = "us"
    cli_globs: tuple[str, ...] = CLI_PLUGIN_GLOBS

    def alg(self, role: str) -> str:
        return self.algorithms[role]

    @property
    def suite(self) -> str:
        """The plugin set, for messages."""
        return "DWR DamSafety plugins" if self.profile == "nd" else "DamIT plugins"

    def as_json(self) -> dict:
        nd = self.profile == "nd"
        info, defaults, env = (ND_ROLE_INFO, ND_ALGORITHMS, ND_ENV_VARS) if nd else (ROLE_INFO, DEFAULT_ALGORITHMS, ENV_VARS)
        return {
            "profile": self.profile,
            "algorithms": dict(self.algorithms),
            "sources": dict(self.sources),
            "roles": {role: {**info[role], "default": defaults[role], "env": env[role]} for role in defaults},
            "cli": self.cli,
            "cliNames": list(self.cli_names),
            "problems": list(self.problems),
        }


def is_legacy(alg_id: str) -> bool:
    provider = alg_id.split(":", 1)[0].lower()
    return provider in LEGACY_PROVIDERS or provider.startswith("nd_")


def is_damit(alg_id: str) -> bool:
    return alg_id.split(":", 1)[0].lower().startswith("damit")


def check_alg_id(role: str, value, profile: str = "us") -> str:
    """The id, stripped, or HandoffConfigError. Refuses the other suite's ids (ND ids in the US profile, DamIT ids in
    the ND profile) and a batch id for a one-dam role."""
    if not isinstance(value, str) or not _ALG_ID.match(value.strip()):
        raise HandoffConfigError(f"{role}: {value!r} is not a qgis_process algorithm id (provider:name)")
    alg_id = value.strip()
    if profile == "nd":
        if is_damit(alg_id):
            raise HandoffConfigError(
                f"{role}: {alg_id} is a DamIT id. The North Dakota profile hands off to the DWR DamSafety plugins "
                f"(default {ND_ALGORITHMS[role] or 'none'}); the DamIT plugins live in another QGIS profile."
            )
    elif is_legacy(alg_id):
        raise HandoffConfigError(
            f"{role}: {alg_id} is a North Dakota suite id. DamIT Desk hands off to the DamIT plugins only; "
            f"use the DamIT id (default {DEFAULT_ALGORITHMS[role]})."
        )
    if role != "batch" and alg_id.split(":", 1)[1].lower() == "batch":
        raise HandoffConfigError(f"{role}: {alg_id} looks like a batch algorithm; the one-dam buttons never start batch")
    return alg_id


def config_path(settings_dir: Path | None = None) -> Path | None:
    raw = (os.environ.get(CONFIG_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    if settings_dir is not None:
        return Path(settings_dir) / CONFIG_NAME
    return None


def _read_file(path: Path | None, problems: list[str]) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"{path} was not read: {exc}")
        return {}
    if not isinstance(data, dict):
        problems.append(f"{path} is not a JSON object; ignored")
        return {}
    return data


def load_config(settings_dir: Path | None = None, profile: str | None = None) -> HandoffConfig:
    """Resolve every role for the profile (default: the job's, profile.current()). A bad override is reported in
    ``problems`` and the default is kept."""
    from damit_desktop import profile as desk_profile

    chosen_profile = desk_profile.normalize(profile if profile is not None else desk_profile.current())
    problems: list[str] = []
    path = config_path(settings_dir)
    data = _read_file(path, problems)
    if chosen_profile == "nd":
        return _load_nd(data, path, problems)
    file_algs = data.get("algorithms") if isinstance(data.get("algorithms"), dict) else {}
    algorithms: dict[str, str] = {}
    sources: dict[str, str] = {}
    for role, default in DEFAULT_ALGORITHMS.items():
        chosen, source = default, "default"
        for value, where in ((os.environ.get(ENV_VARS[role]), ENV_VARS[role]), (file_algs.get(role), str(path))):
            if value in (None, ""):
                continue
            try:
                chosen, source = check_alg_id(role, value), where
                break
            except HandoffConfigError as exc:
                problems.append(f"{exc} (from {where}); kept {default}")
        algorithms[role], sources[role] = chosen, source
    cli = (os.environ.get(CLI_ENV) or "").strip() or (str(data.get("cli") or "").strip() or None)
    if cli and "ndbreach" in Path(cli).name.lower():
        problems.append(f"{cli} is the North Dakota runner CLI; DamIT Desk does not call it")
        cli = None
    names = data.get("cliNames")
    cli_names = tuple(str(n) for n in names if isinstance(n, str) and n.endswith(".py")) if isinstance(names, list) else ()
    cli_names = tuple(n for n in cli_names if "ndbreach" not in n.lower()) or DEFAULT_CLI_NAMES
    return HandoffConfig(algorithms=algorithms, sources=sources, cli=cli, cli_names=cli_names, problems=problems)


def _load_nd(data: dict, path: Path | None, problems: list[str]) -> HandoffConfig:
    """The North Dakota profile: DAMIT_ND_ALG_<ROLE>, else damit-handoff.json's "nd" section, else ND_ALGORITHMS."""
    section = data.get("nd") if isinstance(data.get("nd"), dict) else {}
    file_algs = section.get("algorithms") if isinstance(section.get("algorithms"), dict) else {}
    where_file = f"{path} (nd)"
    algorithms: dict[str, str] = {}
    sources: dict[str, str] = {}
    for role, default in ND_ALGORITHMS.items():
        chosen, source = default, "default"
        for value, where in ((os.environ.get(ND_ENV_VARS[role]), ND_ENV_VARS[role]), (file_algs.get(role), where_file)):
            if value in (None, ""):
                continue
            try:
                chosen, source = check_alg_id(role, value, "nd"), where
                break
            except HandoffConfigError as exc:
                problems.append(f"{exc} (from {where}); kept {default or 'none'}")
        algorithms[role], sources[role] = chosen, source
    cli = (os.environ.get(ND_CLI_ENV) or "").strip() or (str(section.get("cli") or "").strip() or None)
    names = section.get("cliNames")
    cli_names = tuple(str(n) for n in names if isinstance(n, str) and n.endswith(".py")) if isinstance(names, list) else ()
    return HandoffConfig(algorithms=algorithms, sources=sources, cli=cli, cli_names=cli_names or ND_CLI_NAMES,
                         problems=problems, profile="nd", cli_globs=ND_CLI_PLUGIN_GLOBS)


def qgis_profile_roots(home: Path | None = None) -> list[Path]:
    """QGIS profile folders on macOS, Linux and Windows (QGIS 3 and 4 keep the QGIS3 folder name)."""
    home = home or Path.home()
    roots = [
        home / "Library/Application Support/QGIS/QGIS3/profiles",
        home / ".local/share/QGIS/QGIS3/profiles",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "QGIS/QGIS3/profiles")
    return roots


def find_damit_cli(config: HandoffConfig, home: Path | None = None) -> str | None:
    """The one-dam runner CLI: DAMIT_CLI / DAMIT_ND_CLI / the config's ``cli``, else a search of the profile's plugin
    folders (DamIT's damit_cli.py, or the DWR Runner's ndbreach_cli.py in the ND profile)."""
    if config.cli:
        return config.cli if Path(config.cli).is_file() else None
    for root in qgis_profile_roots(home):
        if not root.is_dir():
            continue
        for plugin_glob in config.cli_globs:
            for name in config.cli_names:
                for pattern in (f"*/python/plugins/{plugin_glob}/scripts/{name}", f"*/python/plugins/{plugin_glob}/{name}"):
                    found = sorted(root.glob(pattern))
                    if found:
                        return str(found[-1])
    return None
