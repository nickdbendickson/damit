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


HPMS_LAYER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hpms_nd_layer_fields.json")
HPMS_ERROR_PAGE = (b'<html lang="en">\n<head>\n<title>\nError: Field name \'AADT\' does not exist. Did you mean '
                   b'\'aadt\'?</title>\n</head><body>ArcGIS REST Framework</body></html>')


class FakeArcgisLayer(object):
    """Answers like the live FHWA HPMS FeatureServer (checked 2026-11-20): ?f=json gives the layer's fields (from the
    recorded fixture); /query refuses a field name with the wrong case (its HTML error page; the live server sends it
    with HTTP 500, which DamIT's client raises, and some ArcGIS servers with 200) and pages GeoJSON with
    exceededTransferLimit under "properties"."""

    def __init__(self, url, total=3, page=2):
        with open(HPMS_LAYER, encoding="utf-8") as fh:
            self.layer = json.load(fh)
        self.url, self.total, self.page = url.rstrip("/"), total, page
        self.names = {f["name"] for f in self.layer["fields"]}
        self.queries = []

    def __call__(self, url):
        import urllib.parse
        if url == self.url + "?f=json":
            return json.dumps(self.layer).encode()
        base, _, query = url.partition("?")
        assert base == self.url + "/query", url
        q = dict(urllib.parse.parse_qsl(query))
        self.queries.append(q)
        fields = [f for f in q["outFields"].split(",") if f != "*"]
        if any(f not in self.names for f in fields):
            return HPMS_ERROR_PAGE
        start = int(q["resultOffset"])
        stop = min(self.total, start + min(self.page, int(q["resultRecordCount"])))
        feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-97.0, 47.0 + i * 1e-3],
                                                                                         [-97.0, 47.001 + i * 1e-3]]},
                  "properties": {f: i for f in (fields or sorted(self.names))}} for i in range(start, stop)]
        return json.dumps({"type": "FeatureCollection", "features": feats,
                           "properties": {"exceededTransferLimit": stop < self.total}}).encode()


