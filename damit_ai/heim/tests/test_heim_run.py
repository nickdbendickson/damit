"""heim_run 1.0.0: `heim run "plain English"` drafts a damchain run, and nothing reaches a run unchecked.

Rules agreed 2026-11-23: the model only fills fixed fields; code checks every id against the words and
the dams layer and every number against the words and a range; anything else asked for is refused, not
guessed; redo only when the words ask; the command is shown and nothing runs until y; --check-only first;
the sentence, the reply and the command are logged.

No Ollama and no QGIS: the model, the prompt and damchain are stubbed.
"""
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HR = load("heim_run_under_test", "heim_run.py")
RQ = load("rag_query_for_heim_run_test", "rag_query.py")


def fields(**kw):
    d = {"ids": [], "cell_m": None, "solver": "", "manning": None, "redo": False, "unsupported": []}
    d.update(kw)
    return d


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="heim-run-")
        os.environ["HEIM_RUN_SETTINGS"] = os.path.join(self.tmp, "heim_run.json")
        HR.SAVED = os.environ["HEIM_RUN_SETTINGS"]
        self.dams = os.path.join(self.tmp, "dams.gpkg")
        con = sqlite3.connect(self.dams)
        con.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
        con.execute("INSERT INTO gpkg_contents VALUES ('dams', 'features')")
        con.execute("CREATE TABLE dams (fid INTEGER PRIMARY KEY, dam_id TEXT)")
        con.executemany("INSERT INTO dams (dam_id) VALUES (?)", [("2801",), ("4031",), ("DWR-3034",)])
        con.commit()
        con.close()
        self.dem = os.path.join(self.tmp, "dem.tif")
        open(self.dem, "w").close()
        self.out = os.path.join(self.tmp, "runs")
        self.calls = []

    def tearDown(self):
        os.environ.pop("HEIM_RUN_SETTINGS", None)

    def go(self, request, reply, answer="y", rc=(0, 0), extra=()):
        said, rcs = [], list(rc)

        def chat(messages, fmt=None, timeout=None):
            self.assertEqual(fmt, HR.SCHEMA)
            if isinstance(reply, Exception):
                raise reply
            return json.dumps(reply) if isinstance(reply, dict) else reply

        def runner(argv):
            self.calls.append(argv)
            return rcs.pop(0) if rcs else 0
        argv = ["--set", "damit", "--dams", self.dams, "--out", self.out, "--dem", self.dem] + list(extra) + [request]
        code = HR.main(argv, chat=chat, ask=lambda prompt: answer, runner=runner, out=said.append)
        return code, "\n".join(said)


