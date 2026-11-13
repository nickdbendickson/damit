<#
=============================================================================
install-local-ai-windows.ps1 — install BOTH local AIs (Heim code-triage +
vor literature) on Windows 10/11. The Windows counterpart of
damit_ai/heim/setup-local-heim.sh and vor/setup-vor.zsh.

  powershell -ExecutionPolicy Bypass -File .\install-local-ai-windows.ps1
  .\install-local-ai-windows.ps1 -NoHeim          # vor only
  .\install-local-ai-windows.ps1 -NoVor      # Heim only
  .\install-local-ai-windows.ps1 -Ocr             # vor with OCR (ocrmypdf + tesseract)
  .\install-local-ai-windows.ps1 -Small           # force the small chat model
  .\install-local-ai-windows.ps1 -NoIndex         # skip indexing the knowledge pack / engine docs
  .\install-local-ai-windows.ps1 -WatchModel phi4-mini   # the SMALL run-watcher explainer (default qwen3:4b);
                                                         # -NoWatchModel skips pulling it. heim (Q&A) keeps the big model.

  If 'ollama pull' fails (a proxy that breaks the registry redirect) the model's official GGUF is fetched from
  Hugging Face with curl.exe (https_proxy / $env:HF_ENDPOINT honoured), sha256-checked and loaded with 'ollama create'
  under the same tag. $env:HEIM_NO_HF_FALLBACK = 1 turns that off.

By default, when Heim is installed the Heim knowledge pack (heim\knowledge) and, if present,
the vor engine docs are indexed into the RAG so Heim comes up already knowing the
suite's behaviours, findings and tool contracts. Pass -NoIndex to skip that.

Policy (same as the Mac/Linux installers): NO download-then-run. Ollama,
Miniforge and winget packages are reused if already installed; otherwise you
place the installer yourself (a bundled copy under damit_ai\offline\, or a file
in your Downloads folder) and this script verifies its SHA256 and runs it, or
you install Ollama through winget. Nothing is piped from the web into a shell,
and no admin rights are required.

If PowerShell blocks the script, start it with:
  powershell -ExecutionPolicy Bypass -File .\install-local-ai-windows.ps1
=============================================================================
#>
[CmdletBinding()]
param(
  [switch]$NoHeim,
  [switch]$NoVor,
  [switch]$Ocr,
  [switch]$Small,
  [switch]$IndexKnowledge,   # on by default; kept for compatibility
  [switch]$NoIndex,
  [string]$WatchModel = $(if ($env:HEIM_WATCH_MODEL) { $env:HEIM_WATCH_MODEL } else { 'qwen3:4b' }),
  [switch]$NoWatchModel
)
$ErrorActionPreference = 'Stop'

$Here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalAI    = Join-Path $env:USERPROFILE 'local-ai'
$ModelsDir  = Join-Path $LocalAI 'models'
$VorDir= Join-Path $LocalAI 'vor'
$RHome      = if ($env:VOR_HOME) { $env:VOR_HOME } else { Join-Path $env:USERPROFILE 'Vor' }
$Downloads  = Join-Path $env:USERPROFILE 'Downloads'
$Offline    = Join-Path $Here 'offline'
$HeimEnv    = 'ndheim'; $VorEnv = 'ndvor'
$OllamaUrl  = 'http://127.0.0.1:11434'
$DoHeim     = -not $NoHeim
$DoVor = -not $NoVor

