"""The dam inventory: the USACE National Inventory of Dams (NID), one state at a time.

DamIT Crest's dam picker and batch list are the NID only (Nick, 2026-11-09): no state dam-safety, dugout or other
inventory. The desk ships one state as an offline example (src/lib/crest/data/nid_ND.json). For any other state
(or a fresh copy of ND) the desk asks this server, GET /api/nid/state?state=XX[&refresh=1], which downloads that
state's NID bulk CSV once, converts it to the desk's bundle format (the same conversion as
scripts/build-nid-dams.mjs) and caches the result in the settings folder (<settings>/nid/nid_XX.json), never in the
repository or the install folder.

One bulk CSV per state; no per-dam NID API calls. "Owner Names" (and the other owner / designer columns) are never
read, so no owner text is cached or reaches the desk. The raw CSV is not kept on disk.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from damit_desktop.nid_rule import NID_ID_RE, is_nid_id  # noqa: F401 (DamIT Catalog's NID ID format)

#: Set by __main__.main() to <settings>/nid; tests set it directly.
NID_DIR: Path | None = None

QUERY_URL = "https://nid.sec.usace.army.mil/api/query?sy=%40stateKey%3A{state}&out=csv"
#: The NID's state and territory codes (the desk's state picker, src/lib/crest/nid-state.ts).
STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
    "PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split()
)
MAX_BYTES = 200_000_000
ATTRIBUTION = (
    "Dam inventory data: U.S. Army Corps of Engineers, National Inventory of Dams (nid.sec.usace.army.mil), "
    "downloaded {date}. Values as reported by the owning agency; verify against the dam file."
)

#: The NID columns read (exact headers). A missing one is a schema change and fails the conversion.
REQUIRED = (
    "NID ID", "Federal ID", "Dam Name", "Other Names", "County", "Latitude", "Longitude", "NID Height (Ft)",
    "Dam Height (Ft)", "Structural Height (Ft)", "Hydraulic Height (Ft)", "NID Storage (Acre-Ft)",
    "Max Storage (Acre-Ft)", "Normal Storage (Acre-Ft)", "Surface Area (Acres)", "Hazard Potential Classification",
    "Dam Length (Ft)", "Year Completed", "Drainage Area (Sq Miles)", "River or Stream Name", "City", "Primary Purpose",
    "Primary Dam Type", "Data Last Updated", "Last Inspection Date", "EAP Prepared",
)
#: (bundle column, NID header, kind). Same order as scripts/build-nid-dams.mjs COLS.
FIELDS = (
    ("nid", "NID ID", "str"), ("name", "Dam Name", "str"), ("otherNames", "Other Names", "str"),
    ("county", "County", "str"), ("countyNote", None, "none"), ("lat", "Latitude", "coord"),
    ("lon", "Longitude", "coord"), ("nidHeightFt", "NID Height (Ft)", "num"), ("damHeightFt", "Dam Height (Ft)", "num"),
    ("structuralHeightFt", "Structural Height (Ft)", "num"), ("hydraulicHeightFt", "Hydraulic Height (Ft)", "num"),
    ("nidStorageAcFt", "NID Storage (Acre-Ft)", "num"), ("maxStorageAcFt", "Max Storage (Acre-Ft)", "num"),
    ("normalStorageAcFt", "Normal Storage (Acre-Ft)", "num"), ("surfaceAreaNormalAc", "Surface Area (Acres)", "num"),
    ("lengthFt", "Dam Length (Ft)", "num"), ("yearCompleted", "Year Completed", "num"),
    ("drainageMi2", "Drainage Area (Sq Miles)", "num"), ("nidHazard", "Hazard Potential Classification", "str"),
    ("river", "River or Stream Name", "str"), ("city", "City", "str"), ("purpose", "Primary Purpose", "str"),
    ("damType", "Primary Dam Type", "str"), ("nidUpdated", "Data Last Updated", "date"),
    ("lastInspection", "Last Inspection Date", "date"), ("eap", "EAP Prepared", "str"),
)
COLS = [f[0] for f in FIELDS]


class NidError(Exception):
    """A state the NID does not have, a failed download, or a CSV that is not the NID's."""


def state_code(value) -> str:
    code = str(value or "").strip().upper()
    if code not in STATES:
        raise NidError(f"not an NID state code: {value!r}")
    return code


