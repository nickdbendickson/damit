"""Local API hardening: per-launch token, Host/Origin/Content-Type checks, work folder confined to allowed roots.

    python3 damit_crest/desktop/tests/test_local_api.py
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

DESKTOP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DESKTOP))

import damit_desktop.__main__ as m  # noqa: E402
from damit_desktop.qgis_run import WorkFolderError, resolve_work  # noqa: E402


class LocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = Path(cls.tmp.name) / "home"
        cls.home.mkdir()
        cls.env = mock.patch.dict(os.environ, {"HOME": str(cls.home), "DAMIT_WORK": "", "DAMIT_WORK_ROOTS": ""})
        cls.env.start()
        web = Path(cls.tmp.name) / "web"
        web.mkdir()
        (web / "index.html").write_text("<!doctype html><html><head><title>t</title></head><body></body></html>")
        cls.server = m.serve(web, port=0)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.env.stop()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, token=True, host=None, ctype="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h[m.TOKEN_HEADER] = m.API_TOKEN
        if body is not None and ctype:
            h["Content-Type"] = ctype
        h.update(headers or {})
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    def test_index_carries_token(self):
        status, data = self.req("GET", "/index.html", token=False)
        self.assertEqual(status, 200)
        self.assertIn(f'<meta name="damit-token" content="{m.API_TOKEN}">'.encode(), data)

    def test_token_is_random_and_long(self):
        self.assertGreaterEqual(len(m.API_TOKEN), 32)

    def test_single_cache_control_header(self):
        # Cache-Control: no-store is added by the end_headers() override; _send must not also emit it,
        # or every API/static response carries the header twice.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/index.html", headers={"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        r.read()
        cache = [v for (k, v) in r.getheaders() if k.lower() == "cache-control"]
        conn.close()
        self.assertEqual(cache, ["no-store"], f"exactly one Cache-Control header, got {cache}")

    def test_handoff_endpoint_reports_damit_ids_and_needs_the_token(self):
        status, _ = self.req("GET", "/api/handoff", token=False)
        self.assertEqual(status, 403)
        with mock.patch.dict(os.environ, {"DAMIT_ALG_RUNDAM": "damit_runner:rundam"}):
            status, data = self.req("GET", "/api/handoff")
        self.assertEqual(status, 200)
        info = json.loads(data)
        self.assertEqual(info["algorithms"]["classify"], "damit:classify")
        self.assertEqual(info["algorithms"]["preflight"], "damit_screen:preflight")
        self.assertEqual(info["algorithms"]["rundam"], "damit_runner:rundam")
        self.assertEqual(info["sources"]["rundam"], "DAMIT_ALG_RUNDAM")
        self.assertEqual(info["roles"]["classify"]["status"], "published")
        self.assertEqual(info["roles"]["batch"]["status"], "not published")

    def test_nid_state_endpoint_needs_the_token_and_serves_the_cached_state(self):
        from damit_desktop import nid

        status, _ = self.req("GET", "/api/nid/state?state=RI", token=False)
        self.assertEqual(status, 403)
        fixture = (DESKTOP / "tests" / "fixtures" / "nid_ri_fixture.csv").read_text(encoding="utf-8")
        calls = []
        cache = Path(self.tmp.name) / "settings" / "nid"

        def fake_download(url, timeout=120):
            calls.append(url)
            return fixture

        with mock.patch.object(nid, "NID_DIR", cache), mock.patch.object(nid, "_download", fake_download):
            # load_state's default fetch was bound at import, so patch the bound default too.
            with mock.patch.object(nid.load_state, "__defaults__", (False, fake_download, None)):
                status, data = self.req("GET", "/api/nid/state?state=RI")
                self.assertEqual(status, 200, data)
                body = json.loads(data)
                self.assertEqual(body["source"]["state"], "RI")
                self.assertTrue(all(r[0].startswith("RI") for r in body["rows"]))
                self.req("GET", "/api/nid/state?state=RI")
                self.assertEqual(len(calls), 1, "cached after the first download")
                self.req("GET", "/api/nid/state?state=RI&refresh=1")
                self.assertEqual(len(calls), 2)
                status, data = self.req("GET", "/api/nid/state?state=North%20Dakota")
                self.assertEqual(status, 400)
                self.assertIn("state code", json.loads(data)["error"])
        self.assertTrue((cache / "nid_RI.json").is_file())

    def test_classify_job_kind_is_routed(self):
        with mock.patch.object(m, "start_job", return_value={"id": "abc"}) as sj:
            status, data = self.req("POST", "/api/classify", {"dam": {"id": "x"}})
        self.assertEqual(status, 200)
        self.assertEqual(sj.call_args.args[0], "classify")

    def test_classify_forwards_the_receptor_layers_and_rasters(self):
        payload = {"format": "damit_crest/classify_receptors", "layers": {}}
        with mock.patch.object(m, "start_job", return_value={"id": "abc"}) as sj:
            self.req("POST", "/api/classify", {"dam": {"id": "x"}, "receptors": payload, "depth": " /d.tif ",
                                               "wse": "/w.tif", "arrival": "/a.tif"})
        self.assertEqual(sj.call_args.args[8], payload)
        dam = sj.call_args.args[1]
        self.assertEqual((dam["depthRaster"], dam["wseRaster"], dam["arrivalRaster"]), ("/d.tif", "/w.tif", "/a.tif"))
        # Only the classify job takes receptors.
        with mock.patch.object(m, "start_job", return_value={"id": "abc"}) as sj:
            self.req("POST", "/api/screen", {"dam": {"id": "x"}, "receptors": payload})
        self.assertIsNone(sj.call_args.args[8])

    def test_classify_job_carries_hazards_class_back_to_the_page(self):
        got = {}

        def fake(dam, analysis, work, log, files, cancel=None, receptors=None):
            got["receptors"] = receptors
            return {"ok": True, "classification": {"suggestedClass": "High", "ordinal": "3"}}

        with mock.patch.object(m, "run_classify", side_effect=fake):
            job = m.start_job("classify", {"id": "x"}, {}, None, receptors={"format": "damit_crest/classify_receptors"})
            for _ in range(100):
                snap = m.job_snapshot(job["id"])
                if snap and snap["done"]:
                    break
                time.sleep(0.02)
        self.assertEqual(snap["classification"], {"suggestedClass": "High", "ordinal": "3"})
        self.assertEqual(got["receptors"], {"format": "damit_crest/classify_receptors"})

    def test_legacy_pack_source_is_the_data_folder(self):
        with mock.patch.object(m, "start_job", return_value={"id": "abc"}) as sj:
            self.req("POST", "/api/layers", {"dam": {"id": "x"}, "source": "pack"})
        self.assertEqual(sj.call_args.args[6], "data")

    def test_post_without_token_rejected(self):
        status, _ = self.req("POST", "/api/folder", {"dam": {"id": "x"}}, token=False)
        self.assertEqual(status, 403)

    def test_post_wrong_token_rejected(self):
        status, _ = self.req("POST", "/api/folder", {"dam": {"id": "x"}}, token=False, headers={m.TOKEN_HEADER: "nope"})
        self.assertEqual(status, 403)

    def test_text_plain_rejected(self):
        status, _ = self.req("POST", "/api/folder", {"dam": {"id": "x"}}, ctype="text/plain")
        self.assertEqual(status, 415)

    def test_foreign_origin_rejected(self):
        status, _ = self.req("POST", "/api/folder", {"dam": {"id": "x"}}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_rebinding_host_rejected(self):
        for path in ("/api/job?id=x", "/index.html"):
            status, _ = self.req("GET", path, host=f"evil.example:{self.port}")
            self.assertEqual(status, 403, path)

    def _raw_post(self, extra_headers, body: bytes | None):
        """POST /api/folder with headers set by hand (to send a chunked or malformed framing the req() helper
        can't). Returns the status code."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/api/folder", skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.putheader(m.TOKEN_HEADER, m.API_TOKEN)
        conn.putheader("Content-Type", "application/json")
        for key, value in extra_headers.items():
            conn.putheader(key, value)
        conn.endheaders()
        if body is not None:
            conn.send(body)
        r = conn.getresponse()
        status = r.status
        r.read()
        conn.close()
        return status

    def test_chunked_body_rejected(self):
        # A chunked body would read as empty and start a job with defaults; it must be a 400 instead.
        self.assertEqual(self._raw_post({"Transfer-Encoding": "chunked"}, b"0\r\n\r\n"), 400)

    def test_bad_content_length_rejected(self):
        # A non-numeric Content-Length must be a 400, not an unhandled exception in the handler thread.
        self.assertEqual(self._raw_post({"Content-Length": "not-a-number"}, None), 400)

    def test_job_get_needs_token(self):
        status, _ = self.req("GET", "/api/job?id=x", token=False)
        self.assertEqual(status, 403)
        status, _ = self.req("GET", "/api/job?id=x")
        self.assertEqual(status, 404)

    def test_cancel_needs_token(self):
        status, _ = self.req("POST", "/api/cancel?id=x", token=False)
        self.assertEqual(status, 403)

    def test_localhost_host_and_own_origin_allowed(self):
        status, _ = self.req("GET", "/api/job?id=x", host=f"localhost:{self.port}",
                             headers={"Origin": f"http://localhost:{self.port}"})
        self.assertEqual(status, 404)

    def test_work_outside_root_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        status, data = self.req("POST", "/api/folder", {"dam": {"id": "x"}, "work": str(outside)})
        self.assertEqual(status, 400, data)
        self.assertFalse(outside.exists())

    def test_work_inside_root_accepted(self):
        with mock.patch.object(m, "start_job", return_value={"id": "j"}) as sj:
            status, _ = self.req("POST", "/api/folder", {"dam": {"id": "x"}, "work": str(self.home / "DamITDams" / "a")})
        self.assertEqual(status, 200)
        self.assertEqual(sj.call_args.args[3], str((self.home / "DamITDams" / "a").resolve()))


class ResolveWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "DAMIT_WORK": "", "DAMIT_WORK_ROOTS": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_default(self):
        self.assertIsNone(resolve_work(None))
        self.assertIsNone(resolve_work("  "))

    def test_dotdot_escape(self):
        with self.assertRaises(WorkFolderError):
            resolve_work(str(self.home / "DamITDams" / ".." / "elsewhere"))

    def test_relative_goes_under_default_root(self):
        self.assertEqual(resolve_work("proj"), str((self.home / "DamITDams" / "proj").resolve()))
        with self.assertRaises(WorkFolderError):
            resolve_work("../x")

    def test_symlink_escape(self):
        (self.home / "DamITDams").mkdir()
        target = self.home / "secret"
        target.mkdir()
        (self.home / "DamITDams" / "link").symlink_to(target)
        with self.assertRaises(WorkFolderError):
            resolve_work(str(self.home / "DamITDams" / "link"))

    def test_extra_roots(self):
        extra = self.home / "data"
        with mock.patch.dict(os.environ, {"DAMIT_WORK_ROOTS": str(extra)}):
            self.assertEqual(resolve_work(str(extra / "a")), str((extra / "a").resolve()))
        with mock.patch.dict(os.environ, {"DAMIT_WORK": str(extra)}):
            self.assertEqual(resolve_work(str(extra)), str(extra.resolve()))

    def test_non_string(self):
        with self.assertRaises(WorkFolderError):
            resolve_work(["/etc"])


if __name__ == "__main__":
    unittest.main()
