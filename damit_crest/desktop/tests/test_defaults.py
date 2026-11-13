"""Your shared defaults file in the desktop window (defaults.py, the pywebview bridge) and the assumptions entry the
hand-off writes into dam.json.

    python3 damit_crest/desktop/tests/test_defaults.py
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

import damit_desktop.__main__ as m  # noqa: E402
from damit_desktop import defaults  # noqa: E402
from damit_desktop.handoff import write_dam_folder  # noqa: E402

GOOD = json.dumps({"format": "dam-defaults", "format_version": 1, "name": "Your defaults",
                   "values": {"manning_n": 0.05, "sunny_day_start_pool": "normal_pool"}}, indent=1)


def env(**values):
    """The environment without any DamIT path variable, plus `values`. HOME points at an empty folder unless given, so
    a settings file on the machine running the tests is never read."""
    clean = {k: v for k, v in os.environ.items() if k not in (defaults.ENV_PATH, defaults.SETTINGS_ENV)}
    clean.update(values)
    return mock.patch.dict(os.environ, clean, clear=True)


class PathTests(unittest.TestCase):
    def test_default_is_damit_in_the_home_folder(self):
        with tempfile.TemporaryDirectory() as home, env(HOME=home, USERPROFILE=home):
            self.assertEqual(defaults.user_path(), Path(home) / "DamIT" / "defaults.json")

    def test_env_overrides_the_home_folder(self):
        with tempfile.TemporaryDirectory() as home, env(HOME=home, USERPROFILE=home, DAMIT_DEFAULTS="/x/suite.json"):
            self.assertEqual(defaults.user_path(), Path("/x/suite.json"))

    def test_the_damit_settings_file_wins_as_in_damit_core(self):
        # damit_core.lib.shared_defaults.user_path: the defaults_file setting, else DAMIT_DEFAULTS, else ~/DamIT.
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home) / "settings.json"
            settings.write_text(json.dumps({"state": "ND", "defaults_file": "/y/mine.json"}), encoding="utf-8")
            with env(HOME=home, USERPROFILE=home, DAMIT_SETTINGS=str(settings), DAMIT_DEFAULTS="/x/suite.json"):
                self.assertEqual(defaults.user_path(), Path("/y/mine.json"))
            # The default place of that file, with no DAMIT_SETTINGS.
            cfg = Path(home) / ".config" / "damit"
            cfg.mkdir(parents=True)
            (cfg / "settings.json").write_text(json.dumps({"defaults_file": "/z/other.json"}), encoding="utf-8")
            with env(HOME=home, USERPROFILE=home):
                self.assertEqual(defaults.user_path(), Path("/z/other.json"))

    def test_a_settings_file_without_the_key_or_not_json_is_passed_over(self):
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home) / "settings.json"
            for text in ('{"defaults_file": ""}', '{"state": "ND"}', "not json", "[1, 2]", '{"defaults_file": 5}'):
                settings.write_text(text, encoding="utf-8")
                with env(HOME=home, USERPROFILE=home, DAMIT_SETTINGS=str(settings), DAMIT_DEFAULTS="/x/suite.json"):
                    self.assertEqual(defaults.user_path(), Path("/x/suite.json"), text)


class ReadWriteTests(unittest.TestCase):
    def test_no_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "DamIT" / "defaults.json"
            self.assertEqual(defaults.read_user(path), {"path": str(path), "text": None})

    def test_write_then_read_round_trip_creates_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "DamIT" / "defaults.json"
            self.assertEqual(defaults.write_user(GOOD, path), {"saved": str(path)})
            got = defaults.read_user(path)
            self.assertEqual(json.loads(got["text"])["values"], {"manning_n": 0.05, "sunny_day_start_pool": "normal_pool"})
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
            self.assertEqual([p.name for p in path.parent.iterdir()], ["defaults.json"], "no temp file left behind")

    def test_reads_a_file_saved_with_a_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "defaults.json"
            path.write_text(GOOD, encoding="utf-8-sig")
            self.assertEqual(defaults.read_user(path)["text"], GOOD)

    def test_refuses_what_is_not_a_defaults_file_and_keeps_the_old_one(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "defaults.json"
            defaults.write_user(GOOD, path)
            before = path.read_text(encoding="utf-8")
            for bad in (
                "{",
                "[]",
                json.dumps({"format": "crest-desk", "format_version": 1, "values": {}}),
                json.dumps({"format": "dam-defaults", "format_version": 2, "values": {}}),
                json.dumps({"format": "dam-defaults", "format_version": 1, "values": []}),
                json.dumps({"format": "dam-defaults", "format_version": 1, "values": {"manning_n": True}}),
                json.dumps({"format": "dam-defaults", "format_version": 1, "values": {"manning_n": {"a": 1}}}),
                json.dumps({"format": "dam-defaults", "format_version": 1, "values": {"x": "y" * 300_000}}),
                None,
                42,
            ):
                self.assertIn("error", defaults.write_user(bad, path), repr(bad)[:60])
                self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_an_oversized_or_unreadable_file_is_an_error_not_a_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "defaults.json"
            path.write_bytes(b" " * (defaults.MAX_BYTES + 1))
            self.assertIn("too large", defaults.read_user(path)["error"])
            path.write_bytes(b"\xff\xfe\xff")
            self.assertIn("cannot be read", defaults.read_user(path)["error"])

    def test_the_bridge_reads_and_writes_your_file(self):
        with tempfile.TemporaryDirectory() as d, env(HOME=d, USERPROFILE=d, DAMIT_DEFAULTS=str(Path(d) / "mine.json")):
            api = m.Api()
            self.assertIsNone(api.get_defaults()["text"])
            self.assertEqual(api.save_defaults(GOOD), {"saved": str(Path(d) / "mine.json")})
            self.assertEqual(json.loads(api.get_defaults()["text"])["values"]["manning_n"], 0.05)
            self.assertIn("error", api.save_defaults("not json"))


DAM = {"id": "d1", "nid": "ND00199", "name": "Test", "heightFt": 27.5, "storageAcFt": 1612.59, "lengthFt": 1700,
       "method": "froehlich", "failureMode": "piping"}
ASSUME = {"used": {"sunny_day_start_pool": "normal_pool", "manning_n": 0.06}, "differs": {"sunny_day_start_pool": {"used": "normal_pool", "shared": "max_pool"}},
          "shared_values": {"sunny_day_start_pool": "max_pool", "manning_n": 0.06}, "tool": "damit_crest", "version": "1+abc", "when": "2026-11-13T18:00:00"}
ANALYSIS = {"datum": {"crestNavdFt": 1071.09, "streambedNavdFt": 1043.59, "poolNavdFt": 1061.09},
            "breach": {"peakCfs": 9000, "widthFt": 80, "series": [], "startPool": "normal", "startPoolNavdFt": 1061.09, "startPoolLabel": "normal pool"},
            "screen": {"level": "Low", "label": "Low", "reasons": []}, "assumptions": ASSUME}


class HandoffAssumptionsTests(unittest.TestCase):
    def read(self, folder: Path) -> dict:
        return json.loads((folder / "dam.json").read_text(encoding="utf-8"))

    def test_the_hand_off_writes_the_assumptions_entry_and_the_starting_pool(self):
        with tempfile.TemporaryDirectory() as d:
            folder, _ = write_dam_folder(Path(d), DAM, ANALYSIS)
            rec = self.read(folder)
            self.assertEqual(rec["assumptions"], ASSUME)
            result = rec["status"][-1]["result"]
            self.assertEqual(result["assumptions"], ASSUME)
            self.assertEqual(result["starting_pool_ft"], 1061.09)
            self.assertEqual(result["starting_pool_rule"], "normal pool")

    def test_crest_replaces_its_own_entry_but_keeps_another_tools(self):
        with tempfile.TemporaryDirectory() as d:
            folder, _ = write_dam_folder(Path(d), DAM, ANALYSIS)
            newer = {**ASSUME, "when": "2026-11-14T08:00:00"}
            write_dam_folder(Path(d), DAM, {**ANALYSIS, "assumptions": newer})
            self.assertEqual(self.read(folder)["assumptions"]["when"], "2026-11-14T08:00:00")
            rec = self.read(folder)
            rec["assumptions"] = {"tool": "damit_run", "used": {"manning_n": 0.05}}
            (folder / "dam.json").write_text(json.dumps(rec), encoding="utf-8")
            _, notes = write_dam_folder(Path(d), DAM, ANALYSIS)
            rec = self.read(folder)
            self.assertEqual(rec["assumptions"]["tool"], "damit_run")
            self.assertEqual(rec["status"][-1]["result"]["assumptions"], ASSUME)
            self.assertTrue(any("Kept the assumptions entry damit_run" in n for n in notes))

    def test_an_older_desk_without_the_entry_writes_none(self):
        with tempfile.TemporaryDirectory() as d:
            old = {k: v for k, v in ANALYSIS.items() if k != "assumptions"}
            old["breach"] = {"peakCfs": 9000, "widthFt": 80, "series": []}
            folder, _ = write_dam_folder(Path(d), DAM, old)
            rec = self.read(folder)
            self.assertNotIn("assumptions", rec)
            self.assertNotIn("assumptions", rec["status"][-1]["result"])
            self.assertNotIn("starting_pool_ft", rec["status"][-1]["result"])


if __name__ == "__main__":
    unittest.main()
