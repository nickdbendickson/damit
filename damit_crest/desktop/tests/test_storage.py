"""The settings folder moves from DamIT Crest's name to DamIT Desk's (2026-11-20): copied once, the old folder kept."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import damit_desktop.__main__ as m  # noqa: E402


class StorageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.new = self.root / "damit-desk"
        self.old = self.root / "damit-crest"
        self.patches = [mock.patch.object(m, "storage_dir", return_value=self.new),
                        mock.patch.object(m, "legacy_storage_dir", return_value=self.old)]
        for p in self.patches:
            p.start()
        self.lines: list[str] = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def old_store(self):
        (self.old / "nid").mkdir(parents=True)
        (self.old / "nid" / "ND.csv").write_text("NID ID\nND00199\n")
        (self.old / "damit-crest-settings.json").write_text(json.dumps({"dem_path": "/data/cass.vrt"}))
        (self.old / "Local Storage").mkdir()
        (self.old / "Local Storage" / "leveldb.log").write_bytes(b"records")

    def test_first_run_copies_the_old_folder_and_leaves_it(self):
        self.old_store()
        before = sorted(str(p.relative_to(self.old)) for p in self.old.rglob("*"))
        store, settings = m.prepare_storage(self.lines.append)
        self.assertEqual(store, self.new)
        self.assertEqual(settings, self.new / "damit-desk-settings.json")
        self.assertEqual(json.loads(settings.read_text())["dem_path"], "/data/cass.vrt")
        self.assertEqual((self.new / "nid" / "ND.csv").read_text(), "NID ID\nND00199\n")
        self.assertEqual((self.new / "Local Storage" / "leveldb.log").read_bytes(), b"records")
        self.assertEqual(sorted(str(p.relative_to(self.old)) for p in self.old.rglob("*")), before, "old folder unchanged")
        self.assertTrue(any("left as it was" in line for line in self.lines))

    def test_later_runs_do_not_copy_again(self):
        self.old_store()
        m.prepare_storage(self.lines.append)
        (self.new / "damit-desk-settings.json").write_text(json.dumps({"dem_path": "/data/new.vrt"}))
        (self.old / "damit-crest-settings.json").write_text(json.dumps({"dem_path": "/data/changed-in-crest.vrt"}))
        _, settings = m.prepare_storage(self.lines.append)
        self.assertEqual(json.loads(settings.read_text())["dem_path"], "/data/new.vrt")

    def test_a_missing_settings_file_is_read_from_the_old_name(self):
        self.new.mkdir()
        (self.new / "damit-crest-settings.json").write_text(json.dumps({"export_dir": "/w/exports"}))
        _, settings = m.prepare_storage(self.lines.append)
        self.assertEqual(json.loads(settings.read_text())["export_dir"], "/w/exports")

    def test_a_fresh_install_starts_empty(self):
        store, settings = m.prepare_storage(self.lines.append)
        self.assertTrue(store.is_dir())
        self.assertFalse(settings.exists())
        self.assertFalse(self.old.exists())

    def test_when_the_copy_fails_the_old_folder_is_used(self):
        self.old_store()
        with mock.patch.object(m.shutil, "copytree", side_effect=OSError("disk full")):
            store, settings = m.prepare_storage(self.lines.append)
        self.assertEqual(store, self.old)
        self.assertEqual(settings, self.old / "damit-crest-settings.json")
        self.assertFalse(self.new.exists())


if __name__ == "__main__":
    unittest.main()
