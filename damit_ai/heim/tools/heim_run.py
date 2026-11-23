#!/usr/bin/env python3
# heim_run.py v1.0.0 — `heim run "plain English"`: Heim drafts a damchain run, you check it, you type y.
#
#   heim run "run 2801 and 4031 at 5 m with FV2"
#   heim run --set damit --dams ~/Dams/dams.gpkg --out ~/Dams/runs --dem ~/DEM/nd.vrt "run 2801 at 10 m"
#   heim run --show "rerun 2801 with n 0.04"          show the command only, never run
#
# The local model only FILLS IN FIXED FIELDS (dam ids, cell size, solver, Manning's n, redo). It never
# writes the command. This code builds the command and refuses, rather than guesses, when:
#   - a dam id is not in your words as a word of its own, or not in the dams layer;
#   - a cell size is not in your words next to m / "at" / "cell", is out of range, or is in feet, cm...;
#   - Manning's n is not in your words next to "n" / "Manning", or is out of range;
#   - your words hold a number that no field accounts for ("the 2 m DEM", a second cell size);
#   - the solver word is not in your words, or your words say "not" that solver;
#   - you asked for something these fields cannot hold (ANUGA, a pool, a scenario, a DEM, all dams...),
#     whether or not the model listed it (it says what, and how to type it yourself);
#   - redo (run again over finished dams) is set but your own words did not ask for it ("do not
#     overwrite" is not asking): redo is then left out, with a note.
# It then shows the exact damchain command and what differs from the defaults, runs nothing until you
# type y, runs damchain's checks (--check-only) first, and writes your sentence, the model's reply and
# the command to <out>/_chain_logs/heim_run_<time>.txt. Every reading, refused, stopped or run, also
# goes to ~/local-ai/reports/heim_run_drafts.log. Typing the damchain command yourself is still
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
# a set named on its own ('DWR-2801' is a dam id, not the DamSafety set)
SET_WORDS = {"damit": r"(?<![\w-])damit(?![\w-])", "dwr": r"(?<![\w-])(?:dwr|damsafety)(?![\w-])"}
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


# A number standing on its own: not inside an id (ND00123, DWR-50), not part of a longer decimal.
_NUM = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?|\.\d+)(?![\d]|\.\d)")
_METRE = re.compile(r"\s*-?\s*(?:m|metres?|meters?)(?![a-z])", re.I)
_OTHER_UNIT = re.compile(r"\s*-?\s*(ft|feet|foot|cm|mm|km|yd|yards?|inch(?:es)?|mi|miles?|us\s*ft)(?![a-z])|"
                         r"\s*(['’′″\"])", re.I)
_CELL_BEFORE = re.compile(r"(?:\bat|\bcells?(?:\s+size)?|\bgrid(?:\s+size)?|\bresolution|\bres)\s*(?:of|=|:|to|is)?\s*$",
                          re.I)
_N_BEFORE = re.compile(r"(?:\bn|\bmanning'?s?(?:\s+n)?|\broughness)\s*(?:of|=|:|to|is)?\s*$", re.I)
_NEG = r"\b(?:not|no|never|don'?t|do\s+not|without|avoid|skip)\b\W+(?:\w+\W+){0,3}?"
# Things a sentence may ask for that heim run cannot set. Refused even when the model leaves them out.
_CANNOT = re.compile(r"\b(anuga|lisflood|hec-?ras|gpu|sgc|boann|builtin|built-in|scenario|pmf|sunny|"
                     r"froehlich|macdonald|von\s+thun|pool|inflow|hours?|duration|classif\w*|hazard|"
                     r"workers?|threads?|dem|lidar|terrain|vrt|every\s+dam|all\s+(?:the\s+)?dams|tier|mesh)\b",
                     re.I)


def read_numbers(text):
    """Each number written on its own in the text, with what it is next to:
    {"value", "text", "role": "cell" | "n" | "plain", "unit": "m" | other unit | ""}."""
    out = []
    for m in _NUM.finditer(text):
        after = text[m.end():]
        if after[:1].isalpha() and not (_METRE.match(after) or _OTHER_UNIT.match(after)):
            continue                                    # '2801a': part of a word, not a number
        before = text[max(0, m.start() - 30):m.start()]
        unit = ""
        if _METRE.match(after):
            unit = "m"
        else:
            u = _OTHER_UNIT.match(after)
            if u and (u.group(1) or _CELL_BEFORE.search(before)):   # a quote is feet only for a cell size
                unit = (u.group(1) or u.group(2)).lower()
        if _N_BEFORE.search(before):
            role = "n"
        elif unit or _CELL_BEFORE.search(before):
            role = "cell"
        else:
            role = "plain"
        out.append({"value": float(m.group(1)), "text": m.group(1), "role": role, "unit": unit})
    return out


def _same(a, b):
    return abs(float(a) - float(b)) < 1e-9


def _negated(word_re, text):
    return bool(re.search(_NEG + r"(?:%s)" % word_re, text, re.I))


