#!/usr/bin/env python3
# heim_run.py v1.0.0 — `heim run "plain English"`: Heim drafts a damchain run, you check it, you type y.
#
#   heim run "run 2801 and 4031 at 5 m with FV2"
#   heim run --set damit --dams ~/Dams/dams.gpkg --out ~/Dams/runs --dem ~/DEM/nd.vrt "run 2801 at 10 m"
#   heim run --show "rerun 2801 with n 0.04"          show the command only, never run
#
# The local model only FILLS IN FIXED FIELDS (dam ids, cell size, solver, Manning's n, redo). It never
# writes the command. This code builds the command and refuses, rather than guesses, when:
#   - your words hold anything besides a run word, dam ids, the settings above and a few small words
#     ("the", "and", "with", "at", "dam" ...): "the 30 m high dam", "thanks", "2 at a time" stop it;
#   - a dam id is not in your words as a word of its own, or not in the dams layer;
#   - with several dams: a run / redo word other than once before them, a dam named twice, or a dam
#     after a setting ("run 2801 at 5 m and 4031"): one set of settings goes to every dam;
#   - a cell size is not in your words after "at" / "cell" or before "cells", is out of range, or is
#     in feet, cm...;
#   - Manning's n is not in your words next to "n" / "Manning", or is out of range;
#   - your words hold a number that no field accounts for ("the 2 m DEM", a second cell size);
#   - the solver word is not in your words, or your words name two;
#   - your words say "not", "except", "instead of" ... (it does not work out what is ruled out), give
#     a range (2801-2805, 2801 to 2805, 5-10 m), a comma in a number (5,5 m, 2,801) or a
#     number in letters (five metres);
#   - you asked for something these fields cannot hold (ANUGA, a pool, a scenario, a DEM, all dams...),
#     whether or not the model listed it (it says what, and how to type it yourself);
#   - redo (run again over finished dams) is set but your own words did not ask for it: redo is then
#     left out, with a note.
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
import unicodedata

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
SAVED = os.path.expanduser(os.environ.get("HEIM_RUN_SETTINGS", "~/local-ai/heim_run.json"))
SETS = ("damit", "dwr")
# a set named on its own ('DWR-2801' is a dam id, not the DamSafety set)
SET_WORDS = {"damit": r"(?<![\w-])damit(?![\w-])", "dwr": r"(?<![\w-])(?:dwr|damsafety)(?![\w-])"}
SOLVERS = ("acc", "fv2", "mwdg2")
CELL_RANGE = (0.5, 200.0)          # metres
MANNING_RANGE = (0.01, 0.25)
REDO_WORDS = re.compile(r"\b(?:re-?do(?:ing)?|re[-\s]?run(?:ning)?|again|one\s+more\s+time|overwrite|replace|"
                        r"from\s+scratch)\b", re.I)
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
_NUM = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?|\.\d+)(?![\d]|\.\w)")
_METRE = re.compile(r"\s*-?\s*(?:m|metres?|meters?)(?![a-z])", re.I)
_OTHER_UNIT = re.compile(r"\s*-?\s*(ft|feet|foot|cm|mm|km|yd|yards?|inch(?:es)?|mi|miles?|us\s*ft|"
                         r"(?:us\s+)?survey\s+f\w*|[ap]\.?m\b\.?|o'?clock|h|hrs?|hours?|min\w*|s|secs?|"
                         r"seconds?|days?|%|percent|cores?|cpus?)(?![a-z])|"
                         r"\s*(['’′″\"])", re.I)
_CELL_BEFORE = re.compile(r"(?:\bat|\bcells?(?:\s+size)?|\bgrid(?:\s+size)?|\bresolution|\bres)\s*(?:of|=|:|to|is)?\s*$",
                          re.I)
_N_BEFORE = re.compile(r"(?:\bn|\bmanning'?s?(?:\s+n)?|\broughness)\s*(?:of|=|:|to|is)?\s*$", re.I)
# Any "not", "except", "instead of" ... : heim run does not work out what is ruled out; it refuses.
# ('no.' before a number is a dam number; a bare 'no' is a no: "run 2801, no 4031" is refused)
_NEGATION = re.compile(r"\b(?:not|never|no(?!\.\s*\d)|none|nor|cannot|without|avoid|skip\w*|except\w*|exclud\w*|"
                       r"instead|rather\s+than|other\s+than|dont|doesnt|didnt|shouldnt|wont|cant|mustnt)\b|"
                       r"\b\w+n['’]t\b", re.I)
