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
        qp = ps[ps.index("function QgisProcessProfile"):ps.index("$CrestSrc =")]
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
    def test_bash_scripts_parse(self):
        for f in ("install-all.sh", "download-all.sh", "tools/make_package.sh"):
            subprocess.run(["bash", "-n", os.path.join(SI, f)], check=True)


if __name__ == "__main__":
    unittest.main()
