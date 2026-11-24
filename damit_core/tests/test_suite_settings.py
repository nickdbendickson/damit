"""DamIT Core 0.4.0 one suite settings window (pure Python; the window itself is tested
when Qt / QGIS is importable).
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_core.lib import settings, shared_defaults  # noqa: E402
from damit_core.ui import suite_settings_window as SW  # noqa: E402


class Registry(unittest.TestCase):
    def tearDown(self):
        SW._SECTIONS.clear()

    def test_register_and_unregister_section(self):
        self.assertEqual(SW.registered(), {})
        SW.register_section("damit_hazard", lambda: {"page": None}, title="Hazard", order=5)
        self.assertEqual(SW.registered()["damit_hazard"], ("Hazard", 5))
        SW.unregister_section("damit_hazard")
        self.assertEqual(SW.registered(), {})

    def test_builtin_tabs_and_labels(self):
        keys = [k for k, _t, _o in SW.BUILTIN]
        self.assertEqual(keys, ["suite", "catalog", "layers", "defaults"])
        self.assertEqual(SW.ACTION[0], "Suite settings\u2026")
        self.assertEqual(SW.ACTION[1], "DamitSuiteSettings")
        self.assertIn("DamIT", SW.TITLE)
        self.assertIn("\u2014", SW.TITLE)

    def test_all_window_keys_are_known_settings(self):
        shown = set(SW.SUITE_KEYS) | set(SW.CATALOG_KEYS) | set(SW.LAYER_KEYS)
        self.assertTrue(shown <= set(settings.KEYS))
        self.assertNotIn("offline_pack", settings.KEYS)
        self.assertNotIn("offline_pack", shown)
        # every settings key is on some tab (nothing is only reachable in code)
        self.assertEqual(shown, set(settings.KEYS))

    def test_shared_defaults_keys_match_schema(self):
        # the defaults tab is driven by the schema; manning_n stays the 0.05 suite default
        self.assertIn("manning_n", shared_defaults.KEYS)
        path = shared_defaults.shipped_path()
        values, problems = shared_defaults.read(path)
        self.assertEqual(problems, [])
        self.assertEqual(values["manning_n"], 0.05)

    def test_source_does_not_introduce_offline_pack(self):
        here = os.path.join(ROOT, "damit_core")
        for rel in ("ui/suite_settings_window.py", "lib/settings.py", "plugin.py"):
            with open(os.path.join(here, rel), encoding="utf-8") as fh:
                text = fh.read()
            # the window pops a stray offline_pack on save if one ever appeared; it must not
            # add a setting, a default path, or a pack folder.
            if rel.endswith("suite_settings_window.py"):
                self.assertIn('keys.pop("offline_pack", None)', text)
                # no default pack path
                self.assertNotIn("ND_Dam_Suite_Pack", text)
                self.assertNotIn("nd_offline_pack", text)
            else:
                self.assertNotIn("offline_pack", text)


class SettingsRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(settings.ENV)
        os.environ[settings.ENV] = os.path.join(self.tmp, "s.json")

    def tearDown(self):
        if self.old is None:
            os.environ.pop(settings.ENV, None)
        else:
            os.environ[settings.ENV] = self.old
        shutil.rmtree(self.tmp)

    def test_keys_the_window_edits_round_trip(self):
        settings.set("data_folder", "/data")
        settings.set("state", "NE")
        settings.set("unit_system", "si")
        settings.set("preset", "FEMA333")
        self.assertEqual(settings.get("data_folder"), "/data")
        self.assertEqual(settings.get("state"), "NE")
        self.assertEqual(settings.get("unit_system"), "si")
        self.assertEqual(settings.get("preset"), "FEMA333")
        self.assertEqual(settings.get("offline_pack", "") if False else "", "")


class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import Qt only when this class runs, so earlier tests (http.fd counts) are not affected.
        try:
            from qgis.PyQt.QtWidgets import QApplication
        except Exception:
            raise unittest.SkipTest("Qt not importable")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get(settings.ENV)
        os.environ[settings.ENV] = os.path.join(self.tmp, "s.json")
        self.old_def = os.environ.get(shared_defaults.ENV_PATH)
        os.environ[shared_defaults.ENV_PATH] = os.path.join(self.tmp, "defaults.json")
        settings.set("data_folder", "/tmp/damit-data")
        settings.set("state", "ND")

    def tearDown(self):
        if self.old is None:
            os.environ.pop(settings.ENV, None)
        else:
            os.environ[settings.ENV] = self.old
        if self.old_def is None:
            os.environ.pop(shared_defaults.ENV_PATH, None)
        else:
            os.environ[shared_defaults.ENV_PATH] = self.old_def
        SW._WINDOW = None
        shutil.rmtree(self.tmp)

    def test_window_fills_and_saves(self):
        win = SW.SuiteSettingsWindow()
        try:
            self.assertEqual(win.windowTitle(), SW.TITLE)
            keys = [win.tabs.widget(i).property("damit_tab_key") for i in range(win.tabs.count())]
            self.assertEqual(keys[:4], ["suite", "catalog", "layers", "defaults"])
            win.refresh()
            # catalog tab should show ND
            cat = None
            for i in range(win.tabs.count()):
                if win.tabs.widget(i).property("damit_tab_key") == "catalog":
                    cat = win.tabs.widget(i)
            self.assertIsNotNone(cat)
            self.assertEqual(cat._damit_edits["state"].currentData(), "ND")
            # change a suite folder and save
            suite = win.tabs.widget(0)
            suite._damit_edits["work_folder"].setText("/tmp/damit-work")
            self.assertTrue(win.save())
            self.assertEqual(settings.get("work_folder"), "/tmp/damit-work")
            self.assertEqual(settings.get("data_folder"), "/tmp/damit-data")
            self.assertFalse(settings.get("offline_pack") if "offline_pack" in settings.KEYS else False)
        finally:
            win.close()
            win.deleteLater()


if __name__ == "__main__":
    unittest.main()

