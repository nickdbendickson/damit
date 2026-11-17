"""Parity of damit:classify with DWR ndhazard:classify 2.25.6 on DWR-2659 Tewaukon.

Skipped when the local offline pack or the 2659 flood rasters are missing. Never commits DWR,
pack or derived data. HABITABLE_RULE=reviewed is used only in this test (the default rule is
unchanged).

Reference (Tewaukon 17 Nov 2026 classify, DWR Hazard 2.25.6, HABITABLE_RULE=reviewed):
  13826 99th St SE (Site_NGUID {02A3C62A-C9BA-4F2A-AD0B-70AB7127AE26}) drives ND High at
  4.30 ft and 12.76 ft/s.
"""
import json
import os
import tempfile
import unittest

from _helpers import ROOT  # noqa: F401  (puts the repo root on sys.path)

# Official 911 house that drives ND High on DWR-2659 under the reviewed rule.
REF_NGUID = "{02A3C62A-C9BA-4F2A-AD0B-70AB7127AE26}"
REF_ADDRESS = "13826 99TH ST SE"
REF_DEPTH_FT = 4.30
REF_VEL_FPS = 12.76
TOL_FT = 0.05
TOL_FPS = 0.05

# Local work folders used on this box; CI has none and the test is skipped.
# Override with DAMIT_TEST_DWR2659 (the dam folder that holds Depth (Max).tif).
_LOCAL_DAMS = (
    "/workspace/tewaukon_911rule_20261117/dam/ND00046",
    "/workspace/dam_suite_2659_localai_update_20261112/dam/ND00046",
    "/workspace/swe_damit_2659_20261112/dam/ND00046",
)


def _dam_folder():
    env = (os.environ.get("DAMIT_TEST_DWR2659") or "").strip()
    for folder in ((env,) if env else ()) + _LOCAL_DAMS:
        if folder and os.path.isfile(os.path.join(folder, "Depth (Max).tif")):
            return folder
    return ""


def _have_qgis():
    try:
        from qgis.core import QgsApplication  # noqa: F401
        return True
    except Exception:
        return False


def _have_pack():
    from damit_hazard.engine import e911_pack as P
    return P.resolve_e911_source() is not None


def _skip_reason():
    if not _have_qgis():
        return "QGIS not available"
    if not _dam_folder():
        return "DWR-2659 local flood rasters not present (set DAMIT_TEST_DWR2659)"
    if not _have_pack():
        return "configured offline pack with NDGISHUB_address_points not present"
    return ""


def _run_classify(dam, out):
    import processing
    from damit_hazard.engine import catalog as C
    presets = [None] + list(C.load()["presets"])
    # ND alias / REG_05.2026
    pid = "REG_05.2026" if "REG_05.2026" in C.load()["presets"] else "ND"
    params = {
        "PRESET": presets.index(pid) if pid in presets else presets.index("ND"),
        "PRESET_ID": pid,
        "RUN_SCENARIO": 0,
        "MODEL_DIM": 0,
        "DEPTH": os.path.join(dam, "Depth (Max).tif"),
        "VELOCITY": os.path.join(dam, "Velocity (Max).tif"),
        "METRES": False,
        "HABITABLE_RULE": 1,          # reviewed / 911 — opt-in for this parity check only
        "OUTPUT": out,
        "DAM_NAME": "Tewaukon",
    }
    # Do not pass this folder's dam.json as DAM_JSON: it has no NID ID and would fail the
    # explicit-record rule. Auto-find still sees it and leaves it out with a warning.
    roads = os.path.join(dam, "roads_clip.gpkg")
    rail = os.path.join(dam, "rail_clip.gpkg")
    if os.path.isfile(roads):
        params["ROADS"] = roads
    if os.path.isfile(rail):
        params["RAIL"] = rail
    # ADDRESS_POINTS left empty: the official layer must come from the configured pack.
    return processing.run("damit:classify", params)


def test_damit_matches_dwr_on_2659_official_911_house():
    reason = _skip_reason()
    if reason:
        raise unittest.SkipTest(reason)
    # Reuse the QGIS app bootstrap from the classify smoke tests when they have run,
    # otherwise start a throw-away offscreen profile here.
    from test_qgis_classify import _app
    _app()
    dam = _dam_folder()
    out = tempfile.mkdtemp(prefix="damit_2659_e911_")
    res = _run_classify(dam, out)
    with open(os.path.join(out, "damit_hazard_report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    assert report.get("habitable_rule") == "reviewed"
    from qgis.core import QgsVectorLayer
    gpkg = res["GPKG"]
    lyr = QgsVectorLayer(gpkg + "|layername=address_points", "e911", "ogr")
    if not lyr.isValid():
        lyr = QgsVectorLayer(gpkg + "|layername=structures", "e911", "ogr")
    assert lyr.isValid(), gpkg
    hit = None
    for f in lyr.getFeatures():
        raw_nguid = "{}".format(f["struct_key"] or "")
        names = lyr.fields().names()
        blob = " ".join(str(f[n]) for n in names if f[n] not in (None, ""))
        if REF_NGUID in raw_nguid or REF_NGUID in blob or REF_ADDRESS.replace(" ", "") in blob.replace(" ", "").upper():
            hit = f
            break
    assert hit is not None, "official 911 house {} / {} not found in {}".format(REF_ADDRESS, REF_NGUID, gpkg)
    assert int(hit["is_911"] or 0) == 1, "13826 99th St SE was loaded but not flagged as a 911 point"
    depth = float(hit["depth_ft"])
    vel = float(hit["vel_fps"] if "vel_fps" in lyr.fields().names() else hit["velocity_fps"])
    assert abs(depth - REF_DEPTH_FT) <= TOL_FT, "depth {} ft, expected {} ± {}".format(depth, REF_DEPTH_FT, TOL_FT)
    assert abs(vel - REF_VEL_FPS) <= TOL_FPS, "velocity {} ft/s, expected {} ± {}".format(vel, REF_VEL_FPS, TOL_FPS)
    label = str(res.get("CLASS") or report.get("suggested_label") or "")
    assert "high" in label.lower(), "suggested class {!r}, expected ND High".format(label)
    tally = (report.get("habitability") or {}).get("tally") or {}
    assert tally.get("by_basis", {}).get("911_address") >= 1