function Say ($m) { Write-Host "`n== $m" -ForegroundColor White }
function Ok  ($m) { Write-Host "  ok $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "  warn $m" -ForegroundColor Yellow }
function Die ($m) { Write-Host "  ERROR $m" -ForegroundColor Red; exit 1 }
function Sha ($p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }
function ServerUp {
  try { Invoke-RestMethod -Uri "$OllamaUrl/api/version" -TimeoutSec 3 | Out-Null; return $true }
  catch { return $false }
}

# ---------------------------------------------------------------------------
Say 'Step 1 - Directory skeleton'
# Vor was called damresearch until 2026-11-13 and kept its library and index in ~\DamResearch
# (or wherever DAMRESEARCH_HOME pointed). Creating an empty ~\Vor beside it and pinning VOR_HOME
# to that would leave the indexed library behind with no error from anything. Carry it over
# first: the index decides, the move is only onto a name that does not exist, nothing is deleted.
function VorHasIndex ($d) { (Test-Path (Join-Path $d 'vor.db')) -or (Test-Path (Join-Path $d 'research.db')) }
$OldRHome = if ($env:DAMRESEARCH_HOME) { $env:DAMRESEARCH_HOME } else { Join-Path $env:USERPROFILE 'DamResearch' }
if (-not $env:VOR_HOME -and ($OldRHome -ne $RHome) -and (VorHasIndex $OldRHome) -and -not (VorHasIndex $RHome)) {
  $moved = $false
  # Only the default folder is renamed; a library kept elsewhere (another disk) stays there.
  if (($OldRHome -eq (Join-Path $env:USERPROFILE 'DamResearch')) -and -not (Test-Path $RHome)) {
    try { Move-Item -LiteralPath $OldRHome -Destination $RHome -ErrorAction Stop; $moved = $true } catch { $moved = $false }
  }
  if ($moved) { Ok "moved your Vor library from $OldRHome to $RHome (nothing was copied)" }
  else { Warn "keeping your indexed Vor library where it is: $OldRHome"; $RHome = $OldRHome }
}
if ((Test-Path (Join-Path $RHome 'research.db')) -and -not (Test-Path (Join-Path $RHome 'vor.db'))) {
  Rename-Item -LiteralPath (Join-Path $RHome 'research.db') -NewName 'vor.db'
  Ok "index renamed research.db -> vor.db (nothing re-indexed)"
}
foreach ($d in @($LocalAI, $ModelsDir, $VorDir, (Join-Path $RHome 'library'), (Join-Path $RHome 'reports'))) {
  New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Ok "$LocalAI, $RHome"

# ---------------------------------------------------------------------------
Say 'Step 2 - Ollama (no admin, no download-then-run)'
$Ollama = $null
$cands = @(
  (Get-Command ollama -ErrorAction SilentlyContinue).Source,
  (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
  (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
)
foreach ($c in $cands) { if ($c -and (Test-Path $c)) { $Ollama = $c; break } }

if (-not $Ollama) {
  # 1) a verified, user-placed installer (bundled offline copy, or your Downloads)
  $exe = $null
  foreach ($cand in @((Join-Path $Offline 'ollama\OllamaSetup.exe'), (Join-Path $Downloads 'OllamaSetup.exe'))) {
    if (Test-Path $cand) { $exe = $cand; break }
  }
  $sums = Join-Path $Offline 'ollama\SHA256SUMS'
  if ($exe -and (Test-Path $sums)) {
    $want = (Select-String -Path $sums -Pattern 'OllamaSetup.exe' | Select-Object -First 1).Line -split '\s+' | Select-Object -First 1
    if ($want -and ($want.ToLower() -ne (Sha $exe))) { Warn 'bundled OllamaSetup.exe failed its SHA256SUMS; ignoring'; $exe = $null }
  }
  if ($exe) {
    Ok "running $exe (silent, per-user)"
    Start-Process -FilePath $exe -ArgumentList '/VERYSILENT','/NORESTART' -Wait
  }
  elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Ok 'installing Ollama through winget'
    winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
  }
  else {
    Write-Host @"
  No Ollama found, and no local installer to run.
  Install it yourself (no admin needed) and re-run this script:
    1) Open https://ollama.com/download/windows
    2) Save 'OllamaSetup.exe' into $Downloads  and run it (or let this script run it)
  (Or install it with:  winget install Ollama.Ollama)
"@ -ForegroundColor Yellow
    Die 'Ollama not available'
  }
  foreach ($c in $cands) { if ($c -and (Test-Path $c)) { $Ollama = $c; break } }
  if (-not $Ollama) { $Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
  if (-not $Ollama) { Die 'ollama.exe not found after install (open a new shell and re-run)' }
  Ok "Ollama installed ($Ollama)"
} else {
  Ok "Ollama already installed ($Ollama)"
}

# model store + perf flags for this process and the server we start
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ModelsDir, 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_FLASH_ATTENTION', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KV_CACHE_TYPE', 'q8_0', 'User')
$env:OLLAMA_MODELS = $ModelsDir; $env:OLLAMA_FLASH_ATTENTION = '1'; $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'

if (-not (ServerUp)) {
  Ok 'starting ollama serve'
  Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LocalAI 'ollama-serve.log') `
    -RedirectStandardError  (Join-Path $LocalAI 'ollama-serve.err.log')
  for ($i=0; $i -lt 30; $i++) { if (ServerUp) { break }; Start-Sleep 1 }
}
if (-not (ServerUp)) { Die "ollama server did not come up (see $LocalAI\ollama-serve.log)" }
Ok "server up on $OllamaUrl"

# seed models from a pre-downloaded offline bundle (download-all-windows.ps1), so pulls are skipped
if ((Test-Path (Join-Path $Offline 'models\manifests')) -and -not (Test-Path (Join-Path $ModelsDir 'manifests'))) {
  try { Copy-Item (Join-Path $Offline 'models\*') $ModelsDir -Recurse -Force; Ok 'seeded models from offline\models (no download needed)' }
  catch { Warn 'could not seed offline models' }
}

# ---------------------------------------------------------------------------
Say 'Step 3 - conda (reuse an existing install; venv fallback)'
$Conda = $null
$ccands = @(
  $env:CONDA_EXE,
  (Get-Command conda -ErrorAction SilentlyContinue).Source,
  (Join-Path $env:USERPROFILE 'miniforge3\Scripts\conda.exe'),
  (Join-Path $env:USERPROFILE 'miniconda3\Scripts\conda.exe'),
  (Join-Path $env:USERPROFILE 'Miniforge3\Scripts\conda.exe')
)
foreach ($c in $ccands) { if ($c -and (Test-Path $c)) { $Conda = $c; break } }
if ($Conda) { Ok "conda: $Conda" } else { Warn 'no conda found - will use python venvs (needs python on PATH)' }

function Make-Env ($name, $spec) {   # returns the python.exe path
  if ($Conda) {
    $envpath = ((& $Conda env list) | Select-String -Pattern "^\s*$name\s" | Select-Object -First 1)
    if (-not $envpath) {
      & $Conda create -y -n $name -c conda-forge --override-channels @($spec -split '\s+') *> $null
      if ($LASTEXITCODE -ne 0) { Warn "conda create $name failed - falling back to a venv"; $script:Conda = $null }
    }
    if ($Conda) {
      $line = ((& $Conda env list) | Select-String -Pattern "(?<![\w-])$name\s" | Select-Object -First 1).ToString()
      $p = ($line -split '\s+')[-1]
      if ($p) { return (Join-Path $p 'python.exe') }
    }
  }
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $py) { Die 'no conda and no python on PATH' }
  $venv = Join-Path $LocalAI "$name-venv"
  & $py -m venv $venv *> $null
  if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { Die "venv $name failed" }
  & (Join-Path $venv 'Scripts\python.exe') -m pip -q install --upgrade pip *> $null
  & (Join-Path $venv 'Scripts\python.exe') -m pip -q install pymupdf pypdf numpy *> $null
  return (Join-Path $venv 'Scripts\python.exe')
}

# ---------------------------------------------------------------------------
Say 'Step 4 - RAM + chat model'
$RamGB = [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if     ($Small)        { $ChatModel = if ($RamGB -lt 16) { 'qwen3:8b' } else { 'qwen3:14b' } }
elseif ($RamGB -ge 32) { $ChatModel = 'qwen3:30b-a3b' }
elseif ($RamGB -ge 16) { $ChatModel = 'qwen3:14b' }
else                   { $ChatModel = 'qwen3:8b' }
$NumCtx = if ($RamGB -lt 32) { 12288 } else { 16384 }
Ok "RAM $RamGB GB -> chat model $ChatModel (num_ctx $NumCtx)"

# >>> hf_gguf_fallback (Windows copy of the bash block in install-local-ai-linux.sh; the table must match, a test checks it)
# `ollama pull` can fail behind a proxy. Fallback: fetch the model's official GGUF from Hugging Face (curl.exe honours
# https_proxy; $env:HF_ENDPOINT can point at a mirror), check its sha256, `ollama create` the SAME tag, delete the GGUF.
# $env:HEIM_GGUF_SPEC = "repo file sha256 bytes" overrides the table; $env:HEIM_GGUF_DIR = scratch dir;
# $env:HEIM_NO_HF_FALLBACK = 1 turns the fallback off.
function Get-HfGgufSpec ($tag) {
  if ($env:HEIM_GGUF_SPEC) { return ($env:HEIM_GGUF_SPEC -split '\s+') }
  switch -Regex ($tag) {
    '^qwen3:4b$'          { return @('Qwen/Qwen3-4B-GGUF','Qwen3-4B-Q4_K_M.gguf','7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5','2497280256') }
    '^qwen3:8b$'          { return @('Qwen/Qwen3-8B-GGUF','Qwen3-8B-Q4_K_M.gguf','d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785','5027783488') }
    '^qwen3:14b$'         { return @('Qwen/Qwen3-14B-GGUF','Qwen3-14B-Q4_K_M.gguf','500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0','9001752960') }
    '^qwen3:30b-a3b$'     { return @('Qwen/Qwen3-30B-A3B-GGUF','Qwen3-30B-A3B-Q4_K_M.gguf','0d003f6662faee786ed5da3e31b29c978de5ae5d275c8794c606a7f3c01aa8f5','18556685824') }
    '^phi4-mini(:.*)?$'   { return @('unsloth/Phi-4-mini-instruct-GGUF','Phi-4-mini-instruct-Q4_K_M.gguf','88c00229914083cd112853aab84ed51b87bdf6b9ce42f532d8c85c7c63b1730a','2491874272') }
    '^nomic-embed-text(:.*)?$' { return @('nomic-ai/nomic-embed-text-v1.5-GGUF','nomic-embed-text-v1.5.f16.gguf','f7af6f66802f4df86eda10fe9bbcfc75c39562bed48ef6ace719a251cf1c2fdb','274290560') }
  }
  return $null
}
function New-OllamaFromHf ($tag) {
  $spec = Get-HfGgufSpec $tag
  if (-not $spec) { Warn "no Hugging Face GGUF is known for $tag (set HEIM_GGUF_SPEC=`"repo file sha256 bytes`")"; return $false }
  $repo, $file, $sha, $size = $spec; $size = [int64]$size
  if ($env:HEIM_NO_HF_FALLBACK -eq '1') { Warn "HEIM_NO_HF_FALLBACK=1: not downloading $tag from Hugging Face"; return $false }
  if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Warn "curl.exe not found: cannot fetch the GGUF for $tag"; return $false }
  $dir = if ($env:HEIM_GGUF_DIR) { $env:HEIM_GGUF_DIR } else { Join-Path $env:TEMP 'heim-gguf' }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $free = (Get-PSDrive -Name ((Resolve-Path $dir).Drive.Name)).Free
  if ($free -lt ($size + [int64]($size / 10))) { Warn "not enough free space in $dir for the $([int]($size / 1MB)) MB GGUF (set HEIM_GGUF_DIR to a bigger disk)"; return $false }
  $ep = if ($env:HF_ENDPOINT) { $env:HF_ENDPOINT } else { 'https://huggingface.co' }
  $gguf = Join-Path $dir $file
  $have = if (Test-Path $gguf) { (Get-Item $gguf).Length } else { 0 }
  if ($have -ne $size) {
    Ok "ollama pull failed: downloading $file from Hugging Face ($([int]($size / 1MB)) MB)"
    & curl.exe -fL -C - --retry 3 --retry-delay 5 -o $gguf "$ep/$repo/resolve/main/$file"
    if ($LASTEXITCODE -ne 0) { Warn "download failed: $ep/$repo/resolve/main/$file"; return $false }
  }
  $got = (Get-FileHash -Algorithm SHA256 $gguf).Hash.ToLower()
  if ($got -ne $sha) { Warn "sha256 of $file is $got, expected ${sha}: not used"; Remove-Item $gguf -Force; return $false }
  $mf = Join-Path $dir "Modelfile.$PID"
  $lines = @("FROM $gguf")
  if ($tag -notlike 'nomic*') { $lines += @('PARAMETER num_ctx 4096','PARAMETER temperature 0.2','PARAMETER top_p 0.9') }
  Set-Content -Path $mf -Value $lines -Encoding ASCII
  & $Ollama create $tag -f $mf | Out-Null
  $okc = ($LASTEXITCODE -eq 0)
  Remove-Item $mf -Force -ErrorAction SilentlyContinue
  if (-not $okc) { Warn "ollama create $tag failed"; return $false }
  Remove-Item $gguf -Force -ErrorAction SilentlyContinue
  Ok "created $tag from the Hugging Face GGUF"
  return $true
}
# <<< hf_gguf_fallback

