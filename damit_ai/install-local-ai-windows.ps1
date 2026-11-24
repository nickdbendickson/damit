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
  .\install-local-ai-windows.ps1 -Prefix DIR      # a SANDBOX: everything in DIR, nothing outside it. Ollama (the
                                                 # portable zip, or an installed one only run), models, Heim tools,
                                                 # envs (conda -p, or venvs) and databases in DIR\local-ai; Vor in
                                                 # DIR\Vor; its own server on port 11435. NO user environment
                                                 # variables and NO PowerShell-profile edits: the commands are in
                                                 # DIR\local-ai\env.ps1 (dot-source it) and env.cmd. VOR_HOME is ignored.
                                                 # Remove it: stop the server (ollama-serve.pid) and delete DIR.
  .\install-local-ai-windows.ps1 -OllamaPort N    # the Ollama port (default 11434; 11435 with -Prefix)
  .\install-local-ai-windows.ps1 -NoModels        # no model pulls, personas or index: server, envs, tools, commands only
  .\install-local-ai-windows.ps1 -AllowProfileScripts   # let PowerShell load your profile (Set-ExecutionPolicy
                                                      # -Scope CurrentUser RemoteSigned) without asking first

  Or double-click  Install-Windows.cmd  in this folder: it starts this script for you.

  Every command also gets a .cmd launcher in %USERPROFILE%\local-ai\bin, which is put on your user PATH, so
  heim, vor, ai, ai-doctor ... work in cmd.exe, and in PowerShell even where scripts are blocked.
  What it prints also goes to %USERPROFILE%\local-ai\install.log. If it stops, run it again: it carries
  on (models already downloaded are not downloaded again). Before the models are pulled it checks the
  free disk space against their size. At the end it runs ai-doctor and prints the first commands to try.

  Run it from the package's damit_ai\ folder: it copies heim\ and vor\ from beside itself.

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
  [switch]$NoWatchModel,
  [string]$Prefix = '',
  [int]$OllamaPort = 0,
  [switch]$NoModels,
  [switch]$AllowProfileScripts
)
$ErrorActionPreference = 'Stop'

