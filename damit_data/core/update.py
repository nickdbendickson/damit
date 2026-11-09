"""Download / refresh one source into the local store.

Each update is staged in a hidden folder beside the target, verified (zip integrity, GeoJSON
FeatureCollection), then swapped in, so an interrupted update never leaves partial files and the
old copy stays usable. A source whose remote version (ETag / Last-Modified / size, or the content
SHA-256 for the NSI API) is unchanged is not replaced. Sizes over ``max_mb`` are refused before
downloading when the server reports a length.
"""
import datetime
import hashlib
import json
import os
import shutil
import zipfile

from . import store

NSI_INTERVAL_DAYS = 30


class UpdateError(RuntimeError):
    pass


class Feedback(object):
    """Minimal feedback (Processing passes a QgsProcessingFeedback adapter)."""

    def log(self, text):
        print(text)

    def progress(self, pct):
        pass

    def cancelled(self):
        return False


def update(plan, http, root_dir, force=False, feedback=None, max_mb=1500, nsi_interval_days=NSI_INTERVAL_DAYS):
    """Returns {'status': 'updated'|'unchanged'|'skipped', 'entry': manifest entry, 'message': ...}."""
    fb = feedback or Feedback()
    store.check_writable_target(root_dir)
    man = store.read_manifest(root_dir)
    key = store.entry_key(plan)
    old = man.get("entries", {}).get(key)
    target = store.target_dir(root_dir, plan)
    if plan["kind"] == "nsi_api":
        if old and not force and os.path.isdir(target) and _age_days(old.get("checked")) < nsi_interval_days:
            return {"status": "skipped", "entry": old,
                    "message": "{}: checked {} (less than {} days ago); use force to re-check.".format(
                        plan["name"], old.get("checked"), nsi_interval_days)}
        staging, files, version = _fetch_nsi(plan, http, target, fb)
    else:
        url = plan["urls"][0]
        try:
            h = http.head(url)
        except Exception as e:                                   # noqa: BLE001
            raise UpdateError("{}: cannot reach {} ({})".format(plan["name"], url, e))
        version = _header_version(h)
        size = int(h.get("content-length") or 0)
        if old and not force and os.path.isdir(target) and version and old.get("version") == version:
            old["checked"] = store.now()
            man["entries"][key] = old
            store.write_manifest(root_dir, man)
            return {"status": "unchanged", "entry": old, "message": "{}: unchanged ({}).".format(plan["name"], version)}
        if size and max_mb and size > max_mb * 1e6:
            raise UpdateError("{}: {:.0f} MB is over the {:g} MB limit; raise the limit to download it.".format(
                plan["name"], size / 1e6, max_mb))
        staging, files = _fetch_file(plan, http, target, fb, max_mb)
    entry = {"id": plan["id"], "name": plan["name"], "area": plan["area"], "urls": plan["urls"][:3],
             "url_count": len(plan["urls"]), "version": version, "checked": store.now(), "updated": store.now(),
             "files": [os.path.relpath(os.path.join(target, f), root_dir) for f in files],
             "layer_globs": plan["layer_globs"], "citation": plan["citation"]}
    if plan["kind"] == "nsi_api" and old and old.get("version") == version and os.path.isdir(target) and not force:
        shutil.rmtree(staging, ignore_errors=True)
        entry["updated"] = old.get("updated")
        status = "unchanged"
    else:
        _swap(staging, target)
        status = "updated"
    man.setdefault("entries", {})[key] = entry
    store.write_manifest(root_dir, man)
    return {"status": status, "entry": entry, "message": "{}: {} ({} file(s)).".format(plan["name"], status, len(files))}


def _age_days(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return 1e9
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 86400.0


def _header_version(h):
    parts = [h.get("etag") or "", h.get("last-modified") or "", h.get("content-length") or ""]
    return "|".join(parts) if any(parts) else ""


def _staging(target):
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    st = os.path.join(parent, ".staging_" + os.path.basename(target))
    shutil.rmtree(st, ignore_errors=True)
    os.makedirs(st)
    return st


def _swap(staging, target):
    old = target + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(target):
        os.replace(target, old)
    os.replace(staging, target)
    shutil.rmtree(old, ignore_errors=True)


def _fetch_file(plan, http, target, fb, max_mb):
    staging = _staging(target)
    dest = os.path.join(staging, plan["filename"])
    try:
        http.download_file(plan["urls"][0], dest, progress=lambda d, t: fb.progress(100.0 * d / t if t else 0),
                           cancelled=fb.cancelled, max_bytes=int(max_mb * 1e6) if max_mb else None)
        if plan.get("extract"):
            try:
                with zipfile.ZipFile(dest) as z:
                    bad = z.testzip()
                    if bad:
                        raise UpdateError("{}: damaged zip member {}".format(plan["name"], bad))
                    for n in z.namelist():
                        if n.startswith("/") or ".." in n.split("/"):
                            raise UpdateError("{}: unsafe path in zip: {}".format(plan["name"], n))
                    z.extractall(staging)
            except zipfile.BadZipFile as e:
                raise UpdateError("{}: not a zip file ({})".format(plan["name"], e))
            os.remove(dest)
        files = _list(staging)
        if not files:
            raise UpdateError("{}: the download held no files.".format(plan["name"]))
        return staging, files
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _fetch_nsi(plan, http, target, fb):
    staging = _staging(target)
    try:
        feats = []
        h = hashlib.sha256()
        n = len(plan["urls"])
        for i, url in enumerate(plan["urls"]):
            if fb.cancelled():
                raise UpdateError("cancelled")
            raw = http.get_bytes(url, timeout=300)
            try:
                d = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise UpdateError("NSI: {} returned invalid JSON ({})".format(url, e))
            if not isinstance(d, dict) or d.get("type") != "FeatureCollection":
                raise UpdateError("NSI: {} did not return a FeatureCollection".format(url))
            part = d.get("features") or []
            feats.extend(part)
            h.update(raw)
            fb.progress(100.0 * (i + 1) / n)
            fb.log("NSI: {} of {}: {} structures".format(i + 1, n, len(part)))
        with open(os.path.join(staging, "nsi.geojson"), "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": feats}, fh)
        with open(os.path.join(staging, "nsi_source.json"), "w", encoding="utf-8") as fh:
            json.dump({"requests": len(plan["urls"]), "structures": len(feats), "sha256": h.hexdigest(),
                       "fetched": store.now(), "citation": plan["citation"]}, fh, indent=1)
        return staging, _list(staging), "sha256:" + h.hexdigest()
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _list(folder):
    out = []
    for base, dirs, files in os.walk(folder):
        for d in list(dirs):
            if d.lower().endswith(".gdb"):
                out.append(os.path.relpath(os.path.join(base, d), folder) + "/")
                dirs.remove(d)
        for f in files:
            out.append(os.path.relpath(os.path.join(base, f), folder))
    return sorted(out)