_RANGE = re.compile(r"(?<![\w.\-])\d*\.?\d+\s*(?:-|–|—|\.\.\.?)\s*\.?\d|"
                    r"(?<![\w.\-])[\w\-]*\d[\w\-]*\s+(?:to|thru|through|till|until)\s+[\w\-]*\d", re.I)
_THOUSANDS = re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?![\w,]|\.\d)")
_NUMBER_WORDS = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                           r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
                           r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|half|quarter|dozen|"
                           r"first|second|third)\b", re.I)
# Things a sentence may ask for that heim run cannot set. Refused even when the model leaves them out.
_CANNOT = re.compile(r"\b(anuga|lisflood|hec-?ras|gpus?|cpus?|cores?|processors?|nodes?|jobs?|sgc|boann|builtin|"
                     r"built-in|scenario|pmf|sunny|froehlich|macdonald|von\s+thun|pool|inflow|hours?|duration|"
                     r"classif\w*|hazard|workers?|threads?|dem|lidar|terrain|vrt|every\s+dam|"
                     r"all\s+(?:the\s+)?dams|tier|mesh|width|depth|height|side\s*slopes?|breach\s+\w+\s+time|"
                     r"(?:failure|formation)\s+time)\b", re.I)


# 'cells' / 'grid' after a number makes it the cell size ('5 m cells'), unless the word has a number of its
# own ('run 2801 grid 5 m': 2801 is the dam)
_CELL_AFTER = re.compile(r"\s*(?:cells?|grid|resolution|res)\b(?!(?:\s+size)?\s*(?:of|=|:|to|is|at)?\s*\.?\d)", re.I)
# The only words a request may hold besides dam ids, numbers (with their units) and solver names.
# Anything else ("high", "thanks", "crashed", "folder", "processes") is refused, not guessed at.
_FILLER = {
    "please", "can", "could", "would", "you", "heim", "now", "the", "a", "an", "dam", "dams", "id", "ids",
    "no", "number", "and", "with", "using", "use", "at", "on", "for", "of", "to", "in", "by", "is", "it",
    "them", "both", "these", "this", "me", "cell", "cells", "size", "grid", "resolution", "res", "solver",
    "manning", "manning's", "mannings", "n", "roughness", "m", "metre", "metres", "meter", "meters",
    "set", "damit", "dwr", "damsafety", "model", "models", "breach", "runs", "go", "ahead"}
_VERB = re.compile(r"\b(?:run|re-?run|re\s+run|re-?do|redo|rerunning|redoing|running)\b", re.I)
_REDO_PHRASES = re.compile(r"\b(?:again|one\s+more\s+time|overwrite|replace|from\s+scratch|re-?do(?:ing)?|"
                           r"re[-\s]?run(?:ning)?)\b", re.I)
_PLACEHOLDERS = {"none", "nothing", "n/a", "na", "null", "-", "no", "empty", ""}


def _unit_len(after):
    u = _METRE.match(after) or _OTHER_UNIT.match(after)
    return u.end() if u else 0