# The messages, the stop note and the trap come first, so a stop anywhere below (even before the
# log is open) says how to carry on. `exit 1` from here ends only this script when install-all runs
# it with &; install-all reads $LASTEXITCODE, and the last line below is `exit 0`.
$InstallLog = $null; $Transcript = $false
function Say ($m) { Write-Host "`n== $m" -ForegroundColor White }
function Ok  ($m) { Write-Host "  ok $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "  warn $m" -ForegroundColor Yellow }
function Stop-Log { if ($script:Transcript) { try { Stop-Transcript | Out-Null } catch { } ; $script:Transcript = $false } }
function Rerun-Note {
  Write-Host "`n  The install stopped. What it did so far is kept: fix what it says above, then run the same" -ForegroundColor Yellow
  Write-Host "  command again and it carries on from there (models already downloaded are not downloaded again)." -ForegroundColor Yellow
  if ($script:InstallLog) { Write-Host "  Everything it printed is in $script:InstallLog" -ForegroundColor Yellow }
}
function Die ($m) { Write-Host "  ERROR $m" -ForegroundColor Red; Rerun-Note; Stop-Log; exit 1 }
# any other stop ($ErrorActionPreference = 'Stop'): the same note, and the log closed
trap { Write-Host "  ERROR $_" -ForegroundColor Red; Rerun-Note; Stop-Log; exit 1 }

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
if ($Prefix) {
  # -Prefix: a sandbox. Every path moves into it, and the caches and registries that would otherwise
  # land in your profile (conda's package cache and env list, pip's cache, Ollama's key in
  # ~\.ollama, the GGUF download folder) are pointed into it too.
  $Prefix = [IO.Path]::GetFullPath($Prefix).TrimEnd('\')
  if ($Prefix -eq $env:USERPROFILE -or $Prefix.Length -le 3) { Die '-Prefix needs its own folder' }
  $LocalAI = Join-Path $Prefix 'local-ai'; $ModelsDir = Join-Path $LocalAI 'models'; $VorDir = Join-Path $LocalAI 'vor'
  $RHome = Join-Path $Prefix 'Vor'
  if (-not $OllamaPort) { $OllamaPort = 11435 }
  $env:CONDA_PKGS_DIRS = Join-Path $LocalAI 'conda-pkgs'; $env:CONDA_REGISTER_ENVS = 'false'; $env:PIP_NO_CACHE_DIR = '1'
  if (-not $env:HEIM_GGUF_DIR) { $env:HEIM_GGUF_DIR = Join-Path $LocalAI 'gguf-tmp' }
  # the Heim tools' own defaults are ~\local-ai\...: the index step runs them, so point them here
  $env:HEIM_DB = Join-Path $LocalAI 'knowledge.db'; $env:HEIM_RUNS_DB = Join-Path $LocalAI 'runs.db'; $env:HEIM_REPORTS = Join-Path $LocalAI 'reports'
}
$Bin = Join-Path $LocalAI 'bin'      # a .cmd launcher per command (Step 6)
if ($OllamaPort) {
  $OllamaUrl = "http://127.0.0.1:$OllamaPort"
  $env:OLLAMA_HOST = "127.0.0.1:$OllamaPort"; $env:OLLAMA_URL = $OllamaUrl   # the ollama CLI and the Heim/Vor tools
}
if ($DoHeim -and -not (Test-Path (Join-Path $Here 'heim\tools'))) {
  Write-Host "  warn no heim\tools beside this script ($Here): run it from the package's damit_ai\ folder, or Heim gets no tools and no index" -ForegroundColor Yellow
}

# Everything shown from here on also goes to the install log (Start-Transcript; it records what the
# script writes, though not always the progress bars of ollama.exe), and a stop says how to carry on.
New-Item -ItemType Directory -Force -Path $LocalAI | Out-Null
$InstallLog = Join-Path $LocalAI 'install.log'
try { Start-Transcript -Path $InstallLog -Append | Out-Null; $script:Transcript = $true } catch { $script:Transcript = $false }

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
if (-not $Prefix -and -not $env:VOR_HOME -and ($OldRHome -ne $RHome) -and (VorHasIndex $OldRHome) -and -not (VorHasIndex $RHome)) {
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
if ($Prefix) {
  # the sandbox's own copy first; else the portable zip (no installer: it is only unzipped into the
  # sandbox); else an Ollama already installed here, which is only run, never changed. OllamaSetup.exe
  # and winget are not used, since both install outside the sandbox.
  $own = Join-Path $LocalAI 'ollama\ollama.exe'
  if (-not (Test-Path $own)) {
    $zip = @((Join-Path $Offline 'ollama\ollama-windows-amd64.zip'), (Join-Path $Here '..\offline\tools\ollama-windows-amd64.zip'),
             (Join-Path $Downloads 'ollama-windows-amd64.zip')) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($zip) { Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $LocalAI 'ollama') -Force; Ok "Ollama unzipped to $LocalAI\ollama" }
  }
  $cands = @($own) + $cands
  foreach ($c in $cands) { if ($c -and (Test-Path $c)) { $Ollama = $c; break } }
  if (-not $Ollama) { Die "no Ollama for the sandbox: put ollama-windows-amd64.zip (the portable Ollama, github.com/ollama/ollama/releases) in $Downloads and run this again" }
}
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
if (-not $Prefix) {      # -Prefix writes no user environment variables (env.ps1 / env.cmd carry them)
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ModelsDir, 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_FLASH_ATTENTION', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KV_CACHE_TYPE', 'q8_0', 'User')
}
$env:OLLAMA_MODELS = $ModelsDir; $env:OLLAMA_FLASH_ATTENTION = '1'; $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'

# -Prefix: the port must be this sandbox's own server, or models would go into another Ollama's store
$PidFile = Join-Path $LocalAI 'ollama-serve.pid'
if ($Prefix -and (ServerUp)) {
  $sp = if (Test-Path $PidFile) { Get-Content $PidFile -TotalCount 1 } else { '' }
  if (-not ($sp -and (Get-Process -Id $sp -ErrorAction SilentlyContinue))) {
    Die "something else already answers on $OllamaUrl (another Ollama?). Stop it, or pick a free port with -OllamaPort N"
  }
}
$StartedServer = $false
if (-not (ServerUp)) {
  Ok "starting ollama serve on $OllamaUrl"
  $StartedServer = $true
  # -Prefix: the server's home is the sandbox, so its key (~\.ollama) is made there
  $keep = @{ USERPROFILE = $env:USERPROFILE; HOME = $env:HOME }
  if ($Prefix) { $env:USERPROFILE = $LocalAI; $env:HOME = $LocalAI }
  try {
    $sproc = Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $LocalAI 'ollama-serve.log') `
      -RedirectStandardError  (Join-Path $LocalAI 'ollama-serve.err.log')
  } finally { $env:USERPROFILE = $keep.USERPROFILE; $env:HOME = $keep.HOME }
  if ($Prefix) { $sproc.Id | Set-Content $PidFile -Encoding ASCII }
  for ($i=0; $i -lt 30; $i++) { if (ServerUp) { break }; Start-Sleep 1 }
}
if (-not (ServerUp)) { Die "ollama server did not come up (see $LocalAI\ollama-serve.log)" }
Ok "server up on $OllamaUrl"

# seed models from a pre-downloaded offline bundle (download-all-windows.ps1), so pulls are skipped
if (-not $NoModels -and (Test-Path (Join-Path $Offline 'models\manifests')) -and -not (Test-Path (Join-Path $ModelsDir 'manifests'))) {
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

$CondaLog = Join-Path $LocalAI 'conda.log'
function Make-Env ($name, $spec) {   # returns the python.exe path
  if ($Conda -and $Prefix) {
    # -Prefix: the env is made BY PATH in the sandbox (install-all -Sandbox builds it there first)
    $ep = Join-Path $LocalAI "envs\$name"
    if (-not (Test-Path (Join-Path $ep 'conda-meta'))) {
      # conda's home is the sandbox while it runs (it rewrites ~\.conda\environments.txt otherwise)
      $keep = @{ USERPROFILE = $env:USERPROFILE; HOME = $env:HOME }
      $env:USERPROFILE = Join-Path $LocalAI '.home'; $env:HOME = $env:USERPROFILE
      try { & $Conda create -y -p $ep -c conda-forge --override-channels @($spec -split '\s+') *>> $CondaLog }
      finally { $env:USERPROFILE = $keep.USERPROFILE; $env:HOME = $keep.HOME }
      if ($LASTEXITCODE -ne 0) { Warn "conda create $ep failed (see $CondaLog) - falling back to a venv"; $script:Conda = $null }
    }
    if ($Conda) { return (Join-Path $ep 'python.exe') }
  }
  if ($Conda) {
    $envpath = ((& $Conda env list) | Select-String -Pattern "^\s*$name\s" | Select-Object -First 1)
    if (-not $envpath) {
      Ok "making the conda environment $name (a few minutes; its output goes to $CondaLog)"
      & $Conda create -y -n $name -c conda-forge --override-channels @($spec -split '\s+') *>> $CondaLog
      if ($LASTEXITCODE -ne 0) { Warn "conda create $name failed (see $CondaLog) - falling back to a venv"; $script:Conda = $null }
    }
    if ($Conda) {
      $line = ((& $Conda env list) | Select-String -Pattern "(?<![\w-])$name\s" | Select-Object -First 1).ToString()
      $p = ($line -split '\s+')[-1]
      if ($p) { return (Join-Path $p 'python.exe') }
    }
  }
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  # Windows ships a 'python' in WindowsApps that only opens the Microsoft Store: it is not a Python
  if ($py -and $py -like '*\WindowsApps\*') { Warn "the 'python' on PATH ($py) is the Microsoft Store shortcut, not a Python"; $py = $null }
  if (-not $py) { Die 'no conda and no Python: install Miniforge (github.com/conda-forge/miniforge, no admin needed) and run this again' }
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
  if ($NoModels) { return }             # -NoModels: nothing is pulled
  if (-not ((& $Ollama list) -match [regex]::Escape($m))) {
    Ok "pulling $m (first time, large)"
    & $Ollama pull $m
    if ($LASTEXITCODE -ne 0) { if (-not [bool](@(New-OllamaFromHf $m))[-1]) { Die "pull failed: $m" } }
  }
}

# Free disk space before the downloads (12-22 GB): a full disk half way through a pull is the worst place
# to find out. Sizes: the 4-bit files in the table above; qwen3-embedding is ~0.64 GB.
function Model-Bytes ($tag) {
  $keepSpec = $env:HEIM_GGUF_SPEC; $env:HEIM_GGUF_SPEC = $null
  try { $sp = Get-HfGgufSpec $tag } finally { $env:HEIM_GGUF_SPEC = $keepSpec }
  if ($sp) { return [int64]$sp[3] }
  if ($tag -like 'qwen3-embedding:*') { return [int64]639000000 }
  return [int64]0
}
if (-not $NoModels) {
  $want = @()
  if ($WatchModel -eq 'phi') { $WatchModel = 'phi4-mini' } elseif ($WatchModel -eq 'small') { $WatchModel = 'qwen3:4b' }
  if ($DoHeim) { $want += @($ChatModel, 'nomic-embed-text'); if (-not $NoWatchModel) { $want += $WatchModel } }
  if ($DoVor)  { $want += @($ChatModel, 'qwen3-embedding:0.6b') }
  $haveList = @(& $Ollama list 2>$null)
  $need = [int64]0; $needNames = @()
  foreach ($m in ($want | Where-Object { $_ } | Select-Object -Unique)) {
    if ($haveList -match ('^' + [regex]::Escape($m))) { continue }
    $need += (Model-Bytes $m); $needNames += $m
  }
  # a pull stopped part way left its blobs\*-partial* files: a re-run downloads only the rest
  $part = [int64](Get-ChildItem -Path (Join-Path $ModelsDir 'blobs') -Filter '*-partial*' -File -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
  $need = [Math]::Max([int64]0, $need - $part)
  if ($need -gt 0 -and $env:HEIM_SKIP_DISK_CHECK -eq '1') {
    Ok "disk-space check skipped (HEIM_SKIP_DISK_CHECK=1); models to download: $($needNames -join ', ')"
  } elseif ($need -gt 0 -and -not $StartedServer -and -not $Prefix) {
    # an Ollama that was already running keeps models in ITS folder, which may not be $ModelsDir
    Ok "models to download: $($needNames -join ', ') (about $('{0:N1}' -f ($need / 1GB)) GB) into the folder of the Ollama that was already running; make sure that disk has room. Ctrl+C is safe, a re-run carries on."
  } elseif ($need -gt 0) {
    $free = (Get-PSDrive -Name ((Resolve-Path $ModelsDir).Drive.Name)).Free
    $gb = { param($b) '{0:N1}' -f ($b / 1GB) }
    if ($free -lt ($need + [int64]($need / 10) + 1GB)) {
      $small = if ($ChatModel -ne 'qwen3:8b') { ' (or add -Small for a smaller chat model)' } else { '' }
      Die "not enough free disk space for the models ($($needNames -join ', ')): they need about $(& $gb $need) GB in $ModelsDir and $(& $gb $free) GB is free. Free some space$small, then run this again (or set HEIM_SKIP_DISK_CHECK=1 to try anyway)."
    }
    Ok "models to download: $($needNames -join ', ') (about $(& $gb $need) GB; $(& $gb $free) GB free). Progress shows below; Ctrl+C is safe, a re-run carries on."
  }
}

# ===========================================================================
if ($DoHeim) {
  Say 'Heim - code triage'
  Pull $ChatModel; Pull 'nomic-embed-text'
  # the run-watcher's explainer: a SMALL model. Stock Ollama uses only NVIDIA, Apple or AMD ROCm GPUs, so an
  # Intel Arc / Intel iGPU box runs it on the CPU, which is why a 4B model is the default there.
  if ($WatchModel -eq 'phi') { $WatchModel = 'phi4-mini' } elseif ($WatchModel -eq 'small') { $WatchModel = 'qwen3:4b' }
  if (-not $NoWatchModel -and -not $NoModels) {
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
  if (-not $NoModels) {
  & $Ollama create heim -f $mf | Out-Null
  if ($LASTEXITCODE -ne 0) { Die 'heim persona creation failed' }
  Ok "'heim' persona created"
  }
  $PyL = Make-Env $HeimEnv 'python=3.12 pymupdf pypdf numpy'
  Ok "heim python: $PyL"
  foreach ($t in @('rag_index.py','rag_query.py','audit_plugin.py','dam_chain.py','repo_audit.py','suite_check.py','eval_heim.py','run_digest.py','heim_watch.py','run_results.py','true_hole.py','ai_doctor.py','ai_ui.py','ai_score.py','heim_run.py')) {
    $src = Join-Path $Here "heim\tools\$t"
    if (Test-Path $src) { Copy-Item $src (Join-Path $LocalAI $t) -Force }
  }
  $evalL = Join-Path $Here 'heim\eval'
  if (Test-Path $evalL) { New-Item -ItemType Directory -Force (Join-Path $LocalAI 'eval') | Out-Null; Copy-Item (Join-Path $evalL '*') (Join-Path $LocalAI 'eval') -Recurse -Force }   # code-triage eval set
  # .cmd launchers so heim/damchain work from cmd.exe too
  "@echo off`r`n`"$PyL`" `"$LocalAI\rag_query.py`" %*" | Set-Content (Join-Path $LocalAI 'heim.cmd') -Encoding ASCII
  "@echo off`r`n`"$PyL`" `"$LocalAI\dam_chain.py`" %*" | Set-Content (Join-Path $LocalAI 'damchain.cmd') -Encoding ASCII
  Ok "heim tools -> $LocalAI"
}

# ===========================================================================
if ($DoVor) {
  Say 'vor - literature'
  $Embed = 'qwen3-embedding:0.6b'
  if (-not $NoModels) {
  if (-not ((& $Ollama list) -match [regex]::Escape($Embed))) {
    Ok "pulling $Embed (Vor's search model, about 0.6 GB)"
    & $Ollama pull $Embed
    if ($LASTEXITCODE -ne 0) { Warn 'qwen3-embedding pull failed; using nomic-embed-text'; $Embed = 'nomic-embed-text' }
  }
  }
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
  if (-not $NoModels) {
  & $Ollama create vor -f $mf | Out-Null
  if ($LASTEXITCODE -ne 0) { Die 'could not create the vor model' }
  Ok "'vor' persona created"
  }
  $RSpec = 'python=3.12 numpy pymupdf'; if ($Ocr) { $RSpec = "$RSpec ocrmypdf tesseract" }
  $PyR = Make-Env $VorEnv $RSpec
  Ok "research python: $PyR"
  foreach ($t in @('vor.py','fetch_asdso.py','eval_vor.py','reference_sources.json')) {
    $src = Join-Path $Here "vor\$t"
    if (Test-Path $src) { Copy-Item $src (Join-Path $VorDir $t) -Force }
  }
  $evalSrc = Join-Path $Here 'vor\eval'
  if (Test-Path $evalSrc) { New-Item -ItemType Directory -Force (Join-Path $VorDir 'eval') | Out-Null; Copy-Item (Join-Path $evalSrc '*') (Join-Path $VorDir 'eval') -Recurse -Force }
  "@echo off`r`n`"$PyR`" `"$VorDir\vor.py`" %*" | Set-Content (Join-Path $VorDir 'vor.cmd') -Encoding ASCII
  Ok "vor tools -> $VorDir; drop PDFs in $RHome\library"
}

# ===========================================================================
$DoIndex = (-not $NoIndex -and -not $NoModels)
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
# Vor's library: a new install has nothing to answer from. The offline pack's library (download-all)
# is copied in (nothing already there is overwritten) and indexed; without one, the line to fetch the
# starter library is printed at the end.
$LibEmpty = $false
if ($DoVor) {
  $libDir = Join-Path $RHome 'library'
  $hasDocs = Get-ChildItem -Path $libDir -Recurse -File -Include '*.pdf','*.md','*.txt' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $hasDocs) {
    $LibEmpty = $true
    $offLib = Join-Path $Offline 'Vor\library'
    if (Get-ChildItem -Path $offLib -Recurse -File -Filter '*.pdf' -ErrorAction SilentlyContinue | Select-Object -First 1) {
      Say "Vor's library: the offline pack's publications"
      & robocopy.exe $offLib $libDir /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { Warn "some library files were not copied (robocopy exit $LASTEXITCODE)" } else { Ok "copied into $libDir" }
      $global:LASTEXITCODE = 0
      $LibEmpty = $false
    }
  }
  # index the library when it has files and no index yet (also when an earlier run copied it and
  # its ingest was stopped); a library you already indexed is left to `vor ingest`
  $hasLib = Get-ChildItem -Path $libDir -Recurse -File -Include '*.pdf','*.md','*.txt' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($hasLib -and -not (VorHasIndex $RHome)) {
    if (-not $NoModels -and -not $NoIndex) {
      Say "Vor's library: indexing it"
      Ok 'a while for a full library; Ctrl+C is safe, then run: vor ingest'
      $env:VOR_HOME = $RHome
      & $PyR (Join-Path $VorDir 'vor.py') ingest
      if ($LASTEXITCODE -ne 0) { Warn 'the library index stopped; run: vor ingest' }
      $global:LASTEXITCODE = 0
    } else { Ok "Vor's library is not indexed yet (no models or -NoIndex this run): run  vor ingest  later" }
  }
}

