"""Fixes from the fresh DamIT Desk install test of 2026-11-21 (Absaraka, sandbox install):

- the first-start copy of the old DamIT Crest settings folder is announced (terminal, Report step, a note file);
- the Work folder hint shows the folder a blank field really means (DAMIT_WORK when it is set);
- Check QGIS reads QGIS_CUSTOM_CONFIG_PATH from the qgis_process launcher, which is where the installer sets it.

Headless: nothing is started but the desk's own local server on a free port.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import damit_desktop.__main__ as m  # noqa: E402
from damit_desktop import qgis_run  # noqa: E402


class MigrationNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.new, self.old = root / "damit-desk", root / "damit-crest"
        self.patches = [mock.patch.object(m, "storage_dir", return_value=self.new),
                        mock.patch.object(m, "legacy_storage_dir", return_value=self.old)]
        for p in self.patches:
            p.start()
        self.lines: list[str] = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        m.STORAGE_NOTICES.clear()
        self.tmp.cleanup()

    def test_the_copy_is_announced_and_noted_in_the_new_folder(self):
        self.old.mkdir()
        (self.old / "damit-crest-settings.json").write_text("{}")
        m.prepare_storage(self.lines.append)
        self.assertEqual(len(m.STORAGE_NOTICES), 1, m.STORAGE_NOTICES)
        self.assertIn(str(self.old), m.STORAGE_NOTICES[0])
        self.assertIn("left as it was", m.STORAGE_NOTICES[0])
        self.assertEqual(self.lines, ["DamIT Desk: " + m.STORAGE_NOTICES[0]])
        note = (self.new / m.MIGRATED_NOTE).read_text()
        self.assertIn(str(self.old), note)
        self.assertFalse((self.old / m.MIGRATED_NOTE).exists(), "the old folder is not written")

    def test_later_runs_and_fresh_installs_say_nothing(self):
        m.prepare_storage(self.lines.append)                  # fresh: no old folder
        self.assertEqual(m.STORAGE_NOTICES, [])
        self.old.mkdir()
        m.prepare_storage(self.lines.append)                  # new folder exists now: no copy
        self.assertEqual(m.STORAGE_NOTICES, [])
        self.assertEqual(self.lines, [])

    def test_a_settings_file_taken_from_the_old_folder_is_announced(self):
        self.new.mkdir()
        self.old.mkdir()
        (self.old / "damit-crest-settings.json").write_text('{"dem_path": "/d.vrt"}')
        _, settings = m.prepare_storage(self.lines.append)
        self.assertEqual(json.loads(settings.read_text())["dem_path"], "/d.vrt")
        self.assertEqual(len(m.STORAGE_NOTICES), 1)
        self.assertIn("settings file", m.STORAGE_NOTICES[0])


class WorkFolderTests(unittest.TestCase):
    def test_default_work_dir_follows_damit_work(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.dict(os.environ, {"DAMIT_WORK": t}):
                self.assertEqual(qgis_run.default_work_dir(), Path(t).resolve())
                self.assertEqual(qgis_run.work_dir(None), Path(t).resolve())
            with mock.patch.dict(os.environ, {"DAMIT_WORK": "", "HOME": t, "USERPROFILE": t}):
                self.assertEqual(qgis_run.default_work_dir(), (Path(t) / "DamITDams").resolve())
                self.assertFalse((Path(t) / "DamITDams").exists(), "showing the folder does not create it")


class HandoffInfoTests(unittest.TestCase):
    def test_handoff_answers_the_work_folder_and_the_notices(self):
        with tempfile.TemporaryDirectory() as t:
            web = Path(t) / "web"
            web.mkdir()
            (web / "index.html").write_text("<!doctype html><title>t</title>")
            work = Path(t) / "my work"
            with mock.patch.dict(os.environ, {"DAMIT_WORK": str(work)}), \
                    mock.patch.object(m, "STORAGE_NOTICES", ["first start: copied the old DamIT Crest settings"]):
                server = m.serve(web, port=0)
                try:
                    port = server.server_address[1]
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request("GET", "/api/handoff", headers={"Host": f"127.0.0.1:{port}", m.TOKEN_HEADER: m.API_TOKEN})
                    r = conn.getresponse()
                    info = json.loads(r.read())
                    conn.close()
                finally:
                    server.shutdown()
                    server.server_close()
            self.assertEqual(r.status, 200)
            self.assertEqual(info["work"], str(work.resolve()))
            self.assertEqual(info["notices"], ["first start: copied the old DamIT Crest settings"])
            self.assertEqual(info["algorithms"]["classify"], "damit:classify")


class LauncherConfigPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def script(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_the_installers_sh_launcher(self):
        # As install-all.sh writes it (mk_qgis_process, printf %q), including a path with a space.
        exe = self.script("qgis-process-damit.sh", "#!/bin/bash\n# QGIS_CUSTOM_CONFIG_PATH=/not/this\n"
                          "export PYTHONPATH=/q/share/qgis/python\n"
                          "export QGIS_CUSTOM_CONFIG_PATH=/sb/my\\ sandbox/qgis-process/damit\n"
                          'exec /q/bin/qgis_process "$@"\n')
        self.assertEqual(qgis_run.launcher_config_path(exe), "/sb/my sandbox/qgis-process/damit")

    def test_the_installers_cmd_launcher(self):
        exe = self.script("qgis-process-damit.cmd", '@echo off\r\nrem QGIS_CUSTOM_CONFIG_PATH=C:\\no\r\n'
                          'set "QGIS_CUSTOM_CONFIG_PATH=C:\\Users\\nick\\dam suite\\qgis-process\\damit"\r\n'
                          '"C:\\q\\bin\\qgis_process.exe" %*\r\n')
        self.assertEqual(qgis_run.launcher_config_path(exe), "C:\\Users\\nick\\dam suite\\qgis-process\\damit")

    def test_a_binary_or_a_plain_script_sets_nothing(self):
        binary = self.dir / "qgis_process"
        binary.write_bytes(b"\x7fELF\x00\x00QGIS_CUSTOM_CONFIG_PATH=/x\n")
        self.assertIsNone(qgis_run.launcher_config_path(str(binary)))
        plain = self.script("wrap.sh", '#!/bin/sh\nexec qgis_process "$@"\n')
        self.assertIsNone(qgis_run.launcher_config_path(plain))
        self.assertIsNone(qgis_run.launcher_config_path(str(self.dir / "missing")))

    def test_the_launcher_wins_over_the_desk_environment(self):
        exe = self.script("q.sh", "export QGIS_CUSTOM_CONFIG_PATH=/from/launcher\n")
        with mock.patch.dict(os.environ, {"QGIS_CUSTOM_CONFIG_PATH": "/from/env"}):
            self.assertEqual(qgis_run.qgis_config_path(exe)[0], "/from/launcher")
            plain = self.script("p.sh", "exec qgis_process\n")
            self.assertEqual(qgis_run.qgis_config_path(plain), ("/from/env", "from the desk's environment"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QGIS_CUSTOM_CONFIG_PATH", None)
            self.assertEqual(qgis_run.qgis_config_path(plain), (None, ""))


@unittest.skipIf(os.name == "nt", "the fake qgis_process is a shell script (POSIX only)")
class CheckQgisReadsTheLauncherTests(unittest.TestCase):
    def test_check_reports_the_launchers_profile_not_unset(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "qgis-process" / "damit"
            real = Path(t) / "qgis_profile" / "profiles" / "damit"
            (root / "profiles").mkdir(parents=True)
            real.mkdir(parents=True)
            (root / "profiles" / "default").symlink_to(real)
            exe = Path(t) / "qgis-process-damit.sh"
            exe.write_text("#!/bin/sh\nexport QGIS_CUSTOM_CONFIG_PATH=%s\n"
                           'if [ "$1" = help ]; then echo "$2"; exit 0; fi\nexit 2\n' % root)
            exe.chmod(0o755)
            lines: list[str] = []
            with mock.patch.dict(os.environ, {"QGIS_PROCESS": str(exe)}):
                os.environ.pop("QGIS_CUSTOM_CONFIG_PATH", None)
                r = qgis_run.run_check(lines.append, config=qgis_run.load_config(Path(t) / "settings"))
            self.assertTrue(r["ok"], lines)
            text = "\n".join(lines)
            self.assertNotIn("is not set", text)
            self.assertIn(f"default profile under {root} (QGIS_CUSTOM_CONFIG_PATH, set by the launcher qgis-process-damit.sh)", text)
            self.assertIn(f"-> {os.path.realpath(real)}", text)


if __name__ == "__main__":
    unittest.main()