def _str(v):
    t = (v or "").strip()
    return t or None


def _num(v, zero_is_missing=True):
    t = (v or "").strip()
    if not t:
        return None
    try:
        n = float(t)
    except ValueError:
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    if zero_is_missing and n == 0:
        return None
    return int(n) if n.is_integer() else n


def _date(v):
    t = _str(v)
    m = t and re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", t)
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else t


def convert_csv(text: str, state: str, fetched_utc: str | None = None, url: str | None = None) -> dict:
    """The desk bundle ({v, source, cols, rows}) of one state's NID CSV. Main dams only (Federal ID == NID ID);
    associated structures are dropped and listed. Owner columns are never read."""
    state = state_code(state)
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise NidError("the NID answered an empty file") from None
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise NidError(f"NID schema changed: missing column(s) {', '.join(missing)}")
    ix = {h: i for i, h in enumerate(header)}

    def get(row, col):
        i = ix[col]
        return row[i] if i < len(row) else ""

    out, dropped, warnings, seen = [], [], [], set()
    for row in reader:
        if not row or row == [""]:
            continue
        nid = _str(get(row, "NID ID"))
        if not nid:
            continue
        fed = _str(get(row, "Federal ID"))
        if fed != nid:
            dropped.append({"federalId": fed, "nid": nid, "name": _str(get(row, "Dam Name"))})
            continue
        if not is_nid_id(nid):
            warnings.append(f"{nid}: not an NID ID, skipped")
            continue
        if nid in seen:
            raise NidError(f"duplicate main dam NID ID {nid}")
        seen.add(nid)
        rec = {}
        for col, head, kind in FIELDS:
            raw = get(row, head) if head else ""
            rec[col] = (None if kind == "none" else _str(raw) if kind == "str" else _num(raw, False) if kind == "coord"
                        else _date(raw) if kind == "date" else _num(raw))
        if rec["lat"] is None or rec["lon"] is None:
            warnings.append(f"{nid}: no point")
        out.append(rec)
    if not out:
        raise NidError(f"the NID CSV for {state} has no main dams")
    key = lambda s: (s or "").lower()  # noqa: E731
    out.sort(key=lambda r: (key(r["county"]), key(r["name"]), r["nid"]))
    counties: dict[str, int] = {}
    hazards: dict[str, int] = {}
    for r in out:
        counties[r["county"] or ""] = counties.get(r["county"] or "", 0) + 1
        hazards[r["nidHazard"] or ""] = hazards.get(r["nidHazard"] or "", 0) + 1
    fetched = fetched_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = {
        "url": url or QUERY_URL.format(state=state),
        "state": state,
        "fetchedUtc": fetched,
        "sha256Raw": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "rows": len(out),
        "dropped": dropped,
        "warnings": warnings,
        "counties": dict(sorted(counties.items())),
        "hazards": dict(sorted(hazards.items())),
        "inventoryPass": None,
        "attribution": ATTRIBUTION.format(date=fetched[:10]),
    }
    return {"v": 2, "source": source, "cols": COLS, "rows": [[r[c] for c in COLS] for r in out]}


def _download(url: str, timeout: float = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "damit-crest-desktop (NID bulk CSV)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - fixed https NID host
            data = res.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise NidError(f"the NID download failed ({exc})") from exc
    if len(data) > MAX_BYTES:
        raise NidError("the NID answered more than 200 MB for one state; not cached")
    return data.decode("utf-8-sig", errors="replace")


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(state: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(state, threading.Lock())


def cache_path(state: str, folder: Path | None = None) -> Path:
    base = folder or NID_DIR
    if base is None:
        raise NidError("no NID cache folder (the desktop app sets it at start)")
    return Path(base) / f"nid_{state_code(state)}.json"


def load_state(state: str, refresh: bool = False, fetch=_download, folder: Path | None = None) -> dict:
    """The state's bundle: from the cache, else (or with refresh) downloaded, converted and cached."""
    code = state_code(state)
    path = cache_path(code, folder)
    with _lock(code):
        if path.is_file() and not refresh:
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(bundle, dict) and bundle.get("cols") == COLS:
                    return bundle
            except (OSError, ValueError):
                pass  # a damaged cache is downloaded again
        url = QUERY_URL.format(state=code)
        bundle = convert_csv(fetch(url), code, url=url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
        tmp.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
        return bundle
