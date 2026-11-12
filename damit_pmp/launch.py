"""The only module in damit_pmp that starts a process, and only on an explicit request.

Two optional jobs, both in the ANUGA Python the user names (damit_pmp never guesses an interpreter):
  * run_mesher: the runner's gmsh_mesher.py on the mesh spec, as anuga_model.make_gmsh_mesh does
    (clean environment, wall-clock timeout, SIGTERM then SIGKILL via the runner's wallclock.run);
  * run_script: the generated run_anuga_rain.py. damit_pmp:anugarain never calls it unless RUN_ANUGA
    is switched on (default off); the dry check (`run_anuga_rain.py --dry`) is the way to test a job.
No shell is used; the command is always an argument list. tests/test_metadata_suite.py allows
process launching in this one file and nowhere else in damit_pmp.
"""
import json
import os
import subprocess

from . import anugarain as AR
from .runner_shared import wallclock

MESHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner_shared", "gmsh_mesher.py")


def clean_env(environ=None):
    """The runner's anuga_model._clean_env: the ANUGA Python must not see QGIS's Python variables."""
    env = dict(os.environ if environ is None else environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "QGIS_PREFIX_PATH", "PYTHONNOUSERSITE"):
        env.pop(k, None)
    return env


def check_python(python):
    """The interpreter path as a usable executable path, else JobError."""
    p = os.path.realpath(os.path.expanduser(str(python or "")))
    if not python or not os.path.isfile(p) or not os.access(p, os.X_OK):
        raise AR.JobError("ANUGA Python {!r} is not an executable file".format(python))
    return p


def probe(python, timeout_s=120):
    """{'python', 'anuga', 'gmsh', 'numpy', 'messages'}: versions seen by the ANUGA interpreter."""
    py = check_python(python)
    code = ("import sys, json\nr = {'python': sys.version.split()[0]}\n"
            "for n in ('numpy', 'anuga', 'gmsh'):\n"
            "    try:\n        m = __import__(n); r[n] = getattr(m, '__version__', '?')\n"
            "    except Exception as e:\n        r[n] = None; r.setdefault('messages', []).append(n + ': ' + str(e)[:160])\n"
            "print(json.dumps(r))\n")
    try:
        out = subprocess.run([py, "-c", code], capture_output=True, text=True, env=clean_env(),
                             timeout=timeout_s, errors="replace")
    except Exception as e:           # noqa: BLE001 - reported, never fatal
        return {"python": None, "messages": ["probe failed: {}".format(e)]}
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"python": None, "messages": [(out.stdout + out.stderr).strip()[-200:] or "no output"]}


def run_mesher(python, spec_path, out_npz, timeout_s=600.0, mesher=MESHER, log=None):
    """Run gmsh_mesher.py. Returns (mesh_stats dict | None, note). The runner's own wording:
    a quality-gate failure comes back as 'MESHERROR ...' (note), a timeout as 'gmsh took over N s'."""
    py = check_python(python)
    if os.path.exists(out_npz):
        os.remove(out_npz)
    try:
        out = wallclock.run([py, mesher, spec_path, out_npz], env=clean_env(), timeout=float(timeout_s),
                            grace=5.0, what="gmsh", log=log)
    except wallclock.Timeout:
        return None, "gmsh took over {:.0f} s (timeout)".format(timeout_s)
    except OSError as e:
        return None, "could not start gmsh: {}".format(e)
    msg = (out.stdout or "").strip().splitlines() + (out.stderr or "").strip().splitlines()
    if out.returncode != 0 or not os.path.exists(out_npz):
        why = next((m[len("MESHERROR "):] for m in msg if m.startswith("MESHERROR ")),
                   msg[-1][:200] if msg else "code {}".format(out.returncode))
        hint = (" (Linux: install libglu1-mesa libxcursor1 libxinerama1 libxft2)"
                if "libGLU" in why or ".so" in why else "")
        return None, "gmsh mesh failed: {}{}".format(why, hint)
    line = next((m for m in msg if m.startswith("MESHOK ")), None)
    stats = json.loads(line[len("MESHOK "):]) if line else AR.mesh_arrays(out_npz)[3]
    return stats, "ok"


def run_script(python, script, args=(), timeout_s=None, log=None):
    """Run a generated script (cwd = its folder). Returns the CompletedProcess (text output)."""
    py = check_python(python)
    return wallclock.run([py, script] + [str(a) for a in args], cwd=os.path.dirname(os.path.abspath(script)),
                         env=clean_env(), timeout=timeout_s, grace=15.0, what="anuga", log=log)
