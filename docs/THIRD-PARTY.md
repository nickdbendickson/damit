# Third-party software, models and data

DamIT is built on other people's work. This page credits it. **"In repo"** means files from that project
are stored in this repository; **"installed"** means `suite_install/` or `damit_ai/` downloads a pinned copy
at install time; **"runtime"** means you install or download it yourself. Each project's own license applies to it.

## Local AI models (run through Ollama)

| Model | Source | License | How it arrives |
|---|---|---|---|
| Qwen3 4B / 8B / 14B / 30B-A3B | [Qwen (Alibaba)](https://huggingface.co/Qwen) via the Ollama library, fallback `Qwen/Qwen3-*-GGUF` (Q4_K_M) | Apache-2.0 | installed |
| Qwen3.6 27B / 35B-A3B | [Qwen (Alibaba)](https://huggingface.co/Qwen) via the Ollama library | Apache-2.0 | installed |
| Qwen3-Embedding 0.6B | [Qwen (Alibaba)](https://huggingface.co/Qwen) via the Ollama library | Apache-2.0 | installed |
| nomic-embed-text v1.5 | [Nomic AI](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) via the Ollama library | Apache-2.0 | installed |
| Phi-4-mini-instruct (optional) | [Microsoft](https://huggingface.co/microsoft/Phi-4-mini-instruct), GGUF from `unsloth/Phi-4-mini-instruct-GGUF` | MIT | installed on request |

## Models and engines

| Project | Source | License | How it arrives |
|---|---|---|---|
| LISFLOOD-FP 8.3 | University of Bristol, [Zenodo 13121119](https://zenodo.org/records/13121119) | GPL-3.0 | installed (binary built from the official source with the DamSafety `inittm_depth` patch; LICENSE and source shipped beside it) |
| ANUGA 4.1 | [anuga-community/anuga_core](https://github.com/anuga-community/anuga_core) | Apache-2.0 | installed (conda-forge) |
| gmsh 4.15 | [gmsh.info](https://gmsh.info) | GPL-2.0-or-later | installed (conda-forge) |
| QGIS 3.34 | [qgis.org](https://qgis.org) | GPL-2.0-or-later | installed (conda-forge) |
| GDAL, NumPy, SciPy | conda-forge | MIT, BSD-3-Clause, BSD-3-Clause | installed |
| Miniforge | [conda-forge/miniforge](https://github.com/conda-forge/miniforge) | BSD-3-Clause | installed |
| Ollama 0.40 | [ollama/ollama](https://github.com/ollama/ollama) | MIT | installed |
| PyMuPDF | [pymupdf/PyMuPDF](https://github.com/pymupdf/PyMuPDF) | AGPL-3.0 (or commercial) | installed for Vor |
| laspy (+ lazrs) | [laspy/laspy](https://github.com/laspy/laspy) | BSD-2-Clause (laspy) | installed for DamIT Finder |
| HEC-RAS | US Army Corps of Engineers | US government software | runtime (DamIT Runner refuses HEC-RAS today) |

Breach equations (Froehlich 1995/2008, MacDonald & Langridge-Monopolis, Von Thun & Gillette, NRCS TR-60) are
published methods implemented in DamIT's own code and cited in each run report.

## DamIT Crest desktop app

pywebview (BSD-3-Clause), React (MIT), Leaflet (BSD-2-Clause), leaflet-draw (MIT), react-leaflet (Hippocratic-2.1),
proj4js (MIT), geotiff.js (MIT), fflate (MIT), zustand (MIT), TanStack Table (MIT), lucide (ISC),
html-to-image (MIT), Tailwind CSS (MIT), Vite (MIT), PyInstaller (GPL-2.0 with bootloader exception). Exact versions:
`damit_crest/package.json`, `damit_crest/desktop/requirements.txt`. All runtime (npm / pip).

## Data sources

USACE National Inventory of Dams and National Structure Inventory; USGS 3DEP elevation and lidar, 3DHP / NHD
hydrography, StreamStats; Microsoft US Building Footprints (ODbL); OpenStreetMap via Geofabrik
(**© OpenStreetMap contributors, ODbL**: keep this credit on any map that shows OSM data); FEMA / ORNL USA
Structures; FHWA HPMS and National Bridge Inventory; FRA rail network; US Census TIGER; HIFLD; MRLC NLCD;
NOAA Atlas 14 (PFDS); NOAA VERTCON. US federal data is public domain unless the source says otherwise.
The Vor library (ASDSO and other papers) is downloaded to your own machine for private use and is not
redistributed. DamIT Catalog encodes *US Dam Hazard Classification — Corrected Edition* and the Nov 2026
*In-Depth Summaries*, with a citation on every rule.

## Brand

DaMiT wordmark and mark (`docs/img/`): the project wordmark; not licensed for reuse. The DaMiT name
and logo are not licensed for reuse.
