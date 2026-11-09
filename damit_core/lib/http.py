"""Small HTTP helper for the DamIT plugins.

``get_bytes`` uses QGIS's network stack (proxy and SSL settings of the QGIS profile) when a QGIS
application is running, else urllib. ``head`` and ``download_file`` use urllib (streamed to a
temporary file beside the target, then renamed; honours HTTP(S)_PROXY). Every function takes a
timeout; nothing retries in a loop. Tests pass a fake object with the same three methods.
"""
import os
import shutil
import tempfile
import urllib.error
import urllib.request

USER_AGENT = "DamIT-QGIS-plugins/0.1 (+https://github.com/nickdbendickson/damit)"


class HttpError(IOError):
    def __init__(self, url, status=None, message=""):
        self.url, self.status = url, status
        super(HttpError, self).__init__("{} {}: {}".format(status or "error", url, message).strip())


def _qgis_get(url, timeout):
    try:
        from qgis.core import QgsApplication, QgsBlockingNetworkRequest
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtNetwork import QNetworkRequest
    except ImportError:
        return None
    if QgsApplication.instance() is None:
        return None
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT.encode())
    try:
        req.setTransferTimeout(int(timeout * 1000))
    except AttributeError:                       # pragma: no cover - old Qt
        pass
    br = QgsBlockingNetworkRequest()
    err = br.get(req, True)
    reply = br.reply()
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) \
        if hasattr(QNetworkRequest, "Attribute") else reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
    no_error = getattr(getattr(QgsBlockingNetworkRequest, "ErrorCode", QgsBlockingNetworkRequest), "NoError", 0)
    if err != no_error:
        raise HttpError(url, status, br.errorMessage())
    if status and int(status) >= 400:
        raise HttpError(url, status, "HTTP error")
    return bytes(reply.content())


def get_bytes(url, timeout=60, headers=None):
    data = _qgis_get(url, timeout) if not headers else None
    if data is not None:
        return data
    req = urllib.request.Request(url, headers=dict({"User-Agent": USER_AGENT}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - https URLs we build
            return r.read()
    except urllib.error.HTTPError as e:
        raise HttpError(url, e.code, str(e.reason))
    except (urllib.error.URLError, OSError) as e:
        raise HttpError(url, None, str(e))


def head(url, timeout=30):
    """Response headers of a HEAD request (redirects followed), lower-case keys."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
            return {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        raise HttpError(url, e.code, str(e.reason))
    except (urllib.error.URLError, OSError) as e:
        raise HttpError(url, None, str(e))


def download_file(url, dest, timeout=120, progress=None, cancelled=None, max_bytes=None):
    """Stream ``url`` to ``dest`` (temporary file, then rename). ``progress(done, total)``;
    ``cancelled()`` True stops it; ``max_bytes`` refuses a larger download. Returns bytes written."""
    folder = os.path.dirname(os.path.abspath(dest))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".part_", dir=folder)
    done = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r, os.fdopen(fd, "wb") as out:  # noqa: S310
            total = int(r.headers.get("Content-Length") or 0) or None
            if max_bytes and total and total > max_bytes:
                raise HttpError(url, None, "download is {:.0f} MB, over the {:.0f} MB limit".format(
                    total / 1e6, max_bytes / 1e6))
            while True:
                if cancelled is not None and cancelled():
                    raise HttpError(url, None, "cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if max_bytes and done > max_bytes:
                    raise HttpError(url, None, "download passed the {:.0f} MB limit".format(max_bytes / 1e6))
                if progress is not None:
                    progress(done, total)
        shutil.move(tmp, dest)
        return done
    except urllib.error.HTTPError as e:
        raise HttpError(url, e.code, str(e.reason))
    except (urllib.error.URLError, OSError) as e:
        if isinstance(e, HttpError):
            raise
        raise HttpError(url, None, str(e))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class Client(object):
    """The object the DamIT tools take (tests pass a fake with the same methods)."""

    def get_bytes(self, url, timeout=60):
        return get_bytes(url, timeout)

    def head(self, url, timeout=30):
        return head(url, timeout)

    def download_file(self, url, dest, timeout=120, progress=None, cancelled=None, max_bytes=None):
        return download_file(url, dest, timeout, progress, cancelled, max_bytes)
