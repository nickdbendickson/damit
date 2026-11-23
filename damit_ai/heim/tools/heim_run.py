#!/usr/bin/env python3
# heim_run.py v1.0.0 — `heim run "plain English"`: Heim drafts a damchain run, you check it, you type y.
#
#   heim run "run 2801 and 4031 at 5 m with FV2"
#   heim run --set damit --dams ~/Dams/dams.gpkg --out ~/Dams/runs --dem ~/DEM/nd.vrt "run 2801 at 10 m"
#   heim run --show "rerun 2801 with n 0.04"          show the command only, never run
#
# The local model only FILLS IN FIXED FIELDS (dam ids, cell size, solver, Manning's n, redo). It never
# writes the command. This code builds the command and refuses, rather than guesses, when:
#   - a dam id is not in your words, or not in the dams layer;
#   - a number (cell, n) is not in your words, is out of range, or the cell is given in feet;
#   - the solver word is not in your words;
#   - you asked for something these fields cannot hold (it says what, and how to type it yourself);
#   - redo (run again over finished dams) is set but your own words did not ask for it.
# It then shows the exact damchain command and what differs from the defaults, runs nothing until you
# type y, runs damchain's checks (--check-only) first, and writes your sentence, the model's reply and
# the command to <out>/_chain_logs/heim_run_<time>.txt. Typing the damchain command yourself is still
# the main way to run; this is a drafting aid. Paths (dams layer, output folder, DEM) come from the
# flags, or from the last ones you used for that set (~/local-ai/heim_run.json).
#
# Rules agreed 2026-11-23 (a plain-text reading must never reach a run unchecked): see above.
import argparse
import datetime
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
SAVED = os.path.expanduser(os.environ.get("HEIM_RUN_SETTINGS", "~/local-ai/heim_run.json"))
SETS = ("damit", "dwr")
SET_WORDS = {"damit": r"\bdamit\b", "dwr": r"\b(?:dwr|damsafety|dam\s*safety)\b"}
SOLVERS = ("acc", "fv2", "mwdg2")
CELL_RANGE = (0.5, 200.0)          # metres
MANNING_RANGE = (0.01, 0.25)
REDO_WORDS = re.compile(r"\b(?:redo|re-?run|rerun|again|overwrite|replace|from scratch)\b", re.I)
DEFAULTS = {"damit": {"cell_m": 10.0, "solver": "ACC", "manning": 0.05},
            "dwr": {"cell_m": None, "solver": None, "manning": None}}     # None: the Runner's own setting

