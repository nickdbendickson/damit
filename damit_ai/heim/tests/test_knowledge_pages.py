"""The knowledge pack pages added 2026-11-13: generated help is current, the curated pages
name only flags that exist, and every eval question can be answered from the pack.

Why this exists: a page that tells Heim about a flag is worse than no page if the flag is
not real, because Heim repeats it with the page as its source.
"""
import importlib.util
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.dirname(HERE)
KN = os.path.join(HEIM, "knowledge")
CURATED = ("KNOWN-BEHAVIOURS.md", "FAILURE-CASEBOOK.md", "FILE-CONTRACTS.md", "RUN-RECIPES.md")

# Flags of scripts that live in the DamSafety repo or travel with the batch packages, so
# CLI-HELP.md (this repo's tools) cannot vouch for them. Each was read off the script's own
# argument list when the page was written. A flag in a curated page must be in CLI-HELP.md
# or here; anything else is a typo or an invention.
EXTERNAL_FLAGS = {
    # run_nickreview.sh / nickreview_mac.py
    "--dam", "--data", "--out", "--stages", "--no-kits", "--redo", "--dry-run",
    # use_local_terrain.sh
    "--vrt", "--no-redo",
    # run_lisflood_44.py / run_anuga_culverts_44.py / run_county.py
    "--only", "--parallel", "--dem", "--cell", "--watch", "--triage", "--county", "--list",
    "--limit", "--kind", "--mode", "--status",
    # batch_watch.py, which those three start with --watch (DamSafety tools/batch)
    "--with-model",
    # the heim-chat shell function the Mac installer writes (test_heim_chat checks it is there)
    "--bare",
}

# Named in a page precisely to say it does NOT exist (KNOWN-BEHAVIOURS: "There is no ...
# `--no-refine`"), because Heim once invented it.
NAMED_AS_NOT_EXISTING = {"--no-refine"}


def read(name):
    with open(os.path.join(KN, name), encoding="utf-8") as f:
        return f.read()


