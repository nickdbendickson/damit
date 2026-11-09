"""DamIT hand-off wiring: algorithm ids (defaults and overrides), no ND-suite fallback, the piping default, the DamIT
runner CLI search, and damit:classify. Runs against a fake qgis_process; nothing real is ever started.

    python3 damit_crest/desktop/tests/test_algorithms.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))

import damit_desktop.qgis_run as qr  # noqa: E402
from damit_desktop.algorithms import (  # noqa: E402
    DEFAULT_ALGORITHMS,
    ENV_VARS,
    HandoffConfigError,
    check_alg_id,
    find_damit_cli,
    load_config,
)
from damit_desktop.handoff import resolved_failure_mode, write_dam_folder  # noqa: E402

# The parameter lists of the published DamIT algorithms: damit_screener / damit_runner 0.1.0 (SWE, PR #2) and
# damit_hazard's damit:classify (QGIS Dev, PR #1). FAKE_STYLE=nd gives rundam an ND-style port's METHOD / TIER enums.
FAKE_QGIS = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ["CALLS"]).open("a").write(" ".join(args) + "\n")
if any(a.startswith(("nddam:", "ndbreach:", "nd_")) for a in args):
    sys.exit(42)
missing = [x for x in os.environ.get("QGIS_MISSING", "").split(",") if x]
SCREEN = ["WORK", "DAMS", "FIELD_MAP", "MODE", "PRESET", "SCENARIOS", "METHODS", "RECEPTORS", "TERRAIN",
          "APPLY_ADVISORIES", "SETTINGS"]
LISTS = {
    "preflight": SCREEN + ["REPORT"],
    "runchain": SCREEN + ["PREFLIGHT", "FAIL_ON_ERROR"],
    "rundam": ["HANDOFF", "DAM_ID", "X", "Y", "CRS", "HEIGHT_FT", "STORAGE_ACFT", "MODE", "PRESET", "SCENARIOS",
               "METHODS", "TERRAIN", "HYDROGRAPH", "OUTPUT_FOLDER", "ENGINE", "DRY_RUN"],
}
ENUMS = {"MODE": ["preset", "custom"], "ENGINE": ["None - prepare and record the run only (0.1.0)", "LISFLOOD-FP"],
         "PRESET@classify": ["Custom (methods ticked below)", "FEMA P-333 baseline", "Nebraska (unverified)", "North Dakota"]}
if args[:1] == ["help"]:
    if args[1] in missing:
        sys.exit(1)
    name = args[1].split(":", 1)[1]
    if name == "classify":
        params = ["PRESET", "METHODS", "MODIFIERS", "SCENARIOS", "OVERRIDES", "APPLY_ADVISORY", "RUN_SCENARIO",
                  "MODEL_DIM", "DEPTH", "VELOCITY", "DV", "STRUCTURES", "DAM_JSON", "DAM_NAME", "OUTPUT"]
    elif name == "rundam" and os.environ.get("FAKE_STYLE") == "nd":
        params = ["DAM_ID", "DAMS_FOLDER", "DEM", "METHOD", "TIER", "HEIGHT_FT", "STORAGE_ACFT", "TOP_FT"]
        ENUMS["METHOD"] = ["Overtopping failure, Froehlich (2008) parameters, routed",
                           "Piping failure, Froehlich (2008) parameters, routed"]
        ENUMS["TIER"] = ["LISFLOOD-FP only"]
    else:
        params = LISTS.get(name, ["WORK"])
    for p in params:
        print(p + ": " + p.title())
        opts = ENUMS.get(p + "@" + name) or ENUMS.get(p)
        if opts:
            print("\tArgument type:\tenum")
            print("\tAvailable values:")
            for i, o in enumerate(opts):
                print("\t\t- %d: %s" % (i, o))
    sys.exit(0)
vals = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
if any(a.endswith(":preflight") for a in args):
    print("READY:\ttrue")
    print("FAILS:\t0")
if any(a.endswith(":runchain") for a in args) and os.environ.get("FAKE_PACKAGE"):
    settings = json.loads(Path(vals["SETTINGS"]).read_text())
    for dam_id in settings.get("dam_ids", []):
        folder = Path(vals["WORK"]) / "handoff" / dam_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "damit_handoff.json").write_text(json.dumps({"schema": "damit.handoff", "screening": {
            "status": "computed_preliminary", "suggested_label": "Significant", "suggested_ordinal": 2,
            "flags": ["preliminary"]}}))
if any(a.endswith(":rundam") for a in args) and "OUTPUT_FOLDER" in vals:
    print("RUN_FOLDER:\t" + vals["OUTPUT_FOLDER"] + "/run_1")
    print("STATUS:\tprepared")
if any(a.endswith(":classify") for a in args):
    print("CLASS:\tSignificant")
    print("ORDINAL:\t2")
sys.exit(0)
"""

