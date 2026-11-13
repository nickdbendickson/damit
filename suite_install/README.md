# Dam suite: install everything (Windows, Linux, macOS)

One package installs the whole suite on Windows 10/11 (x64), Linux (x86_64, tested for openSUSE)
and macOS (Apple Silicon or Intel, macOS 13+):

| What | Where it goes |
|---|---|
| **DamSafety plugins** (DWR_Plugins): Core, Setup, Data, Screening, Runner, Hazard, Hazard Lite, PMP, Finder | QGIS profile `damsafety` (Core first) |
| **DamIT plugins** (damit): Core, Catalog, Setup, Data, Screener, Runner, Hazard, Hazard Lite, PMP | QGIS profile `damit` (Core and Catalog first) |
| **QGIS 3.34** | conda env `ndqgis` |
| **ANUGA 4.1 + gmsh 4.15** (the Runners mesh with gmsh) | conda env `ndanuga` |
| **LISFLOOD-FP 8.3** with the Runner patch (`inittm_depth`) | `~/dam-suite/bin` (Windows/Linux: shipped binary; macOS: built at install) |
| **Local AIs**: Heim (code triage) and Vor (literature), with Ollama, models and library | `~/local-ai`, `~/Vor` (damit_ai's own installers) |
| A launcher per profile, and the Absaraka Dam (DWR-2801) run folder | `~/dam-suite` |

Everything installs for you only: **no sudo or admin, no pip, no system packages.** Your data
folders, offline packs and other QGIS profiles are not touched.

## Two ways to get the files

**1. Offline set (nothing downloaded on the target).** Unzip the package. Then unzip every
`offline-<platform>-partNNofMM.zip` for your platform *inside the package folder*. Each part is a
separate zip, so their order doesn't matter.

| Platform | Offline set |
|---|---|
| Windows | `offline-win-64-part*.zip` |
| Linux | `offline-linux-64-part*.zip` |
| Mac Apple Silicon | `offline-osx-arm64-part*.zip` |
| Mac Intel | `offline-osx-64-part*.zip` |

It holds every conda package, Miniforge, Ollama and the LISFLOOD-FP source for that platform. The
AI models are not in it, because they are large (about 25 GB). Get them with step 2, or let the
AI installer pull them over the network.

**2. Download-all (build your own offline set).** On any machine with internet:

```bash
bash download-all.sh                        # this machine's platform, with models + library
bash download-all.sh --platform all --pack  # all four platforms, each zipped as offline-<platform>.zip
```

On Windows, run `download-all-windows.cmd` (options such as `-NoModels` or `-Platform all -Pack`).
Then carry the folder, or the zip, to the target machine.

Every file is pinned in `locks/` by URL and sha256. The conda packages are solved once by
`tools/make_locks.py` and are the same on every machine. A download that doesn't match is
deleted, and nothing downloaded is piped into a shell.

## Install

| | |
|---|---|
| Linux | `bash install-all.sh` |
| macOS | `bash install-all.sh` (keep the folder in your home folder, not Downloads) |
| Windows | double-click `install-all-windows.cmd` |

Options: `--no-damsafety`, `--no-damit`, `--no-ai`, `--no-heim`, `--no-vor`,
`--skip-lisflood`, `--offline` (never download), `--check` (report what's installed).
On Windows the options are `-NoDamSafety`, `-NoDamIT`, `-NoAI`, `-NoHeim`, `-NoVor`,
`-SkipLisflood`, `-Offline`, `-Check` and `-NoShortcuts`.

- **macOS never downloads from the installer**, the same as the earlier Mac packages. If the
  offline set is missing, it stops and asks for it, or for `download-all.sh` to be run first.
  Miniforge is checked against its sha256 before it runs. LISFLOOD-FP is built from the bundled
  source with conda's clang, which needs Apple's Command Line Tools (`xcode-select --install`).
- **Linux and Windows** fetch any missing files first, pinned and checked, unless you pass
  `--offline` / `-Offline`.
- The installer is safe to re-run. It keeps existing conda envs and data, and replaces the plugins.

Open QGIS with a launcher: `~/dam-suite/open-damsafety-qgis.sh` or `open-damit-qgis.sh` (on a
Mac, also the `.command` files). On Windows, use `open-damsafety-qgis.cmd` /
`open-damit-qgis.cmd` or the Desktop shortcuts. Keep the two sets in their own profiles.

## Package layout

```
install-all.sh, install-all-windows.ps1/.cmd   installers
download-all.sh, download-all-windows.ps1/.cmd builders of offline/
locks/<platform>/*.lock, locks/extra.lock      pinned files (url sha256 md5)
plugins/damsafety, plugins/damit               plugin zips (VERSIONS.md, SHA256SUMS)
lisflood/                                      LISFLOOD-FP binaries (GPL-3, see lisflood/README.txt) + macOS build script
damit_ai/                                      the local AIs and their installers
absaraka/                                      the DWR-2801 run folder
offline/ (from an offline set or download-all) conda/<platform>/, miniforge/, lisflood-src/
```

Maintainers: `tools/make_locks.py` re-solves the conda envs (py-rattler), and
`tools/make_package.sh --dwr <DWR_Plugins checkout> --out <dir> --zip` builds the package.