class Hpms(unittest.TestCase):
    """0.2.2: the HPMS request used upper-case field names; the FHWA service has lower-case ones and refused it."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_the_plan_asks_for_fields_the_live_layer_has(self):
        p = sources.plan("hpms", state="ND")
        self.assertEqual(p["urls"][0], "https://geo.dot.gov/server/rest/services/Hosted/NorthDakota_2018_PR/FeatureServer/0")
        with open(HPMS_LAYER, encoding="utf-8") as fh:
            have = {f["name"] for f in json.load(fh)["fields"]}
        asked = p["fields"].split(",")
        self.assertEqual([f for f in asked if f not in have], [], "every field exactly as the service spells it")
        self.assertIn("aadt", asked)
        self.assertIn("f_system", asked)
        self.assertEqual(sources.plan("hpms", state="DC")["urls"][0].split("/")[-3], "District_2018_PR")

    def test_hpms_download_gets_every_page_with_the_real_field_names(self):
        p = sources.plan("hpms", state="ND")
        fake = FakeArcgisLayer(p["urls"][0], total=5, page=2)
        r = update.update(p, FakeHttp(json_by_url=fake), self.root, feedback=Quiet())
        self.assertEqual(r["status"], "updated")
        with open(os.path.join(self.root, "ND", "hpms", "hpms.geojson"), encoding="utf-8") as fh:
            fc = json.load(fh)
        self.assertEqual(len(fc["features"]), 5, "GeoJSON paging reads exceededTransferLimit under properties")
        self.assertEqual([q["resultOffset"] for q in fake.queries], ["0", "2", "4"])
        self.assertIn("aadt", fc["features"][0]["properties"])
        self.assertEqual(fake.queries[0]["outFields"], p["fields"])

    def test_upper_case_names_are_matched_to_the_layer_and_unknown_ones_left_out(self):
        url = sources.HPMS_FEATURE_SERVER.format(state_name="NorthDakota")
        logs = []

        class Log(update.Feedback):
            def log(self, text):
                logs.append(text)
        got = update._arcgis_fields(url, FakeHttp(json_by_url=FakeArcgisLayer(url)), "AADT,F_SYSTEM,NOT_A_FIELD",
                                    Log(), "HPMS")
        self.assertEqual(got, "aadt,f_system")
        self.assertTrue(any("NOT_A_FIELD" in ln for ln in logs))
        self.assertEqual(update._arcgis_fields(url, FakeHttp(files={}), "AADT", Log()), "AADT",
                         "layer not readable: sent as given")
        self.assertEqual(update._arcgis_fields(url, FakeHttp(files={}), "*", Log()), "*")

    def test_a_refused_field_says_what_the_server_said(self):
        url = sources.HPMS_FEATURE_SERVER.format(state_name="NorthDakota")
        fake = FakeArcgisLayer(url)
        with self.assertRaises(update.UpdateError) as caught:
            update._arcgis_query_all(url, FakeHttp(json_by_url=fake), "1=1", "AADT", Quiet(), "HPMS")
        self.assertIn("Field name 'AADT' does not exist", str(caught.exception))
        err = json.dumps({"error": {"code": 400, "message": "Invalid query parameters", "details": ["bad where"]}})
        with self.assertRaises(update.UpdateError) as caught:
            update._arcgis_query_all(url, FakeHttp(json_by_url=lambda u: err.encode()), "1=1", "*", Quiet(), "HPMS")
        self.assertIn("Invalid query parameters; bad where", str(caught.exception))


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


class GetDataScript(unittest.TestCase):
    """get_data.py: the same engine from the command line, with no QGIS."""

    def setUp(self):
        import importlib
        self.cli = importlib.import_module("damit_data.get_data")
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = os.path.join(self.root, "data")
        self.lines = []

    def run_cli(self, *argv, http=None):
        return self.cli.main(list(argv) + ["--folder", self.data], client=http, out=self.lines.append)

    def text(self):
        return "\n".join(self.lines)

    def test_a_box_fetches_nsi_and_status_names_it(self):
        http = FakeHttp(json_by_url=lambda u: nsi_fixture())
        self.assertEqual(self.run_cli("--bbox=-96.9,46.8,-96.7,46.95", http=http), 0, self.text())
        areas = [d for d in os.listdir(self.data) if d.startswith("extent_")]
        self.assertEqual(len(areas), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.data, areas[0], "nsi", "nsi.geojson")))
        self.assertIn("bbox=", http.calls[0][1])
        self.assertIn("1 of 1 source(s) in place", self.text())
        self.lines = []
        self.assertEqual(self.run_cli("--status"), 0)
        self.assertIn(areas[0] + "/nsi", self.text())

    def test_a_state_takes_the_default_sources_and_one_failure_keeps_the_rest(self):
        osm = sources.plan("osm", state="ND")["urls"][0]

        class Http(FakeHttp):
            def head(self, url, timeout=30):
                if url not in self.files:
                    raise IOError("server down")
                return FakeHttp.head(self, url, timeout)
        http = Http(files={osm: zip_bytes({"gis_osm_buildings.gpkg": b"GPKG"})}, headers={osm: {"etag": '"v1"'}})
        self.assertEqual(self.run_cli("--state", "North Dakota", "--sources", "osm,microsoft", http=http), 1)
        self.assertTrue(os.path.exists(os.path.join(self.data, "ND", "osm", "gis_osm_buildings.gpkg")))
        self.assertIn("1 of 2 source(s) in place (failed: microsoft)", self.text())
        self.assertIn("FAILED: Microsoft US Building Footprints", self.text())
        self.assertEqual(self.cli.pick_sources("", "ND", None, ""),
                         [s for s in sources.ORDER if sources.SOURCES[s]["default"]])
        self.assertEqual(self.cli.pick_sources("", None, (0, 0, 1, 1), ""), ["nsi"], "a box alone serves NSI only")
        self.assertNotIn("usa_structures", self.cli.pick_sources("all", "ND", None, ""))
        self.assertIn("usa_structures", self.cli.pick_sources("all", "ND", None, "https://x/y.zip"))

    def test_a_dry_run_and_the_list_download_nothing(self):
        http = FakeHttp()
        self.assertEqual(self.run_cli("--state", "ND", "--dry-run", http=http), 0)
        self.assertEqual(self.cli.main(["--list"], client=http, out=self.lines.append), 0)
        self.assertEqual(http.calls, [])
        self.assertFalse(os.path.exists(self.data))
        self.assertIn("53 request(s)", self.text())           # NSI, one per ND county
        self.assertIn("microsoft", self.text())

    def test_requests_that_cannot_be_made_stop_with_the_reason(self):
        http = FakeHttp()
        for argv, want in (((), "give --state"), (("--state", "Narnia"), "unknown US state"),
                           (("--state", "ND", "--sources", "nsi,bogus"), "unknown source(s): bogus"),
                           (("--bbox=1,2,3",), "--bbox needs"),
                           (("--bbox=-97,46,-96.9,46.1", "--sources", "osm"), "OpenStreetMap"),
                           (("--bbox=-104,45,-96,49",), "square degrees")):
            self.lines = []
            self.assertEqual(self.run_cli(*argv, http=http), 2, argv)
            self.assertIn(want, self.text(), argv)
        self.lines = []
        pack = os.path.join(self.root, "ND_Dam_Suite_Pack", "x")
        self.assertEqual(self.cli.main(["--state", "ND", "--folder", pack], client=http, out=self.lines.append), 2)
        self.assertIn("offline pack", self.text())
        self.assertEqual(http.calls, [])

    def test_it_runs_as_a_script_from_anywhere_without_qgis(self):
        import subprocess
        script = os.path.join(ROOT, "damit_data", "get_data.py")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        r = subprocess.run([sys.executable, script, "--list"], capture_output=True, text=True, cwd=self.root, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("National Structure Inventory", r.stdout)


if __name__ == "__main__":
    unittest.main()
