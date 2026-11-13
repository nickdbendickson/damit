#!/usr/bin/env python3
# dump_cli_help.py v1.0 — write knowledge/CLI-HELP.md: every flag of the local-AI command-line
# tools, read from the tools' own argument parsers. Stdlib only, no QGIS, no Ollama.
#
#   python3 dump_cli_help.py            # rewrite ../knowledge/CLI-HELP.md
#   python3 dump_cli_help.py --check    # exit 1 if the file is out of date (CI runs this)
#
# Why it exists: Heim was asked about flags and could only guess; a guessed flag reads as
# real. The page is generated, never typed, so it cannot name a flag that is not there.
#
# The parsers are read as objects, not by capturing `--help` text: argparse lays help out
# differently from one Python version to the next, and a page that changed with the
# interpreter could never be checked in CI.
import argparse
import importlib.util
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.dirname(HERE)
VOR = os.path.join(os.path.dirname(HEIM), "vor")
OUT = os.path.join(HEIM, "knowledge", "CLI-HELP.md")

# (file, the command the installers give it, one line on what it is for)
TOOLS = [
    (os.path.join(HERE, "dam_chain.py"), "damchain", "run the plugin chains headless; also `damchain vor ...` and `damchain audit ...`"),
    (os.path.join(HERE, "rag_index.py"), "heim-index  (and heim-add = --add)", "build Heim's document index"),
    (os.path.join(HERE, "rag_query.py"), "heim  /  heim-query", "ask Heim a question answered from the index"),
    (os.path.join(HERE, "run_digest.py"), "heim-digest", "the deterministic run checks and the verdict (no model)"),
    (os.path.join(HERE, "heim_watch.py"), "heim-watch", "run the digest at each pass end and at run end"),
    (os.path.join(HERE, "audit_plugin.py"), "heim-audit", "ask Heim to review one plugin's code"),
    (os.path.join(HERE, "suite_check.py"), "heim-test", "check the installed plugin sets and run their self-tests"),
    (os.path.join(HERE, "repo_audit.py"), "damchain audit", "repo audit: packaging, security patterns, hosts, golden runs"),
    (os.path.join(HERE, "eval_heim.py"), "eval_heim.py", "score a model on the code-triage questions"),
    (os.path.join(HERE, "dump_damit_algorithm_help.py"), "dump_damit_algorithm_help.py", "regenerate ALGORITHM-HELP-DAMIT.md"),
    (os.path.join(VOR, "vor.py"), "vor", "the literature assistant"),
    (os.path.join(VOR, "fetch_asdso.py"), "fetch_asdso.py", "download the reference library"),
    (os.path.join(VOR, "eval_vor.py"), "eval_vor.py", "score a model on the literature questions"),
]
# Settings a tool reads from the environment become parser defaults; clear them so the page
# shows the built-in default, not this machine's.
ENV_PREFIXES = ("HEIM_", "VOR_", "DAMCHAIN_", "DAMRESEARCH_", "OLLAMA_", "NDSUITE_", "NDBREACH_",
                "ANUGA_", "QGIS_", "LISFLOOD")


# Several defaults depend on what is in the home folder (Vor uses whichever of ~/Vor and
# ~/DamResearch holds an index). The parsers are therefore built against an EMPTY home, so
# the page shows what a clean machine gets and is the same wherever it is generated.
EMPTY_HOME = tempfile.mkdtemp(prefix="cli-help-home-")


class _Captured(Exception):
    def __init__(self, parser):
        self.parser = parser


def capture(path):
    """The tool's top-level ArgumentParser: import the file, call main(), stop at parse time."""
    name = "cli_help_" + re.sub(r"\W", "_", os.path.basename(path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    keep_argv, keep_env = sys.argv, dict(os.environ)
    real = (argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args)

    def stop(self, *a, **k):
        raise _Captured(self)

    for k in list(os.environ):
        if k.startswith(ENV_PREFIXES):
            del os.environ[k]
    os.environ["HOME"] = os.environ["USERPROFILE"] = EMPTY_HOME
    sys.argv = [os.path.basename(path)]
    argparse.ArgumentParser.parse_args = stop
    argparse.ArgumentParser.parse_known_args = stop
    try:
        spec.loader.exec_module(mod)
        mod.main()
    except _Captured as c:
        return c.parser
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = real
        sys.argv = keep_argv
        os.environ.clear()
        os.environ.update(keep_env)
    raise RuntimeError("%s: main() returned without parsing arguments" % path)


def _text(s):
    return re.sub(r"\s+", " ", (s or "").replace("%%", "%")).strip().replace("|", "\\|")


def _default(a):
    d = a.default
    if d is None or d is argparse.SUPPRESS or isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                                                              argparse._HelpAction, argparse._VersionAction)):
        return ""
    if d == [] or d == "":
        return ""
    s = str(d)
    root = os.path.dirname(HEIM)                # .../damit_ai, wherever the package was unpacked
    if isinstance(d, str) and os.path.isabs(d) and os.path.normpath(d).startswith(root + os.sep):
        s = "<damit_ai>/" + os.path.relpath(os.path.normpath(d), root).replace(os.sep, "/")
    s = s.replace(EMPTY_HOME, "~")
    if isinstance(d, int) and not isinstance(d, bool) and d == (os.cpu_count() or -1) and "thread" in "".join(a.option_strings).lower():
        return "(CPU count)"
    return "`%s`" % s