def read_numbers(text):
    """Each number written on its own in the text, with what it is next to:
    {"value", "text", "role": "cell" | "n" | "plain" | "other" | "comma", "unit", "span"}.
    A cell size is a number after 'at' / 'cell' / 'grid' / 'resolution', or one followed by
    'cell(s)' / 'grid' ('5 m cells'). Any other number with a unit ('a 30 m high dam') is 'other'."""
    out = []
    groups = [g.span() for g in _THOUSANDS.finditer(text)]
    for m in _NUM.finditer(text):
        after = text[m.end():]
        span = (m.start(), m.end() + _unit_len(after))
        if after[:1].isalpha() and not (_METRE.match(after) or _OTHER_UNIT.match(after)):
            # glued to letters ('2801a', '6x'): counted, so a field must account for it (an id can)
            out.append({"value": float(m.group(1)), "text": m.group(1), "role": "other", "unit": "",
                        "span": (m.start(), m.end())})
            continue
        before = text[:m.start()]          # the whole word before ('on' is not 'n')
        unit = ""
        if _METRE.match(after):
            unit = "m"
        else:
            u = _OTHER_UNIT.match(after)
            if u and (u.group(1) or _CELL_BEFORE.search(before)):   # a quote is feet only for a cell size
                unit = (u.group(1) or u.group(2)).lower()
            elif u:
                span = (m.start(), m.end())
        if _N_BEFORE.search(before):
            role = "n"
        elif (_CELL_BEFORE.search(before) and not re.search(r"\bbreach\s+at\s*$", before, re.I)) or \
                (unit and _CELL_AFTER.match(after[_unit_len(after):])):
            role = "cell"                  # not 'breach at 5 m', not '5 cells' (a count)
        elif unit or _CELL_AFTER.match(after):
            role = "other"                 # a length or a time not said to be the cell size, or '5 cells'
        else:
            role = "plain"
        if role in ("cell", "n") and (re.match(r",\d", after) or re.search(r"\d,$", before)):
            role = "comma"                 # '5,5 m': a comma decimal or a list; not guessed which
        elif any(a <= m.start() and m.end() <= b for a, b in groups):
            role = "comma"                 # '2,801': one number with a thousands comma, or two dams?
        out.append({"value": float(m.group(1)), "text": m.group(1), "role": role, "unit": unit, "span": span})
    return out


def _same(a, b):
    return abs(float(a) - float(b)) < 1e-9


def _id_re(i):
    return r"(?<![\w.\-])%s(?![\w\-]|\.\w)" % re.escape(i)      # 2801 is not read out of 2801.A


def _solver_re(x):
    return r"(?<![\w\-])%s(?![\w\-])" % re.sub(r"(?<=[a-z])(?=\d)", "-?", x)    # FV-2 is FV2; ACC-7 is an id


