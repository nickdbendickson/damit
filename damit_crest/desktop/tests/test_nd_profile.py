"""North Dakota profile hand-off (profile.py): the DWR DamSafety suite's ids, its qgis_process launcher, DWR structure
ids as dam ids, the ND offline pack folder, ndhazard:classify and the DWR chain's own dam names. The US profile is
checked to be unchanged beside each. Runs against a fake qgis_process; nothing real is ever started.

    python3 damit_crest/desktop/tests/test_nd_profile.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import damit_desktop.qgis_run as qr  # noqa: E402
from damit_desktop import classify_receptors as cr  # noqa: E402
from damit_desktop import layers  # noqa: E402
from damit_desktop.algorithms import (  # noqa: E402
    ENV_VARS,
    ND_ALGORITHMS,
    ND_ENV_VARS,
    HandoffConfigError,
    check_alg_id,
    find_damit_cli,
    load_config,
)
from damit_desktop.handoff import handoff_ids, lonlat_to_5070, nid_problem  # noqa: E402
from damit_desktop.profile import current, normalize, profile_scope  # noqa: E402
from fakeproc import write_exe  # noqa: E402

#: The DWR suite's published parameter lists (DamSafety Screening / Runner / Hazard), enough for the desk's filter.
FAKE_QGIS = r"""#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ["CALLS"]).open("a").write(" ".join(args) + "\n")
if any(a.startswith("damit") for a in args):
    sys.exit(42)
LISTS = {
    "preflight": ["WORK", "REPORT", "SETTINGS"],
    "runchain": ["WORK", "DAM_ID", "PREFLIGHT", "FAIL_ON_ERROR", "LOG", "SETTINGS"],
    "rundam": ["DAM_ID", "NID_ID", "DAMS_FOLDER", "DEM", "METHOD", "TIER", "LISFLOOD_EXE", "HEIGHT_FT",
               "STORAGE_ACFT", "TOP_FT", "AREA_AC", "DAM_LINES"],
    "classify": ["DAM_FOLDER", "DEPTH", "VELOCITY", "ARRIVAL", "DXV", "BASE_DEPTH", "ROADS", "RAIL",
                 "DOWNLOAD_NSI", "DOWNLOAD_ADDRESS"],
    "atlas14_point": ["POINT", "OUTPUT_CSV", "OUTPUT_JSON", "VOLUME"],
    "embankments": ["DEM", "OUT", "MIN_HEIGHT_FT"],
}
ENUMS = {"METHOD": ["Piping failure, Froehlich (2008) parameters, routed"], "TIER": ["LISFLOOD-FP only"]}
if args[:1] == ["help"]:
    name = args[1].split(":", 1)[1]
    for p in LISTS.get(name, []):
        print(p + ": " + p.title())
        if p in ENUMS:
            print("\tArgument type:\tenum")
            print("\tAvailable values:")
            for i, o in enumerate(ENUMS[p]):
                print("\t\t- %d: %s" % (i, o))
    print(args[1])
    sys.exit(0)
if any(a.endswith(":preflight") for a in args):
    print("READY:\ttrue")
if any(a.endswith(":classify") for a in args):
    print("ND_CLASS:\tHigh")
    print("TM11_CLASS:\tSignificant")
    print("REPORT_PDF:\t/tmp/report.pdf")
    folder = next((a.split("=", 1)[1] for a in args if a.startswith("--DAM_FOLDER=")), "")
    if folder:
        print("OUTPUT_FOLDER:\t" + os.path.join(folder, "outputs"))