def load_dumper():
    spec = importlib.util.spec_from_file_location("dump_cli_help_test", os.path.join(HEIM, "tools", "dump_cli_help.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CliHelpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = read("CLI-HELP.md")

    def test_page_is_current(self):
        built = load_dumper().build()
        self.assertEqual(built, self.page,
                         "knowledge/CLI-HELP.md is out of date: run python3 damit_ai/heim/tools/dump_cli_help.py")

    def test_page_does_not_depend_on_this_machine(self):
        for needle in ("/home/", "/root/", "/Users/", "/tmp/", "cli-help-home"):
            self.assertNotIn(needle, self.page)

    def test_every_tool_is_on_the_page(self):
        for path, _cmd, _what in load_dumper().TOOLS:
            self.assertIn("## " + os.path.basename(path), self.page)

    def test_flags_added_today_are_there(self):
        for flag in ("`--add`", "`--doc`", "`--per-doc`", "`--getdata-param`", "`--redo`", "`--stop-on-error`"):
            self.assertIn(flag, self.page)


class CuratedPagesTest(unittest.TestCase):
    def test_every_flag_a_curated_page_names_exists(self):
        known = set(re.findall(r"`(--[a-z0-9][a-z0-9-]*)`", read("CLI-HELP.md"))) | EXTERNAL_FLAGS
        for name in CURATED:
            for flag in sorted(set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", read(name))) - NAMED_AS_NOT_EXISTING):
                self.assertIn(flag, known, "%s names %s, which no tool has" % (name, flag))

    def test_no_machine_names_or_server_links(self):
        for name in CURATED + ("README.md",):
            t = read(name)
            self.assertNotRegex(t, r"(?i)\b(smb|afp|ftp|ssh)://", name)
            self.assertNotRegex(t, r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", name)
            self.assertNotRegex(t, r"/Volumes/|\\\\\\\\[A-Za-z]", name)
            self.assertNotRegex(t, r"(?i)grok bot|password|api[_ -]?key", name)

    def test_readme_lists_every_page(self):
        readme = read("README.md")
        for f in sorted(os.listdir(KN)):
            if f.endswith(".md") and f != "README.md":
                self.assertIn("`%s`" % f, readme, "knowledge/README.md does not list %s" % f)

    def test_terrain_traps_are_in_known_behaviours(self):
        kb = read("KNOWN-BEHAVIOURS.md")
        for needle in ("## Terrain swaps", "work = dem_crs", "WORK_CRS", "missing source", "nodata",
                       "avg5m", 'READS["record"] = ()', "OVERWRITE=true", "5 m underlay|5 m DEM underneath"):
            self.assertRegex(kb, needle if "|" in needle else re.escape(needle), needle)

    def test_casebook_cases_have_the_four_parts_that_make_them_usable(self):
        cases = re.split(r"\n### ", read("FAILURE-CASEBOOK.md"))[1:]
        self.assertGreaterEqual(len(cases), 18)
        for c in cases:
            title = c.splitlines()[0]
            self.assertRegex(c, r"\*\*(Was|Was, case 1):\*\*", title)
            self.assertRegex(c, r"\*\*(Fix|Rule):\*\*", title)


class EvalAnswerableTest(unittest.TestCase):
    """A question whose facts are nowhere in the pack scores the pack, not the model."""
    NEW = ("dem-overrides-work-crs", "getdata-keeps-old-dem", "batch-ok-but-failed",
           "empty-collection-not-error", "no-invented-flags")

    def test_new_questions_are_answerable_from_the_documents_they_name(self):
        with open(os.path.join(HEIM, "eval", "questions.json"), encoding="utf-8") as f:
            qs = {q["id"]: q for q in json.load(f)["questions"]}
        files = [f for f in os.listdir(KN) if f.endswith(".md")]
        for qid in self.NEW:
            q = qs[qid]
            docs = [f for f in files if re.search(q["doc"], f)]
            self.assertTrue(docs, "%s: doc pattern %r matches no knowledge page" % (qid, q["doc"]))
            text = "\n".join(read(f) for f in docs)
            for fact in q["facts"]:
                self.assertRegex(text, fact, "%s: fact %r is not in %s" % (qid, fact, docs))

    def test_question_ids_are_unique(self):
        with open(os.path.join(HEIM, "eval", "questions.json"), encoding="utf-8") as f:
            ids = [q["id"] for q in json.load(f)["questions"]]
        self.assertEqual(len(ids), len(set(ids)))



def load_indexer():
    spec = importlib.util.spec_from_file_location("rag_index_kn_test", os.path.join(HEIM, "tools", "rag_index.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EveryPageIsIndexableTest(unittest.TestCase):
    """A page the indexer skips is a page Heim never reads, and the skip is one line in an
    install log. The first DamSafety algorithm dump was a single 790 KB file against a 256 KB
    limit: it would have been committed, installed and silently left out."""

    @classmethod
    def setUpClass(cls):
        cls.rag = load_indexer()
        cls.files = []
        for dp, dns, fns in os.walk(KN):
            dns[:] = [d for d in dns if d not in cls.rag.SKIP_DIRS]
            for fn in fns:
                if cls.rag.file_filter(fn):
                    cls.files.append(os.path.join(dp, fn))

    def test_no_page_is_over_the_indexers_size_limit(self):
        self.assertGreater(len(self.files), 20)
        too_big = [(os.path.relpath(f, KN), os.path.getsize(f)) for f in self.files
                   if os.path.getsize(f) > self.rag.MAX_TEXT_BYTES]
        self.assertEqual(too_big, [], "rag_index.py skips these (over MAX_TEXT_BYTES): split them")

    def test_the_indexer_really_reads_every_page(self):
        for f in self.files:
            rel = os.path.relpath(f, KN)
            self.assertTrue(self.rag.read_text(f, rel), "rag_index.read_text returned nothing for " + rel)


class AlgorithmHelpTest(unittest.TestCase):
    """ALGORITHM-HELP.md is the list of DamSafety ids; algorithm-help/ holds one page each."""

    @classmethod
    def setUpClass(cls):
        cls.index = read("ALGORITHM-HELP.md")
        cls.ids = re.findall(r"(?m)^\| `([a-z]+:[A-Za-z0-9_]+)` \|", cls.index)
        cls.dir = os.path.join(KN, "algorithm-help")

    def test_every_listed_id_has_its_page_and_every_page_is_listed(self):
        self.assertGreater(len(self.ids), 60)
        self.assertEqual(len(self.ids), len(set(self.ids)))
        want = sorted(i.replace(":", ".") + ".md" for i in self.ids)
        self.assertEqual(sorted(os.listdir(self.dir)), want)
        m = re.search(r"Algorithms: (\d+)\.", self.index)
        self.assertEqual(int(m.group(1)), len(self.ids))

    def test_each_page_is_that_tools_help(self):
        for i in self.ids:
            with open(os.path.join(self.dir, i.replace(":", ".") + ".md"), encoding="utf-8") as f:
                page = f.read()
            self.assertTrue(page.startswith("# %s\n" % i), i)
            self.assertIn("(%s)" % i, page, "the help text in %s is not for that id" % i)
            self.assertIn("Arguments", page, i)
            self.assertNotIn("(no help for", page, i)

    def test_all_six_providers_and_the_hidden_tools_are_there(self):
        self.assertEqual(sorted({i.split(":")[0] for i in self.ids}),
                         ["ndbreach", "nddam", "ndfind", "ndhazard", "ndlite", "ndpmp"])
        # hidden from `qgis_process list`, so only a dump that probes for them has them
        for hidden in ("nddam:runchain", "ndbreach:selftest", "nddam:selftest"):
            self.assertIn(hidden, self.ids)

    def test_pages_do_not_depend_on_the_machine_that_made_them(self):
        pages = [self.index]
        for fn in os.listdir(self.dir):
            with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                pages.append(f.read())
        for page in pages:
            for needle in ("/home/", "/root/", "/Users/", "/tmp/", "realprof"):
                self.assertNotIn(needle, page)


if __name__ == "__main__":
    unittest.main()