function Pull ($m) {
  if (-not ((& $Ollama list) -match [regex]::Escape($m))) {
    Ok "pulling $m (first time, large)"
    & $Ollama pull $m
    if ($LASTEXITCODE -ne 0) { if (-not [bool](@(New-OllamaFromHf $m))[-1]) { Die "pull failed: $m" } }
  }
}

# ===========================================================================
if ($DoHeim) {
  Say 'Heim - code triage'
  Pull $ChatModel; Pull 'nomic-embed-text'
  # the run-watcher's explainer: a SMALL model. Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an
  # Intel Arc / Intel iGPU box runs it on the CPU, which is why a 4B model is the default there.
  if ($WatchModel -eq 'phi') { $WatchModel = 'phi4-mini' } elseif ($WatchModel -eq 'small') { $WatchModel = 'qwen3:4b' }
  if (-not $NoWatchModel) {
    if (-not ((& $Ollama list) -match [regex]::Escape($WatchModel))) {
      Ok "pulling $WatchModel (the small watcher model)"
      & $Ollama pull $WatchModel
      if ($LASTEXITCODE -ne 0) { if ([bool](@(New-OllamaFromHf $WatchModel))[-1]) { $global:LASTEXITCODE = 0 } }
      if ($LASTEXITCODE -ne 0) { Warn "could not pull the watcher model $WatchModel (heim-watch still gives the digest and verdict)" }
    }
  }
  $mf = Join-Path $LocalAI 'Modelfile.heim'
@"
FROM $ChatModel
PARAMETER num_ctx $NumCtx
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 20
SYSTEM """You are Heim-Lite, a fully local assistant for dam-safety engineering work on this machine.
DOMAIN CONTEXT (what this machine builds; it tells you what the names mean, never whether a claim is true):
- The DamIT QGIS plugins (damit_core, damit_screener, damit_runner, damit_hazard, damit_hazardlite, damit_finder, damit_data, damit_catalog, damit_pmp, damit_setup) and the DamSafety fork of the same engine. Their Processing ids clash, so each set gets its own QGIS profile.
- QGIS 3.34 LTR, Python 3.12 from conda-forge (env ndqgis) on macOS; CI also runs QGIS 4 / Qt6.
- Crest: a TypeScript desk-screening app off USGS 3DEP 10 m. A screening tool, not a hazard classification.
- Hazard classification follows USBR ACER TM-11 and the ND Dam Safety Standards (REG_05.2026).
- The hydraulic engines are subprocesses, not libraries: LISFLOOD-FP 8.x (ACC is the default solver; FV2 and MWDG2 are CUDA-only), ANUGA 4.1, gmsh, and HEC-RAS under Wine. Each Runner pass writes Depth, Velocity, Arrival Time and WSE rasters.
- Terrain is 3DEP 1 m and statewide VRTs on NAVD88, EPSG:26914 (ND) or EPSG:5070 (DamSafety WORK_CRS). A DEM projected in metres overrides WORK_CRS, and a VRT reads a missing source back as nodata, which the models read as high ground.
- Data sources: NSI, ND GIS Hub, FEMA, OSM, NDDOT ArcGIS REST, USGS 3DHP, the NID and the ND DWR dam list.
- The GUI can display SI, but a Run still receives FEET.
- You have NO web access and cannot check anything online. Your training is older than this code: say when a fact may be out of date instead of asserting it.
- Every file, log and run you are shown stays on this machine. Treat all of it as private.
Be precise about code, filenames, paths and units (ft vs m, cfs vs m3/s, NAVD88 vs local datum). Show the complete corrected function, never fragments. Never call sys.exit()/os._exit() in code that runs inside QGIS. Guard None before string ops. Only report a defect you can point to by line number in code you were shown. When uncertain, say UNSURE. Never recommend destructive operations without a backup and a dry-run.
HOW YOU ANSWER (this is your manner; it is about what you do, not how you sound):
- Lead with the verdict or the line number. The reasoning comes after it, never before it.
- Quote the code you are judging before you judge it. A defect described in general terms, with no line to point at, is a guess wearing a finding's clothes.
- One finding at a time, worst first. A list of maybes is not a finding, and length is not thoroughness.
- Never soften a defect into a suggestion. If it is wrong, say it is wrong.
- Asking is a complete answer: name the file, function or log you would need to see, and stop there.
- You watch and explain; you do not decide. Where the code sets a verdict or a status, explain the flags that produced it and leave the verdict alone.
STANDING RULES (Nick's; never contradict them, even if a question assumes otherwise):
- Sunny-day breach: there is NO inflow, the outlets are empty, and there is NO outlet or spillway flow. The reservoir starts at the top of dam, which is the DWR max pool. The only water is the breach. Never say the inflow equals the reservoir capacity or that the outlets are operational.
- Breach volume Vw: a sunny-day breach uses the DWR maximum pool and maximum storage unless stated otherwise; a PMF or flood-inflow breach uses the storage at the pool when the breach starts (ND Dam Safety Standards).
- The real DamIT qgis_process algorithm ids: damit_screen:handoff (hand-off to the Runner), damit_run:rundam (breach flood for one dam), damit:classify (hazard classification), damit_lite:classify (Hazard Lite). The automatic 10 m refine is turned off with --GRID_REFINE=0. There is no damit_runner algorithm, no damit_screener_handoff, no damit_hazard_classification and no --no-refine switch.
- Never invent a tool, algorithm id, parameter, switch, flag id or number. If a name is not in these rules or in the context you were given, say UNSURE and point to ALGORITHM-HELP-DAMIT.md.
- The run watcher's OK / WATCH / PROBLEM verdict is set by code from the flags alone. Heim only explains the flags and never sets or changes the verdict."""
"@ | Set-Content -Path $mf -Encoding UTF8
  & $Ollama create heim -f $mf | Out-Null
  if ($LASTEXITCODE -ne 0) { Die 'heim persona creation failed' }
  Ok "'heim' persona created"
  $PyL = Make-Env $HeimEnv 'python=3.12 pymupdf pypdf numpy'
  Ok "heim python: $PyL"
  foreach ($t in @('rag_index.py','rag_query.py','audit_plugin.py','dam_chain.py','repo_audit.py','suite_check.py','eval_heim.py','run_digest.py','heim_watch.py')) {
    $src = Join-Path $Here "heim\tools\$t"
    if (Test-Path $src) { Copy-Item $src (Join-Path $LocalAI $t) -Force }
  }
  $evalL = Join-Path $Here 'heim\eval'
  if (Test-Path $evalL) { Copy-Item $evalL (Join-Path $LocalAI 'eval') -Recurse -Force }   # code-triage eval set
  # .cmd launchers so heim/damchain work from cmd.exe too
  "@echo off`r`n`"$PyL`" `"$LocalAI\rag_query.py`" %*" | Set-Content (Join-Path $LocalAI 'heim.cmd') -Encoding ASCII
  "@echo off`r`n`"$PyL`" `"$LocalAI\dam_chain.py`" %*" | Set-Content (Join-Path $LocalAI 'damchain.cmd') -Encoding ASCII
  Ok "heim tools -> $LocalAI"
}

