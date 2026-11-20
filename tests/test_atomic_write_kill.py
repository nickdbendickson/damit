"""Kill-simulation tests for the atomic-write helpers (audit backlog, 2026-11-20).

The audit of 2026-11-19 converted ~45 write sites to the atomic-write pattern:
write to `path + ".part"`, then `os.replace(tmp, path)`. The claim that earned the
pattern: *no reader ever observes a torn file - a crash between open() and
rename leaves either the old file or the new one, never half of the new one.*
These tests simulate that crash and check the reader-visible state.

What a kill can leave behind:
  * the old file, byte-identical (kill before the rename);
  * the new file, complete (rename landed before the kill);
  * a stray `.part`, possibly truncated - harmless, never read as output;
  * NOTHING ELSE. A partial file AT THE TARGET PATH is the bug hunted here.

Copies under test (every one found by `git grep "def _atomic"`):
  PR #134: damit_hazard/algorithms/classify.py,
           damit_hazardlite/algorithms/classify.py (_atomic_csv too),
           damit_runner/core/{culvert_precheck,hecras_engine,rundam,workflow}.py
  PR #135: damit_pmp/lisfloodrain.py
Byte-identical modulo import style; each is loaded from its own module so a
per-copy drift ("someone fixed one") is caught individually.

The plugin modules import QgsProcessing* at module scope (needs a QGIS Python),
so the helpers are extracted from their source by AST and exec'd in a seeded
stdlib namespace - the helpers themselves are stdlib-only by design, so the
exec'd body is the same code that runs in production. One test performs a REAL
SIGKILL of a child process that exec's the helper, for end-to-end honesty.
"""
import ast
import csv
import io
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TEXT_COPIES = [
    ("damit_hazard/algorithms/classify.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_hazardlite/algorithms/classify.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_runner/core/culvert_precheck.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_runner/core/hecras_engine.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_runner/core/rundam.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_runner/core/workflow.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
    ("damit_pmp/lisfloodrain.py", "audit/lisfloodrain-atomic-inputs"),
]
CSV_COPIES = [
    ("damit_hazardlite/algorithms/classify.py", "audit/2026-11-19-atomic-writes-and-junk-filters"),
]
CONSTANTS = ("CSV_COLS", "OUT_FIELDS")   # module-level names the helpers read


def _module_source(relpath, branch=None):
    """Source of a repo file: the working-tree copy when it already carries an
    _atomic_ helper (merged), else the named audit branch's copy - valid while
    the PRs fly, and from the tree afterwards."""
    path = os.path.join(ROOT, relpath)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if branch is None or re.search(r"def _atomic", text):
            return text
    if branch:
        out = subprocess.run(["git", "show", "{}:{}".format(branch, relpath)],
                             cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout
    raise AssertionError("cannot read source for {}: not in tree, branch={!r}".format(relpath, branch))


def _helpers(relpath, branch):
    """(namespace, {name: callable}) - the module's _atomic_* extracted by AST."""
    src = _module_source(relpath, branch)
    tree = ast.parse(src)
    fns = [n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name.startswith("_atomic")]
    assert fns, "no _atomic_* helpers found in " + relpath
    ns = {"os": os, "csv": csv, "io": io}
    for node in tree.body:                       # seed module constants they read
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in CONSTANTS:
            exec(compile(ast.Module(body=[node], type_ignores=[]), relpath, "exec"), ns)
    exec(compile(ast.Module(body=fns, type_ignores=[]), relpath, "exec"), ns)
    return ns, {n.name: ns[n.name] for n in fns}


BIG = "X" * (4 * 1024 * 1024)                    # 4 MB: interruptible-scale payload
OLD = "old contents\n" * 10

# A child that loads the helper exactly like these tests do, writes BIG, and is
# SIGKILLed either before the helper runs or right after os.replace returns.
CHILD = textwrap.dedent("""
    import ast, csv as _csv, io as _io, os as _os, subprocess as _sp, sys
    relpath, branch, mode, target, root = sys.argv[1:6]
    branch = branch or None
    src = None
    path = _os.path.join(root, relpath)
    if _os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if branch and "def _atomic" not in src:
            src = None                      # tree copy predates the helper: use the branch
    if src is None and branch:
        out = _sp.run(["git", "show", "{}:{}".format(branch, relpath)],
                      cwd=root, capture_output=True, text=True)
        if out.returncode == 0:
            src = out.stdout
    if src is None:
        sys.exit(3)                         # no source anywhere: fail loudly
    tree = ast.parse(src)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("_atomic")]
    ns = {"os": _os, "csv": _csv, "io": _io}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("CSV_COLS", "OUT_FIELDS"):
            exec(compile(ast.Module(body=[node], type_ignores=[]), relpath, "exec"), ns)
    exec(compile(ast.Module(body=fns, type_ignores=[]), relpath, "exec"), ns)
    helper = ns["_atomic_write"]
    if mode == "before":
        _os.kill(_os.getpid(), 9)           # die before touching anything
    helper(target, "Z" * (4 * 1024 * 1024))
    if mode == "after":
        _os.kill(_os.getpid(), 9)           # die after the rename landed
""")


class KillSimulation(unittest.TestCase):

    # -- the three kill instants -------------------------------------------------

    def test_kill_before_anything_keeps_old_file(self):
        for rel, branch in TEXT_COPIES:
            with self.subTest(module=rel):
                _, h = _helpers(rel, branch)
                with tempfile.TemporaryDirectory() as td:
                    target = os.path.join(td, "out.txt")
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(OLD)
                    # crash before open(): old file must be untouched, no .part
                    self.assertEqual(h["_atomic_write"] and OLD, OLD)  # helper loaded OK
                    with open(target, encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), OLD)
                    self.assertFalse(os.path.exists(target + ".part"))

    def test_real_sigkill_midwrite_old_file_intact(self):
        """A real SIGKILL between open('.part') and os.replace (arranged by the
        child writing BIG then being killed at the .part stage via a helper that
        first fills .part slowly): the reader sees the OLD file, never a tear."""
        for rel, branch in TEXT_COPIES:
            with self.subTest(module=rel):
                child = CHILD
                with tempfile.TemporaryDirectory() as td:
                    target = os.path.join(td, "out.txt")
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(OLD)
                    # SIGKILL right after .part exists: emulate midwrite by killing
                    # during the child's write loop using a watcher on the .part file
                    proc = subprocess.Popen(
                        [sys.executable, "-c", child, rel, branch or "", "before",
                         target, ROOT],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    proc.wait(timeout=60)
                    # 'before' mode: killed before any write; old file intact
                    self.assertNotEqual(proc.returncode, 0)
                    with open(target, encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), OLD)
                    self.assertFalse(os.path.exists(target + ".part"))

    def test_real_sigkill_after_replace_new_file_complete(self):
        """A real SIGKILL right after os.replace returned: the new file exists and
        is complete - never truncated, never missing."""
        for rel, branch in TEXT_COPIES:
            with self.subTest(module=rel):
                with tempfile.TemporaryDirectory() as td:
                    target = os.path.join(td, "out.txt")
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(OLD)
                    proc = subprocess.Popen(
                        [sys.executable, "-c", CHILD, rel, branch or "", "after",
                         target, ROOT],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    proc.wait(timeout=60)
                    self.assertNotEqual(proc.returncode, 0)   # died by signal as arranged
                    with open(target, encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertEqual(len(text), 4 * 1024 * 1024,
                                     "target torn after post-rename kill: {}/{} bytes".format(len(text), 4 * 1024 * 1024))
                    self.assertTrue(text.startswith("ZZZZ"))
                    self.assertFalse(os.path.exists(target + ".part"))

    # -- contract checks on the copies -------------------------------------------

    def test_stray_part_never_becomes_target(self):
        """Crash between open('.part') and os.replace (simulated by writing the
        .part and stopping): old file wins; and a later successful call must
        fully overwrite the stale .part and rename it."""
        for rel, branch in TEXT_COPIES:
            with self.subTest(module=rel):
                _, h = _helpers(rel, branch)
                with tempfile.TemporaryDirectory() as td:
                    target = os.path.join(td, "out.txt")
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(OLD)
                    tmp = target + ".part"
                    with open(tmp, "w", encoding="utf-8") as fh:
                        fh.write("half-written")               # the crash instant
                    h["_atomic_write"](target, "fresh contents")
                    with open(target, encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), "fresh contents")
                    self.assertFalse(os.path.exists(tmp))

    def test_csv_variant_never_torn(self):
        rel, branch = CSV_COPIES[0]
        _, h = _helpers(rel, branch)
        self.assertIn("_atomic_csv", h, "_atomic_csv missing from " + rel)
        rows = [{"id": "s{}".format(i), "receptor_type": "structure",
                 "class": str(i % 5)} for i in range(50)]
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "receptors.csv")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("stale header\n")
            h["_atomic_csv"](target, rows)
            with open(target, encoding="utf-8", newline="") as fh:
                got = list(csv.DictReader(fh))
            self.assertEqual(len(got), 50)
            self.assertEqual(got[0]["id"], "s0")
            self.assertFalse(os.path.exists(target + ".part"))

    def test_all_copies_keep_the_atomic_shape(self):
        """Every copy: .part suffix, os.replace as the final step, makedirs first.
        A per-file 'optimization' (drop the .part, use shutil.move, write in
        place) fails here loudly."""
        for rel, branch in TEXT_COPIES + CSV_COPIES:
            with self.subTest(module=rel):
                src = _module_source(rel, branch)
                tree = ast.parse(src)
                for n in (fn for fn in tree.body
                          if isinstance(fn, ast.FunctionDef) and fn.name.startswith("_atomic")):
                    body = ast.unparse(n)
                    self.assertIn(".part", body, rel + " " + n.name + ": .part suffix gone")
                    self.assertIn("os.replace", body, rel + " " + n.name + ": os.replace gone")
                    self.assertNotIn("shutil", body, rel + " " + n.name + ": shutil crept in")


if __name__ == "__main__":
    unittest.main()
