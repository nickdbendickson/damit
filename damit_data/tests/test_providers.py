"""DamIT Data providers on small offline fixtures (audit 3-pack, lower priority: more provider fixtures).

The engine tests in test_data.py cover NSI (one fixture) and the Geofabrik / Microsoft zip happy path. These
cover the other ways a provider answer is read, and its error paths, each on a fixture in tests/fixtures/ or a
zip built here: the HIFLD multi-layer ArcGIS answer, the NBI delimited file (kept as downloaded), unsafe,
damaged and empty zips, a File Geodatabase in the USA Structures zip, and NSI answers that are not a
FeatureCollection. After every failure the copy the user had is kept and no staged folder is left behind.
Pure Python, fake HTTP, no network.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from damit_data.core import sources, store, update  # noqa: E402
from fakehttp import FakeHttp, zip_bytes  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


class Quiet(update.Feedback):
    def __init__(self):
        self.lines = []

    def log(self, text):
        self.lines.append(text)


HIFLD = {sources.HIFLD_HOSPITALS: "hifld_hospitals_tiny.geojson", sources.HIFLD_SCHOOLS: "hifld_schools_tiny.geojson",
         sources.HIFLD_FIRE_STATIONS: "hifld_fire_stations_tiny.geojson", sources.HIFLD_EMS: "hifld_ems_tiny.geojson"}


def hifld_server(overrides=None):
    """json_by_url for FakeHttp: the layer's fixture for its /query (or an override answer); records the queries."""
    seen = []

    def answer(url):
        base, _q, query = url.partition("/query?")
        seen.append((base, urllib.parse.parse_qs(query)))
        if overrides and base in overrides:
            return overrides[base]
        return fixture(HIFLD[base])
    answer.seen = seen
    return answer


def staged_left(root):
    return [os.path.join(b, d) for b, ds, _f in os.walk(root) for d in ds if d.startswith(".staging")]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)


class Hifld(Base):
    def test_four_layers_from_fixtures(self):
        p = sources.plan("hifld", state="ND")
        server = hifld_server()
        fb = Quiet()
        r = update.update(p, FakeHttp(json_by_url=server), self.root, feedback=fb)
        self.assertEqual(r["status"], "updated")
        folder = os.path.join(self.root, "ND", "hifld")
        self.assertEqual(sorted(os.listdir(folder)), ["ems.geojson", "fire_stations.geojson", "hospitals.geojson",
                                                       "schools.geojson", "source.json"])
        counts = {}
        for n in ("hospitals", "schools", "fire_stations", "ems"):
            with open(os.path.join(folder, n + ".geojson"), encoding="utf-8") as fh:
                d = json.load(fh)
            self.assertEqual(d["type"], "FeatureCollection")
            counts[n] = len(d["features"])
        self.assertEqual(counts, {"hospitals": 2, "schools": 3, "fire_stations": 1, "ems": 0})
        # every query asks for this state only, all fields, GeoJSON
        self.assertEqual(len(server.seen), 4)
        for _base, q in server.seen:
            self.assertEqual(q["where"], ["STATE='ND'"])
            self.assertEqual(q["outFields"], ["*"])
            self.assertEqual(q["f"], ["geojson"])
        with open(os.path.join(folder, "source.json"), encoding="utf-8") as fh:
            src = json.load(fh)
        self.assertEqual(src["layers"], 4)
        self.assertEqual(r["entry"]["version"], "sha256:" + src["sha256"])
        # the layers the store offers: the four GeoJSON files, not source.json (it matches *.geojson only)
        self.assertEqual(sorted(os.path.basename(p_) for _k, p_ in store.all_layers(self.root)),
                         ["ems.geojson", "fire_stations.geojson", "hospitals.geojson", "schools.geojson"])
        # within 30 days: not asked again
        again = hifld_server()
        self.assertEqual(update.update(p, FakeHttp(json_by_url=again), self.root, feedback=Quiet())["status"],
                         "skipped")
        self.assertEqual(again.seen, [])

    def test_one_layer_answering_garbage_keeps_the_old_copy(self):
        p = sources.plan("hifld", state="ND")
        update.update(p, FakeHttp(json_by_url=hifld_server()), self.root, feedback=Quiet())
        folder = os.path.join(self.root, "ND", "hifld")
        with open(os.path.join(folder, "schools.geojson"), "rb") as fh:
            before = fh.read()
        recorded = store.read_manifest(self.root)["entries"]["ND/hifld"]
        for bad in (b"<html><head><title>502 Bad Gateway</title></head></html>", b"\xff\xfe not utf-8"):
            server = hifld_server({sources.HIFLD_SCHOOLS: bad})
            with self.assertRaises(update.UpdateError):
                update.update(p, FakeHttp(json_by_url=server), self.root, force=True, feedback=Quiet())
            with open(os.path.join(folder, "schools.geojson"), "rb") as fh:
                self.assertEqual(fh.read(), before)
            self.assertEqual(staged_left(self.root), [])
            self.assertEqual(store.read_manifest(self.root)["entries"]["ND/hifld"], recorded)


