"""DamIT Crest uses DamIT Catalog's NID-ID rule (damit_catalog/handoff.py), not a copy. No QGIS is started."""

from __future__ import annotations

import importlib
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from damit_desktop import handoff, nid, nid_rule  # noqa: E402

REPO = HERE.parents[2]
CATALOG_HANDOFF = REPO / "damit_catalog" / "handoff.py"
PKG = HERE.parent / "damit_desktop"


def catalog_module():
    """damit_catalog.handoff imported as the plugins import it (the package, from the repository root)."""
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    return importlib.import_module("damit_catalog.handoff")


class OneRuleTests(unittest.TestCase):
    def test_the_rule_is_loaded_from_catalogs_source_file(self):
        self.assertEqual(nid_rule.SOURCE.resolve(), CATALOG_HANDOFF.resolve())
        for fn in (nid_rule.nid_rule, nid_rule.is_nid_id, handoff.nid_rule, handoff.is_nid_id, nid.is_nid_id):
            self.assertEqual(Path(fn.__code__.co_filename).resolve(), CATALOG_HANDOFF.resolve(), fn)
        self.assertIs(handoff.NID_ID_RE, nid_rule.NID_ID_RE)
        self.assertIs(nid.NID_ID_RE, nid_rule.NID_ID_RE)
        ho = catalog_module()
        self.assertEqual(nid_rule.NID_ID_RE.pattern, ho.NID_ID_RE.pattern)
        self.assertEqual(nid_rule.OTHER_INVENTORY_RE.pattern, ho.OTHER_INVENTORY_RE.pattern)

    def test_no_copy_of_the_rule_in_crest_desktop(self):
        for path in PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(r"[A-Z]{2}\d{3,}", text, f"{path.name} has its own NID ID regex")
            self.assertNotRegex(text, r"re\.compile\([^)]*DWR\|DUG", f"{path.name} has its own other-inventory regex")
            self.assertNotRegex(text, r"^def (nid_rule|is_nid_id)\(", path.name)

    def test_same_answers_as_catalog_for_the_records_crest_hands_off(self):
        ho = catalog_module()
        for d in (
            {"dam_id": "ND00199", "nid_id": "ND00199"}, {"dam_id": "", "nid_id": "ND00199"},
            {"dam_id": "DWR-2801", "nid_id": "ND00199"}, {"dam_id": "DWR_2801", "is_new": True},
            {"dam_id": "DWR 2801", "is_sample": True}, {"dam_id": "DWR2801"}, {"dam_id": "DUG-130", "is_new": True},
            {"dam_id": "UNK-9", "is_sample": True}, {"dam_id": "ND00001", "nid_id": "ND00002"},
            {"dam_id": "x", "nid_id": "DWR-1"}, {"dam_id": "Dugan Dam", "nid_id": "ND00199"},
            {"dam_id": "Dugan Dam", "is_new": True}, {"dam_id": "p", "new_or_existing": "Proposed"},
            {"dam_id": "desk-ab12", "is_new": True}, {"dam_id": "local-sample", "is_sample": True}, {"dam_id": "desk-x"},
        ):
            self.assertEqual(handoff.nid_rule(d), ho.nid_rule(d), d)


def desk(**kw):
    return {"name": "Test", **kw}


class NidProblemTests(unittest.TestCase):
    def test_accepted_records(self):
        for d in (
            desk(nid="ND00199", id="nd00199"), desk(nidId="nd00199", id="x"),
            desk(nid="", id="desk-new1", isNew=True), desk(nid="SAMPLE-4031", id="local-sample"),
            desk(nid="DESK-014", id="prairie"), desk(nid="", id="Dugan Dam", isNew=True),
        ):
            self.assertIsNone(handoff.nid_problem(d), d)

    def test_refused_records(self):
        for d in (
            desk(nid="DWR-4031"), desk(nid="", id="desk-x"), desk(nid="NEW", id="desk-y"), desk(nid="DUG-130", id="d"),
        ):
            problem = handoff.nid_problem(d)
            self.assertIsNotNone(problem, d)
            self.assertIn("NID", problem)
            self.assertIn("DamIT Catalog NID rule", problem)

    def test_a_new_dam_or_sample_named_by_another_inventory_is_refused_like_the_plugins(self):
        # Leftover from #9: Crest let a new dam whose desk id is DWR-... through; Catalog's rule refuses it.
        ho = catalog_module()
        for desk_id in ("DWR-2801", "DWR_2801", "DWR 2801", "DWR2801", "dwr-2801", "DUG-130", "UNK-9"):
            for flags in ({"isNew": True}, {"nid": "SAMPLE-4031"}):
                d = desk(id=desk_id, **flags)
                ids = handoff.handoff_ids(d)
                self.assertIsNotNone(ho.nid_rule(ids)[0], ids)
                problem = handoff.nid_problem(d)
                self.assertIsNotNone(problem, d)
                self.assertIn("another inventory's id", problem)

    def test_a_desk_id_is_never_taken_as_the_nid_id(self):
        self.assertIsNotNone(handoff.nid_problem(desk(nid="", id="nd00199")))
        problem = handoff.nid_problem(desk(nid="", id="ND00199", isNew=True))
        self.assertIsNotNone(problem)
        self.assertNotIn("another inventory", problem)

    def test_crest_accepts_exactly_what_catalog_accepts_for_the_handed_off_fields(self):
        ho = catalog_module()
        ids = ["ND00199", "desk-a", "DWR-2801", "DWR2801", "DUG_1", "UNK 9", "Dugan Dam", "SAMPLE-4031", "NEW", ""]
        for i in ids:
            for n in ids:
                for new in (False, True):
                    d = desk(id=i, nid=n, isNew=new)
                    rec = handoff.handoff_ids(d)
                    error, _w, got = ho.nid_rule(rec)
                    expect_ok = error is None and got == rec["nid_id"]
                    self.assertEqual(handoff.nid_problem(d) is None, expect_ok, d)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.saved = sys.modules.get("damit_desktop.nid_rule")

    def tearDown(self):
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
            importlib.reload(nid_rule)  # back to the repository's damit_catalog/handoff.py
        sys.modules["damit_desktop.nid_rule"] = self.saved

    def test_a_pyinstaller_bundle_loads_the_shipped_catalog_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "damit_catalog").mkdir()
            shutil.copy(CATALOG_HANDOFF, Path(tmp) / "damit_catalog" / "handoff.py")
            sys._MEIPASS = tmp
            mod = importlib.reload(nid_rule)
            self.assertEqual(mod.SOURCE, Path(tmp) / "damit_catalog" / "handoff.py")
            self.assertIsNone(mod.nid_rule({"dam_id": "ND00199"})[0])

    def test_missing_catalog_stops_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig = nid_rule.candidates
            try:
                nid_rule.candidates = lambda: [Path(tmp) / "nope" / "handoff.py"]
                with self.assertRaises(nid_rule.CatalogRuleMissing):
                    nid_rule._load()
            finally:
                nid_rule.candidates = orig

    def test_the_desktop_build_ships_catalogs_file(self):
        spec = (HERE.parent / "damit_crest.spec").read_text(encoding="utf-8")
        self.assertIn('("../../damit_catalog/handoff.py", "damit_catalog")', spec)
        self.assertIn('"damit_desktop.nid_rule"', spec)
        self.assertTrue((HERE.parent / "../../damit_catalog/handoff.py").resolve().is_file())
        self.assertTrue(re.search(r"nid_rule", (PKG / "handoff.py").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