class HeimRunTest(Case):
    def test_a_good_request_is_shown_checked_then_run(self):
        code, said = self.go("run 2801 and 4031 at 5 m with FV2", fields(ids=["2801", "4031"], cell_m=5, solver="fv2"))
        self.assertEqual(code, 0, said)
        self.assertIn("damchain run --set damit", said)
        self.assertIn("cell size 5 m (default 10 m)", said)
        self.assertIn("solver FV2 (default ACC)", said)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][-1], "--check-only")                # checks first
        self.assertEqual(self.calls[1][:3], ["run", "--set", "damit"])
        self.assertIn("--ids", self.calls[1])
        self.assertEqual(self.calls[1][self.calls[1].index("--ids") + 1], "2801,4031")
        self.assertEqual(self.calls[1][self.calls[1].index("--solver") + 1], "fv2")
        self.assertNotIn("--redo", self.calls[1])
        logs = os.listdir(os.path.join(self.out, "_chain_logs"))
        with open(os.path.join(self.out, "_chain_logs", logs[0]), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("request: run 2801 and 4031 at 5 m with FV2", log)
        self.assertIn("confirmed: y", log)
        self.assertIn("run exit: 0", log)

    def test_a_setting_equal_to_the_default_says_so(self):
        code, said = self.go("run 2801 at 10 m with ACC, n 0.05", fields(ids=["2801"], cell_m=10, solver="acc",
                                                                       manning=0.05), extra=["--show"])
        self.assertIn("cell size 10 m (the same as the default)", said)
        self.assertIn("solver ACC (the same as the default)", said)
        self.assertIn("Manning's n 0.05 (the same as the default)", said)
        code, said = self.go("run 2801", fields(ids=["2801"]), extra=["--show"])
        self.assertIn("Settings: none asked for", said)

    def test_nothing_runs_without_y(self):
        for answer in ("", "n", "yes please", "Y "):
            self.calls = []
            code, said = self.go("run 2801", fields(ids=["2801"]), answer=answer)
            if answer.strip().lower() in ("y", "yes"):
                self.assertEqual(len(self.calls), 2)
            else:
                self.assertEqual(self.calls, [], answer)
                self.assertIn("nothing was run", said)

    def test_failed_checks_stop_the_run(self):
        code, said = self.go("run 2801", fields(ids=["2801"]), rc=(1,))
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("The checks failed", said)

    def test_an_id_not_in_the_words_or_the_layer(self):
        code, said = self.go("run 2801", fields(ids=["2801", "4031"]))
        self.assertEqual(self.calls, [])
        self.assertIn("'4031' is not in your words", said)
        code, said = self.go("run 2801 and 5555", fields(ids=["2801", "5555"]))
        self.assertEqual(self.calls, [])
        self.assertIn("not in the dams layer", said)
        self.assertIn("5555", said)

    def test_numbers_must_be_in_the_words_and_in_range(self):
        for req, f, why in (("run 2801", fields(ids=["2801"], cell_m=5), "cell size 5 is not in your words"),
                            ("run 2801 at 0.1 m", fields(ids=["2801"], cell_m=0.1), "outside"),
                            ("run 2801 at 30 ft", fields(ids=["2801"], cell_m=30), "takes metres"),
                            ("run 2801 with n 0.5", fields(ids=["2801"], manning=0.5), "outside"),
                            ("run 2801", fields(ids=["2801"], manning=0.04), "not in your words"),
                            ("run 2801", fields(ids=["2801"], solver="fv2"), "FV2 is not in your words")):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(self.calls, [], req)
            self.assertIn(why, said, req)

    def test_a_number_must_stand_in_its_own_place(self):
        # review 2026-11-23: digits inside a decimal or an id, and ids swapped with a cell size.
        # Every id the model gives is in the layer, so only the reading of the words can stop these.
        con = sqlite3.connect(self.dams)
        con.executemany("INSERT INTO dams (dam_id) VALUES (?)", [(x,) for x in ("5", "04", "10", "ND00123", "DWR-50")])
        con.commit()
        con.close()
        for req, f in (("run 2801 at 5.5 m", fields(ids=["5"], cell_m=5.5)),
                       ("run 2801 with n 0.04", fields(ids=["04"], manning=0.04)),
                       ("run ND00123", fields(ids=["ND00123"], cell_m=123)),
                       ("run DWR-50", fields(ids=["DWR-50"], cell_m=50)),
                       ("run 10 at 5 m", fields(ids=["5"], cell_m=10)),
                       ("run 2801 at 5 m", fields(ids=["2801"], manning=5))):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(self.calls, [], req)
            self.assertIn("Not run", said, req)

    def test_feet_and_other_units_are_refused(self):
        for req in ("run 2801 at 10.0 ft", "run 2801 with 10-foot cells", "run 2801 at 50 cm",
                    "run 2801 at .5 ft", "run 2801 at 5\u2019 cells", "run 2801 at 10 feet"):
            v = 0.5 if ".5 ft" in req else (50 if "cm" in req else (5 if "5\u2019" in req else 10))
            self.calls = []
            code, said = self.go(req, fields(ids=["2801"], cell_m=v))
            self.assertEqual(self.calls, [], req)
            self.assertIn("heim run takes metres", said, req)

    def test_a_number_nothing_accounts_for_stops_it(self):
        for req, f in (("run 2801 at 5 m and 4031 at 10 m", fields(ids=["2801", "4031"], cell_m=5)),
                       ("run 2801 with the 2 m DEM", fields(ids=["2801"])),
                       ("run 2801 for 48", fields(ids=["2801"]))):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(self.calls, [], req)
            self.assertIn("did not use", said, req)

    def test_what_it_cannot_set_is_refused_even_if_the_model_drops_it(self):
        for req in ("run 2801 with ANUGA", "run 2801 at max pool", "run all dams", "run 2801 with the PMF"):
            self.calls = []
            code, said = self.go(req, fields(ids=["2801"]))
            self.assertEqual(self.calls, [], req)
            self.assertIn("heim run cannot set", said, req)

    def test_not_except_instead_are_refused_not_worked_out(self):
        # second review 2026-11-23: "but not 4031", curly don’t, shouldn't, "redo: no", "instead of FV2"
        for req, f in (("run 2801 but not 4031", fields(ids=["2801", "4031"])),
                       ("run 2801, skip 4031", fields(ids=["2801", "4031"])),
                       ("run 2801 but don\u2019t overwrite finished dams", fields(ids=["2801"], redo=True)),
                       ("run 2801; it shouldn't overwrite finished dams", fields(ids=["2801"], redo=True)),
                       ("run 2801, redo: no", fields(ids=["2801"], redo=True)),
                       ("run 2801 with ACC instead of FV2", fields(ids=["2801"], solver="fv2")),
                       ("run 2801, don't use FV2", fields(ids=["2801"], solver="fv2")),
                       ("run 2801 but do not overwrite finished dams", fields(ids=["2801"]))):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(self.calls, [], req)
            self.assertIn("heim run does not read", said, req)
        code, said = self.go("rerun dam no. 2801 again", fields(ids=["2801"], redo=True))
        self.assertEqual(code, 0, said)                                     # 'no.' before a number is a number
        self.assertIn("--redo", self.calls[-1])

    def test_ranges_comma_decimals_and_words_are_refused(self):
        con = sqlite3.connect(self.dams)
        con.executemany("INSERT INTO dams (dam_id) VALUES (?)", [(x,) for x in ("2802", "2803", "2805")])
        con.commit()
        con.close()
        for req, f, why in (("run 2801-2805", fields(ids=["2801"]), "range"),
                            ("run 2801..2805", fields(ids=["2801"]), "range"),
                            ("run 2801 at 5-10 m", fields(ids=["2801"], cell_m=5), "range"),
                            ("run 2801 at 5,5 m", fields(ids=["2801"], cell_m=5), "not in your words as a cell size"),
                            ("run 2801 at five metres", fields(ids=["2801"]), "digits"),
                            ("run 2801 for 6h", fields(ids=["2801"]), "did not use"),
                            ("run 2801 at \uff15\uff4d", fields(ids=["2801"]), "did not use"),
                            ("run 2801 with a 12 m breach width", fields(ids=["2801"], cell_m=12), "cannot set"),
                            ("run 2801 at 5 pm", fields(ids=["2801"], cell_m=5), "takes metres"),
                            ("run 2801 at 5 US survey feet", fields(ids=["2801"], cell_m=5), "takes metres"),
                            ("run 2801 with 4 cores", fields(ids=["2801", "4"]), "cannot set"),
                            ("run 2801 with ACC, then FV2", fields(ids=["2801"], solver="fv2"), "more than one solver")):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(self.calls, [], req)
            self.assertIn(why, said, req)

    def test_reasonable_sentences_still_run(self):
        for req, f in (("run 2801 and 4031 at 5 m with FV-2", fields(ids=["2801", "4031"], cell_m=5, solver="fv2")),
                       ("redo dam 2801 at a 5 m cell", fields(ids=["2801"], cell_m=5, redo=True)),
                       ("run 2801 at 5 metres, Manning's n = 0.035", fields(ids=["2801"], cell_m=5, manning=0.035)),
                       ("please re-run 2801 one more time", fields(ids=["2801"], redo=True)),
                       ("run DWR-3034 and 2801,4031 at 10m using mwdg2",
                        fields(ids=["DWR-3034", "2801", "4031"], cell_m=10, solver="mwdg2")),
                       ("run dam 2801.", fields(ids=["2801"]))):
            self.calls = []
            code, said = self.go(req, f)
            self.assertEqual(code, 0, req + "\n" + said)
            self.assertEqual(len(self.calls), 2, req)

    def test_an_id_takes_the_layers_spelling(self):
        code, said = self.go("run dwr-3034", fields(ids=["dwr-3034"]))
        self.assertEqual(code, 0, said)
        self.assertEqual(self.calls[1][self.calls[1].index("--ids") + 1], "DWR-3034")

    def test_a_dwr_id_does_not_switch_the_set(self):
        self.go("run 2801", fields(ids=["2801"]))
        said = []
        self.calls = []
        code = HR.main(["run DWR-3034"], chat=lambda m, fmt=None, timeout=None: json.dumps(fields(ids=["DWR-3034"])),
                       ask=lambda p: "y", runner=lambda a: self.calls.append(a) or 0, out=said.append)
        self.assertEqual(code, 0, said)
        self.assertEqual(self.calls[-1][2], "damit", said)

    def test_paths_are_remembered_in_full(self):
        here = os.getcwd()
        os.chdir(self.tmp)
        try:
            said = []
            HR.main(["--set", "damit", "--dams", "dams.gpkg", "--out", "runs", "--dem", "dem.tif", "run 2801"],
                    chat=lambda m, fmt=None, timeout=None: json.dumps(fields(ids=["2801"])),
                    ask=lambda p: "y", runner=lambda a: 0, out=said.append)
        finally:
            os.chdir(here)
        with open(HR.SAVED, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["damit"]["dams"], self.dams)

    def test_every_reading_is_logged(self):
        self.go("run 2801", fields(ids=["2810"]))
        self.go("run 2801", fields(ids=["2801"]), answer="n")
        self.go("run 2801", fields(ids=["2801"]), extra=["--show"])
        with open(HR.drafts_log(), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("refused: dam id '2810'", log)
        self.assertIn("stopped (no y)", log)
        self.assertIn("shown (--show)", log)
        self.assertIn('"2810"', log)

    def test_written_numbers_count(self):
        code, said = self.go("run 2801 at 5m, n=0.035.", fields(ids=["2801"], cell_m=5, manning=0.035))
        self.assertEqual(code, 0, said)
        self.assertIn("--manning", self.calls[1])

    def test_anything_else_asked_for_is_refused(self):
        code, said = self.go("run 2801 with Froehlich 2008 at max pool",
                             fields(ids=["2801"], unsupported=["breach method Froehlich 2008", "max pool"]))
        self.assertEqual(self.calls, [])
        self.assertIn("cannot set 'max pool'", said)

    def test_redo_only_when_the_words_ask(self):
        code, said = self.go("run 2801", fields(ids=["2801"], redo=True))
        self.assertIn("left out redo", said)
        self.assertNotIn("--redo", self.calls[1])
        self.calls = []
        code, said = self.go("rerun 2801", fields(ids=["2801"], redo=True))
        self.assertIn("--redo", self.calls[1])
        self.assertIn("REDO", said)

    def test_no_model_or_bad_json(self):
        for reply in (OSError("connection refused"), "I think you want 2801", '{"ids": [}'):
            self.calls = []
            code, said = self.go("run 2801", reply)
            self.assertEqual(self.calls, [])
            self.assertIn("could not read the request", said)

    def test_show_runs_nothing(self):
        code, said = self.go("run 2801", fields(ids=["2801"]), extra=["--show"])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("--show: nothing was run", said)

    def test_paths_are_remembered_after_a_confirmed_run(self):
        self.go("run 2801", fields(ids=["2801"]))
        with open(HR.SAVED, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["_last_set"], "damit")
        self.assertEqual(saved["damit"]["dams"], self.dams)
        said = []
        code = HR.main(["run 4031"], chat=lambda m, fmt=None, timeout=None: json.dumps(fields(ids=["4031"])),
                       ask=lambda p: "y", runner=lambda a: self.calls.append(a) or 0, out=said.append)
        self.assertEqual(code, 0, said)
        self.assertIn(self.dams, self.calls[-1])

    def test_no_paths_yet(self):
        said = []
        code = HR.main(["--set", "damit", "run 2801"], chat=lambda m, fmt=None, timeout=None: json.dumps(fields(ids=["2801"])),
                       ask=lambda p: "y", runner=lambda a: 0, out=said.append)
        self.assertEqual(code, 2)
        self.assertIn("no dams layer (--dams) yet", "\n".join(said))


class CommandWordTest(unittest.TestCase):
    def test_run_is_a_command_and_a_question_stays_a_question(self):
        self.assertEqual(RQ.command_word(["run", "2801 at 5 m"]), ("heimrun", ["2801 at 5 m"]))
        self.assertEqual(RQ.command_word(["run"]), ("heimrun", []))
        self.assertEqual(RQ.command_word(["run", "--help"]), ("heimrun", ["--help"]))
        self.assertIsNone(RQ.command_word(["run", "times", "for", "ANUGA?"]))
        self.assertIsNone(RQ.command_word(["running", "2801"]))

    def test_windows_does_not_exec(self):
        # os.execv on Windows ends heim and leaves `heim run` asking for y behind the console prompt
        with open(os.path.join(TOOLS, "rag_query.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('if os.name == "nt":', src)
        self.assertIn("sys.exit(subprocess.call([sys.executable, tool] + word[1]))", src)

    def test_help_names_it(self):
        self.assertIn('heim run "run 2801 at 5 m"', RQ.HELP)


class InstallTest(unittest.TestCase):
    def test_every_installer_copies_it(self):
        root = os.path.dirname(os.path.dirname(HERE))
        with open(os.path.join(os.path.dirname(HERE), "setup-local-heim.sh"), encoding="utf-8") as fh:
            self.assertIn("ai_score heim_run; do", fh.read())
        for name in ("install-local-ai-linux.sh", "install-local-ai-windows.ps1"):
            p = os.path.join(root, name)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    self.assertIn("heim_run.py", fh.read(), name)


if __name__ == "__main__":
    unittest.main()