FAKE_CLI = r"""#!/usr/bin/env python3
import os, sys
from pathlib import Path
Path(os.environ["CALLS"]).open("a").write("CLI " + " ".join(sys.argv[1:]) + "\n")
"""

DAM = {
    "nid": "XX00001",
    "name": "Test dam",
    "heightFt": 20,
    "storageAcFt": 300,
    "statedDatum": "NAVD88",
    "method": "froehlich",
    "lon": -100.0,
    "lat": 46.75,
}
ANALYSIS = {"datum": {"crestNavdFt": 1000.0}, "breach": {"series": []}, "screen": {"level": "Low"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.calls = self.root / "calls.txt"
        self.qgis = self.root / "qgis_process"
        self.qgis.write_text(FAKE_QGIS, encoding="utf-8")
        self.qgis.chmod(0o755)
        clean = {k: "" for k in ENV_VARS.values()}
        self.env = mock.patch.dict(
            os.environ,
            {
                **clean,
                "HOME": str(self.home),
                "QGIS_PROCESS": str(self.qgis),
                "CALLS": str(self.calls),
                "DAMIT_CLI": "",
                "DAMIT_HANDOFF_CONFIG": "",
                "DAMIT_DATA": "",
                "NDSUITE_DATA": "",
                "DAMIT_DEM": "",
                "QGIS_MISSING": "",
                "FAKE_STYLE": "",
                "FAKE_PACKAGE": "",
                "APPDATA": "",
            },
        )
        self.env.start()
        qr._ENUM_HELP.clear()
        self.saved_dir = qr.SETTINGS_DIR
        qr.SETTINGS_DIR = self.root / "settings"
        qr.SETTINGS_DIR.mkdir()
        self.lines: list[str] = []

    def tearDown(self):
        qr.SETTINGS_DIR = self.saved_dir
        qr._ENUM_HELP.clear()
        self.env.stop()
        self.tmp.cleanup()

    def log(self, line):
        self.lines.append(str(line))

    def calls_text(self) -> str:
        return self.calls.read_text(encoding="utf-8") if self.calls.is_file() else ""

    def work_with_dem(self) -> Path:
        work = self.root / "work"
        work.mkdir(exist_ok=True)
        (work / "dem.tif").write_bytes(b"not a dem")
        return work


class ConfigTests(Base):
    def test_defaults_are_the_damit_ids(self):
        cfg = load_config(qr.SETTINGS_DIR)
        self.assertEqual(cfg.algorithms, DEFAULT_ALGORITHMS)
        self.assertEqual(
            DEFAULT_ALGORITHMS,
            {
                "classify": "damit:classify",
                "preflight": "damit_screen:preflight",
                "runchain": "damit_screen:runchain",
                "rundam": "damit_run:rundam",
                "batch": "damit_run:batch",
            },
        )
        self.assertTrue(all(src == "default" for src in cfg.sources.values()))
        self.assertEqual(cfg.problems, [])

    def test_environment_beats_the_file_beats_the_default(self):
        (qr.SETTINGS_DIR / "damit-handoff.json").write_text(
            json.dumps({"algorithms": {"preflight": "damit_screener:preflight", "rundam": "damit_runner:rundam"}}),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"DAMIT_ALG_RUNDAM": "damitrun:onedam"}):
            cfg = load_config(qr.SETTINGS_DIR)
        self.assertEqual(cfg.alg("preflight"), "damit_screener:preflight")
        self.assertEqual(cfg.alg("rundam"), "damitrun:onedam")
        self.assertEqual(cfg.sources["rundam"], "DAMIT_ALG_RUNDAM")
        self.assertEqual(cfg.alg("runchain"), "damit_screen:runchain")

    def test_config_path_from_the_environment(self):
        path = self.root / "elsewhere.json"
        path.write_text(json.dumps({"algorithms": {"classify": "damit_hazard:classify"}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMIT_HANDOFF_CONFIG": str(path)}):
            self.assertEqual(load_config(None).alg("classify"), "damit_hazard:classify")

    def test_legacy_nd_ids_are_refused_and_the_damit_default_kept(self):
        with mock.patch.dict(os.environ, {"DAMIT_ALG_PREFLIGHT": "nddam:preflight", "DAMIT_ALG_RUNDAM": "ndbreach:rundam"}):
            cfg = load_config(None)
        self.assertEqual(cfg.alg("preflight"), "damit_screen:preflight")
        self.assertEqual(cfg.alg("rundam"), "damit_run:rundam")
        self.assertEqual(len(cfg.problems), 2)
        self.assertTrue(all("North Dakota suite id" in p for p in cfg.problems))

    def test_batch_is_refused_for_the_one_dam_role(self):
        with self.assertRaises(HandoffConfigError):
            check_alg_id("rundam", "damit_run:batch")
        with self.assertRaises(HandoffConfigError):
            check_alg_id("rundam", "not an id")
        self.assertEqual(check_alg_id("batch", "damit_run:batch"), "damit_run:batch")

    def test_a_broken_file_is_reported_not_fatal(self):
        (qr.SETTINGS_DIR / "damit-handoff.json").write_text("{not json", encoding="utf-8")
        cfg = load_config(qr.SETTINGS_DIR)
        self.assertEqual(cfg.algorithms, DEFAULT_ALGORITHMS)
        self.assertTrue(cfg.problems)


class CliSearchTests(Base):
    def plugin_file(self, plugin: str, name: str) -> Path:
        path = self.home / ".local/share/QGIS/QGIS3/profiles/default/python/plugins" / plugin / "scripts" / name
        path.parent.mkdir(parents=True)
        path.write_text(FAKE_CLI, encoding="utf-8")
        return path

    def test_finds_the_damit_runner_cli_in_a_damit_plugin(self):
        path = self.plugin_file("damit_runner", "damit_cli.py")
        self.assertEqual(find_damit_cli(load_config(None)), str(path))

    def test_ignores_the_nd_runner_cli(self):
        self.plugin_file("DamSafety_Runner", "ndbreach_cli.py")
        self.assertIsNone(find_damit_cli(load_config(None)))
        nd = self.root / "ndbreach_cli.py"
        nd.write_text(FAKE_CLI, encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMIT_CLI": str(nd)}):
            cfg = load_config(None)
        self.assertIsNone(cfg.cli)
        self.assertTrue(any("North Dakota runner CLI" in p for p in cfg.problems))

    def test_finds_the_cli_in_a_windows_profile(self):
        appdata = self.root / "AppData"
        path = appdata / "QGIS/QGIS3/profiles/default/python/plugins/damit_runner/scripts/damit_cli.py"
        path.parent.mkdir(parents=True)
        path.write_text(FAKE_CLI, encoding="utf-8")
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
            self.assertEqual(find_damit_cli(load_config(None)), str(path))


class HandoffRunTests(Base):
    def test_screening_uses_the_damit_ids_and_never_an_nd_id(self):
        result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        text = self.calls_text()
        self.assertIn("run damit_screen:preflight", text)
        self.assertIn("run damit_screen:runchain", text)
        self.assertNotIn("nddam", text)
        self.assertNotIn("ndbreach", text)

    def test_an_override_is_what_runs(self):
        with mock.patch.dict(os.environ, {"DAMIT_ALG_PREFLIGHT": "damit_screener:preflight", "DAMIT_ALG_RUNCHAIN": "damit_screener:runchain"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertIn("run damit_screener:preflight", self.calls_text())
        self.assertIn("run damit_screener:runchain", self.calls_text())
        self.assertIn("preflight: damit_screener:preflight (from DAMIT_ALG_PREFLIGHT)", self.lines)

    def test_a_missing_algorithm_stops_before_anything_runs(self):
        with mock.patch.dict(os.environ, {"QGIS_MISSING": "damit_screen:runchain"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missingAlgorithm"], "damit_screen:runchain")
        self.assertNotIn("run ", self.calls_text())
        self.assertTrue(any("not installed" in line and "DAMIT_ALG_RUNCHAIN" in line + " ".join(self.lines) for line in self.lines))
        self.assertTrue(any("ND suite ids are not used as a fallback" in line for line in self.lines))

    def test_missing_rundam_does_not_fall_back(self):
        work = self.work_with_dem()
        with mock.patch.dict(os.environ, {"QGIS_MISSING": "damit_run:rundam"}):
            result = qr.run_model(DAM, ANALYSIS, str(work), self.log)
        self.assertFalse(result["ok"])
        self.assertNotIn("run ", self.calls_text())
        self.assertNotIn("ndbreach", self.calls_text())

    def test_one_dam_model_runs_rundam_never_batch(self):
        work = self.work_with_dem()
        result = qr.run_model(DAM, ANALYSIS, str(work), self.log)
        self.assertTrue(result["ok"], self.lines)
        text = self.calls_text()
        self.assertIn("run damit_run:rundam", text)
        self.assertNotIn("batch", text)
        self.assertTrue(any("damit_run:batch was not started" in line for line in self.lines))


class PublishedInterfaceTests(Base):
    """The arguments damit_screen:preflight / runchain and damit_run:rundam (0.1.0) declare, and nothing else."""

    def runs(self) -> list[str]:
        return [line for line in self.calls_text().splitlines() if line.startswith("run ")]

    def test_screening_sends_a_dams_layer_mode_preset_and_settings(self):
        dam = {**DAM, "classification": {"mode": "preset", "preset": "NE"}}
        result = qr.run_screening(dam, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        pre, chain = self.runs()
        work = self.root / "work"
        for run in (pre, chain):
            self.assertIn(f"--WORK={work.resolve()}", run)
            self.assertIn("--DAMS=" + str(Path(result["folder"]) / "dam_point.geojson"), run)
            self.assertIn("--MODE=0", run)
            self.assertIn("--PRESET=NE", run)
            self.assertIn("--SETTINGS=", run)
        self.assertIn("--REPORT=", pre)
        self.assertIn("--PREFLIGHT=true", chain)
        self.assertIn("--FAIL_ON_ERROR=true", chain)
        self.assertNotIn("--DAM_ID=", chain)  # damit_screen:runchain filters by the settings' dam_ids
        self.assertNotIn("--LOG=", chain)
        settings = json.loads((work / "damit_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["dam_ids"], ["XX00001"])
        layer = json.loads((Path(result["folder"]) / "dam_point.geojson").read_text(encoding="utf-8"))
        feature = layer["features"][0]
        self.assertEqual(feature["geometry"]["coordinates"], [-100.0, 46.75])
        self.assertEqual(feature["properties"]["dam_id"], "XX00001")
        self.assertEqual(feature["properties"]["storage_acft"], 300)
        self.assertEqual(feature["properties"]["top_of_dam_elev_ft"], 1000.0)

    def test_custom_mode_sends_scenarios_and_methods(self):
        dam = {**DAM, "classification": {"mode": "custom", "methods": ["S1", "S5", "M1", "M13", "R2"]}}
        qr.run_screening(dam, ANALYSIS, str(self.root / "work"), self.log)
        pre = self.runs()[0]
        self.assertIn("--MODE=1", pre)
        self.assertIn("--SCENARIOS=S1,S5", pre)
        self.assertIn("--METHODS=M1,M13", pre)
        self.assertNotIn("--PRESET=", pre)

    def test_the_hand_off_package_is_read_back(self):
        with mock.patch.dict(os.environ, {"FAKE_PACKAGE": "1"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertEqual(result["screening"]["suggested_label"], "Significant")
        self.assertTrue(any("preliminary Significant" in line and "not an official" in line for line in self.lines))

    def test_rundam_uses_the_package_and_a_dry_run(self):
        work = self.work_with_dem()
        with mock.patch.dict(os.environ, {"FAKE_PACKAGE": "1"}):
            qr.run_screening(DAM, ANALYSIS, str(work), self.log)
        result = qr.run_model(DAM, ANALYSIS, str(work), self.log)
        self.assertTrue(result["ok"], self.lines)
        run = self.runs()[-1]
        self.assertTrue(run.startswith("run damit_run:rundam "))
        self.assertIn("--HANDOFF=" + str(work.resolve() / "handoff" / "XX00001" / "damit_handoff.json"), run)
        self.assertIn("--DRY_RUN=true", run)
        self.assertIn("--OUTPUT_FOLDER=" + str(work.resolve() / "runs"), run)
        self.assertNotIn("--ENGINE=", run)  # the runner's default: prepare and record only
        self.assertNotIn("--DAMS_FOLDER=", run)
        self.assertEqual(result["runFolder"], str(work.resolve() / "runs") + "/run_1")

    def test_rundam_without_a_package_sends_the_dam(self):
        result = qr.run_model(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)  # damit_run:rundam takes no DEM parameter; terrain is a gap
        run = self.runs()[-1]
        self.assertNotIn("--HANDOFF=", run)
        for arg in ("--DAM_ID=XX00001", "--X=-100.0", "--Y=46.75", "--CRS=EPSG:4326", "--HEIGHT_FT=20.0",
                    "--STORAGE_ACFT=300.0", "--MODE=0", "--DRY_RUN=true"):
            self.assertIn(arg, run)
        self.assertNotIn("--TERRAIN=", run)
        self.assertTrue(any("records the terrain as a gap" in line for line in self.lines))


class PipingDefaultTests(Base):
    def test_resolved_failure_mode(self):
        self.assertEqual(resolved_failure_mode({}), "piping")
        self.assertEqual(resolved_failure_mode({"failureMode": None}), "piping")
        self.assertEqual(resolved_failure_mode({"failureMode": "sideways"}), "piping")
        self.assertEqual(resolved_failure_mode({"failureMode": "Overtopping"}), "overtopping")
        self.assertEqual(qr._method_key({}), ("froehlich", "piping"))

    def test_rundam_gets_the_piping_option_when_none_was_chosen(self):
        # An ND-style runner port with a METHOD enum: the piping option's index is sent.
        work = self.work_with_dem()
        with mock.patch.dict(os.environ, {"FAKE_STYLE": "nd"}):
            qr.run_model(DAM, ANALYSIS, str(work), self.log)
        self.assertIn("--METHOD=1", self.calls_text())  # index 1 = the piping label in the fake help
        self.assertTrue(any(line.startswith("Failure mode: piping (the default") for line in self.lines))

    def test_cli_config_and_dam_json_say_piping(self):
        work = self.work_with_dem()
        cli = self.root / "damit_cli.py"
        cli.write_text(FAKE_CLI, encoding="utf-8")
        dam = {**DAM, "lisflood": {"pointX": 1.0, "pointY": 2.0}}
        with mock.patch.dict(os.environ, {"DAMIT_CLI": str(cli), "DAMIT_PYTHON": sys.executable}):
            result = qr.run_model(dam, ANALYSIS, str(work), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertIn("CLI run ", self.calls_text())
        cfg = json.loads((Path(result["folder"]) / "runner_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["breach"], {"method": "piping", "failure_mode": "piping"})
        record = json.loads((Path(result["folder"]) / "dam.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"][-1]["result"]["failure_mode"], "piping")

    def test_the_dams_layer_says_piping(self):
        result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        layer = json.loads((Path(result["folder"]) / "dam_point.geojson").read_text(encoding="utf-8"))
        self.assertEqual(layer["features"][0]["properties"]["failure_mode"], "piping")

    def test_a_chosen_overtopping_is_kept(self):
        work = self.work_with_dem()
        with mock.patch.dict(os.environ, {"FAKE_STYLE": "nd"}):
            qr.run_model({**DAM, "failureMode": "overtopping"}, ANALYSIS, str(work), self.log)
        self.assertIn("--METHOD=0", self.calls_text())


class ClassificationTests(Base):
    def test_dam_json_and_settings_carry_the_choice(self):
        dam = {**DAM, "classification": {"mode": "preset", "preset": "NE", "catalogVersion": "2026-11-09"}}
        with tempfile.TemporaryDirectory() as d:
            folder, _ = write_dam_folder(Path(d), dam, ANALYSIS)
            record = json.loads((folder / "dam.json").read_text(encoding="utf-8"))
        self.assertEqual(record["format"], "damit/dam_record")
        self.assertEqual(record["classification"]["mode"], "preset")
        self.assertEqual(record["classification"]["preset"], "NE")
        self.assertEqual(record["classification"]["tool"], "damit_crest")
        qr.run_screening(dam, ANALYSIS, str(self.root / "work"), self.log)
        settings = json.loads((self.root / "work" / "damit_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["classification"]["preset"], "NE")
        self.assertEqual(settings["format"], "damit/settings")

    def test_custom_mode_keeps_only_method_ids(self):
        dam = {**DAM, "classification": {"mode": "custom", "methods": ["S1", "M2", "R7", "nddam:runchain", "x"]}}
        with tempfile.TemporaryDirectory() as d:
            folder, _ = write_dam_folder(Path(d), dam, ANALYSIS)
            record = json.loads((folder / "dam.json").read_text(encoding="utf-8"))
        self.assertEqual(record["classification"]["methods"], ["S1", "M2", "R7"])
        self.assertNotIn("preset", record["classification"])

    def depth(self) -> str:
        path = self.root / "depth.tif"
        path.write_bytes(b"not a raster")
        return str(path)

    def classify_run(self) -> str:
        return [line for line in self.calls_text().splitlines() if line.startswith("run ")][0]

    def test_classify_sends_the_preset_index_depth_and_flat_record(self):
        dam = {**DAM, "depthRaster": self.depth(),
               "classification": {"mode": "preset", "preset": "NE", "presetLabel": "Nebraska"}}
        result = qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        run = self.classify_run()
        self.assertTrue(run.startswith("run damit:classify "))
        self.assertIn("--PRESET=2", run)  # "Nebraska (unverified)" in the fake help
        self.assertIn("--DEPTH=" + str(Path(dam["depthRaster"]).resolve()), run)
        self.assertIn("--OUTPUT=", run)
        self.assertNotIn("--METHODS=", run)
        self.assertNotIn("--WORK=", run)  # not a damit:classify parameter, so not sent
        record = json.loads((Path(result["folder"]) / "damit_dam.json").read_text(encoding="utf-8"))
        self.assertEqual(record["storage_acft"], 300)
        self.assertIn("--DAM_JSON=" + str(Path(result["folder"]) / "damit_dam.json"), run)
        self.assertEqual(result["suggestedClass"], "Significant")

    def test_classify_custom_mode_splits_the_ids(self):
        dam = {**DAM, "depthRaster": self.depth(),
               "classification": {"mode": "custom", "methods": ["S1", "M2", "M8a", "R1"]}}
        qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log)
        run = self.classify_run()
        self.assertIn("--PRESET=0", run)  # Custom
        self.assertIn("--METHODS=M2,M8a", run)
        self.assertIn("--SCENARIOS=S1", run)
        self.assertIn("--MODIFIERS=R1", run)

    def test_classify_without_a_depth_raster_stops(self):
        result = qr.run_classify({**DAM, "classification": {"mode": "preset", "preset": "FEMA333"}}, ANALYSIS,
                                 str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertNotIn("run ", self.calls_text())
        self.assertTrue(any("depth raster" in line for line in self.lines))

    def test_classify_unknown_preset_stops(self):
        dam = {**DAM, "depthRaster": self.depth(), "classification": {"mode": "preset", "preset": "ZZ"}}
        result = qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertNotIn("run ", self.calls_text())

    def test_classify_missing_stops(self):
        with mock.patch.dict(os.environ, {"QGIS_MISSING": "damit:classify"}):
            result = qr.run_classify(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missingAlgorithm"], "damit:classify")
        self.assertNotIn("run ", self.calls_text())


class DataFolderTests(Base):
    def test_damit_data_first_nd_pack_only_as_an_example(self):
        from damit_desktop.layers import find_data_folder_with_source, use_data_folder

        nd = self.root / "ndpack"
        nd.mkdir()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": str(nd)}):
            folder, where = find_data_folder_with_source()
            self.assertEqual(folder, str(nd.resolve()))
            self.assertIn("North Dakota example", where)
            (self.root / "work").mkdir()
            result = use_data_folder(self.root / "work", self.log)
            self.assertTrue(result["ok"])
            self.assertTrue(any("example data source" in line for line in self.lines))
            damit = self.root / "damitdata"
            damit.mkdir()
            with mock.patch.dict(os.environ, {"DAMIT_DATA": str(damit)}):
                self.assertEqual(find_data_folder_with_source(), (str(damit.resolve()), "DAMIT_DATA"))

    def test_default_work_folder_is_damitdams(self):
        with mock.patch.dict(os.environ, {"DAMIT_WORK": ""}):
            self.assertEqual(qr.work_dir(None), (self.home / "DamITDams").resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