def check_fields(request, data):
    """Code's check of the model's fields against the request. Returns (fields, refusals, notes).
    The request must read as: a run word, the dam ids, then the settings for all of them ("rerun
    2801 and 4031 at 5 m with FV2, n 0.04"). Every word must be a dam id the model gave, a number
    a field uses (a cell size after 'at' / 'cell' or before 'cells'; n after 'n' / 'Manning'), a
    solver name, a run / redo word, or one of a short list of small words. Anything else stops the
    run: it is refused, not guessed."""
    bad, notes = [], []
    blank = {"ids": [], "cell_m": None, "solver": "", "manning": None, "redo": False}
    words = unicodedata.normalize("NFKC", request)          # full-width ５ｍ is 5m
    words = re.sub(r"\b(fv|mwdg)\s(2)\b", r"\1-\2", words, flags=re.I)   # 'FV 2' is FV2 (same length)
    for what, rx, why in (
            ("not", _NEGATION, "heim run does not read %r: say only what to run (finished dams are skipped "
                               "unless you say rerun; a solver or cell size is the Runner's own unless you name one)"),
            ("range", _RANGE, "your words give a range (%r); heim run takes single values: list each dam, "
                              "or type the damchain command yourself"),
            ("words", _NUMBER_WORDS, "write numbers as digits (%r)")):
        hit = rx.search(re.sub(r"\bone\s+more\s+time\b", "", words, flags=re.I) if what == "words" else words)
        if hit:
            bad.append(why % hit.group(0).strip())
    raw = data.get("unsupported") or []
    if isinstance(raw, str):
        raw = [raw]
    asked = [str(u).strip() for u in raw if str(u).strip().lower().strip(".") not in _PLACEHOLDERS]
    for m in _CANNOT.finditer(words):
        if not any(m.group(0).lower() in a.lower() for a in asked):
            asked.append(m.group(0))
    for u in asked:
        bad.append("heim run cannot set %r; type the damchain command yourself (damchain run --help)" % u)
    if bad:
        return blank, bad, notes
    nums = read_numbers(words)
    used = set()
    taken = []                                    # spans of the words the fields account for
    ids, id_pos = [], []
    raw_ids = data.get("ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    for r in raw_ids:
        i = unicodedata.normalize("NFKC", str(r)).strip()
        if not i:
            continue
        if i.lower() in _FILLER or _VERB.fullmatch(i) or i.lower() in SOLVERS:
            bad.append("dam id %r is also a word heim run reads in a request; type the damchain command "
                       "yourself for this dam" % i)
            continue
        hit = None
        if re.fullmatch(r"\d+(?:\.\d+)?", i):
            for k, n in enumerate(nums):
                if n["role"] == "plain" and n["text"] == i and re.compile(_id_re(i)).match(words, n["span"][0]):
                    hit = k
                    used.add(k)
                    taken.append(n["span"])
                    id_pos.append(n["span"][0])
        else:
            spelled = set()
            for m in re.finditer(_id_re(i), words, re.I):
                if any(n["role"] in ("cell", "n") and m.start() <= n["span"][0] and n["span"][1] <= m.end()
                       for n in nums):
                    continue                       # '10M' after 'at' is a cell size, not dam 10M
                hit = -1
                spelled.add(m.group(0))
                taken.append(m.span())
                id_pos.append(m.start())
                used.update(k for k, n in enumerate(nums) if m.start() <= n["span"][0] and n["span"][1] <= m.end())
            if len(spelled) == 1:
                i = spelled.pop()                  # the words' spelling, not the model's ('a1' is not 'A1')
            elif len(spelled) > 1:
                bad.append("your words write %s in more than one way (%s); write it once, as in the layer"
                           % (i, ", ".join(sorted(spelled))))
                continue
        if hit is None:
            bad.append("dam id %r is not in your words as a dam id" % i)
            continue
        if i not in ids:
            ids.append(i)
    if len(ids) > 1 and len(set(id_pos)) > len(ids):
        bad.append("your words name a dam more than once; heim run gives every dam the same settings, so "
                   "name each dam once (\"run 2801 and 4031 at 5 m\"), or run them one at a time")
    if not ids and not bad:
        bad.append("no dam id: name the dams (e.g. \"run 2801 and 4031\"); a question about runs ends "
                   "with ? (heim run times for ANUGA?)")
    f = dict(blank, ids=ids)

    def number(key, what):
        v = data.get(key)
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            bad.append("%s is not a number" % what)
            return None
    set_pos = []
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
        if at and not [k for k in at if not nums[k]["unit"]]:
            bad.append("Manning's n has no unit; %s %s is a length, not n (write it as \"n 0.04\")"
                       % (_g(n), nums[at[0]]["unit"]))
        elif not at:
            bad.append("Manning's n %s is not in your words as Manning's n (write it as \"n 0.04\")" % _g(n))
        elif not MANNING_RANGE[0] <= n <= MANNING_RANGE[1]:
            bad.append("Manning's n %s is outside %g-%g" % ((_g(n),) + MANNING_RANGE))
        else:
            f["manning"] = n
            used.update(at)
    for k in used:
        if nums[k]["role"] in ("cell", "n"):
            taken.append(nums[k]["span"])
            set_pos.append(nums[k]["span"][0])
    left = [nums[k]["text"] + (" " + nums[k]["unit"] if nums[k]["unit"] else "")
            for k in range(len(nums)) if k not in used]
    if left and not bad:
        bad.append("your words have %s, which heim run did not use; it will not guess what %s for "
                   "(type the damchain command yourself)" % (", ".join(left), "it is" if len(left) == 1 else "they are"))
    # solvers: looked for outside the dam ids, so a dam called ACC-7 does not name ACC
    rest = list(words)
    for a, b in taken:
        rest[a:b] = " " * (b - a)
    rest = "".join(rest)
    named = []
    for x in SOLVERS:
        for m in re.finditer(_solver_re(x), rest, re.I):
            named.append(x)
            set_pos.append(m.start())
            rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    named = sorted(set(named))
    solver = str(data.get("solver") or "").strip().lower()
    if len(named) > 1:
        bad.append("your words name more than one solver (%s); name one" % ", ".join(x.upper() for x in named))
    elif solver:
        if solver not in SOLVERS:
            bad.append("solver %r is not one of %s" % (solver, ", ".join(SOLVERS)))
        elif solver not in named:
            bad.append("solver %s is not in your words (write it as ACC, FV2 or MWDG2)" % solver.upper())
        else:
            f["solver"] = solver
    elif named and not bad:
        bad.append("your words name %s but the reading has no solver; write it again plainly" % named[0].upper())
    # one run word, the dams, then the settings for all of them
    verbs = _VERB.findall(rest)
    redo_hits = [m for m in _REDO_PHRASES.finditer(rest)]
    run_pos = [m.start() for m in _VERB.finditer(rest)] + [m.start() for m in redo_hits]
    if len(ids) > 1 and id_pos and (any(min(id_pos) < q < max(id_pos) for q in run_pos)
                                    or any(m.start() > min(id_pos) for m in redo_hits)):
        bad.append("with several dams, a run or redo word goes once, before them (\"rerun 2801 and 4031\"); "
                   "otherwise run the dams one at a time")
    elif len(verbs) > 1 and len(ids) > 1:
        bad.append("your words have more than one run (%s); heim run makes one run with one set of "
                   "settings for every dam: run them one at a time" % ", ".join(verbs))
    if len(ids) > 1 and set_pos and id_pos and max(id_pos) > min(set_pos):
        bad.append("a dam comes after a setting; heim run gives every dam the same settings, so write the "
                   "dams first (\"run 2801 and 4031 at 5 m\"), or run them one at a time")
    for m in redo_hits:
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    rest = _VERB.sub(" ", rest)
    unknown = []
    for tok in re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*|[\d_]+|[^\w\s]", rest):
        t = tok.lower().replace("’", "'")
        if t in _FILLER or t in ",.;:!=&+":
            continue
        if t not in unknown:
            unknown.append(t)
    if unknown and not bad:
        bad.append("heim run does not know %s; it reads only dam ids, a cell size in m, a solver (ACC, FV2, "
                   "MWDG2), Manning's n and rerun. Type the damchain command for anything else"
                   % ", ".join(repr(u) for u in unknown[:5]))
    if data.get("redo") is True:
        if redo_hits:
            f["redo"] = True
        else:
            notes.append("left out redo: your words did not ask to run finished dams again")
    elif redo_hits and not bad:
        bad.append("your words ask to run again (%r) but the reading has no redo; write it again plainly"
                   % redo_hits[0].group(0))
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
    return None, "which plugin set? give --set damit or --set dwr (it is remembered after a run you confirm)"


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


def check_paths(set_name, p, ids, layer_ids, words=""):
    bad = []
    for k, what in (("dams", "dams layer (--dams)"), ("out", "output folder (--out)"), ("dem", "DEM (--dem)")):
        if not p.get(k):
            bad.append("no %s yet for --set %s: give it with a run you confirm with y, and it is "
                       "remembered (--show and a stop do not remember it)" % (what, set_name))
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
            src, _, rest = p["dams"].partition("|")
            if src.lower().endswith(".gpkg") and not rest.lower().startswith("layername="):
                hint = "name its layer: --dams '%s|layername=LAYER'" % src
            elif src.lower().endswith((".gpkg", ".csv")):
                hint = "give its dam id field with --id-field"
            else:
                hint = "heim run reads a .gpkg or .csv; type the damchain command yourself for this layer"
            bad.append("cannot read the dam ids in %s here: %s" % (p["dams"], hint))
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
            # a longer id of the layer written in the words ('2801 A' when 2801 and '2801 A' are both
            # dams): the words may name that dam, not the shorter one
            for i in ids:
                longer = sorted(h for h in have if len(h) > len(i) and h.lower().startswith(i.lower())
                                and words and re.search(r"(?<![\w.\-])%s(?![\w\-]|\.\w)" % re.escape(h), words, re.I))
                if longer:
                    bad.append("your words may name dam %s, not %s (both are in the layer); write the dam "
                               "plainly, or type the damchain command" % (longer[0], i))
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
        bad = check_paths(set_name, p, f["ids"], dc.layer_ids, unicodedata.normalize("NFKC", request))
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