def _value(a):
    if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._HelpAction,
                      argparse._VersionAction, argparse._CountAction)):
        return ""
    if a.choices is not None and not isinstance(a, argparse._SubParsersAction):
        return "one of " + ", ".join("`%s`" % c for c in a.choices)
    m = a.metavar if isinstance(a.metavar, str) else (a.dest or "").upper()
    n = a.nargs
    if n in ("*",):
        return "[%s ...]" % m
    if n in ("+",):
        return "%s [%s ...]" % (m, m)
    if n == "?":
        return "[%s]" % m
    if isinstance(n, int):
        return " ".join([m] * n)
    return m


def render(parser, title, depth, out):
    out.append("%s `%s`" % ("#" * depth, title))
    out.append("")
    if parser.description:
        out.append(_text(parser.description))
        out.append("")
    subs = None
    pos, opt = [], []
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            subs = a
        elif isinstance(a, argparse._HelpAction):
            continue
        elif a.option_strings:
            opt.append(a)
        else:
            pos.append(a)
    if pos or opt:
        out.append("| Argument | Value | Default | Meaning |")
        out.append("|---|---|---|---|")
        for a in pos:
            out.append("| `%s` | %s | %s | %s |" % (a.metavar if isinstance(a.metavar, str) else a.dest,
                                                    _value(a), _default(a), _text(a.help)))
        for a in opt:
            req = " **(required)**" if a.required else ""
            help_ = "" if a.help is argparse.SUPPRESS else _text(a.help)
            out.append("| %s | %s | %s | %s%s |" % (", ".join("`%s`" % o for o in a.option_strings),
                                                    _value(a), _default(a), help_, req))
        out.append("")
    elif subs is None:
        out.append("No arguments.")
        out.append("")
    if subs is not None:
        helps = {c.dest: c.help for c in subs._choices_actions}
        seen = set()
        for name, sp in subs.choices.items():
            if id(sp) in seen:            # an alias of a subcommand already written
                continue
            seen.add(id(sp))
            names = [n for n, p in subs.choices.items() if p is sp]
            head = "%s %s" % (title, names[0])
            start = len(out)
            render(sp, head, min(depth + 1, 6), out)
            extra = []
            if helps.get(names[0]) and helps[names[0]] is not argparse.SUPPRESS:
                extra.append(_text(helps[names[0]]))
            if len(names) > 1:
                extra.append("Also accepted as: %s." % ", ".join("`%s`" % n for n in names[1:]))
            if extra:
                out[start + 2:start + 2] = [" ".join(extra), ""]


def build():
    out = ["# Command-line help for the local-AI tools",
           "",
           "GENERATED by `tools/dump_cli_help.py` from the tools' own argument parsers. Do not edit:",
           "run the script. CI fails when this page and the parsers disagree.",
           "",
           "Heim: a flag that is not on this page does not exist. Do not offer one from memory.",
           "A default shown here is the built-in one; an environment variable or the installer's",
           "shell block can change it on a given machine. `~` stands for the user's home folder.",
           ""]
    for path, cmd, what in TOOLS:
        parser = capture(path)
        with open(path, encoding="utf-8") as f:
            first = f.readline() + f.readline()
        m = re.search(r"\bv(\d+(?:\.\d+)+)", first)
        out.append("---")
        out.append("")
        out.append("## %s%s" % (os.path.basename(path), (" " + m.group(1)) if m else ""))
        out.append("")
        out.append("Installed command: `%s`. %s." % (cmd, what[0].upper() + what[1:]))
        out.append("")
        render(parser, os.path.basename(path), 3, out)
    return "\n".join(out).rstrip("\n") + "\n"


def main():
    ap = argparse.ArgumentParser(description="Write knowledge/CLI-HELP.md from the tools' argument parsers.")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the page is out of date")
    ap.add_argument("--out", default=OUT, help="the page to write or check")
    args = ap.parse_args()
    text = build()
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as f:
                have = f.read()
        except OSError:
            have = ""
        if have != text:
            sys.exit("%s is out of date: run python3 %s" % (args.out, os.path.relpath(__file__)))
        print("%s is current" % args.out)
        return
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.rmdir(EMPTY_HOME)
    except OSError:
        pass
    print("wrote %s (%d lines)" % (args.out, text.count("\n")))


if __name__ == "__main__":
    main()
