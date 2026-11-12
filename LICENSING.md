# Licensing

DamIT is **multi-licensed**, because different parts combine with other software in different ways.
This file is the authoritative map. Full license texts are in [`LICENSES/`](LICENSES/); credits for
third-party software, models and data are in [`docs/THIRD-PARTY.md`](docs/THIRD-PARTY.md).

## The two licenses

| Part of the repo | License | SPDX | Why |
|---|---|---|---|
| **The QGIS plugins** — `damit_catalog/`, `damit_core/`, `damit_data/`, `damit_finder/`, `damit_hazard/`, `damit_hazardlite/`, `damit_pmp/`, `damit_runner/`, `damit_screener/`, `damit_setup/` | **GNU GPL v3.0 or later** | `GPL-3.0-or-later` | Each loads inside QGIS and imports the QGIS Python API (`qgis.*`), which is GPL. A QGIS plugin is a combined work with QGIS, so it must be GPL-compatible — this is also the QGIS plugin-repository requirement. GPL permits commercial use but forbids proprietary (closed-source) forks. |
| **The standalone apps** — `damit_crest/` (desktop app) and `damit_ai/` (Lumo + dam-research) | **PolyForm Noncommercial 1.0.0** | `LicenseRef-PolyForm-Noncommercial-1.0.0` | These do **not** link the QGIS API in-process — Crest drives QGIS only by running `qgis_process` as a separate program, and the AI tools talk to a local Ollama. Because they stand apart from the GPL code, they can carry a noncommercial license: anyone may use, modify and share them for non-commercial purposes; commercial use needs the author's permission. |

**Exception inside `damit_ai/`:** `damit_ai/lumo/tools/dump_damit_algorithm_help.py` imports the QGIS
API when run, so that one file is **GPL-3.0-or-later**, not PolyForm. The rest of `damit_ai/` is PolyForm
Noncommercial.

## What this means in practice

- You can run, study, modify and redistribute the **plugins** freely, including commercially, but any
  distribution must stay open-source under the GPL (no closed-source forks). Because N.D. Bendickson holds
  the copyright, he may additionally offer commercial licenses for them.
- You may **not** use **Crest** or the **AI tools** for a commercial purpose without permission.
- Every **bundled or downloaded third-party component** (LISFLOOD-FP, gmsh, QGIS, ANUGA, the Ollama models,
  npm/pip packages, data sources) keeps **its own license**. DamIT's licenses never override them. See
  [`docs/THIRD-PARTY.md`](docs/THIRD-PARTY.md).

## The DaMiT name and logo

The **DaMiT** name and the DaMiT logo/wordmark (`docs/img/`, and each plugin's `icon.svg`) are **not**
covered by either code license. All rights reserved; trademark rights reserved. The logo artwork is drawn
with the Inter typeface (SIL Open Font License 1.1).

> This file describes the maintainer's licensing intent; it is not legal advice. For anything you intend to
> enforce, confirm with a lawyer familiar with open-source and GPL combination.