class Nbi(Base):
    def test_delimited_file_kept_as_downloaded_then_unchanged(self):
        p = sources.plan("nbi", state="ND")
        self.assertEqual(p["urls"], ["https://www.fhwa.dot.gov/bridge/nbi/2023/delimited/38ND23.txt"])
        self.assertFalse(p["extract"])
        url = p["urls"][0]
        data = fixture("nbi_nd_tiny.txt")
        http = FakeHttp(files={url: data}, headers={url: {"last-modified": "Tue, 01 Oct 2024 00:00:00 GMT"}})
        r = update.update(p, http, self.root, feedback=Quiet())
        self.assertEqual(r["status"], "updated")
        got = os.path.join(self.root, "ND", "nbi", "nbi.csv")
        with open(got, "rb") as fh:
            self.assertEqual(fh.read(), data)                           # byte for byte, quotes and all
        import csv
        with open(got, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh, quotechar="'"))
        self.assertEqual([r_["STRUCTURE_NUMBER_008"] for r_ in rows],
                         ["TEST0000000001", "TEST0000000002", "TEST0000000003"])
        self.assertEqual({r_["STATE_CODE_001"] for r_ in rows}, {"38"})
        self.assertIn("Tue, 01 Oct 2024", r["entry"]["version"])
        self.assertEqual(update.update(p, http, self.root, feedback=Quiet())["status"], "unchanged")
        self.assertEqual([c[0] for c in http.calls].count("download"), 1)

    def test_no_state_is_refused(self):
        with self.assertRaises(sources.SourceError):
            sources.plan("nbi")


