"""The official DaMiT wordmark is the desk icon: copies stay identical, and logo_path() finds one."""

from __future__ import annotations

import unittest
from pathlib import Path

from damit_desktop.__main__ import logo_path

DESKTOP = Path(__file__).resolve().parents[1]
CREST = DESKTOP.parent
REPO = CREST.parent
OFFICIAL = REPO / "docs" / "img" / "damit-wordmark-light.png"
COPIES = (
    CREST / "src" / "assets" / "damit-wordmark-light.png",
    DESKTOP / "damit_desktop" / "icon.png",
)


class LogoTests(unittest.TestCase):
    def test_official_wordmark_is_in_the_repo(self):
        self.assertTrue(OFFICIAL.is_file(), f"missing official wordmark {OFFICIAL}")

    def test_copies_match_the_official_wordmark(self):
        official = OFFICIAL.read_bytes()
        self.assertGreater(len(official), 1000)
        for path in COPIES:
            with self.subTest(path=str(path.relative_to(REPO))):
                self.assertTrue(path.is_file(), f"missing copy {path}")
                self.assertEqual(path.read_bytes(), official, f"{path} does not match {OFFICIAL}")

    def test_logo_path_finds_the_wordmark(self):
        found = logo_path()
        self.assertIsNotNone(found)
        self.assertTrue(found.is_file())
        self.assertEqual(found.read_bytes(), OFFICIAL.read_bytes())


if __name__ == "__main__":
    unittest.main()
