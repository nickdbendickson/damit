#!/usr/bin/env python3
"""Solve the suite's conda environments for every platform and write lock files.

    python3 -m venv /tmp/rv && /tmp/rv/bin/pip install py-rattler
    /tmp/rv/bin/python suite_install/tools/make_locks.py            # all platforms, all roles
    /tmp/rv/bin/python suite_install/tools/make_locks.py --platform win-64 --role ndqgis

Writes suite_install/locks/<platform>/<role>.lock, one package per line:

    <url> <sha256> <md5>

download-all / install-all fetch exactly these files and check each sha256, so every
machine gets the same packages and nothing is solved (or trusted) at install time.
Only conda-forge is used. Run this again to move the suite to newer packages.
"""
import argparse
import asyncio
import datetime
import os
import sys

import rattler
from rattler import BuildString, GenericVirtualPackage, PackageName, Version

HERE = os.path.dirname(os.path.abspath(__file__))
LOCKS = os.path.join(os.path.dirname(HERE), "locks")

# role -> specs (the same packages the Mac and Linux installers have used)
ROLES = {
    # QGIS 3.34 LTR is built against NumPy 1.x
    # draco 1.5.7: QGIS 3.34.6 links libdraco.so.9, which newer draco builds no longer provide
    # laspy + lazrs: the Finder's open-water tool reads water from a classified LiDAR point cloud
    # (.las/.laz, ASPRS class 9); laspy reads LAS and, with the lazrs backend, LAZ
    "ndqgis": ["python=3.12", "qgis=3.34", "numpy<2", "scipy", "h5py", "matplotlib-base",
               "draco=1.5.7", "laspy", "lazrs"],
    # ANUGA 4.1 + gmsh (the DamSafety / DamIT Runners mesh with gmsh) + NetCDF I/O
    "ndanuga": ["python=3.12", "anuga=4.1", "gmsh=4.15", "python-gmsh", "numpy", "scipy", "gdal",
                "netcdf4", "matplotlib-base"],
    # the local AIs (Lumo + dam-research), OCR included
    "ndresearch": ["python=3.12", "numpy", "pymupdf", "pypdf", "ocrmypdf", "tesseract"],
    # macOS / Linux: conda compilers + OpenMP to build the patched LISFLOOD-FP 8.3 at install time
    "ndbuild": ["cmake", "make", "llvm-openmp", "c-compiler", "cxx-compiler"],
}
PLATFORMS = {
    "linux-64": [("__linux", "5.4"), ("__glibc", "2.28"), ("__unix", "0"), ("__archspec", "1=x86_64")],
    "osx-arm64": [("__osx", "13.0"), ("__unix", "0"), ("__archspec", "1=arm64")],
    "osx-64": [("__osx", "13.0"), ("__unix", "0"), ("__archspec", "1=x86_64")],
    "win-64": [("__win", "0"), ("__archspec", "1=x86_64")],
}
# ndbuild: macOS always builds LISFLOOD-FP at install; Linux only if the shipped binary cannot run
ROLES_FOR = {p: ["ndqgis", "ndanuga", "ndresearch"] + ([] if p == "win-64" else ["ndbuild"]) for p in PLATFORMS}
# packages that some platforms do not have: dropped there (and said so in the lock's header)
OPTIONAL = {"ndresearch": ["ocrmypdf", "tesseract"]}


def vpkgs(platform):
    out = []
    for name, ver in PLATFORMS[platform]:
        v, _, build = ver.partition("=")
        out.append(GenericVirtualPackage(PackageName(name), Version(v), BuildString(build or "0")))
    return out


async def solve(platform, role):
    specs = list(ROLES[role])
    dropped = []
    while True:
        try:
            recs = await rattler.solve(["conda-forge"], specs, platforms=[platform, "noarch"],
                                       virtual_packages=vpkgs(platform))
            return recs, dropped
        except Exception as e:                                     # noqa: BLE001 - retry without optional pkgs
            opt = [s for s in specs if s in OPTIONAL.get(role, [])]
            if not opt:
                raise
            print("  {} {}: solve failed ({}); dropping {}".format(platform, role, str(e).splitlines()[0][:120], opt))
            specs = [s for s in specs if s not in opt]
            dropped += opt


def write(platform, role, recs, dropped):
    d = os.path.join(LOCKS, platform)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, role + ".lock")
    recs = sorted(recs, key=lambda r: r.name.normalized)
    with open(path, "w", newline="\n") as fh:
        fh.write("# {} {} solved {} from conda-forge: {}\n".format(
            role, platform, datetime.date.today().isoformat(), " ".join(ROLES[role])))
        if dropped:
            fh.write("# not available here, left out: {}\n".format(" ".join(dropped)))
        for r in recs:
            sha = r.sha256.hex() if isinstance(r.sha256, (bytes, bytearray)) else str(r.sha256)
            md5 = r.md5.hex() if isinstance(r.md5, (bytes, bytearray)) else str(r.md5)
            fh.write("{} {} {}\n".format(r.url, sha, md5))
    key = {r.name.normalized: str(r.version) for r in recs}
    want = [k for k in ("qgis", "numpy", "anuga", "gmsh", "python", "pymupdf", "ocrmypdf", "clang", "cmake") if k in key]
    print("  wrote {} ({} packages; {})".format(os.path.relpath(path), len(recs),
                                               ", ".join("{} {}".format(k, key[k]) for k in want)))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", action="append", choices=sorted(PLATFORMS))
    ap.add_argument("--role", action="append", choices=sorted(ROLES))
    a = ap.parse_args()
    for p in a.platform or sorted(PLATFORMS):
        for role in ROLES_FOR[p]:
            if a.role and role not in a.role:
                continue
            recs, dropped = await solve(p, role)
            write(p, role, recs, dropped)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