sys.exit(0)
"""

def _gp(wkb: bytes) -> bytes:
    """A GeoPackage blob (no envelope, EPSG:5070) around a little-endian WKB geometry."""
    return b"GP\x00\x01" + struct.pack("<i", 5070) + wkb


def _xy(pts):
    return [lonlat_to_5070(lon, lat) for lon, lat in pts]


def nd_polygon(pts) -> bytes:
    """A MultiPolygon of one ring, as ndhazard:classify writes Habitable_Structures (EPSG:5070)."""
    ring = _xy(pts)
    poly = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", *p) for p in ring)
    return _gp(struct.pack("<BII", 1, 6, 1) + poly)


def nd_line(pts) -> bytes:
    xy = _xy(pts)
    return _gp(struct.pack("<BII", 1, 2, len(xy)) + b"".join(struct.pack("<dd", *p) for p in xy))


#: Columns of ndhazard:classify 2.25.8's layers (a real Absaraka ND00199 run, 2026-11-22), the ones the desk reads.
ND_LAYERS = {
    "Habitable_Structures": ("Struct_ID integer, Address text, City text, Occupancy text, Habitable text, ACER_Type text, "
                             "ACER_Zone_Label text, ND_Outcome text, Max_Depth_ft real, Max_Vel_fps real", "MULTIPOLYGON"),
    "Roads_Inundated": ("Road_Name text, Road_Class text, AADT real, ND_Class text, ND_Basis text, Max_Depth_ft real, "
                        "Max_Vel_fps real", "LINESTRING"),
    "Rail_Inundated": ("Railroad text, Subdivision text, Passenger text, ND_Class text, ND_Basis text, Max_Depth_ft real, "
                       "Max_Vel_fps real", "LINESTRING"),
}
HOUSE = [(-97.3578, 46.9555), (-97.3576, 46.9555), (-97.3576, 46.9556), (-97.3578, 46.9555)]


def make_nd_layers(folder: Path, rail_basis: str = "22 trains/day >= 10 - probable loss of life") -> Path:
    """<folder>/Habitable_Structures.gpkg, Roads_Inundated.gpkg, Rail_Inundated.gpkg in ndhazard:classify's layout."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = {
        "Habitable_Structures": [
            (1086, None, None, "RES1-2SWB", "Yes", "House on foundation", "HIGH", "Probable loss of life", 6.1, 4.08,
             nd_polygon(HOUSE)),
            (778, "1341 MORNINGSIDE DR", "CASSELTON", "RES1-1SWB", "Yes", "Habitable", "JUDGMENT", "Judgment zone", 5.05,
             1.2, nd_polygon(HOUSE)),
            (2201, None, None, "", "Unverified", "House on foundation", "JUDGMENT", "Judgment zone", 4.79, 1.0,
             nd_polygon(HOUSE)),
            (5, None, None, "RES1", "Yes", "Habitable", "LOW", "Below consequence depth", 0.2, 0.1, nd_polygon(HOUSE)),
            (1, "15854 36TH ST SE", "CASSELTON", "AGR1", "Yes", "Habitable", "DRY", "Not inundated", None, None,
             nd_polygon(HOUSE)),
        ],
        "Roads_Inundated": [
            ("LANGER AVE S", "State Highway", 3423.0, "High", "AADT 3,423 > 2,000 - probable loss of life", 2.29, 0.94,
             nd_line([(-97.2120, 46.8968), (-97.2118, 46.8970)])),
            ("6TH AVE S", "Local/County", None, "Medium",
             "no AADT found - assumed Medium for a public road (verify traffic)", 1.6, 0.6,
             nd_line([(-97.2, 46.89), (-97.19, 46.89)])),
        ],
        "Rail_Inundated": [
            ("BNSF", "KO", "No", "High", rail_basis, 2.44, 3.29, nd_line([(-97.2170, 46.9000), (-97.2130, 46.9005)])),
        ],
    }
    for table, (cols, gtype) in ND_LAYERS.items():
        (folder / f"{table}.gpkg").unlink(missing_ok=True)  # a rerun writes the layers anew, as the plugin does
        con = sqlite3.connect(folder / f"{table}.gpkg")
        con.execute("create table gpkg_spatial_ref_sys (srs_id integer, organization text, organization_coordsys_id integer)")
        con.execute("insert into gpkg_spatial_ref_sys values (5070, 'EPSG', 5070)")
        con.execute("create table gpkg_contents (table_name text, data_type text, srs_id integer)")
        con.execute("insert into gpkg_contents values (?, 'features', 5070)", (table,))
        con.execute(f'create table "{table}" (fid integer primary key, {cols}, geom {gtype})')
        n = len(rows[table][0])
        names = [c.split()[0] for c in cols.split(", ")] + ["geom"]
        con.executemany(f'insert into "{table}" ({", ".join(names)}) values ({", ".join("?" * n)})', rows[table])
        con.commit()
        con.close()
    return folder / "Habitable_Structures.gpkg"