# ===========================================================================
if ($DoVor) {
  Say 'vor - literature'
  $Embed = 'qwen3-embedding:0.6b'
  & $Ollama pull $Embed *> $null
  if ($LASTEXITCODE -ne 0) { Warn 'qwen3-embedding pull failed; using nomic-embed-text'; $Embed = 'nomic-embed-text' }
  Pull $ChatModel; Pull $Embed
  $mf = Join-Path $VorDir 'Modelfile'
@"
FROM $ChatModel
PARAMETER num_ctx $NumCtx
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.05
SYSTEM """You are Vor, a research assistant for dam-safety engineers in North Dakota: dam safety, dam and spillway design, breach parameters, inundation mapping, hydrology and flood hazards.
DOMAIN CONTEXT (the vocabulary of this library; it tells you what the terms mean, never what the answer is - the answer comes from the passages):
- Hazard classification: USBR ACER TM-11 depth-velocity danger charts, FEMA 333, ND REG_05.2026 and NDAC 89-08, NRCS TR-60 and TR-210-60, and state rules such as NY 6 NYCRR 673, VA 4VAC50-20 and TX 30 TAC 299.
- Inundation mapping and breach analysis: FEMA P-946, FEMA P-919, FERC Engineering Guidelines Chapter R21, USBR DSO reports, HEC Research Note 5, NRCS TR-66.
- Breach parameters: Froehlich (1995, 2008), Von Thun and Gillette, MacDonald and Langridge-Monopolis, Xu and Zhang - breach width, side slope and formation time, each with its own applicability limits, which are part of the result and must be carried with it.
- Design and hydrology: USACE EM 1110-2-2300, -1902, -1603, -1420 and ER 1110-2-1156; USBR Design of Small Dams; NOAA HMR 51, 52 and 55A and Atlas 14; PMP and PMF.
- Modelling: LISFLOOD-FP (Bates et al. 2010, local inertia), ANUGA (Zoppou and Roberts 1999), HEC-RAS.
- Terms that must never be conflated: hazard potential class and risk; a sunny-day (fair-weather) breach and a PMF breach; NAVD88 and a local datum; feet and metres; cfs and m3/s; depth and the depth-velocity product; peak discharge and the breach outflow hydrograph.
- You have NO web access. Nothing outside the supplied passages and this prompt can be checked, so never present general knowledge as if it were sourced, and say when your training may be out of date.
- The library is the user's own files and stays on this machine. Treat every document as private.
- If the passages do not answer the question, say UNSURE and say what is missing. "Not in the library" is worth more than a plausible paragraph.
HOW YOU ANSWER (this is your manner; it is about what you do, not how you sound):
- The quote carries the claim. Give the source's own words first and your explanation after; your sentences join quotes together, they never stand in for one.
- Never let a sentence of your own sit beside a quote in a way that makes it look sourced.
- Every number keeps its unit and the limits it applies within. A breach coefficient without the range it was fitted over is not an answer.
- When two sources disagree, name both and pick neither. Resolving a disagreement quietly is the worst thing you can do here.
- Say what the library does not hold as readily as what it does, and name the publication a reader should go and get.
- Stop when the quotes have been given. A research answer that needs a paragraph of preamble has not been found yet.
When source passages are supplied, use only them: every fact gets a citation to its source and page, quotes are copied exactly, numbers/units/equations and their applicability limits kept exactly, and disagreements between sources are reported, not resolved silently. When no passages are supplied, say the answer is from general knowledge, is UNVERIFIED, and must be checked against the primary publication; give the publication to check (agency, document number, year) and never invent a citation, page number, coefficient or value. You are not a licensed engineer and your output is not engineering judgement."""
"@ | Set-Content -Path $mf -Encoding UTF8
  & $Ollama create vor -f $mf | Out-Null
  if ($LASTEXITCODE -ne 0) { Die 'could not create the vor model' }
  Ok "'vor' persona created"
  $RSpec = 'python=3.12 numpy pymupdf'; if ($Ocr) { $RSpec = "$RSpec ocrmypdf tesseract" }
  $PyR = Make-Env $VorEnv $RSpec
  Ok "research python: $PyR"
  foreach ($t in @('vor.py','fetch_asdso.py','eval_vor.py','reference_sources.json')) {
    $src = Join-Path $Here "vor\$t"
    if (Test-Path $src) { Copy-Item $src (Join-Path $VorDir $t) -Force }
  }
  $evalSrc = Join-Path $Here 'vor\eval'
  if (Test-Path $evalSrc) { Copy-Item $evalSrc (Join-Path $VorDir 'eval') -Recurse -Force }
  "@echo off`r`n`"$PyR`" `"$VorDir\vor.py`" %*" | Set-Content (Join-Path $VorDir 'vor.cmd') -Encoding ASCII
  Ok "vor tools -> $VorDir; drop PDFs in $RHome\library"
}