# ---------------------------------------------------------------------------
if (-not $NoModels) {
  Say 'Check (ai-doctor)'
  $env:VOR_HOME = $RHome; $env:VOR_TOOL = Join-Path $VorDir 'vor.py'
  if ($DoVor) { $env:VOR_PYTHON = $PyR }
  if ($DoHeim) {
    & $PyL (Join-Path $LocalAI 'ai_doctor.py')
    if ($LASTEXITCODE -ne 0) { Warn 'ai-doctor found a PROBLEM above: its line says what to run' }
  } else {
    & $PyR (Join-Path $VorDir 'vor.py') doctor
    if ($LASTEXITCODE -ne 0) { Warn 'vor doctor found a PROBLEM above: its line says what to run' }
  }
  $global:LASTEXITCODE = 0
}

# ---------------------------------------------------------------------------
Say "Step 5 - PowerShell profile ($(if ($Prefix) { "$LocalAI\env.ps1" } else { $PROFILE }))"
$mark = '# >>> dam local AI (heim + vor) >>>'
if ($Prefix) {
  # -Prefix: the sandbox's own files, written whole; $PROFILE and the user environment are not touched
  $el = @("# dam local AIs in the sandbox ${Prefix}: dot-source this file ( . '$LocalAI\env.ps1' ). Nothing was added to your PowerShell profile.",
    $mark, "`$env:OLLAMA_MODELS = '$ModelsDir'", "`$env:OLLAMA_FLASH_ATTENTION = '1'", "`$env:OLLAMA_KV_CACHE_TYPE = 'q8_0'",
    "`$env:OLLAMA_HOST = '127.0.0.1:$OllamaPort'", "`$env:OLLAMA_URL = '$OllamaUrl'", "`$env:HEIM_WATCH_URL = '$OllamaUrl'",
    "`$env:HEIM_DB = '$LocalAI\knowledge.db'", "`$env:HEIM_RUNS_DB = '$LocalAI\runs.db'", "`$env:HEIM_REPORTS = '$LocalAI\reports'",
    "`$env:DAMAUDIT_REPORTS = '$LocalAI\reports'", "`$env:DAMAUDIT_GOLDEN = '$LocalAI\golden'",
    "`$env:DAMCHAIN_BATCH_ROOT = '$LocalAI\qgis-batch'", "`$env:DAMCHAIN_CREST_DIR = '$LocalAI\crest-desktop'", "`$env:VOR_TOOL = '$VorDir\vor.py'",
    "`$env:PIP_NO_CACHE_DIR = '1'; `$env:CONDA_PKGS_DIRS = '$LocalAI\conda-pkgs'; `$env:CONDA_REGISTER_ENVS = 'false'",
    "function dam-ollama-serve { `$u = `$env:USERPROFILE; `$env:USERPROFILE = '$LocalAI'; try { (Start-Process '$Ollama' serve -WindowStyle Hidden -PassThru -RedirectStandardOutput '$LocalAI\ollama-serve.log' -RedirectStandardError '$LocalAI\ollama-serve.err.log').Id | Set-Content '$PidFile' } finally { `$env:USERPROFILE = `$u } }")
  $ec = @('@echo off', "rem dam local AIs in the sandbox $Prefix (cmd.exe). Nothing was added to your user environment.",
    "set `"OLLAMA_MODELS=$ModelsDir`"", 'set OLLAMA_FLASH_ATTENTION=1', 'set OLLAMA_KV_CACHE_TYPE=q8_0',
    "set `"OLLAMA_HOST=127.0.0.1:$OllamaPort`"", "set `"OLLAMA_URL=$OllamaUrl`"", "set `"HEIM_WATCH_URL=$OllamaUrl`"",
    "set `"HEIM_DB=$LocalAI\knowledge.db`"", "set `"HEIM_RUNS_DB=$LocalAI\runs.db`"", "set `"HEIM_REPORTS=$LocalAI\reports`"",
    "set `"DAMAUDIT_REPORTS=$LocalAI\reports`"", "set `"DAMAUDIT_GOLDEN=$LocalAI\golden`"",
    "set `"DAMCHAIN_BATCH_ROOT=$LocalAI\qgis-batch`"", "set `"DAMCHAIN_CREST_DIR=$LocalAI\crest-desktop`"", "set `"VOR_TOOL=$VorDir\vor.py`"",
    "set `"PATH=$LocalAI\bin;$LocalAI;$VorDir;%PATH%`"")
  if ($DoHeim) {
    $el += "`$env:HEIM_NUM_CTX = '$NumCtx'"; $el += "`$env:HEIM_WATCH_MODEL = '$WatchModel'"
    $el += "function heim     { & '$PyL' '$LocalAI\rag_query.py' @args }"
    $el += "function damchain { & '$PyL' '$LocalAI\dam_chain.py' @args }"
    $el += "function heim-chat { & '$PyL' '$LocalAI\rag_query.py' --chat @args }"
    $el += "function heim-add { & '$PyL' '$LocalAI\rag_index.py' --add @args }"
    $el += "function heim-doctor { & '$PyL' '$LocalAI\rag_index.py' --doctor @args }"
    $el += "function heim-digest { & '$PyL' '$LocalAI\run_digest.py' @args }"
    $el += "function heim-watch  { & '$PyL' '$LocalAI\heim_watch.py' @args }"
    $el += "function heim-runs   { & '$PyL' '$LocalAI\run_results.py' @args }"
    $el += "function ai-doctor   { & '$PyL' '$LocalAI\ai_doctor.py' @args }"
    $el += "function ai          { & '$PyL' '$LocalAI\ai_ui.py' @args }"
    $el += "function ai-score    { & '$PyL' '$LocalAI\ai_score.py' @args }"
    $el += "function heim-index  { & '$PyL' '$LocalAI\rag_index.py' @args }"
    $ec += "set `"HEIM_NUM_CTX=$NumCtx`""; $ec += "set `"HEIM_WATCH_MODEL=$WatchModel`""
  }
  if ($DoVor) { $el += "`$env:VOR_HOME = '$RHome'"; $el += "`$env:VOR_PYTHON = '$PyR'"; $el += "function vor { & '$PyR' '$VorDir\vor.py' @args }"; $ec += "set `"VOR_HOME=$RHome`""; $ec += "set `"VOR_PYTHON=$PyR`"" }
  $el += '# <<< dam local AI <<<'
  $el | Set-Content (Join-Path $LocalAI 'env.ps1') -Encoding UTF8
  $ec | Set-Content (Join-Path $LocalAI 'env.cmd') -Encoding ASCII
  Ok "commands written to $LocalAI\env.ps1 and env.cmd (your PowerShell profile and user environment left alone)"
} else {
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
    $lines += "function heim-doctor { & '$PyL' '$LocalAI\rag_index.py' --doctor @args }"
    $lines += "`$env:HEIM_WATCH_MODEL = '$WatchModel'"
    $lines += "function heim-digest { & '$PyL' '$LocalAI\run_digest.py' @args }"
    $lines += "function heim-watch  { & '$PyL' '$LocalAI\heim_watch.py' @args }"
    $lines += "function heim-runs   { & '$PyL' '$LocalAI\run_results.py' @args }"
    $lines += "function ai-doctor   { & '$PyL' '$LocalAI\ai_doctor.py' @args }"
    $lines += "function ai          { & '$PyL' '$LocalAI\ai_ui.py' @args }"
    $lines += "function ai-score    { & '$PyL' '$LocalAI\ai_score.py' @args }"
    $lines += "function heim-index  { & '$PyL' '$LocalAI\rag_index.py' @args }"
  }
  if ($DoVor) {
    $lines += "`$env:VOR_HOME = '$RHome'"
    $lines += "`$env:VOR_PYTHON = '$PyR'"
    $lines += "function vor { & '$PyR' '$VorDir\vor.py' @args }"
  }
  $lines += '# <<< dam local AI <<<'
  Add-Content -Path $PROFILE -Value $lines
  Ok "functions written to $PROFILE$(if($profExists){' (backup: '+$PROFILE+'.bak-localai)'})"
} else {
  Warn "profile block in $PROFILE left as it is: this run installs only one of the two AIs. Run without -NoHeim / -NoVor to refresh it."
}
}

