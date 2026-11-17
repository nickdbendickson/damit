# Installing the two local AIs on macOS, Linux and Windows

The suite ships two fully-local Ollama assistants, and each platform has one
installer that sets up **both**:

| Assistant | What it does |
|-----------|--------------|
| **Heim** | Code triage over the suite repos (RAG + `heim` / `damchain`). |
| **Vor** | Literature Q&A over dam-safety PDFs (`vor`, cited answers). |

| Platform | Installer | Run it with |
|----------|-----------|-------------|
| macOS | `heim/setup-local-heim.sh` (+ `vor/setup-vor.zsh`), or the packaged `install_all.zsh` | `zsh …` |
| Linux / openSUSE | `install-local-ai-linux.sh` | `./install-local-ai-linux.sh` |
| Windows 10/11 | `install-local-ai-windows.ps1` | `powershell -ExecutionPolicy Bypass -File .\install-local-ai-windows.ps1` |

All three do the same thing and share the same conventions: models in
`~/local-ai/models` (`%USERPROFILE%\local-ai\models`), chat persona `heim` and
`vor`, the server on `127.0.0.1:11434`, and conda envs `ndheim` /
`ndvor` (a Python venv is the fallback when conda isn't present).

## No download-then-run

None of the installers pipe anything from the web into a shell (SWC flagged
that pattern). Ollama and Miniforge are **reused** if already installed.
Otherwise you place the installer yourself and the script verifies its SHA256
before running it:

- **Linux** — save `ollama-linux-amd64.tar.zst` (older releases: `.tgz`) into `~/Downloads` (or put it under
  `damit_ai/offline/ollama/` with a `SHA256SUMS`), then re-run. No `sudo`.
- **Windows** — save `OllamaSetup.exe` into your Downloads (or
  `damit_ai\offline\ollama\` with `SHA256SUMS`), or let the script use
  `winget install Ollama.Ollama`. No admin rights.
- **macOS** — as documented in `setup-local-heim.sh` (bundled zip or
  `~/Downloads/Ollama-darwin.zip`, SHA256-checked).

## Options (same meaning on every platform)

| Linux / macOS flag | Windows switch | Effect |
|--------------------|----------------|--------|
| `--no-heim` | `-NoHeim` | Install Vor only. |
| `--no-vor` | `-NoVor` | Install Heim only. |
| `--ocr` | `-Ocr` | Add `ocrmypdf` + `tesseract` for scanned PDFs. |
| `--small` | `-Small` | Force the small chat model (for low-RAM machines). |
| `--index-knowledge` | `-IndexKnowledge` | Also index `heim/knowledge/` into the RAG. |

## Which model you get

Picked from installed RAM: ≥32 GB → `qwen3:30b-a3b` (num_ctx 16384); ≥16 GB →
`qwen3:14b`; otherwise `qwen3:8b` (num_ctx 12288). Embeddings: `nomic-embed-text`
for Heim, `qwen3-embedding:0.6b` (falling back to `nomic-embed-text`) for
vor.

## After it finishes

Open a new shell (the aliases/functions load from `~/.bashrc` / `~/.zshrc` /
PowerShell `$PROFILE`), then:

```
heim "where is the breach width computed"       # set ND_REPO / DWR_REPO / CREST_REPO for repo audits
vor ingest                               # after dropping PDFs in ~/Vor/library
```

On Windows, `cmd.exe` users get `heim.cmd`, `damchain.cmd` and
`vor.cmd` in `%USERPROFILE%\local-ai` (and `…\local-ai\research`).

## Download everything for an offline install

To install on a machine with no network (or a locked-down one), pre-download everything on a
connected machine first:

```
./download-all-mac.sh              # macOS
./download-all-linux.sh            # Linux/openSUSE
.\download-all-windows.ps1         # Windows
```

Each one fills `damit_ai/offline/` with the Ollama runtime (checked against Ollama's own published
sha256), the AI models, and the Vor PDF library. Then carry the whole `damit_ai/` folder to
the target and run the normal installer — it picks up `offline/` automatically (no Ollama download,
and it seeds the models from `offline/models` so nothing is pulled). Flags: `--no-models` /
`-NoModels`, `--models "…"` / `-Models "…"`, `--no-library` / `-NoLibrary`, `--ollama-version` /
`-OllamaVersion`. The default model set is ~25–30 GB; `offline/` is never committed to git.

## What the installers now set up for you

- **Knowledge pack indexed on install** — the Heim knowledge pack (`heim/knowledge/`) and,
  if the Vor library has them, the engine docs are indexed into the RAG automatically,
  so Heim answers behaviour/findings questions out of the box. Skip with `--no-index` / `-NoIndex`.
- **Heim code-triage eval** — `eval_heim.py` (+ `heim/eval/questions.json`, 10 questions) is
  installed next to the other Heim tools. Score a model against known answers:
  `python3 ~/local-ai/eval_heim.py` (or `--model qwen3:14b` to compare models). Mirrors
  `vor/eval_vor.py`.
- **Periodic library refresh** — `vor/refresh-library.zsh` (macOS/Linux) and
  `vor/refresh-library.ps1` (Windows) download any new catalog/ASDSO files and re-index them.
  Each script's header has the launchd / cron / Task Scheduler line to run it weekly.
- **ALGORITHM-HELP** — the DamSafety tool help (`heim/knowledge/ALGORITHM-HELP.md` and one page per tool
  in `heim/knowledge/algorithm-help/`) is committed, so an install indexes it with the rest of the pack.
  It needs a QGIS with the plugins only to REGENERATE it, after a tool's parameters change:
  `heim/knowledge/dump-algorithm-help.zsh <profile>`, then commit what changed.

## openSUSE GUI-QGIS note

The AIs need no system libraries. If you *also* run the QGIS plugins on the same
openSUSE box and the Qt `xcb` platform plugin fails, install the GL/X libraries:

```
sudo zypper install -y Mesa-libGL1 libxcb-cursor0 libxkbcommon-x11-0
```