def check_fields(request, data):
    """Code's check of the model's fields against the request. Returns (fields, refusals, notes).
    Every value must stand in the words in its own place: a dam id as a word of its own (a number
    followed by m or ft is a cell size, one after n is Manning's n), a cell size next to m / 'at' /
    'cell', n next to 'n' / 'Manning'. A number in the words that no field accounts for, or a thing
    heim run cannot set, stops the run: it is refused, not guessed."""
    bad, notes = [], []
    words = request
    nums = read_numbers(words)
    used = set()
    ids = []
    for raw in data.get("ids") or []:
        i = str(raw).strip()
        if not i:
            continue
        hit = None
        if re.fullmatch(r"\d+(?:\.\d+)?", i):
            hit = next((k for k, n in enumerate(nums) if n["role"] == "plain" and n["text"] == i), None)
        elif re.search(r"(?<![\w.\-])%s(?![\w\-]|\.\d)" % re.escape(i), words, re.I):
            hit = -1
        if hit is None:
            bad.append("dam id %r is not in your words as a dam id" % i)
            continue
        if hit >= 0:
            used.add(hit)
        if i not in ids:
            ids.append(i)
    if not ids and not bad:
        bad.append("no dam id: name the dams (e.g. \"run 2801 and 4031\"); a question about runs ends "
                   "with ? (heim run times for ANUGA?)")
    f = {"ids": ids, "cell_m": None, "solver": "", "manning": None, "redo": False}

    def number(key, what):
        v = data.get(key)
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            bad.append("%s is not a number" % what)
            return None
    cell = number("cell_m", "the cell size")
    if cell is not None:
        at = [k for k, n in enumerate(nums) if n["role"] == "cell" and _same(n["value"], cell)]
        metric = [k for k in at if nums[k]["unit"] in ("m", "")]
        if not at:
            bad.append("cell size %s is not in your words as a cell size (write it as \"at 5 m\")" % _g(cell))
        elif not metric:
            bad.append("the cell size is given in %s; heim run takes metres (e.g. \"at 5 m\")"
                       % nums[at[0]]["unit"])
        elif not CELL_RANGE[0] <= cell <= CELL_RANGE[1]:
            bad.append("cell size %s m is outside %g-%g m" % ((_g(cell),) + CELL_RANGE))
        else:
            f["cell_m"] = cell
            used.update(metric)
    n = number("manning", "Manning's n")
    if n is not None:
        at = [k for k, x in enumerate(nums) if x["role"] == "n" and _same(x["value"], n)]
        if not at:
            bad.append("Manning's n %s is not in your words as Manning's n (write it as \"n 0.04\")" % _g(n))
        elif not MANNING_RANGE[0] <= n <= MANNING_RANGE[1]:
            bad.append("Manning's n %s is outside %g-%g" % ((_g(n),) + MANNING_RANGE))
        else:
            f["manning"] = n
            used.update(at)
    left = [nums[k]["text"] + (" " + nums[k]["unit"] if nums[k]["unit"] else "")
            for k in range(len(nums)) if k not in used]
    if left and not bad:
        bad.append("your words have %s, which heim run did not use; it will not guess what %s for "
                   "(type the damchain command yourself)" % (", ".join(left), "it is" if len(left) == 1 else "they are"))
    solver = str(data.get("solver") or "").strip().lower()
    if solver:
        if solver not in SOLVERS:
            bad.append("solver %r is not one of %s" % (solver, ", ".join(SOLVERS)))
        elif not re.search(r"\b%s\b" % solver, words, re.I):
            bad.append("solver %s is not in your words" % solver.upper())
        elif _negated(solver, words):
            bad.append("your words say not %s; name the solver to use, or none" % solver.upper())
        else:
            f["solver"] = solver
    if data.get("redo") is True:
        if REDO_WORDS.search(words) and not _negated(REDO_WORDS.pattern, words):
            f["redo"] = True
        else:
            notes.append("left out redo: your words did not ask to run finished dams again")
    asked = [str(u).strip() for u in data.get("unsupported") or [] if str(u).strip()]
    for m in _CANNOT.finditer(words):
        if not any(m.group(0).lower() in a.lower() for a in asked):
            asked.append(m.group(0))
    for u in asked:
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
        if v and k in ("dams", "out", "dem"):
            # full paths, so a path remembered from one folder means the same file from any other
            path, bar, rest = v.partition("|")
            v = os.path.abspath(os.path.expanduser(path)) + bar + rest
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
            # the layer's own spelling is what the Runner matches; 'nd00123' in the words is ND00123
            low = {}
            for h in have:
                low.setdefault(h.lower(), []).append(h)
            missing = []
            for k, i in enumerate(ids):
                if i in have:
                    continue
                same = low.get(i.lower(), [])
                if len(same) == 1:
                    ids[k] = same[0]
                else:
                    missing.append(i)
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


def drafts_log():
    """Every reading is kept here, run or not: the sentence, the model's reply, and what happened."""
    return os.path.join(os.path.dirname(SAVED), "reports", "heim_run_drafts.log")


def _draft(request, reply, outcome):
    try:
        _log(drafts_log(), ["%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), outcome),
                            "  request: " + request, "  model reply: " + " ".join((reply or "").split()), ""])
    except OSError:
        pass


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
        _draft(request, "", "not read: %s" % e)
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
        _draft(request, reply, "refused: " + " | ".join(bad))
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
        _draft(request, reply, "shown (--show): " + shown)
        return 0
    try:
        answer = ask("Run it? Type y to run, anything else stops: ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        out("Stopped; nothing was run.")
        _draft(request, reply, "stopped (no y): " + shown)
        return 1
    _draft(request, reply, "confirmed: " + shown)
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