class Zips(Base):
    def plan_with(self, payload, sid="microsoft", etag="a"):
        p = sources.plan(sid, state="ND")
        url = p["urls"][0]
        return p, FakeHttp(files={url: payload}, headers={url: {"etag": etag}})

    def test_unsafe_member_paths_are_refused(self):
        for evil in ("../escape.geojson", "/abs.geojson", "a/../../escape.geojson"):
            p, http = self.plan_with(zip_bytes({"NorthDakota.geojson": b"{}", evil: b"{}"}))
            with self.assertRaises(update.UpdateError) as cm:
                update.update(p, http, self.root, feedback=Quiet())
            self.assertIn("unsafe path", str(cm.exception))
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "escape.geojson")))
            self.assertFalse(os.path.exists(os.path.join(self.root, "escape.geojson")))
            self.assertEqual(staged_left(self.root), [])
            self.assertFalse(os.path.exists(os.path.join(self.root, "ND", "microsoft_footprints")))

    def test_damaged_member_is_refused_and_the_old_copy_kept(self):
        good = zip_bytes({"NorthDakota.geojson": b'{"type": "FeatureCollection", "features": []}'})
        p, http = self.plan_with(good)
        update.update(p, http, self.root, feedback=Quiet())
        # a stored member whose bytes no longer match its CRC
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("NorthDakota.geojson", b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        raw = bytearray(buf.getvalue())
        i = raw.index(b"AAAAAAAA")
        raw[i] = ord("B")
        url = p["urls"][0]
        http.files[url] = bytes(raw)
        http.headers[url] = {"etag": "b"}
        with self.assertRaises(update.UpdateError) as cm:
            update.update(p, http, self.root, feedback=Quiet())
        self.assertIn("damaged zip member NorthDakota.geojson", str(cm.exception))
        with open(os.path.join(self.root, "ND", "microsoft_footprints", "NorthDakota.geojson"), "rb") as fh:
            self.assertIn(b"FeatureCollection", fh.read())
        self.assertEqual(staged_left(self.root), [])

    def test_an_empty_zip_is_refused(self):
        p, http = self.plan_with(zip_bytes({}))
        with self.assertRaises(update.UpdateError) as cm:
            update.update(p, http, self.root, feedback=Quiet())
        self.assertIn("held no files", str(cm.exception))
        self.assertEqual(staged_left(self.root), [])
        self.assertNotIn("ND/microsoft", store.read_manifest(self.root).get("entries", {}))

    def test_usa_structures_file_geodatabase_is_one_layer(self):
        url = "https://fema.example/USA_Structures/Deliverable20230526ND.zip?download=1"
        p = sources.plan("usa_structures", state="ND", url=url)
        self.assertEqual(p["filename"], "Deliverable20230526ND.zip")
        members = {"Deliverable20230526ND/ND_Structures.gdb/a00000001.gdbtable": b"t",
                   "Deliverable20230526ND/ND_Structures.gdb/a00000001.gdbtablx": b"x",
                   "Deliverable20230526ND/ND_Structures.gdb/gdb": b"g",
                   "Deliverable20230526ND/readme.txt": b"r"}
        http = FakeHttp(files={url: zip_bytes(members)}, headers={url: {"etag": "v1"}})
        r = update.update(p, http, self.root, feedback=Quiet())
        # the .gdb folder is one entry (update._list stops at it), not its dozens of internal files
        gdb = os.path.join("ND", "usa_structures", "Deliverable20230526ND", "ND_Structures.gdb")
        self.assertEqual(r["entry"]["files"],
                         [gdb, os.path.join("ND", "usa_structures", "Deliverable20230526ND", "readme.txt")])
        self.assertEqual([os.path.relpath(p_, self.root) for _k, p_ in store.all_layers(self.root)], [gdb])

    def test_http_links_for_usa_structures_are_refused(self):
        for bad in ("http://fema.example/x.zip", "", "ftp://x/y.zip"):
            with self.assertRaises(sources.SourceError):
                sources.plan("usa_structures", state="ND", url=bad)


class NsiAnswers(Base):
    def test_answers_that_are_not_a_feature_collection(self):
        p = sources.plan("nsi", bbox=(-96.792, 46.874, -96.789, 46.876))
        for raw, why in ((json.dumps({"type": "Feature", "geometry": None}).encode(), "did not return a FeatureCollection"),
                         (json.dumps([1, 2]).encode(), "did not return a FeatureCollection"),
                         (b"\xff\xfe\x00", "invalid JSON"),
                         (b"", "invalid JSON")):
            with self.assertRaises(update.UpdateError) as cm:
                update.update(p, FakeHttp(json_by_url=lambda u, _r=raw: _r), self.root, feedback=Quiet())
            self.assertIn(why, str(cm.exception))
            self.assertEqual(staged_left(self.root), [])

    def test_a_county_with_no_structures_is_fine(self):
        p = sources.plan("nsi", state="DE")
        answers = [fixture("nsi_fargo_tiny.json"), json.dumps({"type": "FeatureCollection", "features": None}).encode(),
                   json.dumps({"type": "FeatureCollection", "features": []}).encode()]
        it = iter(answers)
        fb = Quiet()
        r = update.update(p, FakeHttp(json_by_url=lambda u: next(it)), self.root, feedback=fb)
        self.assertEqual(r["status"], "updated")
        with open(os.path.join(self.root, "DE", "nsi", "nsi.geojson"), encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["features"]), 3)
        self.assertEqual([ln for ln in fb.lines if ln.startswith("NSI:")][-2:],
                         ["NSI: 2 of 3: 0 structures", "NSI: 3 of 3: 0 structures"])


if __name__ == "__main__":
    unittest.main()