DAM = {"nid": "ND00199", "name": "Absaraka", "heightFt": 20, "storageAcFt": 300, "statedDatum": "NAVD88",
       "method": "froehlich", "lon": -97.4, "lat": 46.99}
DWR_DAM = {**DAM, "nid": "DWR-16431", "name": "DWR-16431 (UNK-2400)"}
ANALYSIS = {"datum": {"crestNavdFt": 1000.0}, "breach": {"series": []}, "screen": {"level": "Low"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.calls = self.root / "calls.txt"
        self.qgis = write_exe(self.root / "qgis_process", FAKE_QGIS)
        clean = {k: "" for k in (*ENV_VARS.values(), *ND_ENV_VARS.values())}
        self.env = mock.patch.dict(os.environ, {
            **clean,
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "QGIS_PROCESS": "",
            "DAMIT_ND_QGIS_PROCESS": str(self.qgis),
            "CALLS": str(self.calls),
            "DAMIT_CLI": "",
            "DAMIT_ND_CLI": "",
            "DAMIT_HANDOFF_CONFIG": "",
            "DAMIT_DATA": "",
            "NDSUITE_DATA": "",
            "DAMIT_DEM": "",
            "APPDATA": "",
            "DAMIT_OFFLINE": "1",
            "DAMSUITE_PREFIX": str(self.root / "no-dam-suite"),
            "DAMSAFETY_PREFIX": str(self.root / "no-dwr-suite"),
        })
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

    def runs(self) -> list[str]:
        if not self.calls.is_file():
            return []
        return [ln for ln in self.calls.read_text(encoding="utf-8").splitlines() if ln.startswith("run ")]


class ProfileScopeTests(unittest.TestCase):
    def test_scope_sets_and_restores(self):
        self.assertEqual(current(), "us")
        with profile_scope("ND"):
            self.assertEqual(current(), "nd")
            with profile_scope("bogus"):
                self.assertEqual(current(), "us")
            self.assertEqual(current(), "nd")
        self.assertEqual(current(), "us")
        self.assertEqual(normalize(None), "us")


class ConfigTests(Base):
    def test_nd_defaults_and_overrides(self):
        cfg = load_config(profile="nd")
        self.assertEqual(cfg.profile, "nd")
        self.assertEqual(cfg.algorithms, ND_ALGORITHMS)
        self.assertEqual(cfg.alg("rundam"), "ndbreach:rundam")
        self.assertEqual(cfg.cli_names, ("ndbreach_cli.py",))
        with mock.patch.dict(os.environ, {"DAMIT_ND_ALG_RUNDAM": "ndbreach:rundam2", "DAMIT_ND_ALG_CLASSIFY": "damit:classify"}):
            cfg = load_config(profile="nd")
        self.assertEqual(cfg.alg("rundam"), "ndbreach:rundam2")
        self.assertEqual(cfg.alg("classify"), "ndhazard:classify")
        self.assertTrue(any("DamIT id" in p for p in cfg.problems), cfg.problems)
        # the job's profile is the default
        with profile_scope("nd"):
            self.assertEqual(load_config().profile, "nd")
        self.assertEqual(load_config().alg("rundam"), "damit_run:rundam")

    def test_the_other_suites_ids_are_refused_each_way(self):
        with self.assertRaises(HandoffConfigError):
            check_alg_id("rundam", "ndbreach:rundam")
        with self.assertRaises(HandoffConfigError):
            check_alg_id("rundam", "damit_run:rundam", "nd")
        self.assertEqual(check_alg_id("rundam", "nddam:other", "nd"), "nddam:other")

    def test_nd_section_of_the_config_file(self):
        path = self.root / "handoff.json"
        path.write_text(json.dumps({"algorithms": {"rundam": "damit_run:x"},
                                    "nd": {"algorithms": {"preflight": "nddam:preflight2"}}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMIT_HANDOFF_CONFIG": str(path)}):
            nd, us = load_config(profile="nd"), load_config(profile="us")
        self.assertEqual(nd.alg("preflight"), "nddam:preflight2")
        self.assertEqual(nd.alg("rundam"), "ndbreach:rundam")
        self.assertEqual(us.alg("rundam"), "damit_run:x")

    def test_as_json_names_the_profile(self):
        info = load_config(profile="nd").as_json()
        self.assertEqual(info["profile"], "nd")
        self.assertEqual(info["roles"]["classify"]["plugin"], "DamSafety_Hazard")
        self.assertEqual(info["roles"]["rundam"]["env"], "DAMIT_ND_ALG_RUNDAM")

    def test_nd_cli_search_finds_ndbreach_cli(self):
        cli = self.home / ".local/share/QGIS/QGIS3/profiles/damsafety/python/plugins/DamSafety_Runner/scripts/ndbreach_cli.py"
        cli.parent.mkdir(parents=True)
        cli.write_text("", encoding="utf-8")
        self.assertEqual(find_damit_cli(load_config(profile="nd"), self.home), str(cli))
        self.assertIsNone(find_damit_cli(load_config(profile="us"), self.home))


class LauncherTests(Base):
    def env_file(self) -> Path:
        prefix = self.root / "dwr-dam-suite"
        prefix.mkdir()
        (self.root / "env-qgis").mkdir()
        exe = self.root / "env-qgis" / "qgis_process"
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
        headless = prefix / "qgis_headless_config"
        (prefix / "damsafety_env.sh").write_text(
            "# DamSafety environment\n"
            f'export DAMSAFETY_HEADLESS_CONFIG="{headless}"\n'
            f'export QGIS_PROCESS="{exe}"\n'
            'export NDBREACH_ANUGA_MESHER=gmsh\n', encoding="utf-8")
        return prefix

    @unittest.skipIf(os.name == "nt", "the DWR installer is macOS / Linux only")
    def test_nd_launcher_from_the_dwr_env_file(self):
        prefix = self.env_file()
        with mock.patch.dict(os.environ, {"DAMSAFETY_PREFIX": str(prefix), "DAMIT_ND_QGIS_PROCESS": "",
                                          "QGIS_PROCESS": str(self.qgis)}):
            with profile_scope("nd"):
                found = qr.find_qgis_process()
            us = qr.find_qgis_process()
        self.assertEqual(found, str(qr.SETTINGS_DIR / "qgis-process-dwr.sh"))
        text = Path(found).read_text(encoding="utf-8")
        self.assertIn(str(prefix / "damsafety_env.sh"), text)
        self.assertEqual(qr.launcher_config_path(found), str(prefix / "qgis_headless_config"))
        self.assertEqual(us, str(self.qgis), "the US profile never uses the DWR launcher")
        # the installer's own launcher wins when there is one
        own = prefix / "qgis-process-dwr.sh"
        own.write_text("#!/bin/sh\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMSAFETY_PREFIX": str(prefix), "DAMIT_ND_QGIS_PROCESS": ""}):
            with profile_scope("nd"):
                self.assertEqual(qr.find_qgis_process(), str(own))

    def test_nd_never_takes_the_damit_suite_launcher(self):
        suite = self.root / "dam-suite"
        suite.mkdir()
        (suite / ("qgis-process-damit.cmd" if os.name == "nt" else "qgis-process-damit.sh")).write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMSUITE_PREFIX": str(suite), "DAMIT_ND_QGIS_PROCESS": ""}):
            self.assertTrue(str(qr.find_qgis_process() or "").endswith(("qgis-process-damit.sh", "qgis-process-damit.cmd")))
            with profile_scope("nd"):
                self.assertNotIn("qgis-process-damit", str(qr.find_qgis_process() or ""))


    def test_nd_takes_the_suite_installers_damsafety_launcher(self):
        suite = self.root / "dam-suite"
        suite.mkdir()
        ext = ".cmd" if os.name == "nt" else ".sh"
        (suite / f"qgis-process-damit{ext}").write_text("", encoding="utf-8")
        (suite / f"qgis-process-damsafety{ext}").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DAMSUITE_PREFIX": str(suite), "DAMIT_ND_QGIS_PROCESS": ""}):
            with profile_scope("nd"):
                self.assertEqual(qr.find_qgis_process(), str(suite / f"qgis-process-damsafety{ext}"))
            self.assertEqual(qr.find_qgis_process(), str(suite / f"qgis-process-damit{ext}"))


class LaunchUrlTests(unittest.TestCase):
    def test_desk_profile_rides_in_the_fragment(self):
        from damit_desktop import __main__ as desk

        with mock.patch.dict(os.environ, {"DAMIT_DESK_PROFILE": "nd"}):
            self.assertTrue(desk.desk_url(1).endswith("&profile=nd"))
        with mock.patch.dict(os.environ, {"DAMIT_DESK_PROFILE": ""}):
            self.assertNotIn("profile=", desk.desk_url(1))


class IdsAndDataTests(Base):
    def test_dwr_structure_ids_are_dam_ids_in_nd_only(self):
        with profile_scope("nd"):
            self.assertEqual(handoff_ids(DWR_DAM)["dam_id"], "DWR-16431")
            self.assertIsNone(handoff_ids(DWR_DAM)["nid_id"])
            self.assertIsNone(nid_problem(DWR_DAM))
            self.assertEqual(handoff_ids(DAM)["dam_id"], "ND00199")
        self.assertNotEqual(handoff_ids(DWR_DAM)["dam_id"], "DWR-16431")
        self.assertIsNotNone(nid_problem(DWR_DAM))

    def test_nd_pack_folder_comes_first_in_nd(self):
        pack, damit = self.root / "ndpack", self.root / "damitdata"
        pack.mkdir()
        damit.mkdir()
        with mock.patch.dict(os.environ, {"NDSUITE_DATA": str(pack), "DAMIT_DATA": str(damit)}):
            with profile_scope("nd"):
                self.assertEqual(layers.find_data_folder_with_source(), (str(pack.resolve()), "NDSUITE_DATA"))
            self.assertEqual(layers.find_data_folder_with_source()[0], str(damit.resolve()))


class RunTests(Base):
    def depth(self) -> str:
        path = self.root / "depth.tif"
        path.write_bytes(b"not a raster")
        return str(path)

    def test_classify_runs_ndhazard_on_the_dam_folder(self):
        dam = {**DAM, "depthRaster": self.depth(), "dvRaster": self.depth()}
        with profile_scope("nd"):
            result = qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        run = self.runs()[0]
        self.assertTrue(run.startswith("run ndhazard:classify "), run)
        self.assertIn("--DAM_FOLDER=" + result["folder"], run)
        self.assertIn("--DXV=", run)
        self.assertNotIn("--STRUCTURES=", run)
        self.assertEqual(result["suggestedClass"], "High")
        self.assertEqual(result["classification"]["tm11Class"], "Significant")
        self.assertEqual(result["classification"]["ordinal"], 3)  # hazard_class: High
        # No receptor layer written (the fake writes none): the class still comes back, complete, with no GeoPackage.
        self.assertTrue(result["classification"]["complete"])
        self.assertNotIn("gpkg", result["classification"])
        self.assertTrue(any("No receptor layer" in ln for ln in self.lines), self.lines)

    def test_classify_reads_the_nd_receptor_layers_back(self):
        dam = {**DAM, "depthRaster": self.depth()}
        work = self.root / "work"
        layers_dir = work / "dams" / "ND00199" / "outputs" / "Classification"
        gpkg = make_nd_layers(layers_dir, rail_basis="22 trains/day >= 10 - probable loss of life - crossing on this "
                                                     "line not confirmed")
        with profile_scope("nd"):
            result = qr.run_classify(dam, ANALYSIS, str(work), self.log)
        self.assertTrue(result["ok"], self.lines)
        c = result["classification"]
        self.assertEqual(Path(c["gpkg"]).resolve(), gpkg.resolve())
        self.assertEqual(result["gpkg"], c["gpkg"])
        self.assertEqual(c["layers"], {"STRUCTURES": 5, "ROADS": 2, "RAIL": 1})
        self.assertEqual(c["impacted"], {"STRUCTURES": 2, "ROADS": 2, "RAIL": 1})
        self.assertEqual(c["wetStructures"], 4)
        self.assertEqual(c["ruling"]["label"], "High")
        self.assertEqual((c["ruling"]["hits"], c["ruling"]["unruled"]), (3, 1))
        self.assertIn("crossing on this line not confirmed", c["ruling"]["why"][0])
        self.assertEqual(c["hits"][0]["ordinal"], 3)
        self.assertTrue(c["complete"])
        self.assertTrue(any(ln.startswith("Receptors by class: ") for ln in self.lines), self.lines)

    def test_screening_runs_nddam_and_reads_the_dwr_name(self):
        work = self.root / "work"
        work.mkdir()
        # a work folder that already ran the DWR chain: ND00199 is DWR-2801 in 1_dams.gpkg
        con = sqlite3.connect(work / "1_dams.gpkg")
        con.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
        con.execute("INSERT INTO gpkg_contents VALUES ('dams', 'features')")
        con.execute("CREATE TABLE dams (dam_id TEXT, nid_id TEXT)")
        con.execute("INSERT INTO dams VALUES ('DWR-2801', 'ND00199')")
        con.commit()
        con.close()
        with profile_scope("nd"):
            result = qr.run_screening(DAM, ANALYSIS, str(work), self.log)
        runs = self.runs()
        self.assertTrue(runs[0].startswith("run nddam:preflight "), runs)
        self.assertTrue(runs[1].startswith("run nddam:runchain "), runs)
        self.assertIn("--DAM_ID=ND00199,DWR-2801", runs[1])
        self.assertEqual(result["chainIds"], ["DWR-2801"])
        settings = json.loads((work / "damit_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["only_ids"], "ND00199,DWR-2801")

    def test_model_runs_ndbreach_for_a_dwr_structure(self):
        dem = self.root / "dem.tif"
        dem.write_bytes(b"x")
        dam = {**DWR_DAM, "demPath": str(dem)}
        with profile_scope("nd"):
            result = qr.run_model(dam, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        run = self.runs()[0]
        self.assertTrue(run.startswith("run ndbreach:rundam "), run)
        self.assertIn("--DAM_ID=DWR-16431", run)
        self.assertNotIn("--NID_ID=", run)
        self.assertIn("--METHOD=0", run)

    def test_data_has_no_nd_algorithm(self):
        with profile_scope("nd"):
            result = qr.run_data(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertEqual(self.runs(), [])
        self.assertTrue(any("offline pack" in ln for ln in self.lines), self.lines)

    def test_check_names_the_profile_and_skips_the_missing_data_role(self):
        with profile_scope("nd"):
            result = qr.run_check(self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertEqual([r["algorithm"] for r in result["check"]],
                         ["nddam:preflight", "nddam:runchain", "ndbreach:rundam", "ndhazard:classify"])
        self.assertTrue(any("North Dakota" in ln for ln in self.lines))



class NdReceptorLayerTests(unittest.TestCase):
    """classify_receptors reading ndhazard:classify's three layers (the US damit_hazard_receptors.gpkg is in
    test_absaraka_ux.py and still passes unchanged)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / "dams" / "ND00199" / "outputs" / "Classification"
        self.gpkg = make_nd_layers(self.folder)
        p = mock.patch.object(cr, "allowed_work_roots", lambda: [self.root])
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_reads_the_three_layers_strongest_first_with_names_and_lonlat(self):
        out = cr.read_receptors(cr.gpkg_path(str(self.gpkg)))
        self.assertEqual([r["rid"] for r in out["receptors"]],
                         ["structure:1086", "rail:1", "road:1", "structure:778", "structure:2201", "road:2", "structure:5"])
        by = {r["rid"]: r for r in out["receptors"]}
        self.assertEqual((by["structure:1086"]["label"], by["structure:1086"]["ordinal"]), ("High", 3))
        self.assertEqual(by["structure:1086"]["name"], "Structure 1086 · RES1-2SWB (single-family home)")
        self.assertEqual(by["structure:778"]["name"], "1341 MORNINGSIDE DR CASSELTON · RES1-1SWB (single-family home)")
        self.assertEqual((by["structure:778"]["label"], by["structure:778"]["advisory"]), ("Medium", False))
        # Habitability unverified: not in the ND class until signed off, so advisory and flagged.
        self.assertTrue(by["structure:2201"]["advisory"])
        self.assertEqual(by["structure:2201"]["flags"], ["habitability_unverified"])
        self.assertIsNone(by["structure:5"]["ordinal"])  # wet, below consequence depth
        self.assertEqual(by["road:1"]["name"], "LANGER AVE S (AADT 3,423)")
        self.assertEqual(by["road:2"]["flags"], ["aadt_assumed"])
        self.assertEqual(by["rail:1"]["name"], "BNSF · subdivision KO")
        # EPSG:5070 back to lon/lat (the map zooms to these).
        lon, lat = by["structure:1086"]["at"]
        self.assertAlmostEqual(lon, -97.3577, delta=2e-4)
        self.assertAlmostEqual(lat, 46.9555, delta=2e-4)
        w, s_, e, n = by["rail:1"]["bbox"]
        self.assertAlmostEqual(w, -97.2170, places=5)
        self.assertAlmostEqual(n, 46.9005, places=5)
        self.assertEqual(out["counts"]["STRUCTURES"], {"total": 5, "wet": 4, "hit": 2})
        self.assertEqual(out["counts"]["ROADS"], {"total": 2, "wet": 2, "hit": 2})
        self.assertEqual(out["source"], "ndhazard:classify")
        self.assertIsNone(out["ruling"])  # the High roads and rail rest on found values

    def test_any_nd_layer_name_reads_all_three(self):
        out = cr.read_receptors(cr.gpkg_path(str(self.folder / "Rail_Inundated.gpkg")))
        self.assertEqual(set(out["counts"]), {"STRUCTURES", "ROADS", "RAIL"})
        self.assertEqual(Path(out["gpkg"]), self.gpkg)

    def test_needs_ruling_when_a_top_class_receptor_rests_on_an_unconfirmed_value(self):
        make_nd_layers(self.folder, rail_basis="22 trains/day >= 10 - probable loss of life - crossing on this line "
                                               "not confirmed")
        g = cr.read_receptors(self.gpkg)["ruling"]
        self.assertEqual((g["label"], g["hits"], g["unruled"]), ("High", 3, 1))
        self.assertTrue(g["why"][0].startswith("1 rail stretch(es) at High: "))

    def test_only_the_receptor_files_inside_the_work_folder(self):
        with self.assertRaises(cr.ReceptorsError):
            cr.gpkg_path(str(self.folder / "Access_Cut_Off.gpkg"))
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "Habitable_Structures.gpkg"
            outside.write_bytes(self.gpkg.read_bytes())
            with self.assertRaises(cr.ReceptorsError):
                cr.gpkg_path(str(outside))
        with self.assertRaisesRegex(cr.ReceptorsError, "ndhazard:classify"):
            cr.gpkg_path(str(self.root / "Roads_Inundated.gpkg"))

    def test_a_broken_nd_layer_is_a_message_not_a_crash(self):
        (self.folder / "Roads_Inundated.gpkg").write_bytes(b"not sqlite at all" * 100)
        with self.assertRaises(cr.ReceptorsError):
            cr.read_receptors(self.gpkg)
        self.assertEqual(cr.nd_summary(self.folder), {})


if __name__ == "__main__":
    unittest.main()