# ---------------------------------------------------------------------------
# .cmd launchers for EVERY command in local-ai\bin, which goes on the user PATH. They work in cmd.exe,
# and in PowerShell where the profile does not load (a blocked execution policy): PowerShell runs its
# profile function when there is one and the launcher when there is not. Paths under your user folder
# are written as %USERPROFILE%\..., so a user name with letters outside ASCII survives the .cmd file.
Say "Step 6 - command launchers ($Bin)"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
function Cmd-Path ($p) {
  $u = $env:USERPROFILE.TrimEnd('\')
  if ($p -and $p.StartsWith($u + '\', [StringComparison]::OrdinalIgnoreCase)) { return '%USERPROFILE%' + $p.Substring($u.Length) }
  return $p
}
$launchEnv = @()
if ($DoHeim) { $launchEnv += "set `"HEIM_NUM_CTX=$NumCtx`""; $launchEnv += "set `"HEIM_WATCH_MODEL=$WatchModel`"" }
if ($DoVor)  { $launchEnv += "set `"VOR_HOME=$(Cmd-Path $RHome)`""; $launchEnv += "set `"VOR_PYTHON=$(Cmd-Path $PyR)`"" }
function New-Launcher ($name, $py, $script, $pre) {
  $l = @('@echo off', 'setlocal') + $launchEnv + @("`"$(Cmd-Path $py)`" `"$(Cmd-Path $script)`" $pre%*")
  $l | Set-Content (Join-Path $Bin "$name.cmd") -Encoding ASCII
}
$made = @()
if ($DoHeim) {
  foreach ($c in @(@('heim','rag_query.py',''), @('damchain','dam_chain.py',''), @('heim-chat','rag_query.py','--chat '),
                   @('heim-add','rag_index.py','--add '), @('heim-doctor','rag_index.py','--doctor '),
                   @('heim-index','rag_index.py',''), @('heim-digest','run_digest.py',''), @('heim-watch','heim_watch.py',''),
                   @('heim-runs','run_results.py',''), @('ai-doctor','ai_doctor.py',''), @('ai','ai_ui.py',''),
                   @('ai-score','ai_score.py',''))) {
    New-Launcher $c[0] $PyL (Join-Path $LocalAI $c[1]) $c[2]; $made += $c[0]
  }
}
if ($DoVor) { New-Launcher 'vor' $PyR (Join-Path $VorDir 'vor.py') ''; $made += 'vor' }
Ok "$($made -join ', ')"

# The Local AI icon (ai_ui 1.2.0): a Start menu and desktop shortcut that opens the `ai` page in a window of
# its own. Your own Start menu and desktop: no admin rights. The shortcut runs a one-line .vbs, so no console
# window opens; that runs ai.cmd --app (ai.cmd sets the assistants' settings, as for every command), which
# starts the page's server in the background when it is not running. Not made for a -Prefix sandbox.
if ($DoHeim -and -not $Prefix) {
  try {
    $ico = Join-Path $LocalAI 'local-ai.ico'
    $icoSrc = Join-Path $Here 'heim\icons\local-ai.ico'
    if (Test-Path $icoSrc) { Copy-Item -LiteralPath $icoSrc -Destination $ico -Force }
    $vbs = Join-Path $Bin 'local-ai-app.vbs'
    $aiCmd = Join-Path $Bin 'ai.cmd'
    # %USERPROFILE% in the file, expanded when it runs: an ASCII .vbs keeps a user name with other letters
    @('Set sh = CreateObject("WScript.Shell")',
      ('sh.Run """" & sh.ExpandEnvironmentStrings("' + (Cmd-Path $aiCmd) + '") & """ --app", 0, False')) |
      Set-Content -LiteralPath $vbs -Encoding ASCII
    $wsh = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
      if (-not $dir) { continue }
      $lnk = $wsh.CreateShortcut((Join-Path $dir 'Local AI.lnk'))
      $lnk.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
      $lnk.Arguments = '"' + $vbs + '"'
      $lnk.WorkingDirectory = $LocalAI
      $lnk.Description = 'Heim and Vor, the dam-safety assistants on this computer'
      if (Test-Path $ico) { $lnk.IconLocation = "$ico,0" }
      $lnk.Save()
    }
    Ok 'Local AI icon -> your Start menu and desktop'
  } catch { Warn "could not make the Local AI shortcut ($($_.Exception.Message)): open the page with  ai  instead" }
}
if (-not $Prefix) {
  # the user PATH as stored (REG_EXPAND_SZ, %VARS% kept), with local-ai\bin added once
  $envKey = 'HKCU:\Environment'
  $raw = (Get-Item $envKey).GetValue('Path', '', 'DoNotExpandEnvironmentNames')
  if (-not (($raw -split ';') | Where-Object { $_.TrimEnd('\') -ieq $Bin.TrimEnd('\') })) {
    $new = if ($raw) { $raw.TrimEnd(';') + ';' + $Bin } else { $Bin }
    Set-ItemProperty -Path $envKey -Name 'Path' -Value $new -Type ExpandString
    # tell Windows the environment changed (new windows see the PATH without signing out):
    # setting a user variable through .NET broadcasts WM_SETTINGCHANGE
    [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ModelsDir, 'User')
    Ok "$Bin added to your user PATH (new windows)"
  } else { Ok "$Bin is on your user PATH" }
  $env:Path = "$env:Path;$Bin"
}

# ---------------------------------------------------------------------------
# PowerShell runs no profile under the default policy on Windows 10/11 (Restricted), and then the heim /
# vor functions are not there. This process may run with -ExecutionPolicy Bypass, which hides that, so
# the policy a NEW window gets is worked out from the other scopes.
function Profile-Policy {
  $list = Get-ExecutionPolicy -List
  foreach ($sc in @('MachinePolicy', 'UserPolicy', 'CurrentUser', 'LocalMachine')) {
    $v = "$(($list | Where-Object { "$($_.Scope)" -eq $sc }).ExecutionPolicy)"
    if ($v -and $v -ne 'Undefined') { return $v }
  }
  if ((Get-CimInstance Win32_OperatingSystem).ProductType -ne 1) { return 'RemoteSigned' }   # Windows Server
  return 'Restricted'
}
# -NonInteractive (a scheduled or scripted run) makes Read-Host fail, so it is not asked there
$NonInteractive = [bool]([Environment]::GetCommandLineArgs() | Where-Object { $_ -like '-NonI*' })
if ($Prefix) {
  Say 'Step 7 - execution policy (not checked for a -Prefix sandbox)'
  Ok "env.ps1 is dot-sourced by hand; if PowerShell refuses it, use env.cmd in cmd.exe or the launchers in $Bin"
} else {
Say 'Step 7 - can PowerShell load your profile?'
$pol = Profile-Policy
if ($pol -in @('Restricted', 'AllSigned')) {
  $doIt = [bool]$AllowProfileScripts
  if (-not $doIt -and [Environment]::UserInteractive -and -not $NonInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host "  A new PowerShell window here uses the execution policy '$pol', so it does not load your profile," -ForegroundColor Yellow
    Write-Host "  where the heim / vor commands are written. The usual fix, for your user only, is:" -ForegroundColor Yellow
    Write-Host "      Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" -ForegroundColor Yellow
    Write-Host "  (scripts you made or installed on this PC run; scripts downloaded from the internet must be signed)." -ForegroundColor Yellow
    try { $ans = Read-Host '  Do that now? Type y for yes, anything else leaves it as it is' } catch { $ans = '' }
    $doIt = ($ans -match '^\s*y(es)?\s*$')
  }
  if ($doIt) {
    try { Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force -ErrorAction Stop }
    catch {
      # this window's own -ExecutionPolicy Bypass outranks CurrentUser: PowerShell still SAVES the new
      # setting and then reports the override as an error. It is not a failure; Profile-Policy re-checks.
      if ("$($_.FullyQualifiedErrorId)" -notlike '*ExecutionPolicyOverride*') { Warn "could not change it: $($_.Exception.Message)" }
    }
    $pol = Profile-Policy
  }
  if ($pol -in @('Restricted', 'AllSigned')) {
    Warn "the policy stays '$pol' (your organisation may set it). The commands still work: the .cmd launchers in $Bin run them in PowerShell and in cmd.exe."
  } else { Ok "execution policy for your user: $pol (your profile loads in a new window)" }
} else { Ok "execution policy '$pol': your profile loads" }
}

# ---------------------------------------------------------------------------
Say 'Done'
if ($Prefix) {
  Write-Host "  Sandbox ${Prefix}: in each PowerShell run  . '$LocalAI\env.ps1'  (cmd.exe: $LocalAI\env.cmd). Its Ollama: $OllamaUrl (dam-ollama-serve starts it again)."
  Write-Host "  To remove it: Stop-Process -Id (Get-Content '$PidFile'), then delete $Prefix."
  Write-Host "  Try it now (after loading env.ps1 or env.cmd):"
} else {
  Write-Host "  Try it now. Open a NEW PowerShell or Command Prompt window first (it reads the new commands), then:"
}
if ($DoVor)  { Write-Host '    vor "what breach width does Froehlich 2008 give?"     answered from your library, quotes checked' }
if ($DoHeim) {
  Write-Host '    heim "what does REFINE_NEAR do?"                      the suite''s tools and known behaviours'
  Write-Host '    ai                                                     both on one page in your browser'
  if (-not $Prefix) { Write-Host '    Local AI (Start menu or desktop)                       the same page in a window of its own: no typing' }
  Write-Host '    heim help                                              the short list of commands'
}
if ($DoVor -and $LibEmpty) {
  Write-Host "  Vor's library is empty, so vor has nothing to quote yet. Add your own PDFs:  vor add FILE ..."
  Write-Host "  or fetch the starter library of public dam-safety publications (a few hundred MB), then index it:"
  Write-Host "    PowerShell:   & '$PyR' '$VorDir\fetch_asdso.py' --catalog"
  Write-Host "    Command Prompt:  `"$PyR`" `"$VorDir\fetch_asdso.py`" --catalog"
  Write-Host "    then:  vor ingest"
}
$doctor = if ($DoHeim) { 'ai-doctor' } else { 'vor doctor' }
Write-Host "  Check it again any time:  $doctor     Everything this printed:  $InstallLog"
if ($DoHeim) { Write-Host '  For developers: set ND_REPO / DWR_REPO / CREST_REPO to your clones, then  heim "where is the breach width computed"' }
Write-Host '  The local AIs need no admin rights and no GPU; a discrete GPU only makes them faster.'
Stop-Log
exit 0
