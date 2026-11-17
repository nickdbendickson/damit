"""Both personas carry their DOMAIN CONTEXT and HOW YOU ANSWER blocks, verbatim, in every installer.

The block is what tells a local model that `damit_run:rundam` is a Processing id and not a typo, that
ACER TM-11 is a publication and not an equation, and - the part that matters most - that it has no web
access and cannot check anything. It is kept in one file per AI and embedded in each installer, the
same way `persona_rules.txt` is, because the three installers write the Modelfile three different
ways and drift between them is invisible until someone asks the model a question on one platform.

Covers both AIs in one file: the Vor installers live beside the Heim ones, and this suite is the one
that runs without QGIS.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.abspath(os.path.join(HERE, ".."))
AI = os.path.abspath(os.path.join(HEIM, ".."))
VOR = os.path.join(AI, "vor")
sys.path.insert(0, HERE)
from strict import StrictCase, slurp  # noqa: E402

CROSS = (os.path.join(AI, "install-local-ai-linux.sh"),
         os.path.join(AI, "install-local-ai-windows.ps1"))
HEIM_INSTALLERS = CROSS + (os.path.join(HEIM, "setup-local-heim.sh"),)
VOR_INSTALLERS = CROSS + (os.path.join(VOR, "setup-vor.zsh"),)

HEIM_CONTEXT = os.path.join(HEIM, "prompts", "domain_context.txt")
VOR_CONTEXT = os.path.join(VOR, "prompts", "domain_context.txt")
HEIM_MANNER = os.path.join(HEIM, "prompts", "manner.txt")
VOR_MANNER = os.path.join(VOR, "prompts", "manner.txt")
BLOCKS = (HEIM_CONTEXT, VOR_CONTEXT, HEIM_MANNER, VOR_MANNER)


def context(path):
    return slurp(path).rstrip("\n")


def persona_system(path, lead):
    t = slurp(path)
    i = t.index(lead)
    return t[i:t.index('"""', i + len(lead))]


class TestTheBlocksAreSafeToEmbed(StrictCase):
    def test_no_character_that_the_installer_quoting_would_eat(self):
        """Mac/Linux write the Modelfile with an UNQUOTED heredoc and Windows with a @"..."@
        here-string: a $, a backtick or a backslash is expanded before Ollama ever sees it, and a
        triple quote ends the SYSTEM block early - which truncates the persona silently."""
        for path in BLOCKS:
            c = context(path)
            self.assertNotRegex(c, r'[$`\\]', os.path.basename(path))
            self.assertNotIn('"""', c, os.path.basename(path))
            self.assertNotIn('"@', c, os.path.basename(path))


class TestEveryInstallerCarriesTheBlock(StrictCase):
    def test_heim(self):
        for block in (HEIM_CONTEXT, HEIM_MANNER):
            c = context(block)
            for path in HEIM_INSTALLERS:
                self.assertIn(c, persona_system(path, 'SYSTEM """You are Heim-Lite'),
                              "%s in %s" % (os.path.basename(block), os.path.basename(path)))

    def test_vor(self):
        for block in (VOR_CONTEXT, VOR_MANNER):
            c = context(block)
            for path in VOR_INSTALLERS:
                self.assertIn(c, persona_system(path, 'SYSTEM """You are Vor,'),
                              "%s in %s" % (os.path.basename(block), os.path.basename(path)))


class TestTheBlocksSayWhatTheyMustSay(StrictCase):
    def test_both_state_that_there_is_no_web_access(self):
        for path in (HEIM_CONTEXT, VOR_CONTEXT):
            self.assertRegex(context(path), r"NO web access", os.path.basename(path))

    def test_both_state_that_the_material_stays_on_this_machine(self):
        for path in (HEIM_CONTEXT, VOR_CONTEXT):
            self.assertRegex(context(path), r"(?i)stays? on this machine", os.path.basename(path))

    def test_vor_is_told_to_say_unsure_rather_than_fill_the_gap(self):
        self.assertRegex(context(VOR_CONTEXT), r"say UNSURE")

    def test_heim_names_the_plugins_that_actually_exist(self):
        """The pre-rename block still named the archived ND repo's plugins (ND_Dam_Hazard_Helper,
        nd_breach_runner, nd_dam_screening, nd_data_updater). Naming a plugin folder that is not
        there is how a local model invents an algorithm id to go with it."""
        c = context(HEIM_CONTEXT)
        for folder in ("damit_core", "damit_screener", "damit_runner", "damit_hazard"):
            self.assertIn(folder, c)
            self.assertTrue(os.path.isdir(os.path.join(AI, "..", folder)), folder)
        for gone in ("ND_Dam_Hazard_Helper", "nd_breach_runner", "nd_dam_screening", "nd_data_updater"):
            self.assertNotIn(gone, c, gone)

    def test_no_block_describes_how_the_model_should_sound(self):
        """Both AIs have a manner, and it is made of behaviours: lead with the line number, give
        the quote before the explanation. None of it is adjectives. A persona told to be curious
        or engaging paraphrases, and Vor's whole job is copying a quote unchanged, so the
        character that belongs to these two lives in the banner line instead - which greets and
        never answers. Keep the SYSTEM blocks to vocabulary, constraints and behaviour."""
        for path in BLOCKS:
            self.assertNotRegex(context(path), r"(?i)\b(personality|curious|thoughtful|engaging|friendly|witty|tone|voice)\b",
                                os.path.basename(path))

    def test_each_manner_says_what_to_do_not_what_to_be(self):
        """Every line is an instruction with a verb, so it can be checked against an answer."""
        for path in (HEIM_MANNER, VOR_MANNER):
            lines = [ln[2:] for ln in context(path).splitlines() if ln.startswith("- ")]
            self.assertGreaterEqual(len(lines), 5, os.path.basename(path))
            for ln in lines:
                self.assertNotRegex(ln, r"(?i)^(you are|be )\b",
                                    "%s: %s" % (os.path.basename(path), ln))

    def test_the_character_lines_are_in_the_banner_and_not_in_any_persona(self):
        """The one line of flavour each AI has greets the user; it must never reach a Modelfile,
        because anything in the SYSTEM prompt steers the answer."""
        voice = {
            "Heim": "It watches and explains; the code sets the verdict.",
            "Vor": "Every sentence traces to a page, or it says it cannot.",
        }
        heim_sh = slurp(os.path.join(HEIM, "setup-local-heim.sh"))
        self.assertIn(voice["Heim"], heim_sh)
        self.assertIn(voice["Vor"], slurp(os.path.join(VOR, "vor.py")))
        for path, lead in ([(p, 'SYSTEM """You are Heim-Lite') for p in HEIM_INSTALLERS]
                           + [(p, 'SYSTEM """You are Vor,') for p in VOR_INSTALLERS]):
            system = persona_system(path, lead)
            for line in voice.values():
                self.assertNotIn(line, system, os.path.basename(path))


class TestTheVorBlockMatchesTheLibrary(StrictCase):
    def test_every_publication_it_names_is_in_the_source_catalog(self):
        """A term the catalog cannot supply a document for is a term the model will answer from
        memory and present as if the library had it."""
        catalog = slurp(os.path.join(VOR, "reference_sources.json"))
        flat = re.sub(r"[^a-z0-9]+", "", catalog.lower())
        for name in ("ACER TM-11", "FEMA 333", "FEMA P-946", "FEMA P-919", "TR-60", "TR-66",
                     "EM 1110-2-2300", "ER 1110-2-1156", "HMR 51", "Design of Small Dams"):
            self.assertIn(re.sub(r"[^a-z0-9]+", "", name.lower()), flat, name)
