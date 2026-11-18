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
| **Crest desks**: DamIT Crest (damit) and North Dakota Crest (crest repo), on the `ndqgis` env; they open in the browser | `~/dam-suite/damit_crest`, `~/dam-suite/nd_crest` |
| A launcher per profile, one per Crest desk, `build-offline-pack.sh`, and the Absaraka Dam (DWR-2801) run folder | `~/dam-suite` |

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

**A test install beside your normal one.** `--root DIR` puts the suite folder in `DIR/dam-suite`, the QGIS
profiles in `DIR/qgis/QGIS3/profiles` (the launchers open QGIS with `--profiles-path DIR/qgis`, so your usual
QGIS profiles are not touched) and, when Miniforge is not installed yet, Miniforge in `DIR/miniforge3`. The local
AIs always use your home folder, so `--root` leaves them out unless you add `--ai` after it. The parts can also be
set one by one: `--prefix DIR`, `--qgis-profiles-path DIR`, `--damsafety-profile NAME`, `--damit-profile NAME`.
Windows: `-Root`, `-Prefix`, `-QgisProfilesPath`, `-DamSafetyProfile`, `-DamitProfile`, `-AI`. Use the same
options with `--check` to see that install.

- **macOS never downloads from the installer**, the same as the earlier Mac packages. If the
  offline set is missing, it stops and asks for it, or for `download-all.sh` to be run first.
  Miniforge is checked against its sha256 before it runs. LISFLOOD-FP is built from the bundled
  source with conda's clang, which needs Apple's Command Line Tools (`xcode-select --install`).
- **Linux and Windows** fetch any missing files first, pinned and checked, unless you pass
  `--offline` / `-Offline`.
- The installer is safe to re-run. It keeps existing conda envs and data, and replaces the plugins.
- The envs always live in `<conda base>/envs` (e.g. `~/miniforge3/envs/ndqgis`), made by path, even
  when `MAMBA_ROOT_PREFIX` points elsewhere. Installs before 2026-11-16 could land them in
  `~/micromamba/envs` instead, which broke the launchers and the ANUGA setting.
- Before building an env the installer searches for one of that name elsewhere (`$MAMBA_ROOT_PREFIX`,
  `~/micromamba`, `~/miniforge3`, `~/miniconda3`, `~/anaconda3`, `~/.conda`, and the envs listed in
  `~/.conda/environments.txt`). One that has every package in the lock is used as it is, through a
  link `<conda base>/envs/<name>` → that env; one that differs is left alone and a fresh env is built.
  Nothing is moved or deleted. `DAMSUITE_REUSE_ENVS=0` always builds fresh. Never `conda env remove`
  a linked env (that empties the real one); undo a link with `rm <conda base>/envs/<name>`, no
  trailing slash.

Open QGIS with a launcher: `~/dam-suite/open-damsafety-qgis.sh` or `open-damit-qgis.sh` (on a
Mac, also the `.command` files). On Windows, use `open-damsafety-qgis.cmd` /
`open-damit-qgis.cmd` or the Desktop shortcuts. Keep the two sets in their own profiles.

The Crest desks: `~/dam-suite/open-damit-crest.sh` and `open-nd-crest.sh` (Windows: `.cmd`). They
use different ports (North Dakota Crest http://127.0.0.1:47231, DamIT Crest http://127.0.0.1:47241; each prints
its address when it starts, and takes a random port if its own is busy), so both can be open at the same time.
Their Report step calls `qgis_process`
in the matching profile (North Dakota Crest: `damsafety`; DamIT Crest: `damit`): `qgis_process` has
no profile option, so the launcher points `QGIS_CUSTOM_CONFIG_PATH` at
`~/dam-suite/qgis-process/<profile>`, whose `profiles/default` is a link to the real profile.

The DamSafety offline pack from Terminal, without opening QGIS:
`~/dam-suite/build-offline-pack.sh` (default folder `~/ND_Suite_Data`; give another folder as the
first argument). A stopped build picks up where it left off. When it finishes, the folder becomes the
suite data folder.

## Package layout

```
install-all.sh, install-all-windows.ps1/.cmd   installers
download-all.sh, download-all-windows.ps1/.cmd builders of offline/
locks/<platform>/*.lock, locks/extra.lock      pinned files (url sha256 md5)
plugins/damsafety, plugins/damit               plugin zips (VERSIONS.md, SHA256SUMS)
nd_crest/                                      North Dakota Crest desk (crest repo crest-desktop/; COMMIT)
lisflood/                                      LISFLOOD-FP binaries (GPL-3, see lisflood/README.txt) + macOS build script
damit_ai/                                      the local AIs and their installers
absaraka/                                      the DWR-2801 run folder
offline/ (from an offline set or download-all) conda/<platform>/, miniforge/, lisflood-src/
```

Maintainers: `tools/make_locks.py` re-solves the conda envs (py-rattler), and
`tools/make_package.sh --dwr <DWR_Plugins checkout> --crest <crest checkout> --out <dir> --zip`
builds the package (without `--crest` there is no North Dakota Crest desk in it).
