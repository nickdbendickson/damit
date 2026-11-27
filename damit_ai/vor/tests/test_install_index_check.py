"""The installers index Vor's library when its index holds no passages, not only when there is no
index FILE.

Why this exists: 2026-11-24 a Mac had 189 files in ~/Vor/library and a vor.db with 0 documents and
0 passages. Install-Mac.command (and the Linux and Windows installers) indexed only when no vor.db
or research.db existed, so every re-run skipped the index, `vor doctor` said "the index is empty",
and ai-score skipped every Vor question. An empty index is a valid index, so nothing errored.

The three installers now ask the index itself (one shared Python line, run by Vor's own Python).
setup-vor.zsh also installs fetch_asdso.py and its catalog beside vor.py, as the Linux and Windows
installers already did, so `~/local-ai/vor/python ~/local-ai/vor/fetch_asdso.py --catalog GROUPS`
works after a Mac install, not only after an update kit.
"""
import importlib.util
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VOR = os.path.dirname(HERE)
AI = os.path.dirname(VOR)
MAC = os.path.join(AI, "Install-Mac.command")
LINUX = os.path.join(AI, "install-local-ai-linux.sh")
WINDOWS = os.path.join(AI, "install-local-ai-windows.ps1")
SETUP_VOR = os.path.join(VOR, "setup-vor.zsh")
SQL = "SELECT COUNT(*) FROM chunks"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def one_liner(text):
    """The Python line an installer runs to ask whether the index holds passages."""
    found = re.findall(r"-c '(import sqlite3,sys;[^']*)'", text)
    return found


def shell_function(text, name):
    """A shell function's definition, from `name() {` to its closing brace at the same indent."""
    m = re.search(r"^([ \t]*)%s\(\) \{\n.*?^\1\}\n" % re.escape(name), text, re.M | re.S)
    if not m:
        raise AssertionError("no %s() in the installer" % name)
    return m.group(0)


class Index(object):
    """Index files of the kinds an installer meets: empty, holding passages, not an index."""

    def __init__(self, folder):
        self.folder = folder
        spec = importlib.util.spec_from_file_location("vor_install_check", os.path.join(VOR, "vor.py"))
        self.vor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vor)

    def empty(self, name="vor.db"):
        p = os.path.join(self.folder, name)
        db = sqlite3.connect(p)
        db.executescript(self.vor.SCHEMA)
        db.commit()
        db.close()
        return p

    def with_passages(self, name="vor.db"):
        p = self.empty(name)
        db = sqlite3.connect(p)
        db.execute("INSERT INTO docs(id, sha1, path, title, pages, notext, added) "
                   "VALUES(1, 's', 'a.pdf', 'a', 1, '', '2026-11-24T00:00:00')")
        db.execute("INSERT INTO chunks(doc_id, page, label, idx, txt, vec) VALUES(1, 1, '1', 0, 't', x'')")
        db.commit()
        db.close()
        return p

    def not_an_index(self, name="vor.db"):
        p = os.path.join(self.folder, name)
        with open(p, "wb") as fh:
            fh.write(b"not sqlite at all")
        return p


class OneLinerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vor-install-check-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.idx = Index(self.tmp)

    def test_the_three_installers_run_the_same_line(self):
        lines = [one_liner(read(p)) for p in (MAC, LINUX, WINDOWS)]
        for p, found in zip((MAC, LINUX, WINDOWS), lines):
            self.assertEqual(len(found), 1, "%s: expected one index check, found %r" % (p, found))
        self.assertEqual(len({f[0] for f in lines}), 1, lines)

    def test_no_double_quote_in_the_line(self):
        """Windows PowerShell 5.1 drops double quotes inside a native command's arguments, so the
        SQL goes in as its own argument and the line itself carries none."""
        self.assertNotIn('"', one_liner(read(WINDOWS))[0])
        self.assertIn("'%s'" % SQL, read(WINDOWS))

    def run_line(self, path):
        code = one_liner(read(LINUX))[0]
        return subprocess.run([sys.executable, "-c", code, path, SQL],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    def test_empty_index_reads_as_not_indexed(self):
        self.assertNotEqual(self.run_line(self.idx.empty()), 0)

    def test_index_with_passages_reads_as_indexed(self):
        self.assertEqual(self.run_line(self.idx.with_passages()), 0)

    def test_a_file_that_is_not_an_index_reads_as_not_indexed(self):
        self.assertNotEqual(self.run_line(self.idx.not_an_index()), 0)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ShellFunctionTest(unittest.TestCase):
    """The Linux function and the Mac one (zsh, but written in the subset bash runs the same way),
    run for real against index files, with a `python` launcher like the installers write."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vor-install-shell-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Vor")
        os.makedirs(self.home)
        self.idx = Index(self.home)
        self.tool = os.path.join(self.tmp, "local-ai", "vor")
        os.makedirs(self.tool)
        launcher = os.path.join(self.tool, "python")
        with open(launcher, "w") as fh:
            fh.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(launcher, 0o755)

    def linux(self):
        fn = shell_function(read(LINUX), "vor_index_has_passages")
        script = fn + 'vor_index_has_passages "$1"\n'
        env = dict(os.environ, VOR_DIR=self.tool)
        return subprocess.run(["bash", "-c", script, "x", self.home], env=env).returncode

    def mac(self):
        fn = shell_function(read(MAC), "indexed")
        script = 'vhome="$1"\n' + fn + "indexed\n"
        env = dict(os.environ, HOME=self.tmp)
        return subprocess.run(["bash", "-c", script, "x", self.home], env=env).returncode

    def check(self, run):
        self.assertNotEqual(run(), 0, "no index file: not indexed")
        self.idx.empty()
        self.assertNotEqual(run(), 0, "an empty vor.db (the 2026-11-24 Mac): not indexed")
        os.remove(os.path.join(self.home, "vor.db"))
        self.idx.with_passages("research.db")
        self.assertEqual(run(), 0, "the pre-rename research.db with passages: indexed")
        self.idx.with_passages("vor.db")
        self.assertEqual(run(), 0, "vor.db with passages: indexed")

    def test_linux(self):
        self.check(self.linux)

    def test_mac(self):
        self.check(self.mac)

    def test_vor_db_decides_over_research_db(self):
        """vor.py reads vor.db when it exists (research.db only without it), so the check does too:
        an empty vor.db beside a full research.db is an empty index to Vor."""
        self.idx.with_passages("research.db")
        self.idx.empty("vor.db")
        self.assertNotEqual(self.linux(), 0)
        self.assertNotEqual(self.mac(), 0)


class WiringTest(unittest.TestCase):
    def test_ingest_decisions_ask_the_index(self):
        self.assertRegex(read(MAC), r'if has_docs "\$lib" && ! indexed; then')
        self.assertIn('&& ! vor_index_has_passages "$RHOME"; then', read(LINUX))
        self.assertIn("if ($hasLib -and -not $hasPassages) {", read(WINDOWS))
        self.assertNotIn('[[ ! -f "$vhome/vor.db" && ! -f "$vhome/research.db" ]]', read(MAC))

    def test_setup_vor_installs_the_fetch_tool_and_its_catalog(self):
        text = read(SETUP_VOR)
        m = re.search(r"^for t in ([^;]+); do\n\s*\[\[ -f \"\$HERE/\$t\" \]\] && cp \"\$HERE/\$t\" \"\$TOOL_DIR/\$t\"\ndone",
                      text, re.M)
        self.assertTrue(m, "setup-vor.zsh: no copy loop for the Vor tools")
        names = m.group(1).split()
        self.assertIn('cp "$HERE/eval_vor.py" "$TOOL_DIR/eval_vor.py"', text)
        for t in ("fetch_asdso.py", "reference_sources.json"):
            self.assertIn(t, names)
            self.assertTrue(os.path.isfile(os.path.join(VOR, t)), t)


if __name__ == "__main__":
    unittest.main()
