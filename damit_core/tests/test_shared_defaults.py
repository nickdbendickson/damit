"""damit_core.lib.shared_defaults (DamIT Core 0.3.0): the shared defaults file, the same format
as DamSafety Core 1.2.0 and Crest. Pure Python."""
import json
import os
import shutil
import tempfile
import unittest

from damit_core.lib import shared_defaults as SD


class SharedDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_sd_")
        self.old_env = {k: os.environ.get(k) for k in (SD.ENV_PATH, "DAMIT_SETTINGS")}
        os.environ["DAMIT_SETTINGS"] = os.path.join(self.tmp, "settings.json")   # never the real store
        os.environ.pop(SD.ENV_PATH, None)

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _user(self, values, name="mine.json"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"format": SD.FORMAT, "format_version": 1, "values": values}, f)
        return p

    def test_shipped_file(self):
        vals, problems = SD.read(SD.shipped_path())
        self.assertEqual(problems, [])
        self.assertEqual(vals, {"sunny_day_start_pool": "max_pool",
                                "pmf_breach_volume": "storage_at_start_pool",
                                "failure_mode": "piping", "breach_method": "froehlich2008",
                                "manning_n": 0.06})

    def test_same_format_and_keys_as_damsafety_core(self):
        self.assertEqual(SD.FORMAT, "dam-defaults")
        self.assertEqual(SD.KEYS, ("sunny_day_start_pool", "pmf_breach_volume", "failure_mode",
                                   "breach_method", "manning_n"))
        for k in ("sunny_day_start_pool", "pmf_breach_volume", "failure_mode", "breach_method"):
            self.assertTrue(SD.SCHEMA[k]["choices"])

    def test_merge_and_problems(self):
        d = SD.load(user=self._user({"manning_n": 0.045, "failure_mode": "sideways"}))
        self.assertEqual(d.get("manning_n"), 0.045)
        self.assertEqual(d.source["manning_n"], "yours")
        self.assertEqual(d.get("failure_mode"), "piping")
        self.assertTrue(any("failure_mode" in p for p in d.problems))

    def test_user_path_from_setting_and_env(self):
        self.assertEqual(SD.user_path(), SD.default_user_path())
        p = self._user({"manning_n": 0.05}, "env.json")
        os.environ[SD.ENV_PATH] = p
        self.assertEqual(SD.user_path(), p)
        self.assertEqual(SD.value("manning_n"), 0.05)
        from damit_core.lib import settings
        q = self._user({"manning_n": 0.04}, "setting.json")
        settings.set("defaults_file", q)
        self.assertEqual(SD.user_path(), q)                 # the setting wins over the env

    def test_save_user_writes_only_changes(self):
        p = os.path.join(self.tmp, "sub", "defaults.json")
        SD.save_user(dict(SD.load(user=p).suite, manning_n=0.08), p)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["values"], {"manning_n": 0.08})
        SD.save_user({}, p)
        self.assertEqual(SD.load(user=p).get("manning_n"), 0.06)

    def test_runner_method_and_assumptions(self):
        self.assertEqual(SD.runner_method({"failure_mode": "piping", "breach_method": "froehlich2008"}),
                         "piping")
        self.assertEqual(SD.from_runner_method("tr60"), (None, "tr60"))
        d = SD.Defaults({"manning_n": 0.06})
        e = SD.assumptions({"manning_n": 0.07}, "damit_run", "0.9", defaults=d)
        self.assertEqual(e["differs"], {"manning_n": {"used": 0.07, "shared": 0.06}})
        json.dumps(e)


if __name__ == "__main__":
    unittest.main()
