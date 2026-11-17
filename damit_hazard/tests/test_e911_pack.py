"""Pack-path discovery and official E911 source resolution. Synthetic folders only; no pack,
DWR or derived data is committed or written."""
import os
import tempfile

from _helpers import ROOT  # noqa: F401
from damit_hazard.engine import e911_pack as P


def _touch(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def test_configured_pack_paths_read_env_and_never_hard_code_a_box_path():
    src = open(P.__file__, encoding="utf-8").read()
    assert "/workspace/offline_packs" not in src
    assert "offline_packs_20261029_full" not in src
    d = tempfile.mkdtemp(prefix="e911_pack_")
    prev = {k: os.environ.get(k) for k in P.ENV_PACKS}
    try:
        for k in P.ENV_PACKS:
            os.environ.pop(k, None)
        os.environ["NDSUITE_DATA"] = d
        found = P.configured_pack_paths()
        assert os.path.realpath(d) in {os.path.realpath(p) for p in found}
        # a missing path is ignored
        os.environ["NDSUITE_PACK"] = os.path.join(d, "missing-pack")
        found2 = P.configured_pack_paths()
        assert not any(p.endswith("missing-pack") for p in found2)
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_resolve_prefers_the_official_gpkg_in_a_suite_pack_folder():
    d = tempfile.mkdtemp(prefix="e911_suite_")
    gpkg = os.path.join(d, "ND_Dam_Suite_Pack", "structures", "NDGISHUB_address_points.gpkg")
    _touch(gpkg, "not a real gpkg; only the path is tested")
    src = P.resolve_e911_source([d])
    assert src is not None and src["kind"] == "gpkg" and os.path.samefile(src["path"], gpkg)
    # parent of ND_Dam_Suite_Pack (NDSUITE_DATA layout) also works
    src2 = P.resolve_e911_source([os.path.dirname(os.path.join(d, "ND_Dam_Suite_Pack"))])
    assert src2["path"] == src["path"]


def test_resolve_finds_a_format1_sqlite_when_it_lists_the_dataset(tmp_path=None):
    import sqlite3
    d = tempfile.mkdtemp(prefix="e911_sqlite_")
    db = os.path.join(d, "nd_offline_pack", "nd_offline_pack.sqlite")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE datasets (name TEXT, status TEXT)")
    con.execute("INSERT INTO datasets VALUES (?, ?)", ("NDGISHUB_address_points", "complete"))
    con.commit()
    con.close()
    src = P.resolve_e911_source([d])
    assert src is not None and src["kind"] == "sqlite" and os.path.samefile(src["path"], db)


def test_resolve_prefers_gpkg_when_both_layouts_exist():
    d = tempfile.mkdtemp(prefix="e911_both_")
    gpkg = os.path.join(d, "ND_Dam_Suite_Pack", "structures", "NDGISHUB_address_points.gpkg")
    _touch(gpkg, "x")
    import sqlite3
    db = os.path.join(d, "nd_offline_pack", "nd_offline_pack.sqlite")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE datasets (name TEXT, status TEXT)")
    con.execute("INSERT INTO datasets VALUES (?, ?)", ("NDGISHUB_address_points", "complete"))
    con.commit()
    con.close()
    src = P.resolve_e911_source([d])
    assert src["kind"] == "gpkg" and os.path.samefile(src["path"], gpkg)


def test_resolve_returns_none_when_the_pack_has_no_e911_layer():
    d = tempfile.mkdtemp(prefix="e911_empty_")
    _touch(os.path.join(d, "readme.txt"), "no pack")
    assert P.resolve_e911_source([d]) is None
    assert P.resolve_e911_source([]) is None
