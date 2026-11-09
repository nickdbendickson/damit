"""A fake DamIT HTTP client: no network in tests."""
import io
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def nsi_fixture():
    with open(os.path.join(HERE, "fixtures", "nsi_fargo_tiny.json"), "rb") as fh:
        return fh.read()


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeHttp(object):
    def __init__(self, files=None, headers=None, json_by_url=None):
        self.files = dict(files or {})          # url -> bytes
        self.headers = dict(headers or {})      # url -> {header: value}
        self.json_by_url = json_by_url          # callable(url) -> bytes, or None
        self.calls = []

    def get_bytes(self, url, timeout=60):
        self.calls.append(("get", url))
        if self.json_by_url is not None:
            return self.json_by_url(url)
        return self.files[url]

    def head(self, url, timeout=30):
        self.calls.append(("head", url))
        h = {"content-length": str(len(self.files.get(url, b"")))}
        h.update(self.headers.get(url, {}))
        return h

    def download_file(self, url, dest, timeout=120, progress=None, cancelled=None, max_bytes=None):
        self.calls.append(("download", url))
        data = self.files[url]
        if max_bytes and len(data) > max_bytes:
            raise IOError("over limit")
        with open(dest, "wb") as fh:
            fh.write(data)
        if progress:
            progress(len(data), len(data))
        return len(data)


FC_EMPTY = json.dumps({"type": "FeatureCollection", "features": []}).encode()
