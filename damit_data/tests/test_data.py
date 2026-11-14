"""DamIT Data engine (pure Python, fake HTTP, no network)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from damit_core.lib import settings  # noqa: E402
from damit_data.core import sources, store, update  # noqa: E402
from fakehttp import FC_EMPTY, FakeHttp, nsi_fixture, zip_bytes  # noqa: E402


class Quiet(update.Feedback):
    def log(self, text):
        pass


class Sources(unittest.TestCase):
    def test_any_state(self):
        for st in ("ND", "NE", "TX", "VT"):
            p = sources.plan("osm", state=st)
            self.assertTrue(p["urls"][0].startswith("https://download.geofabrik.de/north-america/us/"))
            self.assertEqual(p["area"], st)
        self.assertTrue(sources.plan("microsoft", state="NY")["urls"][0].endswith("/NewYork.geojson.zip"))
        nsi = sources.plan("nsi", state="RI")
        self.assertEqual(len(nsi["urls"]), 5)                 # five RI counties, one request each
        self.assertIn("fips=44001", nsi["urls"][0])

    def test_tiger_counties(self):
        for st in ("ND", "CA", "TX"):
            p = sources.plan("tiger_counties", state=st)
            self.assertEqual(p["kind"], "arcgis_feature_service")
            self.assertIn("TIGERweb", p["urls"][0])
            self.assertIn("STATE=", p["state_filter"])
        with self.assertRaises(sources.SourceError):
            sources.plan("tiger_counties")  # no state

    def test_nbi(self):
        p = sources.plan("nbi", state="ND")
        self.assertEqual(p["kind"], "file")
        self.assertIn("38ND23.txt", p["urls"][0])
        p2 = sources.plan("nbi", state="CA")
        self.assertIn("06CA23.txt", p2["urls"][0])
        with self.assertRaises(sources.SourceError):
            sources.plan("nbi")

    def test_hifld(self):
        p = sources.plan("hifld", state="ND")
        self.assertEqual(p["kind"], "arcgis_feature_service_multi")
        self.assertEqual(len(p["multi_files"]), 4)
        names = [f[1] for f in p["multi_files"]]
        self.assertIn("hospitals.geojson", names)
        self.assertIn("schools.geojson", names)
        self.assertIn("fire_stations.geojson", names)
        self.assertIn("ems.geojson", names)
        with self.assertRaises(sources.SourceError):
            sources.plan("hifld")

    def test_all_sources_have_plans(self):
        for sid in sources.ORDER:
            self.assertIn(sid, sources.SOURCES)

    def test_extent_and_refusals(self):
        p = sources.plan("nsi", bbox=(-96.80, 46.87, -96.78, 46.88))
        self.assertIn("bbox=-96.800000,46.870000,", p["urls"][0])
        self.assertTrue(p["area"].startswith("extent_"))
        with self.assertRaises(sources.SourceError):
            sources.plan("nsi", bbox=(-100, 40, -98, 42))       # too big for one request
        with self.assertRaises(sources.SourceError):
            sources.plan("microsoft", bbox=(-96.8, 46.8, -96.7, 46.9))
        with self.assertRaises(sources.SourceError):
            sources.plan("microsoft", state="PR")              # no published file
        with self.assertRaises(sources.SourceError):
            sources.plan("osm")
        with self.assertRaises(sources.SourceError):
            sources.plan("usa_structures", url="http://insecure/x.zip")
        self.assertEqual(sources.plan("usa_structures", state="NE", url="https://x.example/NE_Structures.zip?a=1")
                         ["filename"], "NE_Structures.zip")


class Store(unittest.TestCase):
    def test_refuses_nd_pack(self):
        for bad in ("/data/ND_Dam_Suite_Pack", "/data/ND_Dam_Suite_Pack_v2/structures"):
            with self.assertRaises(store.StoreError):
                store.check_writable_target(bad)

    def test_root_from_setting(self):
        tmp = tempfile.mkdtemp()
        old = os.environ.get(settings.ENV)
        os.environ[settings.ENV] = os.path.join(tmp, "s.json")
        try:
            settings.set("data_folder", os.path.join(tmp, "data"))
            self.assertEqual(store.root(), os.path.join(tmp, "data"))
            self.assertEqual(store.root(os.path.join(tmp, "x")), os.path.join(tmp, "x"))
        finally:
            if old is None:
                os.environ.pop(settings.ENV, None)
            else:
                os.environ[settings.ENV] = old
            shutil.rmtree(tmp)


class Update(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_file_source_staged_then_unchanged(self):
        p = sources.plan("osm", state="ND")
        url = p["urls"][0]
        http = FakeHttp(files={url: zip_bytes({"gis_osm_buildings.gpkg": b"GPKG"})},
                        headers={url: {"etag": '"v1"'}})
        r = update.update(p, http, self.root, feedback=Quiet())
        self.assertEqual(r["status"], "updated")
        gp = os.path.join(self.root, "ND", "osm", "gis_osm_buildings.gpkg")
        self.assertTrue(os.path.exists(gp))
        self.assertFalse(os.path.exists(os.path.join(self.root, "ND", "osm", p["filename"])))   # zip removed
        self.assertEqual([k for k, _ in store.all_layers(self.root)], ["ND/osm"])
        r2 = update.update(p, http, self.root, feedback=Quiet())
        self.assertEqual(r2["status"], "unchanged")
        self.assertEqual([c[0] for c in http.calls].count("download"), 1)
        http.headers[url] = {"etag": '"v2"'}
        self.assertEqual(update.update(p, http, self.root, feedback=Quiet())["status"], "updated")

    def test_bad_zip_keeps_old_copy(self):
        p = sources.plan("microsoft", state="ND")
        url = p["urls"][0]
        http = FakeHttp(files={url: zip_bytes({"NorthDakota.geojson": FC_EMPTY})}, headers={url: {"etag": "a"}})
        update.update(p, http, self.root, feedback=Quiet())
        http.files[url] = b"not a zip"
        http.headers[url] = {"etag": "b"}
        with self.assertRaises(update.UpdateError):
            update.update(p, http, self.root, feedback=Quiet())
        self.assertTrue(os.path.exists(os.path.join(self.root, "ND", "microsoft_footprints", "NorthDakota.geojson")))
        self.assertFalse(any(n.startswith(".staging") for n in os.listdir(os.path.join(self.root, "ND"))))

    def test_a_folder_that_cannot_be_replaced_keeps_the_old_copy(self):
        """0.2.1. On Windows a folder with an open file (a layer in QGIS) cannot be renamed.
        The refusal is played here; the update must say why, keep the copy the user had and
        leave no staged download behind. Both steps of the swap are tried."""
        p = sources.plan("microsoft", state="ND")
        url = p["urls"][0]
        folder = os.path.join(self.root, "ND", "microsoft_footprints")
        mine = os.path.join(folder, "NorthDakota.geojson")
        http = FakeHttp(files={url: zip_bytes({"NorthDakota.geojson": FC_EMPTY})}, headers={url: {"etag": "a"}})
        update.update(p, http, self.root, feedback=Quiet())
        with open(mine, "rb") as fh:
            before = fh.read()
        recorded = store.read_manifest(self.root)["entries"]["ND/microsoft"]["version"]
        real = os.replace
        for refuse in ("old", "new"):
            calls = []

            def replace(src, dst, _refuse=refuse, _calls=calls):
                _calls.append((src, dst))
                if (_refuse == "old" and dst.endswith(".old")) or \
                        (_refuse == "new" and os.path.basename(src).startswith(".staging")):
                    raise PermissionError(13, "The process cannot access the file", src)
                return real(src, dst)
            http.files[url] = zip_bytes({"NorthDakota.geojson": FC_EMPTY, "new.txt": "x"})
            http.headers[url] = {"etag": "b-" + refuse}
            update.os.replace = replace
            try:
                with self.assertRaises(update.UpdateError) as cm:
                    update.update(p, http, self.root, feedback=Quiet())
            finally:
                update.os.replace = real
            self.assertIn("is open in QGIS", str(cm.exception))
            self.assertIn("The copy you had is kept", str(cm.exception))
            self.assertTrue(calls, refuse)
            with open(mine, "rb") as fh:
                self.assertEqual(fh.read(), before, refuse)
            self.assertFalse(os.path.exists(os.path.join(folder, "new.txt")), refuse)
            self.assertEqual(sorted(os.listdir(os.path.join(self.root, "ND"))), ["microsoft_footprints"], refuse)
            self.assertEqual(store.read_manifest(self.root)["entries"]["ND/microsoft"]["version"], recorded)
        # and the next update, with nothing open, goes through
        http.headers[url] = {"etag": "c"}
        self.assertEqual(update.update(p, http, self.root, feedback=Quiet())["status"], "updated")
        self.assertTrue(os.path.exists(os.path.join(folder, "new.txt")))

    def test_size_limit(self):
        p = sources.plan("osm", state="ND")
        url = p["urls"][0]
        http = FakeHttp(files={url: b"x"}, headers={url: {"content-length": str(3 * 10 ** 9)}})
        with self.assertRaises(update.UpdateError):
            update.update(p, http, self.root, feedback=Quiet(), max_mb=1500)
        self.assertNotIn("download", [c[0] for c in http.calls])

    def test_nsi_extent_and_interval(self):
        p = sources.plan("nsi", bbox=(-96.792, 46.874, -96.789, 46.876))
        http = FakeHttp(json_by_url=lambda u: nsi_fixture())
        r = update.update(p, http, self.root, feedback=Quiet())
        self.assertEqual(r["status"], "updated")
        with open(os.path.join(self.root, p["area"], "nsi", "nsi.geojson")) as fh:
            self.assertEqual(len(json.load(fh)["features"]), 3)
        self.assertEqual(update.update(p, http, self.root, feedback=Quiet())["status"], "skipped")
        self.assertEqual(update.update(p, http, self.root, feedback=Quiet(), force=True)["status"], "updated")

    def test_nsi_state_merges_counties(self):
        p = sources.plan("nsi", state="DE")                    # 3 counties
        http = FakeHttp(json_by_url=lambda u: nsi_fixture())
        update.update(p, http, self.root, feedback=Quiet())
        with open(os.path.join(self.root, "DE", "nsi", "nsi.geojson")) as fh:
            self.assertEqual(len(json.load(fh)["features"]), 9)
        self.assertEqual(len([c for c in http.calls if c[0] == "get"]), 3)

    def test_nsi_bad_answer(self):
        p = sources.plan("nsi", state="DE")
        http = FakeHttp(json_by_url=lambda u: b"<html>busy</html>")
        with self.assertRaises(update.UpdateError):
            update.update(p, http, self.root, feedback=Quiet())


if __name__ == "__main__":
    unittest.main()
