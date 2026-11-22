"""Checks on suite_install/ (the cross-platform install-all package): lock files well formed,
every pinned file https + sha256, the installers' plugin lists match the repos' plugin folders,
and the shell scripts parse. No network.

    python3 -m unittest -v tests.test_suite_install
"""
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SI = os.path.join(ROOT, "suite_install")
LOCKS = os.path.join(SI, "locks")
PLATFORMS = ("linux-64", "osx-arm64", "osx-64", "win-64")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def lines(path):
    with open(path, encoding="utf-8") as fh:
        return [l.split() for l in fh if l.strip() and not l.startswith("#")]


class TestLocks(unittest.TestCase):
    def test_every_platform_has_its_envs(self):
        for p in PLATFORMS:
            have = {f[:-5] for f in os.listdir(os.path.join(LOCKS, p)) if f.endswith(".lock")}
            want = {"ndqgis", "ndanuga", "ndvor"} | (set() if p == "win-64" else {"ndbuild"})
            self.assertEqual(have, want, p)

    def test_conda_locks_are_pinned_conda_forge_files(self):
        for p in PLATFORMS:
            for f in os.listdir(os.path.join(LOCKS, p)):
                names = set()
                for url, sha, md5 in lines(os.path.join(LOCKS, p, f)):
                    self.assertTrue(url.startswith("https://conda.anaconda.org/conda-forge/"), url)
                    self.assertIn(url.rsplit("/", 2)[-2], (p, "noarch"), url)
                    self.assertRegex(sha, HEX64, url)
                    self.assertRegex(md5, HEX32, url)
                    names.add(url.rsplit("/", 1)[-1].rsplit("-", 2)[0])
                if f == "ndqgis.lock":
                    self.assertTrue({"qgis", "numpy", "scipy", "draco"} <= names, p)
                if f == "ndanuga.lock":
                    self.assertTrue({"anuga", "gmsh", "python-gmsh", "netcdf4"} <= names, p)

    def test_qgis_334_numpy1_draco157(self):
        for p in PLATFORMS:
            urls = [u for u, _, _ in lines(os.path.join(LOCKS, p, "ndqgis.lock"))]
            self.assertTrue(any("/qgis-3.34." in u for u in urls), p)
            self.assertTrue(any("/numpy-1." in u for u in urls), p)
            self.assertTrue(any("/draco-1.5.7-" in u for u in urls), p)

    def test_extra_lock(self):
        rows = lines(os.path.join(LOCKS, "extra.lock"))
        for plat, kind, path, url, sha in rows:
            self.assertIn(plat, PLATFORMS)
            self.assertTrue(url.startswith("https://"), url)
            self.assertRegex(sha, HEX64, url)
            self.assertFalse(path.startswith("/") or ".." in path, path)
        for p in PLATFORMS:
            kinds = {k for pl, k, *_ in rows if pl == p}
            self.assertTrue({"miniforge", "ollama"} <= kinds, p)
            if p.startswith("osx"):
                self.assertIn("lisflood-src", kinds, p)