SCHEMA = {
    "type": "object",
    "properties": {
        "ids": {"type": "array", "items": {"type": "string"}},
        "cell_m": {"type": ["number", "null"]},
        "solver": {"type": "string", "enum": ["", "acc", "fv2", "mwdg2"]},
        "manning": {"type": ["number", "null"]},
        "redo": {"type": "boolean"},
        "unsupported": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ids", "cell_m", "solver", "manning", "redo", "unsupported"],
}

PROMPT = """You turn one request for dam breach model runs into JSON. Fill ONLY these fields:
- ids: the dam ids exactly as written in the request (e.g. "2801", "DWR-2801", "ND00123"). Never invent one.
- cell_m: the model cell size in metres if the request gives one, else null.
- solver: "acc", "fv2" or "mwdg2" if the request names one, else "".
- manning: Manning's n if the request gives one (e.g. 0.04), else null.
- redo: true only if the request asks to run again / redo / overwrite earlier runs.
- unsupported: every other thing the request asks for that these fields cannot hold (a breach method, a
  pool, a scenario, a duration, ANUGA, HEC-RAS, a different DEM, classification, "all dams", ...), each as
  a few words. Empty list if nothing else was asked.
Return JSON only."""


def _say(msg=""):
    print(msg, flush=True)


def _rr():
    """run_results.py beside this file: its Ollama call (and Ollama auto-start) are reused."""
    spec = importlib.util.spec_from_file_location("heim_run_rr", os.path.join(HERE, "run_results.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def model_fields(request, chat=None):
    """The model's reading of the request, as a dict (or raises ValueError)."""
    if chat is None:
        chat = _rr().ollama_chat
    reply = chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": request}], fmt=SCHEMA)
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S | re.I).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("the model gave no JSON: %r" % (text[:200],))
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("the model's JSON is not an object")
    return data, reply


def _numbers_in(text):
    """Every number written in the text ('5m', '0.04.', 'n=0.035' all count)."""
    return [float(x) for x in re.findall(r"(?<!\d)(?<!\d\.)(\d+(?:\.\d+)?|\.\d+)(?!\d|\.\d)", text)]


def _in_words(value, text):
    return any(abs(v - float(value)) < 1e-9 for v in _numbers_in(text))


def check_fields(request, data):
    """Code's check of the model's fields against the request. Returns (fields, refusals, notes)."""
    bad, notes = [], []
    words = request
    ids = []
    for raw in data.get("ids") or []:
        i = str(raw).strip()
        if not i:
            continue
        if not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(i), words, re.I):
            bad.append("dam id %r is not in your words" % i)
        elif i not in ids:
            ids.append(i)
    if not ids and not bad:
        bad.append("no dam id: name the dams (e.g. \"run 2801 and 4031\"); a question about runs ends "
                   "with ? (heim run times for ANUGA?)")
    f = {"ids": ids, "cell_m": None, "solver": "", "manning": None, "redo": False}
    cell = data.get("cell_m")
    if cell is not None:
        try:
            cell = float(cell)
        except (TypeError, ValueError):
            cell = None
            bad.append("the cell size is not a number")
    if cell is not None:
        if not _in_words(cell, words):
            bad.append("cell size %g is not in your words" % cell)
        elif re.search(r"(?<![\w.])%s\s*(?:ft|feet|foot|')" % re.escape(_g(cell)), words, re.I):
            bad.append("the cell size is in metres; say it in metres (e.g. \"at 5 m\")")
        elif not CELL_RANGE[0] <= cell <= CELL_RANGE[1]:
            bad.append("cell size %g m is outside %g-%g m" % ((cell,) + CELL_RANGE))
        else:
            f["cell_m"] = cell
    n = data.get("manning")
    if n is not None:
        try:
            n = float(n)
        except (TypeError, ValueError):
            n = None
            bad.append("Manning's n is not a number")
    if n is not None:
        if not _in_words(n, words):
            bad.append("Manning's n %g is not in your words" % n)
        elif not MANNING_RANGE[0] <= n <= MANNING_RANGE[1]:
            bad.append("Manning's n %g is outside %g-%g" % ((n,) + MANNING_RANGE))
        else:
            f["manning"] = n
    solver = str(data.get("solver") or "").strip().lower()
    if solver:
        if solver not in SOLVERS:
            bad.append("solver %r is not one of %s" % (solver, ", ".join(SOLVERS)))
        elif not re.search(r"\b%s\b" % solver, words, re.I):
            bad.append("solver %s is not in your words" % solver.upper())
        else:
            f["solver"] = solver
    if data.get("redo"):
        if REDO_WORDS.search(words):
            f["redo"] = True
        else:
            notes.append("left out redo: your words did not ask to run finished dams again")
    for u in data.get("unsupported") or []:
        u = str(u).strip()
        if u:
            bad.append("heim run cannot set %r; type the damchain command yourself (damchain run --help)" % u)
    return f, bad, notes


def _g(x):
    return ("%.6f" % x).rstrip("0").rstrip(".")


def load_saved():
    try:
        with open(SAVED, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_saved(d):
    os.makedirs(os.path.dirname(SAVED), exist_ok=True)
    tmp = SAVED + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
    os.replace(tmp, SAVED)


def pick_set(args, request, saved):
    if args.set:
        return args.set, None
    named = [s for s in SETS if re.search(SET_WORDS[s], request, re.I)]
    if len(named) == 1:
        return named[0], None
    if len(named) > 1:
        return None, "your words name more than one plugin set; give --set damit or --set dwr"
    last = saved.get("_last_set")
    if last in SETS:
        return last, None
    return None, "which plugin set? give --set damit or --set dwr (it is remembered after that)"


def paths_for(args, set_name, saved):
    """dams / out / dem / id_field / dem_units: the flags, else the last ones used for this set."""
    have = dict(saved.get(set_name) or {})
    for k in ("dams", "out", "dem", "id_field", "dem_units"):
        v = getattr(args, k, "") or ""
        if v:
            have[k] = v
    return have


def check_paths(set_name, p, ids, layer_ids):
    bad = []
    for k, what in (("dams", "dams layer (--dams)"), ("out", "output folder (--out)"), ("dem", "DEM (--dem)")):
        if not p.get(k):
            bad.append("no %s yet for --set %s: give it once and it is remembered" % (what, set_name))
    if bad:
        return bad
    dams = os.path.expanduser(p["dams"].partition("|")[0])
    if not os.path.exists(dams):
        bad.append("the dams layer is not there: %s" % dams)
    if not os.path.exists(os.path.expanduser(p["dem"])):
        bad.append("the DEM is not there: %s" % os.path.expanduser(p["dem"]))
    parent = os.path.dirname(os.path.abspath(os.path.expanduser(p["out"])))
    if not os.path.isdir(parent):
        bad.append("the folder above the output folder does not exist: %s" % parent)
    if not bad:
        col, have = layer_ids(p["dams"], p.get("id_field", ""))
        if have is None:
            bad.append("cannot read the dam ids in %s here (a .gpkg or .csv can be read; or give "
                       "--id-field); type the damchain command yourself for this layer" % p["dams"])
        else:
            missing = [i for i in ids if i not in have]
            if missing:
                bad.append("not in the dams layer (field %s): %s" % (col, ", ".join(missing)))
    return bad


def build_argv(set_name, p, f):
    """The damchain argv (after `damchain`). Built here, never by the model."""
    a = ["run", "--set", set_name, "--dams", p["dams"], "--out", p["out"], "--dem", p["dem"],
         "--ids", ",".join(f["ids"])]
    if p.get("id_field"):
        a += ["--id-field", p["id_field"]]
    if p.get("dem_units"):
        a += ["--dem-units", p["dem_units"]]
    if f["cell_m"] is not None:
        a += ["--cell", _g(f["cell_m"])]
    if f["solver"]:
        a += ["--solver", f["solver"]]
    if f["manning"] is not None:
        a += ["--manning", _g(f["manning"])]
    if f["redo"]:
        a += ["--redo"]
    return a


def changes(set_name, f):
    """Each setting the words asked for, next to what the Runner would use without it."""
    d = DEFAULTS[set_name]

    def note(value, default, unit=""):
        if default is None:
            return "instead of the Runner's own setting"
        if isinstance(default, str) and str(value).upper() == default or value == default:
            return "the same as the default"
        return "default %s%s" % (_g(default) if not isinstance(default, str) else default, unit)
    out = []
    if f["cell_m"] is not None:
        out.append("cell size %s m (%s)" % (_g(f["cell_m"]), note(f["cell_m"], d["cell_m"], " m")))
    if f["solver"]:
        out.append("solver %s (%s)" % (f["solver"].upper(), note(f["solver"], d["solver"])))
    if f["manning"] is not None:
        out.append("Manning's n %s (%s)" % (_g(f["manning"]), note(f["manning"], d["manning"])))
    if f["redo"]:
        out.append("REDO: dams that finished before are run again and their results replaced")
    return out


def _quote(a):
    return " ".join(shlex.quote(x) for x in a)


def _log(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None, chat=None, ask=input, runner=None, out=_say):
    ap = argparse.ArgumentParser(prog="heim run", description=(
        "Heim drafts a damchain run from plain English. It only fills in dam ids, cell size, solver, "
        "Manning's n and redo; this code checks each one against your words and your dams layer, shows "
        "the command, and runs nothing until you type y."))
    ap.add_argument("request", nargs="*", help="what to run, e.g. \"run 2801 and 4031 at 5 m with FV2\"")
    ap.add_argument("--set", choices=SETS, default="", help="plugin set (remembered)")
    ap.add_argument("--dams", default="", help="dams points layer (remembered per set)")
    ap.add_argument("--out", default="", help="output folder, one folder per dam (remembered per set)")
    ap.add_argument("--dem", default="", help="DEM or VRT covering the dams (remembered per set)")
    ap.add_argument("--id-field", default="", help="dam id field of the layer (remembered per set)")
    ap.add_argument("--dem-units", choices=("detect", "feet", "us-feet", "meters"), default="",
                    help="the DEM's elevation units (remembered per set)")
    ap.add_argument("--show", action="store_true", help="show the command only; never run")
    ap.add_argument("--version", action="version", version="heim run " + VERSION)
    args = ap.parse_args(argv)
    request = " ".join(args.request).strip()
    if not request:
        ap.print_help()
        return 2
    saved = load_saved()
    set_name, why = pick_set(args, request, saved)
    if not set_name:
        out("Not run: " + why)
        return 2
    p = paths_for(args, set_name, saved)
    dc = _dam_chain()
    try:
        data, reply = model_fields(request, chat=chat)
    except Exception as e:            # noqa: BLE001 - no model, bad JSON: say so and stop
        out("Not run: Heim could not read the request (%s). Type the damchain command yourself." % e)
        return 2
    f, bad, notes = check_fields(request, data)
    if not bad:
        bad = check_paths(set_name, p, f["ids"], dc.layer_ids)
    for n in notes:
        out("  note: " + n)
    if bad:
        out("Not run:")
        for b in bad:
            out("  - " + b)
        return 2
    cmd = build_argv(set_name, p, f)
    shown = "damchain " + _quote(cmd)
    out("Heim read: " + request)
    out("Command:   " + shown)
    ch = changes(set_name, f)
    out("Settings: " + ("; ".join(ch) if ch else "none asked for (the Runner's own settings)"))
    out("Dams: %s   from %s" % (", ".join(f["ids"]), p["dams"]))
    out("Output: %s   DEM: %s" % (p["out"], p["dem"]))
    if args.show:
        out("(--show: nothing was run)")
        return 0
    try:
        answer = ask("Run it? Type y to run, anything else stops: ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        out("Stopped; nothing was run.")
        return 1
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logp = os.path.join(os.path.abspath(os.path.expanduser(p["out"])), "_chain_logs", "heim_run_%s.txt" % stamp)
    _log(logp, ["heim run %s  %s" % (VERSION, stamp), "request: " + request, "model reply: " + (reply or "").strip(),
                "fields: " + json.dumps(f, sort_keys=True), "command: " + shown, "confirmed: y"])
    saved[set_name] = {k: v for k, v in p.items() if v}
    saved["_last_set"] = set_name
    save_saved(saved)
    if runner is None:
        def runner(a):
            return subprocess.call([sys.executable, os.path.join(HERE, "dam_chain.py")] + a)   # nosec B603
    out("Checks first (damchain ... --check-only):")
    rc = runner(cmd + ["--check-only"])
    _log(logp, ["check-only exit: %s" % rc])
    if rc != 0:
        out("The checks failed; nothing was run. Log: " + logp)
        return rc
    rc = runner(cmd)
    _log(logp, ["run exit: %s" % rc])
    out("heim run log: " + logp)
    return rc


def _dam_chain():
    spec = importlib.util.spec_from_file_location("heim_run_dc", os.path.join(HERE, "dam_chain.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    sys.exit(main())
