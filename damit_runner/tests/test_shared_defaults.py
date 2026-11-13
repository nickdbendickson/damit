"""DamIT Core 0.3.0: the DamIT Runner reads the shared defaults file (PMF Vw rule) and records
what a run used in dam.json ("assumptions"). Synthetic numbers; no QGIS."""
import json
import os
import shutil
import tempfile
import types
import unittest

from damit_core.lib import shared_defaults as SD
from damit_runner.core import breach as br
from damit_runner.core import flood as fl
from damit_runner.core import workflow as wf


class RunnerSharedDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="damit_rsd_")
        self.old = {k: os.environ.get(k) for k in (SD.ENV_PATH, "DAMIT_SETTINGS")}
        os.environ["DAMIT_SETTINGS"] = os.path.join(self.tmp, "settings.json")
        self.use(None)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def use(self, values):
        p = os.path.join(self.tmp, "defaults_{}.json".format(len(os.listdir(self.tmp))))
        if values is not None:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"format": SD.FORMAT, "format_version": 1, "values": values}, f)
        os.environ[SD.ENV_PATH] = p

    def _flood(self, **kw):
        dam = br.DamData(dam_id="S5", dam_height_ft=30.0, storage_top_acft=2000.0,
                         top_of_dam_ft=1100.0, surface_area_top_ac=150.0, crest_length_ft=600.0)
        fi = fl.FloodInputs.triangle(3000.0, 12.0, 48.0, normal_pool_ft=1090.0, crest_length_ft=600.0,
                                     trigger="wse", trigger_value=1094.0, **kw)
        return fl.route_flood(dam, br.METHOD_PIPING, br.BreachOverrides(), fi)

    def test_method_ids(self):
        for mode in SD.SCHEMA["failure_mode"]["choices"]:
            for m in SD.SCHEMA["breach_method"]["choices"]:
                self.assertIn(SD.runner_method({"failure_mode": mode, "breach_method": m}), br.METHODS)

    def test_pmf_vw_follows_the_file(self):
        self.assertEqual(fl.pmf_vw_source(), br.VW_POOL)
        self.assertLess(self._flood().with_breach.params["vw_acft"], 1900.0)
        self.use({"pmf_breach_volume": "max_storage"})
        self.assertEqual(fl.pmf_vw_source(), br.VW_MAX_STORAGE)
        self.assertEqual(self._flood().with_breach.params["vw_acft"], 2000.0)
        self.assertLess(self._flood(vw_source=br.VW_POOL).with_breach.params["vw_acft"], 1900.0)

    def test_assumptions(self):
        st = types.SimpleNamespace(scenario=wf.SCENARIO_SUNNY, breach_method=br.METHOD_TR60,
                                   manning_n=0.08, flood=None)
        log, warnings = [], []
        e = wf._assumptions(st, "0.9", log.append, warnings)
        self.assertEqual(e["tool"], "damit_run")
        self.assertEqual(e["used"]["sunny_day_start_pool"], "max_pool")
        self.assertEqual(set(e["differs"]), {"breach_method", "manning_n"})
        self.assertTrue(any("0.08" in x for x in log))
        self.use({"sunny_day_start_pool": "normal_pool"})
        warnings = []
        wf._assumptions(st, "0.9", [].append, warnings)
        self.assertTrue(warnings and "top of dam" in warnings[0])
        json.dumps(e)


if __name__ == "__main__":
    unittest.main()