class TestScripts(unittest.TestCase):
    def test_plugin_lists_match_the_repo(self):
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        di = re.search(r'^DI_PLUGINS="([^"]+)"', sh, re.M).group(1).split()
        self.assertEqual(set(di), {d for d in os.listdir(ROOT) if d.startswith("damit_")
                                   and os.path.isfile(os.path.join(ROOT, d, "metadata.txt"))})
        self.assertEqual(di[:2], ["damit_core", "damit_catalog"])
        ds = re.search(r'^DS_PLUGINS="([^"]+)"', sh, re.M).group(1).split()
        self.assertEqual(ds[0], "DamSafety_Core")
        with open(os.path.join(SI, "install-all-windows.ps1"), encoding="utf-8") as fh:
            ps = fh.read()
        self.assertEqual(re.findall(r"'(damit_[a-z]+)'", re.search(r"\$DiPlugins = @\(([^)]*)\)", ps).group(1)), di)
        self.assertEqual(re.findall(r"'(DamSafety_[A-Za-z]+)'", re.search(r"\$DsPlugins = @\(([^)]*)\)", ps).group(1)), ds)

    def test_no_sudo_pip_or_pipe_to_shell(self):
        for f in ("install-all.sh", "download-all.sh", "install-all-windows.ps1", "download-all-windows.ps1"):
            with open(os.path.join(SI, f), encoding="utf-8") as fh:
                code = "\n".join(l for l in fh.read().splitlines() if not l.lstrip().startswith(("#", "echo", "    openSUSE", "    Debian")))
            self.assertNotRegex(code, r"(^|[;&|]\s*)sudo\s", f)
            self.assertNotRegex(code, r"\bpip3?\s+install\b", f)
            self.assertNotRegex(code, r"curl[^\n|]*\|\s*(ba|z)?sh\b", f)

    def test_mac_installer_never_downloads(self):
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        self.assertIn('[ "$OS" = Darwin ] && OFFLINE_ONLY=1', sh)
        self.assertNotIn("curl ", sh)

    def test_envs_made_and_used_by_path(self):
        """Made by name, mamba 2 puts an env under $MAMBA_ROOT_PREFIX (~/micromamba/envs on a Mac
        that once had micromamba), where the launchers, the ANUGA setting and conda activate never
        look. So every env is created and run by path, in <conda base>/envs."""
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        self.assertNotRegex(sh, r'"\$MAMBA" (create|run)[^\n]* -n ')
        self.assertIn('"$MAMBA" create -y --offline -p "$(env_prefix "$name")"', sh)
        self.assertNotIn("conda activate ndqgis", sh)
        with open(os.path.join(SI, "install-all-windows.ps1"), encoding="utf-8") as fh:
            ps = fh.read()
        self.assertNotRegex(ps, r"\$Mamba (create|run)[^\n]* -n ")
        self.assertNotIn("activate ndqgis", ps)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_make_env_reuses_a_locked_env_found_elsewhere(self):
        """make_env searches first: an env of that name elsewhere (here a mamba root) that has every
        locked package is linked in and used; one that differs from the lock is left alone."""
        import tempfile
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        funcs = sh[sh.index("env_prefix() {"):sh.index("# ----", sh.index("env_prefix() {"))]
        make = re.search(r"^make_env\(\) \{.*?^\}", sh, re.S | re.M).group(0)
        with tempfile.TemporaryDirectory() as t:
            home = os.path.join(t, "home dir")
            lock = os.path.join(t, "locks", "osx-arm64", "ndqgis.lock")
            os.makedirs(os.path.dirname(lock))
            with open(lock, "w") as fh:
                fh.write("# c\nhttps://x/osx-arm64/a-1-0.conda s m\nhttps://x/noarch/b-2-py_0.tar.bz2 s m\n")
            good = os.path.join(home, "micromamba", "envs", "ndqgis", "conda-meta")
            part = os.path.join(home, "miniconda3", "envs", "ndanuga", "conda-meta")
            for d in (good, part, os.path.join(home, "miniforge3")):
                os.makedirs(d)
            for f in ("a-1-0.json", "b-2-py_0.json"):
                open(os.path.join(good, f), "w").close()
            open(os.path.join(part, "a-1-0.json"), "w").close()
            # every locked package recorded, but its own check fails (files replaced): not used
            bad = os.path.join(home, "miniconda3", "envs", "ndvor", "conda-meta")
            os.makedirs(bad)
            for f in ("a-1-0.json", "b-2-py_0.json"):
                open(os.path.join(bad, f), "w").close()
            # a stand-in mamba: `run -p <prefix> ...` fails for the ndvor env only
            mamba = os.path.join(t, "mamba")
            with open(mamba, "w") as fh:
                fh.write('#!/bin/sh\ncase "$3" in *ndvor*) exit 1 ;; esac\nexit 0\n')
            os.chmod(mamba, 0o755)
            script = ("set -eo pipefail\nok(){ echo \"OK $*\"; }; warn(){ echo \"WARN $*\"; }; say(){ :; }\n"
                      "pkg_path(){ echo /none; }; sha(){ echo x; }\n" + funcs + make +
                      "\nmake_env ndqgis ndqgis\nmake_env ndanuga ndqgis || echo built-fresh\n"
                      "make_env ndvor ndqgis || echo vor-fresh\n")
            env = dict(os.environ, HOME=home, CONDA_BASE=os.path.join(home, "miniforge3"), HERE=t,
                       P="osx-arm64", MAMBA_ROOT_PREFIX=os.path.join(home, "micromamba"), MAMBA=mamba)
            out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True).stdout
            link = os.path.join(home, "miniforge3", "envs", "ndqgis")
            self.assertTrue(os.path.islink(link), out)
            self.assertEqual(os.readlink(link), os.path.dirname(good))
            self.assertIn("not the locked build (1 of 2", out)
            self.assertIn("built-fresh", out)
            self.assertFalse(os.path.exists(os.path.join(home, "miniforge3", "envs", "ndanuga")))
            self.assertTrue(os.path.isdir(part))
            self.assertIn("its check fails", out)
            self.assertIn("vor-fresh", out)
            self.assertFalse(os.path.lexists(os.path.join(home, "miniforge3", "envs", "ndvor")))

    @staticmethod
    def _func(sh, name):
        return re.search(r"^" + name + r"\(\) \{.*?^\}", sh, re.S | re.M).group(0)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_crest_launcher_points_qgis_process_at_the_profile(self):
        """qgis_process 3.34 has no --profile and always loads profile "default", so a Crest desk's
        Report step saw neither damsafety nor damit. The launcher line points QGIS_CUSTOM_CONFIG_PATH
        at <prefix>/qgis-process/<profile>, whose profiles/default links to the real profile. With
        qgis_process installed, check that it really lists that profile's plugin."""
        import tempfile
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        func = self._func(sh, "qgis_process_profile")
        with tempfile.TemporaryDirectory() as t:
            prefix = os.path.join(t, "dam suite")
            prof = os.path.join(t, "Application Support", "profiles", "damsafety")
            plug = os.path.join(prof, "python", "plugins", "probe_ds")
            os.makedirs(plug); os.makedirs(os.path.join(prof, "QGIS"))
            with open(os.path.join(plug, "metadata.txt"), "w") as fh:
                fh.write("[general]\nname=probe_ds\nqgisMinimumVersion=3.0\ndescription=x\nversion=1\n"
                         "author=x\nemail=x@x\nhasProcessingProvider=yes\n")
            with open(os.path.join(plug, "__init__.py"), "w") as fh:
                fh.write("def classFactory(iface):\n    class P:\n        def initGui(self): pass\n"
                         "        def initProcessing(self): pass\n        def unload(self): pass\n    return P()\n")
            with open(os.path.join(prof, "QGIS", "QGIS3.ini"), "w") as fh:
                fh.write("[PythonPlugins]\nprobe_ds=true\n")
            env = dict(os.environ, PREFIX=prefix)
            line = subprocess.run(["bash", "-c", func + '\nqgis_process_profile damsafety "$1"\n'
                                   'qgis_process_profile damit "$1/nothing-here"', "x", prof],
                                  env=env, capture_output=True, text=True, check=True).stdout
            root = os.path.join(prefix, "qgis-process", "damsafety")
            self.assertEqual(line.strip().splitlines(), ["export QGIS_CUSTOM_CONFIG_PATH=" +
                                                         root.replace(" ", "\\ ")])
            link = os.path.join(root, "profiles", "default")
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.readlink(link), prof)
            self.assertFalse(os.path.exists(os.path.join(prefix, "qgis-process", "damit")))
            # run again: the link is replaced, not nested inside the profile
            subprocess.run(["bash", "-c", func + '\nqgis_process_profile damsafety "$1" >/dev/null', "x", prof],
                           env=env, check=True)
            self.assertFalse(os.path.lexists(os.path.join(prof, "damsafety")))
            # a real folder in the link's place (qgis_process makes an empty profile when the link
            # is missing) is moved aside, not kept as the profile qgis_process loads (review 2026-11-16)
            os.remove(link); os.makedirs(os.path.join(link, "processing"))
            again = subprocess.run(["bash", "-c", func + '\nqgis_process_profile damsafety "$1"', "x", prof],
                                   env=env, capture_output=True, text=True, check=True).stdout
            self.assertEqual(again, line)
            self.assertEqual(os.readlink(link), prof)
            kept = [n for n in os.listdir(os.path.dirname(link)) if n.startswith("default.bak-")]
            self.assertEqual(len(kept), 1)
            self.assertTrue(os.path.isdir(os.path.join(os.path.dirname(link), kept[0], "processing")))
            if shutil.which("qgis_process"):
                out = subprocess.run(["bash", "-c", line + "\nqgis_process plugins"], cwd=t,
                                     env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                     capture_output=True, text=True, timeout=300).stdout
                self.assertIn("probe_ds", out)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_one_desk_with_a_launcher_per_profile(self):
        """DamIT Desk (Nick, 2026-11-22: the one desk) replaces DamIT Crest and the North Dakota Crest desk. Its block
        installs damit_desk/, writes qgis-process-damit.sh and -damsafety.sh outside --sandbox too, and one launcher
        per desk profile that names the profile and both qgis_process launchers but sets no QGIS_CUSTOM_CONFIG_PATH
        itself (one desk process switches plugin sets per job). The old desks' launchers are removed."""
        import tempfile
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        self.assertNotIn('"$HERE/nd_crest', sh)
        self.assertNotIn('"$HERE/damit_crest', sh)
        block = sh[sh.index('DESK_SRC="$HERE/damit_desk"'):sh.index('if [ -n "$SANDBOX" ]; then\n  say "Sandbox')]
        funcs = self._func(sh, "qgis_process_profile") + "\n" + self._func(sh, "mk_qgis_process")
        with tempfile.TemporaryDirectory() as t:
            here, prefix = os.path.join(t, "pkg"), os.path.join(t, "dam suite")
            os.makedirs(os.path.join(here, "damit_desk", "app", "desktop"))
            os.makedirs(os.path.join(here, "damit_desk", "damit_catalog"))
            open(os.path.join(here, "damit_desk", "app", "desktop", "run.py"), "w").close()
            with open(os.path.join(here, "damit_desk", "damit_catalog", "handoff.py"), "w") as fh:
                fh.write("# desk copy\n")
            os.makedirs(prefix)
            for old in ("open-damit-crest.sh", "open-nd-crest.sh"):
                open(os.path.join(prefix, old), "w").close()
            os.makedirs(os.path.join(prefix, "nd_crest"))
            profiles = os.path.join(t, "profiles")
            for p in ("damsafety", "damit"):
                os.makedirs(os.path.join(profiles, p, "python", "plugins"))
            env = dict(os.environ, HERE=here, PREFIX=prefix, DO_CREST="1", DO_DS="1", DO_DI="1", OS="Linux",
                       STAMP="test", CONDA_BASE=os.path.join(t, "conda"), QP=os.path.join(t, "env"),
                       DS_PROFILE="damsafety", DI_PROFILE="damit", DS_DIR=os.path.join(profiles, "damsafety"),
                       DI_DIR=os.path.join(profiles, "damit"), ANUGA_PY="", LISFLOOD_EXE="")
            script = ("say() { :; }; ok() { echo \"OK $*\"; }; warn() { echo \"WARN $*\"; }\n" + funcs + "\n" + block)
            out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True).stdout
            self.assertIn("OK DamIT Desk", out)
            self.assertIn("nd_crest is the retired desk", out)
            for old in ("open-damit-crest.sh", "open-nd-crest.sh"):
                self.assertFalse(os.path.exists(os.path.join(prefix, old)))
            self.assertTrue(os.path.isfile(os.path.join(prefix, "damit_desk", "app", "desktop", "run.py")))
            for name in ("qgis-process-damit.sh", "qgis-process-damsafety.sh"):
                with open(os.path.join(prefix, name)) as fh:
                    self.assertIn("QGIS_CUSTOM_CONFIG_PATH=", fh.read())
            for name, prof in (("open-damit-desk.sh", "us"), ("open-damit-desk-nd.sh", "nd")):
                with open(os.path.join(prefix, name)) as fh:
                    text = fh.read()
                self.assertIn("export DAMIT_DESK_PROFILE=" + prof, text)
                self.assertIn("DAMIT_ND_QGIS_PROCESS=", text)
                self.assertIn("qgis-process-damsafety.sh", text)
                self.assertIn("DAMSUITE_PREFIX=", text)
                self.assertNotIn("QGIS_CUSTOM_CONFIG_PATH", text)
                self.assertIn("damit_desk/app/desktop", text)
        with open(os.path.join(SI, "install-all-windows.ps1"), encoding="utf-8") as fh:
            ps = fh.read()
        desk = ps[ps.index("$DeskSrc ="):ps.index("Remove-Item $SettingsPy")]
        for want in ("open-damit-desk.cmd", "open-damit-desk-nd.cmd", "DAMIT_DESK_PROFILE=$deskP",
                     "DAMIT_ND_QGIS_PROCESS=$Prefix\\qgis-process-damsafety.cmd", "qgis-process-$($s[1]).cmd"):
            self.assertIn(want, desk)
        self.assertNotIn("nd_crest\\crest-desktop", ps)
        # PowerShell variables ignore case: a loop over $p would overwrite the platform $P used later
        self.assertNotRegex(desk, r"foreach \(\$p in")

    @unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "no bash/python3")
    def test_pack_builder_launcher(self):
        """build-offline-pack.sh runs DamSafety_Data.pack_build from the profile's plugins folder,
        then adopts the folder as the suite data folder (not after --list / --verify)."""
        import tempfile
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        func = self._func(sh, "mk_pack_builder")
        with tempfile.TemporaryDirectory() as t:
            base = os.path.join(t, "conda base"); os.makedirs(os.path.join(base, "etc", "profile.d"))
            with open(os.path.join(base, "etc", "profile.d", "conda.sh"), "w") as fh:
                fh.write("conda() { :; }\n")
            plugins = os.path.join(t, "profiles", "damsafety", "python", "plugins")
            os.makedirs(os.path.join(plugins, "DamSafety_Data"))
            os.makedirs(os.path.join(plugins, "DamSafety_Core", "damsuite"))
            for d in ("DamSafety_Data", "DamSafety_Core", "DamSafety_Core/damsuite"):
                open(os.path.join(plugins, d, "__init__.py"), "w").close()
            log = os.path.join(t, "log.txt")
            with open(os.path.join(plugins, "DamSafety_Data", "pack_build.py"), "w") as fh:
                fh.write("import sys\nopen(%r, 'a').write('build ' + ' '.join(sys.argv[1:]) + '\\n')\n" % log)
            with open(os.path.join(plugins, "DamSafety_Core", "damsuite", "suitedata.py"), "w") as fh:
                fh.write("_qsettings = None\ndef adopt_folder(p):\n"
                         "    open(%r, 'a').write('adopt ' + p + ' ' + str(_qsettings()) + '\\n')\n"
                         "    return {'folder': p}\n" % log)
            out = os.path.join(t, "pack.sh")
            env = dict(os.environ, CONDA_BASE=base, QP=os.path.join(t, "env"),
                       DS_DIR=os.path.dirname(os.path.dirname(plugins)), DS_PROFILE="damsafety",
                       STAMP="test", OS="Linux")
            subprocess.run(["bash", "-c", func + '\nmk_pack_builder "$1"', "x", out], env=env, check=True)
            home = os.path.join(t, "home")
            run = lambda *a: subprocess.run(["bash", out, *a], env=dict(os.environ, HOME=home),
                                            capture_output=True, text=True, check=True)
            run()
            run(os.path.join(t, "My Data"), "--bbox", "1,2,3,4")
            run("--list")
            # review 2026-11-16: a relative folder is taken from where the script was run (it was
            # resolved inside the QGIS plugins folder), --out is the folder that gets adopted, and
            # --help / -h never change the suite data folder.
            cwd = os.path.join(t, "here"); os.makedirs(cwd)
            subprocess.run(["bash", out, "Rel Pack"], env=dict(os.environ, HOME=home), cwd=cwd,
                           capture_output=True, text=True, check=True)
            run("--bbox", "1,2,3,4", "--out", os.path.join(t, "Ext"))
            run("--out=" + os.path.join(t, "Ext2"))
            run("~/Tilde Pack")
            run("--help")
            run("-h")
            with open(log) as fh:
                got = fh.read().splitlines()
            data = os.path.join(home, "ND_Suite_Data")
            rel, ext, ext2 = os.path.join(cwd, "Rel Pack"), os.path.join(t, "Ext"), os.path.join(t, "Ext2")
            tilde = os.path.join(home, "Tilde Pack")
            self.assertEqual(got, [
                "build --out " + data, "adopt " + data + " None",
                "build --out " + os.path.join(t, "My Data") + " --bbox 1,2,3,4",
                "adopt " + os.path.join(t, "My Data") + " None",
                "build --out " + data + " --list",
                "build --out " + rel, "adopt " + rel + " None",
                "build --out " + ext + " --bbox 1,2,3,4", "adopt " + ext + " None",
                "build --out " + ext2, "adopt " + ext2 + " None",
                "build --out " + tilde, "adopt " + tilde + " None",
                "build --out " + data + " --help",
                "build --out " + data + " -h"])

    def test_windows_pack_builder_and_junction(self):
        """review 2026-11-16: build-offline-pack.cmd takes the folder (made absolute, a trailing
        backslash kept as a folder) before it moves into the plugins folder with pushd (a UNC
        profile path works there), and the qgis_process junction is checked: a real folder in its
        place is renamed aside, and a junction that was not made sets no QGIS_CUSTOM_CONFIG_PATH."""
        with open(os.path.join(SI, "install-all-windows.ps1"), encoding="utf-8") as fh:
            ps = fh.read()
        mk = ps[ps.index("function Make-PackBuilder"):ps.index("Say 'Settings and launchers'")]
        self.assertLess(mk.index('set "OUT=%~f1"'), mk.index("pushd"))
        self.assertIn('if "%OUT:~-1%"=="\\" set "OUT=%OUT%."', mk)
        self.assertNotIn("cd /d", mk)
        qp = ps[ps.index("function QgisProcessProfile"):ps.index("$DeskSrc =")]
        self.assertIn("ReparsePoint", qp)
        self.assertIn("default.bak-", qp)
        self.assertIn('return "rem QGIS_CUSTOM_CONFIG_PATH not set', qp)

    def test_settings_written_to_the_file_qgis_reads(self):
        """QGIS keeps a profile's settings in <profile>/qgis.org/QGIS3.ini on macOS (Qt uses the
        organisation domain there) and in <profile>/QGIS/QGIS3.ini elsewhere. install-all wrote
        QGIS/QGIS3.ini on a Mac too, so the engine paths and enabled plugins it set were never read
        (Nick's MacBook, 2026-11-16: QgsSettings().fileName() was .../damsafety/qgis.org/QGIS3.ini)."""
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        darwin = sh[sh.index('QINI="QGIS/QGIS3.ini"'):sh.index('PROFILES="$HOME/.local/share/QGIS')]
        self.assertIn('if [ "$OS" = Darwin ]; then\n  QINI="qgis.org/QGIS3.ini"', darwin)
        self.assertNotIn("/QGIS/QGIS3.ini\" ", sh)
        self.assertEqual(len(re.findall(r'write_settings "\$D[SI]_DIR/\$QINI"', sh)), 2)

    @unittest.skipUnless(shutil.which("qgis_process") and os.uname().sysname == "Linux", "Linux qgis_process")
    def test_linux_qgis_reads_QGIS_slash_QGIS3_ini(self):
        """The Linux half of the rule above, asked of the real QGIS: a plugin enabled in
        profiles/default/QGIS/QGIS3.ini is loaded; enabled only in qgis.org/QGIS3.ini it is not."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            prof = os.path.join(t, "profiles", "default")
            plug = os.path.join(prof, "python", "plugins", "probe_ini")
            os.makedirs(plug)
            with open(os.path.join(plug, "metadata.txt"), "w") as fh:
                fh.write("[general]\nname=probe_ini\nqgisMinimumVersion=3.0\ndescription=x\nversion=1\n"
                         "author=x\nemail=x@x\nhasProcessingProvider=yes\n")
            with open(os.path.join(plug, "__init__.py"), "w") as fh:
                fh.write("def classFactory(iface):\n    class P:\n        def initGui(self): pass\n"
                         "        def initProcessing(self): pass\n        def unload(self): pass\n    return P()\n")
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QGIS_CUSTOM_CONFIG_PATH=t)

            def loaded(folder):
                d = os.path.join(prof, folder)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "QGIS3.ini"), "w") as fh:
                    fh.write("[PythonPlugins]\nprobe_ini=true\n")
                try:
                    out = subprocess.run(["qgis_process", "plugins"], cwd=t, env=env,
                                         capture_output=True, text=True, timeout=300).stdout
                finally:
                    os.remove(os.path.join(d, "QGIS3.ini"))
                line = [l for l in out.splitlines() if "probe_ini" in l]
                self.assertEqual(len(line), 1, out)
                return line[0].lstrip().startswith("*")
            self.assertTrue(loaded("QGIS"))
            self.assertFalse(loaded("qgis.org"))

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_missing_offline_files_are_named(self):
        """2026-11-18 (Nick's osx-64 install): the installer said '1 file(s) are missing' without
        naming it; it was damit_ai/offline/ollama/Ollama-darwin.zip, outside offline/. The
        installer's offline check is run here on a fake package folder."""
        import tempfile
        with open(os.path.join(SI, "install-all.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        a = sh.index("pkg_path() {")
        b = sh.index("\n  fi\n", sh.index('if [ "$OFFLINE_ONLY" = 1 ]; then', a)) + len("\n  fi\n")
        block = sh[a:b] + "fi\n"
        with tempfile.TemporaryDirectory() as tmp:
            here = os.path.join(tmp, "pkg")
            os.makedirs(os.path.join(here, "locks", "osx-64"))
            with open(os.path.join(here, "locks", "osx-64", "ndqgis.lock"), "w") as fh:
                for i in range(25):
                    fh.write("https://conda.anaconda.org/conda-forge/osx-64/p{}.conda a b\n".format(i))
            with open(os.path.join(here, "locks", "extra.lock"), "w") as fh:
                fh.write("osx-64 ollama damit_ai/offline/ollama/Ollama-darwin.zip x\n"
                         "osx-64 ollama-pull models/m y\nosx-arm64 miniforge offline/a.sh z\n")
            with open(os.path.join(tmp, "block.sh"), "w") as fh:
                fh.write(block)
            run = os.path.join(tmp, "run.sh")
            with open(run, "w") as fh:
                fh.write('set -eo pipefail\nsay() { printf "==> %s\\n" "$*"; }\n'
                         'die() { printf "ERROR: %s\\n" "$*" >&2; exit 1; }\n'
                         'HERE="$1"; P=osx-64; ROLES=ndqgis; OS="$2"; OFFLINE_ONLY=0\n'
                         'CONDA_PKGS="$HERE/offline/conda/$P"\n. "$(dirname "$0")/block.sh"\n'
                         'echo "REACHED $MISS"\n')

            def go(os_name):
                return subprocess.run(["bash", run, here, os_name], capture_output=True, text=True)

            r = go("Darwin")                    # everything missing: 25 + Ollama, 20 listed
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("Missing (26):", r.stdout)
            self.assertIn("  offline/conda/osx-64/osx-64/p0.conda", r.stdout)
            self.assertIn("... and 6 more", r.stdout)
            self.assertIn("26 file(s) are missing (listed above)", r.stderr)
            self.assertIn("damit_ai/offline/", r.stderr)
            d = os.path.join(here, "offline", "conda", "osx-64", "osx-64")
            os.makedirs(d)
            for i in range(25):
                open(os.path.join(d, "p{}.conda".format(i)), "w").close()
            r = go("Darwin")                    # Nick's case: only the Ollama installer
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("Missing (1):\n  damit_ai/offline/ollama/Ollama-darwin.zip", r.stdout)
            os.makedirs(os.path.join(here, "damit_ai", "offline", "ollama"))
            open(os.path.join(here, "damit_ai", "offline", "ollama", "Ollama-darwin.zip"), "w").close()
            r = go("Darwin")                    # nothing missing: no list, carries on
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "REACHED 0")
            os.remove(os.path.join(d, "p3.conda"))
            r = go("Linux")                     # Linux lists it, then fetches (carries on)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("  offline/conda/osx-64/osx-64/p3.conda", r.stdout)
            self.assertIn("REACHED 1", r.stdout)

    def test_bash_scripts_parse(self):
        for f in ("install-all.sh", "download-all.sh", "tools/make_package.sh"):
            subprocess.run(["bash", "-n", os.path.join(SI, f)], check=True)
        subprocess.run(["bash", "-n", os.path.join(ROOT, "damit_ai", "install-local-ai-linux.sh")], check=True)


AI = os.path.join(ROOT, "damit_ai")


def slurp(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


@unittest.skipUnless(shutil.which("bash"), "no bash")
class TestSandbox(unittest.TestCase):
    """--sandbox DIR (install-all.sh), --prefix=DIR (install-local-ai-linux.sh) and their Windows
    twins put everything in one folder: nothing is written outside it (install test 2026-11-19)."""

    def run_installer(self, *args, home):
        env = {"HOME": home, "PATH": "/usr/bin:/bin", "LANG": "C"}
        return subprocess.run(["bash", os.path.join(SI, "install-all.sh"), *args],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_qgis_profiles_path_uses_qgis_own_layout(self):
        """QGIS 3.34 keeps profiles in <path>/profiles for --profiles-path <path> and for
        QGIS_CUSTOM_CONFIG_PATH (QgsUserProfileManager::resolveProfilesFolder). The installers
        wrote <path>/QGIS3/profiles, so QGIS opened from the launchers made an empty profile in
        <path>/profiles and loaded none of the plugins (seen on the box 2026-11-19)."""
        sh = slurp(SI, "install-all.sh")
        self.assertIn('PROFILES="$QGIS_PROFILES_PATH/profiles"; PROFILES_ARG=(--profiles-path "$QGIS_PROFILES_PATH")', sh)
        self.assertNotIn('$QGIS_PROFILES_PATH/QGIS3/profiles', sh)
        ps = slurp(SI, "install-all-windows.ps1")
        self.assertIn("$Profiles = Join-Path $QgisProfilesPath 'profiles'", ps)
        self.assertNotIn("Join-Path $QgisProfilesPath 'QGIS3\\profiles'", ps)

    def test_check_in_a_sandbox_reports_its_paths_and_writes_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            home = os.path.join(t, "home"); os.makedirs(home)
            sbx = os.path.join(t, "my sandbox")
            r = self.run_installer("--check", "--sandbox", sbx, home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("QGIS profiles: %s/qgis_profile/profiles" % sbx, r.stdout)
            self.assertIn("sandbox: %s" % sbx, r.stdout)
            self.assertIn("sandbox port 11435", r.stdout)
            self.assertEqual(os.listdir(home), [], "nothing may be written in the home folder")

    def test_sandbox_refuses_the_options_that_place_things_one_by_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            for extra in (["--prefix", t], ["--qgis-profiles-path", t], ["--root", t]):
                r = self.run_installer("--check", "--sandbox", os.path.join(t, "s"), *extra, home=t)
                self.assertEqual(r.returncode, 2, extra)
                self.assertIn("cannot be combined with", r.stderr)
            r = self.run_installer("--check", "--sandbox", t, "--ollama-port", "x1", home=t)
            self.assertEqual(r.returncode, 2)
            r = self.run_installer("--check", "--anuga-env", t, home=t)
            self.assertEqual(r.returncode, 2)
            self.assertIn("only used with --qgis-env", r.stderr)
            r = self.run_installer("--check", "--sandbox", t, home=t)
            self.assertEqual(r.returncode, 2, "the home folder itself is not a sandbox")

    def test_without_sandbox_the_defaults_are_unchanged(self):
        """No --sandbox: the same profiles folder, suite folder and conda search as before."""
        sh = slurp(SI, "install-all.sh")
        self.assertIn('PREFIX="${DAMSUITE_PREFIX:-$HOME/dam-suite}"', sh)
        self.assertIn('PROFILES="$HOME/.local/share/QGIS/QGIS3/profiles"', sh)
        self.assertIn('PROFILES="$HOME/Library/Application Support/QGIS/QGIS3/profiles"', sh)
        self.assertIn('SBX_ENV=()', sh)
        self.assertIn('[ -z "$SANDBOX" ] || AIF+=("--prefix=$SANDBOX" "--ollama-port=$OLLAMA_PORT")', sh)

    def ai_step5(self, sandbox, rc, home):
        text = slurp(AI, "install-local-ai-linux.sh")
        step = text[text.index('say "Step 5 '):text.index('say "Done"')]
        code = ('set -euo pipefail\nsay(){ :; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }\n'
                'RC="%s"; LOCAL_AI="%s/local-ai"; MODELS_DIR="$LOCAL_AI/models"; NUM_CTX=8192\n'
                'VOR_DIR="$LOCAL_AI/vor"; RHOME="%s/Vor"; WATCH_MODEL=qwen3:4b; DO_HEIM=1; DO_VOR=1\n'
                'SANDBOX="%s"; OLLAMA_PORT=11435; OLLAMA=/x/ollama\n' % (rc, sandbox, sandbox, sandbox)) + step
        r = subprocess.run(["bash", "-c", code], env={"HOME": home, "PATH": "/usr/bin:/bin"},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return r.stdout

    def test_ai_sandbox_writes_env_sh_and_never_the_rc_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            home = os.path.join(t, "home"); os.makedirs(home)
            bashrc = os.path.join(home, ".bashrc")
            with open(bashrc, "w") as fh:
                fh.write("export EDITOR=vim\n")
            sbx = os.path.join(t, "sbx"); os.makedirs(os.path.join(sbx, "local-ai"))
            env_sh = os.path.join(sbx, "local-ai", "env.sh")
            for _ in range(2):              # a second run rewrites the file, it does not append
                self.ai_step5(sbx, env_sh, home)
            self.assertEqual(slurp(bashrc), "export EDITOR=vim\n")
            self.assertEqual(sorted(os.listdir(home)), [".bashrc"])
            e = slurp(env_sh)
            self.assertEqual(e.count("# >>> dam local AI (heim + vor) >>>"), 1)
            for needle in ('export OLLAMA_HOST="127.0.0.1:11435"', 'export OLLAMA_URL="http://127.0.0.1:11435"',
                           'HEIM_DB="%s/local-ai/knowledge.db"' % sbx, 'export VOR_HOME="%s/Vor"' % sbx,
                           "CONDA_REGISTER_ENVS=false", "dam-ollama-serve()", "alias heim-chat="):
                self.assertIn(needle, e)
            r = subprocess.run(["bash", "-n", env_sh], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_ai_installer_sandbox_keeps_out_of_home(self):
        t = slurp(AI, "install-local-ai-linux.sh")
        for needle in ('RHOME="$SANDBOX/Vor"; RC="$LOCAL_AI/env.sh"', 'OLLAMA_PORT="${OLLAMA_PORT:-11435}"',
                       '[[ -z "$SANDBOX" ]] || SERVE_ENV+=(HOME="$LOCAL_AI")',
                       'conda_sb create -y -p "$envpath"', 'if [[ -z "${SANDBOX:-}" && -z "${VOR_HOME:-}"',
                       "something else already answers on"):
            self.assertIn(needle, t)
        ps = slurp(AI, "install-local-ai-windows.ps1")
        self.assertIn("if (-not $Prefix) {      # -Prefix writes no user environment variables", ps)
        self.assertIn("$env:USERPROFILE = $LocalAI", ps)
        w = slurp(SI, "install-all-windows.ps1")
        self.assertIn("'/NoRegistry=1','/NoShortcuts=1'", w)
        self.assertIn("$NoShortcuts = $true", w)

    @unittest.skipUnless(shutil.which("pwsh"), "no pwsh")
    def test_powershell_scripts_parse(self):
        for f in (os.path.join(SI, "install-all-windows.ps1"), os.path.join(SI, "download-all-windows.ps1"),
                  os.path.join(AI, "install-local-ai-windows.ps1")):
            cmd = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);"
                   " if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }" % f)
            r = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + ": " + r.stdout + r.stderr)



FAKE_PACKAGER = """import os, sys, zipfile
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for name in os.environ.get("FAKE_PLUGINS", "").split():
    path = os.path.join(out, name + "_0_1_0.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name + "/metadata.txt", "[general]\\nversion=0.1.0\\n")
    print("  {} v0.1.0: 1 files, 1 KB -> {}".format(name, os.path.basename(path)))
"""


@unittest.skipUnless(shutil.which("bash"), "no bash")
@unittest.skipIf(os.name == "nt", "install-all.sh is the Linux/macOS installer")
class TestCheckoutInstall(unittest.TestCase):
    """Install test 2026-11-21: install-all.sh run from a git checkout of damit (no plugins/, no lisflood/)
    installed no plugin, warned "no zip for ..." ten times, and still ended "Done, with warnings" with exit 0.
    A fake checkout here: the installer must build the DamIT zips, or stop with a clear error and exit 1, before
    anything is installed."""

    def make_tree(self, t, packager=True):
        repo = os.path.join(t, "repo")
        os.makedirs(os.path.join(repo, "suite_install"))
        shutil.copy(os.path.join(SI, "install-all.sh"), os.path.join(repo, "suite_install"))
        os.makedirs(os.path.join(repo, "damit_core"))
        os.makedirs(os.path.join(repo, "scripts"))
        if packager:
            with open(os.path.join(repo, "scripts", "package_plugins.py"), "w") as fh:
                fh.write(FAKE_PACKAGER)
        env_dir = os.path.join(t, "qgisenv")
        os.makedirs(os.path.join(env_dir, "conda-meta"))
        home = os.path.join(t, "home")
        os.makedirs(home)
        return repo, env_dir, home

    def run_it(self, repo, env_dir, home, sbx, *extra, plugins=""):
        env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C", "FAKE_PLUGINS": plugins}
        return subprocess.run(["bash", os.path.join(repo, "suite_install", "install-all.sh"), "--sandbox", sbx,
                               "--qgis-env", env_dir, "--no-ai", "--offline", *extra],
                              env=env, capture_output=True, text=True, timeout=120)

    def test_damsafety_without_zips_stops_with_exit_1_and_says_no_damsafety(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            repo, env_dir, home = self.make_tree(t)
            r = self.run_it(repo, env_dir, home, os.path.join(t, "sb"))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            out = r.stdout + r.stderr   # the installer tees stderr into stdout
            self.assertIn("no DamSafety plugin zips", out)
            self.assertIn("--no-damsafety", out)
            self.assertIn("git checkout of damit", out)
            self.assertNotIn("Done", r.stdout)
            self.assertFalse(os.path.isdir(os.path.join(t, "sb", "qgis_profile")), "nothing installed")

    def test_a_checkout_builds_the_damit_zips(self):
        import tempfile
        names = "damit_core damit_catalog damit_setup damit_data damit_screener damit_runner damit_hazard damit_hazardlite damit_pmp damit_finder"
        with tempfile.TemporaryDirectory() as t:
            repo, env_dir, home = self.make_tree(t)
            sbx = os.path.join(t, "sb")
            r = self.run_it(repo, env_dir, home, sbx, "--no-damsafety", plugins=names)
            out = r.stdout + r.stderr
            self.assertIn("building the DamIT plugin zips from " + os.path.realpath(repo), out)
            built = sorted(os.listdir(os.path.join(sbx, "plugins-from-checkout", "damit")))
            self.assertEqual(len([b for b in built if b.endswith(".zip")]), 10, built)
            self.assertIn("    damit_core 0.1.0", r.stdout)
            self.assertNotIn("no DamIT plugin zips", out)
            # (the fake QGIS env stops it later, at "QGIS does not import"; that is not what is tested here)

    def test_no_zips_after_the_build_stops_with_exit_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            repo, env_dir, home = self.make_tree(t)
            r = self.run_it(repo, env_dir, home, os.path.join(t, "sb"), "--no-damsafety", plugins="")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            out = r.stdout + r.stderr
            self.assertIn("no DamIT plugin zips", out)
            self.assertIn("python3 scripts/package_plugins.py suite_install/plugins/damit", out)

    def test_a_missing_plugin_ends_in_an_error_not_done(self):
        sh = slurp(SI, "install-all.sh")
        self.assertIn('MISSING_PLUGINS="$MISSING_PLUGINS $p"', sh)
        a = sh.index('if [ -n "$MISSING_PLUGINS" ]; then')
        self.assertLess(a, sh.index('say "Done$('))
        self.assertIn('die "not installed:$MISSING_PLUGINS.', sh[a:a + 300])


class TestLisfloodMessages(unittest.TestCase):
    """Install test 2026-11-21: --qgis-env from a checkout said LISFLOOD-FP was skipped because "the shipped one did
    not pass its check"; a checkout ships none (tools/make_package.sh adds lisflood/), and nothing said so in the
    README. The real reason is named now, loudly, repeated in INSTALLED.txt, and --lisflood-exe is the way around."""

    def test_the_real_reason_is_named_and_the_old_wording_is_gone(self):
        sh = slurp(SI, "install-all.sh")
        self.assertNotIn("the shipped one did not pass its check", sh)
        self.assertIn("this folder ships no LISFLOOD-FP", sh)
        self.assertIn("a git checkout has none", sh)
        self.assertIn('[ -z "$LF_WHY" ] || echo "  NO LISFLOOD-FP: $LF_WHY"', sh)
        self.assertIn("--lisflood-exe) LF_EXE_ARG=", sh)
        readme = slurp(SI, "README.md")
        self.assertIn("--lisflood-exe", readme)
        self.assertIn("no LISFLOOD-FP binary", readme)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_lisflood_exe_is_checked_before_it_is_used(self):
        import tempfile
        sh = slurp(SI, "install-all.sh")
        lf_ok = next(l for l in sh.splitlines() if l.startswith("lf_ok() {"))
        with tempfile.TemporaryDirectory() as t:
            good = os.path.join(t, "lisflood")
            with open(good, "w") as fh:
                fh.write('#!/bin/sh\n# inittm_depth nd-breach-runner: SGC arrival depth\necho "LISFLOOD-FP 8.3.0"\n')
            os.chmod(good, 0o755)
            bad = os.path.join(t, "old")
            with open(bad, "w") as fh:
                fh.write('#!/bin/sh\n# inittm_depth\necho "LISFLOOD-FP 8.2"\n')
            os.chmod(bad, 0o755)
            code = 'LF_SGC_MARK="nd-breach-runner: SGC arrival depth"\n' + lf_ok + '\nlf_ok "$1" && echo OK || echo NO'
            self.assertEqual(subprocess.run(["bash", "-c", code, "x", good], capture_output=True, text=True).stdout.strip(), "OK")
            self.assertEqual(subprocess.run(["bash", "-c", code, "x", bad], capture_output=True, text=True).stdout.strip(), "NO")


class TestWindowsCheckoutInstall(unittest.TestCase):
    """The same checkout case in install-all-windows.ps1: a set with no zips stops before installing anything,
    and a plugin that is missing at the self-check ends in an error (exit 1), not "Done, with warnings"."""

    def test_missing_zips_stop_the_windows_installer(self):
        ps = slurp(SI, "install-all-windows.ps1")
        self.assertIn("function Assert-Zips", ps)
        self.assertIn("python scripts\\package_plugins.py suite_install\\plugins\\damit", ps)
        self.assertIn("-NoDamSafety", ps[ps.index("function Assert-Zips"):])
        self.assertIn("$MissingPlugins", ps)
        a = ps.index("if ($MissingPlugins.Count)")
        self.assertLess(a, ps.index("Say $(if ($Fail)"))


if __name__ == "__main__":
    unittest.main()
