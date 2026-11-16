#!/usr/bin/env python3
"""Download DamIT Data's offline layers without opening QGIS.

The same engine as the tool `damit_data:download` (Processing > DamIT Data): each source is
downloaded to a staging folder, checked, and only then put in place, so a failed update keeps
the copy that was there. A source that has not changed is not downloaded again. No QGIS is
needed: any Python 3 runs it, from the plugin's own folder.

  python3 get_data.py --list                          # the sources, and which are fetched by default
  python3 get_data.py --state ND                      # the default sources for one State
  python3 get_data.py --state ND --sources nsi,osm    # only these
  python3 get_data.py --state ND --sources all        # every source that needs no link
  python3 get_data.py --bbox=-101.2,46.8,-100.8,47.2  # NSI for a box of at most 1 square degree
  python3 get_data.py --status                        # what the data folder holds
  python3 get_data.py --state ND --dry-run            # say what would be fetched, download nothing

Files go to <data folder>/<STATE or extent_xxxxxxxx>/<source>/ with damit_data_manifest.json
beside them. The data folder is --folder, else the DamIT data_folder setting (DamIT Setup),
else ~/Documents/DamIT Data. A folder inside an ND Dam Suite offline pack is refused.

Exit code: 0 when every source asked for is in place, 1 when one or more failed (the others
are kept), 2 for a request that cannot be made.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:               # run as a script: the plugins folder
    sys.path.insert(0, os.path.dirname(HERE))

from damit_data.core import sources, store, update      # noqa: E402
from damit_core.lib import http, states                 # noqa: E402


class Lines(update.Feedback):
    """The engine's log lines, and the progress every 10 percent."""

    def __init__(self, out=print):
        self.out, self.last = out, -10

    def log(self, text):
        self.out("  " + str(text))

    def progress(self, pct):
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            return
        if pct >= self.last + 10 or pct < self.last:
            self.last = pct - pct % 10
            self.out("  %d%%" % pct)


def pick_sources(text, state, bbox, url):
    """The source ids for --sources: empty = the default ones this request can serve, all =
    every one it can serve, else the comma separated ids (unknown ones raise SourceError)."""
    def can(sid):
        scopes = sources.SOURCES[sid]["scopes"]
        return (("state" in scopes and state) or ("extent" in scopes and bbox) or ("url" in scopes and url))
    text = (text or "").strip().lower()
    if text in ("", "all"):
        return [s for s in sources.ORDER if can(s) and (text == "all" or sources.SOURCES[s]["default"]
                                                         or ("url" in sources.SOURCES[s]["scopes"] and url))]
    ids = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in ids if s not in sources.SOURCES]
    if bad:
        raise sources.SourceError("unknown source(s): %s. Known: %s" % (", ".join(bad), ", ".join(sources.ORDER)))
    return ids


def list_sources(out=print):
    for sid in sources.ORDER:
        s = sources.SOURCES[sid]
        out("%-15s %-8s %-18s %s" % (sid, "default" if s["default"] else "", " / ".join(s["scopes"]), s["name"]))


def status(root, out=print):
    man = store.read_manifest(root)
    entries = man.get("entries", {})
    out("Data folder: %s" % root)
    for key, e in sorted(entries.items()):
        out("  %-22s %d file(s), version %s, checked %s" % (
            key, len(e.get("files") or []), e.get("version") or "?", e.get("checked") or "?"))
    if not entries:
        out("  nothing downloaded yet")
    return len(entries)


def main(argv=None, client=None, out=print):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="", help="a US state: postal code, name or FIPS (ND, Nebraska, 38)")
    ap.add_argument("--bbox", default="", help="NSI only, instead of the whole state: west,south,east,north "
                                               "in degrees, at most 1 square degree (write it with =)")
    ap.add_argument("--sources", default="", help="comma separated source ids, or all (default: the default "
                                                  "sources; --list shows them)")
    ap.add_argument("--usa-structures-url", default="", help="the https link of the FEMA / ORNL USA Structures "
                                                             "zip for the state (FEMA publishes no fixed link)")
    ap.add_argument("--folder", default="", help="data folder (default: the DamIT data_folder setting, else "
                                                 "~/Documents/DamIT Data)")
    ap.add_argument("--force", action="store_true", help="download again even if unchanged")
    ap.add_argument("--max-mb", type=float, default=1500.0, help="refuse a download larger than this (default 1500)")
    ap.add_argument("--list", action="store_true", help="list the sources and stop")
    ap.add_argument("--status", action="store_true", help="say what the data folder holds and stop")
    ap.add_argument("--dry-run", action="store_true", help="say what would be fetched and stop")
    args = ap.parse_args(argv)
    if args.list:
        list_sources(out)
        return 0
    try:
        root = store.root(os.path.expanduser(args.folder) if args.folder else None)
    except store.StoreError as e:
        out("ERROR: %s" % e)
        return 2
    if args.status:
        status(root, out)
        return 0
    state = None
    if args.state:
        try:
            state = states.get(args.state)["postal"]
        except KeyError as e:
            out("ERROR: %s" % str(e).strip("'\""))
            return 2
    bbox = None
    if args.bbox:
        try:
            bbox = tuple(float(v) for v in args.bbox.split(","))
            if len(bbox) != 4:
                raise ValueError
        except ValueError:
            out("ERROR: --bbox needs west,south,east,north in degrees, e.g. --bbox=-101.2,46.8,-100.8,47.2")
            return 2
    if not state and not bbox:
        out("ERROR: give --state (e.g. --state ND) or --bbox. --list shows the sources.")
        return 2
    try:
        chosen = pick_sources(args.sources, state, bbox, args.usa_structures_url)
        if not chosen:
            raise sources.SourceError("no source can serve this request: a box alone serves NSI only")
        plans = [(sid, sources.plan(sid, state=state, bbox=bbox if sid == "nsi" else None,
                                    url=args.usa_structures_url)) for sid in chosen]
    except sources.SourceError as e:
        out("ERROR: %s" % e)
        return 2
    out("Data folder: %s" % root)
    if args.dry_run:
        for sid, p in plans:
            out("  %-15s %d request(s) -> %s" % (sid, len(p["urls"]), store.target_dir(root, p)))
        return 0
    client = client or http.Client()
    done, failed = [], []
    for n, (sid, p) in enumerate(plans, 1):
        out("[%d/%d] %s" % (n, len(plans), p["name"]))
        try:
            r = update.update(p, client, root, force=args.force, feedback=Lines(out), max_mb=args.max_mb)
        except KeyboardInterrupt:
            out("Stopped. The sources that finished are kept; run the same command to go on.")
            return 130
        except Exception as e:                           # noqa: BLE001 - one source never stops the others
            known = isinstance(e, (sources.SourceError, update.UpdateError, store.StoreError, OSError))
            out("  FAILED: %s" % (e if known else "%s: %s" % (type(e).__name__, e)))
            failed.append(sid)
            continue
        out("  " + r["message"])
        done.append((sid, r["status"]))
    out("%d of %d source(s) in place%s. Manifest: %s" % (
        len(done), len(plans), (" (failed: %s)" % ", ".join(failed)) if failed else "",
        os.path.join(root, store.MANIFEST)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