# ===========================================================================
$DoIndex = (-not $NoIndex)
if ($DoIndex -and $DoHeim -and (Test-Path (Join-Path $Here 'heim\knowledge'))) {
  Say 'Indexing the Heim knowledge pack'
  & $PyL (Join-Path $LocalAI 'rag_index.py') -c heim_knowledge (Join-Path $Here 'heim\knowledge')
  if ($LASTEXITCODE -ne 0) { Warn 'knowledge index failed' }
  $edocs = Join-Path $RHome 'library\references\software'
  if (Test-Path $edocs) {
    & $PyL (Join-Path $LocalAI 'rag_index.py') -c engine_docs $edocs
    if ($LASTEXITCODE -ne 0) { Warn 'engine-docs index failed' } else { Ok "indexed engine docs from $edocs" }
  }
}

# ---------------------------------------------------------------------------
Say "Step 5 - PowerShell profile ($PROFILE)"
$mark = '# >>> dam local AI (heim + vor) >>>'
$profExists = Test-Path $PROFILE
# The block is REPLACED on every full install, not written once. It used to be skipped when
# its first line was already there, so a machine installed once never received a command
# added later (heim-add, heim-chat). Blocks written under the earlier names go too. A block
# with no closing line is left as it is, and so is the block when only one AI is installed.
$writeBlock = $true
if ($profExists -and (Select-String -Path $PROFILE -Pattern '^# >>> dam local AI \(.*\) >>>$' -Quiet)) {
  if ($DoHeim -and $DoVor) {
    Copy-Item $PROFILE "$PROFILE.bak-localai" -Force
    $kept = New-Object System.Collections.Generic.List[string]
    $buf = New-Object System.Collections.Generic.List[string]
    $inBlock = $false
    foreach ($ln in (Get-Content -Path $PROFILE)) {
      if ($inBlock) {
        $buf.Add($ln)
        if ($ln -match '^# <<< dam local AI <<<$') { $inBlock = $false; $buf.Clear() }
      } elseif ($ln -match '^# >>> dam local AI \(.*\) >>>$') {
        $inBlock = $true; $buf.Clear(); $buf.Add($ln)
      } else { $kept.Add($ln) }
    }
    if ($inBlock) { $kept.AddRange($buf) }
    Set-Content -Path $PROFILE -Value $kept
  } elseif (Select-String -Path $PROFILE -SimpleMatch $mark -Quiet) {
    $writeBlock = $false
  }
}
if ($writeBlock) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PROFILE) | Out-Null
  if ($profExists -and -not (Test-Path "$PROFILE.bak-localai")) { Copy-Item $PROFILE "$PROFILE.bak-localai" -Force }
  $lines = @('', $mark,
    "`$env:OLLAMA_MODELS = '$ModelsDir'",
    "`$env:OLLAMA_FLASH_ATTENTION = '1'",
    "`$env:OLLAMA_KV_CACHE_TYPE = 'q8_0'")
  if ($DoHeim) {
    $lines += "`$env:HEIM_NUM_CTX = '$NumCtx'"
    $lines += "function heim     { & '$PyL' '$LocalAI\rag_query.py' @args }"
    $lines += "function damchain { & '$PyL' '$LocalAI\dam_chain.py' @args }"
    $lines += "function heim-chat { & '$PyL' '$LocalAI\rag_query.py' --chat @args }"
    $lines += "function heim-add { & '$PyL' '$LocalAI\rag_index.py' --add @args }"
    $lines += "`$env:HEIM_WATCH_MODEL = '$WatchModel'"
    $lines += "function heim-digest { & '$PyL' '$LocalAI\run_digest.py' @args }"
    $lines += "function heim-watch  { & '$PyL' '$LocalAI\heim_watch.py' @args }"
  }
  if ($DoVor) {
    $lines += "`$env:VOR_HOME = '$RHome'"
    $lines += "function vor { & '$PyR' '$VorDir\vor.py' @args }"
  }
  $lines += '# <<< dam local AI <<<'
  Add-Content -Path $PROFILE -Value $lines
  Ok "functions written to $PROFILE$(if($profExists){' (backup: '+$PROFILE+'.bak-localai)'})"
} else {
  Warn "profile block in $PROFILE left as it is: this run installs only one of the two AIs. Run without -NoHeim / -NoVor to refresh it."
}

# ---------------------------------------------------------------------------
Say 'Done'
Write-Host "  Open a new PowerShell (the profile loads automatically), then:"
if ($DoHeim)     { Write-Host '    heim "where is the breach width computed"   # set ND_REPO/DWR_REPO/CREST_REPO first for repo audits' }
if ($DoVor) { Write-Host "    vor ingest    # after dropping PDFs in $RHome\library (or run vor\fetch_asdso.py --catalog)" }
Write-Host "  .cmd launchers for cmd.exe are in $LocalAI (heim.cmd, damchain.cmd) and $VorDir (vor.cmd)."
Write-Host '  The local AIs need no admin rights and no GPU; a discrete GPU only makes them faster.'
