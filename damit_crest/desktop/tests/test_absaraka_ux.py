"""Absaraka (ND00199) desk test 2026-11-21, UX follow-ups: the classify receptor list, hand-off auto-fill, the
"needs ruling" flag and a fixed port.

    python3 app/desktop/tests/test_absaraka_ux.py
"""

from __future__ import annotations

import io
import json
import socket
import sqlite3
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))

import damit_desktop.__main__ as m  # noqa: E402
from damit_desktop import browser_io, classify_receptors as cr, qgis_run  # noqa: E402


def gp_point(lon: float, lat: float) -> bytes:
    """A GeoPackage blob (no envelope, EPSG:4326) holding a little-endian WKB Point."""
    return b"GP\x00\x01" + struct.pack("<i", 4326) + struct.pack("<BIdd", 1, 1, lon, lat)


def gp_line(pts) -> bytes:
    """A GeoPackage blob with an XY envelope holding a WKB LineString."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    env = struct.pack("<dddd", min(xs), max(xs), min(ys), max(ys))
    wkb = struct.pack("<BII", 1, 2, len(pts)) + b"".join(struct.pack("<dd", *p) for p in pts)
    return b"GP\x00\x03" + struct.pack("<i", 4326) + env + wkb


COLS = "rid text, src_fid integer, kind text, class integer, adv_class integer, label text, depth_ft real, vel_fps real, flags text, methods text, geom blob"


def make_classify(folder: Path) -> Path:
    """work/classify/damit_hazard_receptors.gpkg + report + work/classify_inputs/*.geojson, the layout classify writes."""
    out = folder / "classify"
    out.mkdir(parents=True)
    gpkg = out / cr.GPKG_NAME
    con = sqlite3.connect(gpkg)
    con.execute("create table gpkg_contents (table_name text)")
    for t in ("structures", "roads", "rail"):
        con.execute("insert into gpkg_contents values (?)", (t,))
        con.execute(f"create table {t} ({COLS})")
    con.executemany("insert into structures values (?,?,?,?,?,?,?,?,?,?,?)", [
        ("structures:0", 0, "structure", -1, 2, "", 1.25, 0.5, "", "M6", gp_point(-97.1, 46.7)),
        ("structures:1", 1, "structure", -1, -1, "", 0.3, 0.0, "nodata_wse_ground", "", gp_point(-97.2, 46.8)),
        ("structures:2", 2, "structure", -1, -1, "", 0.0, 0.0, "", "", gp_point(-97.3, 46.9)),
    ])
    con.execute("insert into roads values (?,?,?,?,?,?,?,?,?,?,?)",
                ("roads:0", 0, "road", 3, -1, "High", 1.5, 2.0, "", "road_aadt", gp_line([(-97.0, 46.0), (-96.9, 46.1), (-96.8, 46.2)])))
    con.execute("insert into rail values (?,?,?,?,?,?,?,?,?,?,?)",
                ("rail:21", 0, "rail", 3, -1, "High", 2.0, 1.0, "trains_lookup", "rail_trains", gp_line([(-97.5, 46.5), (-97.4, 46.6)])))
    con.commit()
    con.close()
    (out / "damit_hazard_report.json").write_text(json.dumps({"config": {"labels": {"2": "Medium", "3": "High"}}}))
    inputs = folder / "classify_inputs"
    inputs.mkdir()

    def fc(props):
        return json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": p, "geometry": None} for p in props]})

    (inputs / "structures.geojson").write_text(fc([{"name": "1203 Main St"}, {"fd_id": 551, "occtype": "RES1-1SNB"}, {}]))
    (inputs / "roads.geojson").write_text(fc([{"route_name": "I-94", "aadt": 12400}]))
    (inputs / "rail.geojson").write_text(fc([{"RROWNER1": "BNSF", "SUBDIV": "KO", "BRANCH": ""}]))
    return gpkg


class ClassifyReceptorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.gpkg = make_classify(self.root / "dams" / "ND00199")
        p = mock.patch.object(cr, "allowed_work_roots", lambda: [self.root])
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_reads_wet_and_classed_receptors_with_names_strongest_first(self):
        out = cr.read_receptors(cr.gpkg_path(str(self.gpkg)))
        self.assertEqual([r["rid"] for r in out["receptors"]], ["rail:21", "roads:0", "structures:0", "structures:1"])
        self.assertEqual(out["counts"]["STRUCTURES"], {"total": 3, "wet": 2, "hit": 1})
        by = {r["rid"]: r for r in out["receptors"]}
        self.assertEqual(by["rail:21"]["name"], "BNSF · subdivision KO")
        self.assertEqual(by["rail:21"]["flags"], ["trains_lookup"])
        self.assertEqual(by["roads:0"]["name"], "I-94 (AADT 12,400)")
        self.assertEqual(by["roads:0"]["at"], [-96.9, 46.1])
        self.assertEqual(by["roads:0"]["bbox"], [-97.0, 46.0, -96.8, 46.2])
        self.assertEqual(by["structures:0"]["name"], "1203 Main St")
        self.assertEqual((by["structures:0"]["label"], by["structures:0"]["advisory"]), ("Medium", True))
        self.assertEqual(by["structures:1"]["name"], "NSI 551 · RES1-1SNB (single-family home)")
        self.assertIsNone(by["structures:1"]["ordinal"])
        self.assertEqual(by["structures:1"]["at"], [-97.2, 46.8])
        self.assertFalse(out["truncated"])
        self.assertTrue(cr.read_receptors(self.gpkg, limit=2)["truncated"])
        self.assertIsNone(out["ruling"])

    def test_carries_the_needs_ruling_summary_from_the_report(self):
        rep = self.gpkg.parent / "damit_hazard_report.json"
        rep.write_text(json.dumps({"config": {"labels": {"3": "High"}},
                                   "hits": [{"class": 3, "receptors": ["roads:0"]}, {"class": 3, "receptors": ["rail:21"]}],
                                   "flags": [{"code": "trains_lookup", "message": "15 trains/day looked up", "receptors": ["rail:21"]}]}))
        self.assertEqual(cr.read_receptors(self.gpkg)["ruling"],
                         {"label": "High", "hits": 2, "unruled": 1, "why": ["15 trains/day looked up"]})

    def test_only_the_receptors_gpkg_inside_the_work_folder(self):
        with self.assertRaises(cr.ReceptorsError):
            cr.gpkg_path(str(self.gpkg.parent / "damit_hazard_report.json"))
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / cr.GPKG_NAME
            outside.write_bytes(self.gpkg.read_bytes())
            with self.assertRaises(cr.ReceptorsError):
                cr.gpkg_path(str(outside))
        with self.assertRaises(cr.ReceptorsError):
            cr.gpkg_path("")
        self.assertTrue(issubclass(cr.ReceptorsError, browser_io.BrowserIOError))

    def test_a_broken_gpkg_is_a_message_not_a_crash(self):
        self.gpkg.write_bytes(b"not sqlite at all" * 100)
        with self.assertRaises(cr.ReceptorsError):
            cr.read_receptors(self.gpkg)

    def test_geometry_blobs(self):
        self.assertEqual(cr.gpkg_geometry(None), (None, None))
        self.assertEqual(cr.gpkg_geometry(b"XX123456789"), (None, None))
        self.assertEqual(cr.gpkg_geometry(gp_point(1.5, 2.5)), ([1.5, 2.5], [1.5, 2.5, 1.5, 2.5]))


class RulingTests(unittest.TestCase):
    RES = {"hits": [{"class": 3, "receptors": ["roads:4"]}, {"class": 3, "receptors": ["rail:21"]},
                    {"class": 3, "receptors": ["rail:22"]}, {"class": 2, "receptors": ["structures:1"]}],
           "flags": [{"code": "trains_lookup", "message": "BNSF KO 15 trains/day from the lookup", "receptors": ["rail:21", "rail:22"]}]}

    def test_counts_top_class_hits_resting_on_unruled_values(self):
        self.assertEqual(qgis_run.unruled_top(self.RES, {"3": "High"}),
                         {"label": "High", "hits": 3, "unruled": 2, "why": ["BNSF KO 15 trains/day from the lookup"]})

    def test_a_flag_saying_needs_a_ruling_counts_and_ruled_classes_say_nothing(self):
        res = {"hits": [{"class": 3, "receptors": ["rail:9"]}], "flags": [{"code": "x", "message": "needs Nick's ruling", "receptors": ["rail:9"]}]}
        self.assertEqual(qgis_run.unruled_top(res)["unruled"], 1)
        self.assertIsNone(qgis_run.unruled_top({"hits": self.RES["hits"], "flags": []}))
        ruled = {"hits": [{"class": 3, "receptors": ["roads:4"]}], "flags": self.RES["flags"]}
        self.assertIsNone(qgis_run.unruled_top(ruled))


class AutofillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        p1 = mock.patch.object(browser_io, "read_roots", lambda s: [self.root])
        p2 = mock.patch.object(browser_io.localdem, "read_dem_path", lambda s: None)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def put(self, rel: str, data: bytes = b"x") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def test_finds_rasters_by_name_preferring_the_run_folder_and_one_rail_lookup(self):
        run_d = self.put("run/lisflood_hmax_ft.tif", b"D")
        self.put("run/lisflood_vmax_fps.tif", b"V")
        self.put("inputs/lisflood_hmax_ft.tif", b"D")  # an identical copy: same raster
        self.put("tables/rail_trains_lookup.csv", b"a,b")
        out = browser_io.autofill(None, ["lisflood_hmax_ft.tif", "lisflood_vmax_fps.tif", "missing.tif", "notes.txt"])
        self.assertEqual(out["rasters"]["lisflood_hmax_ft.tif"], str(run_d))
        self.assertIsNone(out["rasters"]["missing.tif"])
        self.assertNotIn("notes.txt", out["rasters"])
        self.assertEqual(out["ambiguous"], [])
        self.assertTrue(out["railLookup"].endswith("rail_trains_lookup.csv"))
        self.assertIsNone(out["dem"])

    def test_different_files_with_one_name_are_left_for_the_user(self):
        self.put("a/depth.tif", b"one")
        self.put("b/depth.tif", b"two")
        self.put("x/rail_lookup.csv")
        self.put("y/rail_trains.csv")
        out = browser_io.autofill(None, ["depth.tif"])
        self.assertIsNone(out["rasters"]["depth.tif"])
        self.assertEqual(out["ambiguous"], ["depth.tif"])
        self.assertIsNone(out["railLookup"], "two lookups: the user picks")
        self.assertEqual(len(out["railLookups"]), 2)

    def test_list_dir_csv_mode_lists_tables_only(self):
        self.put("t/rail_trains_lookup.csv")
        self.put("t/dem.tif")
        names = [e["name"] for e in browser_io.list_dir(str(self.root / "t"), "csv")["entries"]]
        self.assertEqual(names, ["rail_trains_lookup.csv"])


class FixedPortTests(unittest.TestCase):
    def test_env_then_settings_then_default(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d) / "damit-desk-settings.json"
            s.write_text(json.dumps({"port": 48001}))
            self.assertEqual(m.configured_port(s, {"DAMIT_PORT": "48002"}), 48002)
            self.assertEqual(m.configured_port(s, {}), 48001)
            self.assertIsNone(m.configured_port(Path(d) / "none.json", {}))
            with redirect_stdout(io.StringIO()) as out:
                self.assertIsNone(m.configured_port(None, {"DAMIT_PORT": "80"}))
                self.assertIsNone(m.configured_port(None, {"DAMIT_PORT": "abc"}))
            self.assertIn("1024 to 65535", out.getvalue())

    def test_a_busy_fixed_port_is_an_error_not_a_random_port(self):
        with tempfile.TemporaryDirectory() as d:
            web = Path(d)
            (web / "index.html").write_text("<!doctype html><html><head><title>t</title></head><body></body></html>")
            busy = socket.socket()
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: otherwise SO_REUSEADDR lets the server bind it too
                busy.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            try:
                with mock.patch.object(m, "check_bundle", lambda root=None: web), \
                        mock.patch.object(m, "load_security_headers", lambda root: {}):
                    with self.assertRaises(m.PortBusyError):
                        m.serve(web, port=port, fixed=True)
                    with redirect_stdout(io.StringIO()):
                        server = m.serve(web, port=port, fixed=False)
                    try:
                        self.assertNotEqual(server.server_address[1], port)
                    finally:
                        server.shutdown()
                        server.server_close()
            finally:
                busy.close()


if __name__ == "__main__":
    unittest.main()
