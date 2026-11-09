import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from damit_hazard.engine import catalog as C, core, receptors as R, report, tm11  # noqa: E402

CAT = C.load()
CHARTS = tm11.load()


def run(cfg, recs, scenario="S1", dim="2D", dam=None, extra_runs=()):
    runs = [{"scenario": scenario, "model_dim": dim, "receptors": recs, "label": "test"}]
    runs += list(extra_runs)
    return core.classify(CAT, cfg, runs, dam=dam, charts=CHARTS)


def preset(pid, **kw):
    return C.preset_config(CAT, pid, **kw)


def custom(methods, **kw):
    return C.custom_config(CAT, methods, **kw)


def home(rid="h1", depth=1.0, vel=1.0, **kw):
    return R.make(rid, "structure", kw.pop("type", "home"), depth_ft=depth, velocity_fps=vel,
                  **kw)


def road(rid, cls=None, depth=0.5, **kw):
    return R.make(rid, "road", cls, depth_ft=depth, velocity_fps=kw.pop("vel", 1.0), **kw)


def rail(rid, depth=0.5, **kw):
    return R.make(rid, "rail", None, depth_ft=depth, velocity_fps=1.0, **kw)


def codes(res, level=None):
    return set(f["code"] for f in res["flags"] if level is None or f["level"] == level)


def methods_hit(res, cls=None, strength=None):
    return set(h["method"] for h in res["hits"] if (cls is None or h["class"] == cls)
               and (strength is None or h["strength"] == strength))
