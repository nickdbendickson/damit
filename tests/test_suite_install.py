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

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_bash_scripts_parse(self):
        for f in ("install-all.sh", "download-all.sh", "tools/make_package.sh"):
            subprocess.run(["bash", "-n", os.path.join(SI, f)], check=True)


if __name__ == "__main__":
    unittest.main()
