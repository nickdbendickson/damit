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

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_bash_scripts_parse(self):
        for f in ("install-all.sh", "download-all.sh", "tools/make_package.sh"):
            subprocess.run(["bash", "-n", os.path.join(SI, f)], check=True)


if __name__ == "__main__":
    unittest.main()
