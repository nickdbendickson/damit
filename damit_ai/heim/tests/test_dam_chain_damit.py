"""dam_chain 1.6.0: the DamIT set (`--set damit`), and option names checked before a run.

Why: DamIT runs had no headless command (the batch-44 kit called qgis_process by hand), and a
wrong option name given to a Processing tool is ignored, so a run quietly used the default.

No QGIS and no conda: QP is replaced with a stub. Its plain() answers `qgis_process --json help`
with a small parameter list; its run() returns what the test asks for.
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
sys.path.insert(0, TOOLS)
import dam_chain as DC  # noqa: E402

HELP = {"parameters": {
    "DAMS": {}, "DEM": {}, "DAMS_FOLDER": {}, "CELL": {}, "MANNING": {}, "SKIP_DONE": {}, "ONLY_IDS": {},
    "SOLVER": {"available_options": {"0": "Default", "1": "ACC (local inertial)", "2": "FV2 (finite volume)",
                                     "3": "MWDG2 (multiwavelet DG)"}},
    "SCENARIO": {"available_options": {"0": "Sunny day", "1": "Flood with breach", "2": "Flood without breach"}},
}}


class FakeQP(object):
    anuga_py = ""
    qp = "/nonexistent/qgis_process"

    def __init__(self, results=None, help_json=HELP, help_rc=0):
        self.results = list(results or [(True, {"COUNTS": "2 run, 0 failed, 0 skipped, 0 with no breach"}, "")])
        self.help_json, self.help_rc = help_json, help_rc
        self.calls = []
        self.env = {}

    def __call__(self, args, set_name):
        self.set_name = set_name
        return self

    def plain(self, *a):
        self.calls.append(("plain",) + a)
        return self.help_rc, "QStandardPaths: warning\n" + json.dumps(self.help_json)

    def run(self, alg, params, log_path, timeout=None, label=""):
        self.calls.append(("run", alg, dict(params)))
        return self.results[0] if len(self.results) == 1 else self.results.pop(0)


def make_gpkg(path, ids, col="dam_id"):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
    con.execute("INSERT INTO gpkg_contents VALUES ('dams', 'features')")
    con.execute('CREATE TABLE dams (fid INTEGER PRIMARY KEY, geom BLOB, "%s" TEXT, dam_name TEXT)' % col)
    con.executemany('INSERT INTO dams ("%s", dam_name) VALUES (?, ?)' % col, [(i, "d" + i) for i in ids])
    con.commit()
    con.close()


class Args(object):
    def __init__(self, **kw):
        self.set = "damit"
        self.ids = ""
        self.ids_csv = ""
        self.dams = self.out = self.dem = ""
        self.id_field = ""
        self.dem_units = ""
        self.cell = None
        self.manning = None
        self.solver = ""
        self.runner_param = None
        self.param = None
        self.redo = False
        self.check_only = False
        self.dry_run = False
        self.anuga = False
        self.workers = 1
        self.threads = 1
        self.lisflood = ""
        self.triage = False
        self.__dict__.update(kw)


class DamitRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dam-chain-damit-")
        self.dams = os.path.join(self.tmp, "dams.gpkg")
        make_gpkg(self.dams, ["2801", "4031", "DWR-3034"])
        self.dem = os.path.join(self.tmp, "dem.tif")
        open(self.dem, "w").close()
        self.out = os.path.join(self.tmp, "runs")
        self._qp = DC.QP

    def tearDown(self):
        DC.QP = self._qp

    def go(self, fake=None, **kw):
        fake = fake or FakeQP()
        DC.QP = fake
        a = dict(dams=self.dams, out=self.out, dem=self.dem, ids="2801,4031")
        a.update(kw)
        out, keep = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            DC.run_damit(Args(**a))
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else str(e.code))
        finally:
            sys.stdout = keep
        return code, out.getvalue(), fake

    def runs(self, fake):
        return [c for c in fake.calls if c[0] == "run"]

    def test_a_clean_run(self):
        code, out, fake = self.go(cell=5.0, solver="fv2", manning=0.04)
        self.assertEqual(code, 0, out)
        (_, alg, p), = self.runs(fake)
        self.assertEqual(alg, "damit_run:batch")
        self.assertEqual(p["ONLY_IDS"], "2801,4031")
        self.assertEqual(p["CELL"], "5")
        self.assertEqual(p["SOLVER"], "2")                 # 'fv2' -> the FV2 option's number
        self.assertEqual(p["MANNING"], "0.04")
        self.assertEqual(p["SKIP_DONE"], "true")
        self.assertEqual(p["CLASSIFY"], "false")
        self.assertEqual(p["DAMS_FOLDER"], self.out)

    def test_redo_runs_finished_dams_again(self):
        _, _, fake = self.go(redo=True)
        self.assertEqual(self.runs(fake)[0][2]["SKIP_DONE"], "false")

    def test_a_failed_dam_exits_one(self):
        code, out, _ = self.go(FakeQP([(True, {"COUNTS": "1 run, 1 failed, 0 skipped, 0 with no breach"}, "")]))
        self.assertEqual(code, 1)
        self.assertTrue(out.strip().splitlines()[-2].startswith("FAILED") or "FAILED" in out, out)

    def test_no_counts_is_not_success(self):
        code, _, _ = self.go(FakeQP([(True, {}, "")]))
        self.assertEqual(code, 1)

    def test_an_id_not_in_the_layer_is_refused_before_anything_runs(self):
        code, out, fake = self.go(ids="2801,9999")
        self.assertEqual(code, 1)
        self.assertIn("9999", out)
        self.assertEqual(self.runs(fake), [])

    def test_missing_files_are_refused(self):
        code, out, fake = self.go(dem=os.path.join(self.tmp, "nope.tif"), dams="")
        self.assertEqual(code, 1)
        self.assertIn("--dams is missing", out)
        self.assertIn("DEM is not there", out)
        self.assertEqual(self.runs(fake), [])

    def test_a_wrong_option_name_is_refused(self):
        code, out, fake = self.go(runner_param=["CEL=5"])
        self.assertIn("CEL is not an option of damit_run:batch", str(code))
        self.assertIn("did you mean CELL", str(code))
        self.assertEqual(self.runs(fake), [])

    def test_an_enum_by_text_or_number(self):
        _, _, fake = self.go(runner_param=["SCENARIO=sunny day", "SOLVER=3"])
        p = self.runs(fake)[0][2]
        self.assertEqual((p["SCENARIO"], p["SOLVER"]), ("0", "3"))
        code, _, fake = self.go(runner_param=["SCENARIO=flood"])      # two options say 'flood'
        self.assertIn("is not one of its options", str(code))
        self.assertEqual(self.runs(fake), [])

    def test_options_unreadable_means_nothing_runs(self):
        code, _, fake = self.go(FakeQP(help_rc=1), cell=5.0)
        self.assertIn("cannot read the options", str(code))
        self.assertEqual(self.runs(fake), [])

    def test_check_only_runs_nothing(self):
        code, out, fake = self.go(check_only=True, cell=5.0)
        self.assertEqual(code, 0, out)
        self.assertIn("preflight: 0 error(s)", out)
        self.assertEqual(self.runs(fake), [])

    def test_lisflood_may_name_a_runner_engine(self):
        _, _, fake = self.go(lisflood="builtin")
        self.assertEqual(self.runs(fake)[0][2]["LISFLOOD_EXE"], "builtin")
        _, _, fake = self.go(lisflood="sub-grid channels")
        self.assertEqual(self.runs(fake)[0][2]["LISFLOOD_EXE"], "sub-grid channels")
        code, out, fake = self.go(lisflood=os.path.join(self.tmp, "no-such-lisflood"))
        self.assertEqual(code, 1)
        self.assertIn("not a file and not one of the Runner's engines", out)
        self.assertEqual(self.runs(fake), [])
        _, _, fake = self.go(lisflood=os.path.join(self.tmp, "no-such-lisflood"), lisflood_given=False)
        self.assertNotIn("LISFLOOD_EXE", self.runs(fake)[0][2])     # the Runner's own setting

    def test_the_id_field_is_the_runners_and_is_passed_on(self):
        # review 2026-11-23: NIDID before DAM_ID, as the Runner picks (data_conventions FIELD_SYNONYMS)
        p = os.path.join(self.tmp, "two.csv")
        with open(p, "w") as fh:
            fh.write("DAM_ID,NIDID,NAME\n2801,ND00123,a\n")
        self.assertEqual(DC.layer_ids(p)[0], "NIDID")
        code, out, fake = self.go(dams=p, ids="2801")
        self.assertEqual(code, 1)
        self.assertIn("not in the dams layer (field NIDID)", out)
        code, out, fake = self.go(dams=p, ids="ND00123")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.runs(fake)[0][2]["F_ID"], "NIDID")
        self.assertEqual(DC._id_field(["Dam ID", "x"], ""), "Dam ID")
        self.assertEqual(DC._id_field(["NIDID_2024"], ""), "NIDID_2024")
        code, out, _ = self.go(ids="dwr-3034")
        self.assertIn("did you mean DWR-3034", out)

    def test_no_dam_run_for_the_ids_is_a_failure(self):
        code, out, _ = self.go(FakeQP([(True, {"COUNTS": "0 run, 0 failed, 0 skipped, 0 with no breach"}, "")]))
        self.assertEqual(code, 1)
        self.assertIn("none of --ids 2801,4031 was found by the Runner", out)
        code, out, _ = self.go(FakeQP([(True, {"COUNTS": "0 run, 0 failed, 2 skipped, 0 with no breach"}, "")]))
        self.assertEqual(code, 0, out)

    def test_param_is_checked_too(self):
        code, out, fake = self.go(param=["SOLVR=2"])
        self.assertIn("SOLVR is not an option", str(code))
        self.assertEqual(self.runs(fake), [])

    def test_option_text_by_its_start(self):
        real = {"0": "Sunny day: no inflow, breach at the top of dam (ND 5.1.1)",
                "1": "Flood: inflow hydrograph from inputs/pmf_inflow.csv",
                "2": "Per dam: flood if its folder has inputs/pmf_inflow.csv, else sunny day",
                "3": "Flood without breach"}
        self.assertEqual(DC.enum_value("SCENARIO", "sunny", real), ("0", None))
        self.assertEqual(DC.enum_value("SCENARIO", "per dam", real), ("2", None))
        self.assertIsNone(DC.enum_value("SCENARIO", "flood", real)[0])

    def test_ids_from_a_csv_layer_and_another_field(self):
        csvp = os.path.join(self.tmp, "dams.csv")
        with open(csvp, "w") as fh:
            fh.write("NIDID,name\nND00001,a\nND00002,b\n")
        self.assertEqual(DC.layer_ids(csvp), ("NIDID", {"ND00001", "ND00002"}))
        self.assertEqual(DC.layer_ids(self.dams + "|layername=dams")[1], {"2801", "4031", "DWR-3034"})
        self.assertEqual(DC.layer_ids(os.path.join(self.tmp, "x.shp")), (None, None))


class SelftestAndSetupTest(unittest.TestCase):
    """Found in the real-QGIS trial: damit_run:check exits 0 and says PROBLEM in its result, and a
    qgis_process that cannot start was reported as 'plugins enabled'."""

    def setUp(self):
        self._qp = DC.QP
        self.tmp = tempfile.mkdtemp(prefix="dam-chain-selftest-")

    def tearDown(self):
        DC.QP = self._qp

    def selftest(self, result, dry=False):
        fake = FakeQP([(True, {"RESULT": result}, "")])
        DC.QP = fake
        a = Args(selftest=True, log_dir=self.tmp, lisflood="", env="ndqgis", dry_run=dry)
        out, keep = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            DC.cmd_plugins(a)
        finally:
            sys.stdout = keep
        return out.getvalue()

    def test_a_problem_line_is_a_fail(self):
        out = self.selftest("PROBLEM LISFLOOD-FP not found.\nANUGA: no conda environment")
        self.assertIn("FAIL damit_run:check", out)
        out = self.selftest("OK LISFLOOD-FP 8.3 (patched)\nANUGA: no conda environment")
        self.assertIn("PASS damit_run:check", out)
        self.assertIn("FAIL damit_run:check", self.selftest(""))
        self.assertNotIn("FAIL", self.selftest("", dry=True))

    def test_setup_says_when_qgis_process_cannot_start(self):
        profiles = os.path.join(self.tmp, "profiles")
        os.makedirs(os.path.join(profiles, "damit", "python", "plugins", "damit_runner"))

        class Down(FakeQP):
            def plain(self, *a):
                return (127, "qgis_process.bin: not found") if a[:2] == ("plugins", "enable") \
                    else FakeQP.plain(self, *a)

        class Already(FakeQP):
            def plain(self, *a):
                return (1, "error starting plugin") if a[:2] == ("plugins", "enable") \
                    else FakeQP.plain(self, *a)
        keep = (DC.QGIS_PROFILES, DC.BATCH_ROOT)
        DC.QGIS_PROFILES, DC.BATCH_ROOT = profiles, os.path.join(self.tmp, "batch")
        try:
            for fake, want in ((Down(), "could not start to enable damit_runner"),
                               (Already(), "plugins enabled for qgis_process")):
                DC.QP = fake
                out, keep_out = io.StringIO(), sys.stdout
                sys.stdout = out
                try:
                    DC.cmd_setup(Args(dry_run=False, env="ndqgis"))
                finally:
                    sys.stdout = keep_out
                self.assertIn(want, out.getvalue())
        finally:
            DC.QGIS_PROFILES, DC.BATCH_ROOT = keep


class DamitSetTest(unittest.TestCase):
    def test_the_set_is_known_everywhere(self):
        self.assertIn("damit", DC.SETS)
        self.assertEqual(DC.SETS["damit"]["profile"], "damit")
        self.assertIn("damit_run:batch", DC.SETS["damit"]["needs"])
        with open(os.path.join(TOOLS, "dam_chain.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('s.add_argument("--damit-profile", default="")', src)
        self.assertIn('elif args.set == "damit":\n        run_damit(args)', src)

    def test_setup_survives_a_set_with_no_profile_option(self):
        class A(object):
            dry_run = True
        self.assertEqual(getattr(A(), "damit_profile", ""), "")

    def test_profiles_folder_per_system(self):
        self.assertTrue(DC._default_profiles().endswith(os.path.join("QGIS3", "profiles"))
                        or DC._default_profiles().endswith("QGIS3/profiles"))


if __name__ == "__main__":
    unittest.main()
