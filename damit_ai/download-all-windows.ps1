<#
=============================================================================
download-all-windows.ps1 — pre-download EVERYTHING the Windows installer needs
into damit_ai\offline\, so install-local-ai-windows.ps1 can then run offline:

  offline\ollama\OllamaSetup.exe (+ SHA256SUMS)   the Ollama installer
  offline\models\                                 the AI models (Heim + vor)
  offline\Vor\library\                    the vor PDF library + url list

Run this on a machine WITH network, then carry the whole damit_ai\ folder to the
target and run install-local-ai-windows.ps1 there (it picks up offline\ automatically).

  .\download-all-windows.ps1                       # Ollama + default models + library
  .\download-all-windows.ps1 -NoModels             # skip the (large) model pull
  .\download-all-windows.ps1 -Models 'qwen3:14b nomic-embed-text'
  .\download-all-windows.ps1 -NoLibrary            # skip the PDF library
  .\download-all-windows.ps1 -OllamaVersion v0.12.6

Policy: downloads FILES only (never piped into a shell); every file is checked against
Ollama's own published sha256. No admin, no pip. Your own Ollama/models are untouched.
=============================================================================
#>
[CmdletBinding()]
param(
  [switch]$NoModels,
  [switch]$NoLibrary,
  [string]$Models = 'qwen3:30b-a3b qwen3:14b nomic-embed-text qwen3-embedding:0.6b',
  [string]$OllamaVersion = 'latest'
)
$ErrorActionPreference = 'Stop'
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Offline = Join-Path $Here 'offline'
$Py      = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

function Say ($m) { Write-Host "`n== $m" -ForegroundColor White }
function Ok  ($m) { Write-Host "  ok $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "  warn $m" -ForegroundColor Yellow }
function Die ($m) { Write-Host "  ERROR $m" -ForegroundColor Red; exit 1 }
function Sha ($p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }

function Fetch ($url, $dest, $want) {   # keep a matching file, else download + verify
  if ((Test-Path $dest) -and $want -and $want -ne '-' -and (Sha $dest) -eq $want) { Ok "have $(Split-Path -Leaf $dest) (sha256 ok)"; return $true }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  try { Invoke-WebRequest -Uri $url -OutFile "$dest.part" -UseBasicParsing } catch { Remove-Item "$dest.part" -EA SilentlyContinue; Warn "download failed: $url"; return $false }
  if (-not $want -or $want -eq '-' -or (Sha "$dest.part") -eq $want) { Move-Item -Force "$dest.part" $dest; Ok "downloaded $(Split-Path -Leaf $dest)"; return $true }
  Remove-Item "$dest.part" -EA SilentlyContinue; Warn "sha256 mismatch, discarded: $url"; return $false
}

$base = 'https://github.com/ollama/ollama/releases'

# ---------------------------------------------------------------------------
Say "Ollama runtime -> offline\ollama (version: $OllamaVersion)"
if ($OllamaVersion -eq 'latest') {
  try {
    $r = Invoke-WebRequest -Uri "$base/latest" -MaximumRedirection 5 -UseBasicParsing
    $OllamaVersion = ($r.BaseResponse.ResponseUri.AbsoluteUri -split '/tag/')[-1]
  } catch { $OllamaVersion = '' }
  if (-not $OllamaVersion) { Die 'could not resolve the latest Ollama version (pass -OllamaVersion)' }
  Ok "latest Ollama release is $OllamaVersion"
}
# published checksums for this release
$sumsTmp = New-TemporaryFile
try { Invoke-WebRequest -Uri "$base/download/$OllamaVersion/sha256sum.txt" -OutFile $sumsTmp -UseBasicParsing } catch { Warn 'could not fetch sha256sum.txt (downloads will be unverified)' }
function PublishedHash ($asset) {
  $line = Select-String -Path $sumsTmp -Pattern ([regex]::Escape($asset)) | Select-Object -First 1
  if ($line) { ($line.Line -split '\s+')[0] } else { '-' }
}

# the installer consumes OllamaSetup.exe; we also grab the portable zip to pull models
$setup = 'OllamaSetup.exe'
$hSetup = PublishedHash $setup
if (Fetch "$base/download/$OllamaVersion/$setup" (Join-Path $Offline "ollama\$setup") $hSetup) {
  "$(Sha (Join-Path $Offline "ollama\$setup"))  $setup" | Set-Content (Join-Path $Offline 'ollama\SHA256SUMS') -Encoding ASCII
  Ok 'wrote offline\ollama\SHA256SUMS'
}

# ---------------------------------------------------------------------------
if (-not $NoModels) {
  Say "AI models -> offline\models: $Models"
  $mdir = Join-Path $Offline 'models'; New-Item -ItemType Directory -Force -Path $mdir | Out-Null
  $zip = 'ollama-windows-amd64.zip'
  $hZip = PublishedHash $zip
  $tmpZip = Join-Path $env:TEMP $zip
  if (Fetch "$base/download/$OllamaVersion/$zip" $tmpZip $hZip) {
    $tmp = Join-Path $env:TEMP ("ollama-portable-" + [guid]::NewGuid().ToString('N'))
    Expand-Archive -Path $tmpZip -DestinationPath $tmp -Force
    $ol = Get-ChildItem -Path $tmp -Recurse -Filter 'ollama.exe' | Select-Object -First 1
    if ($ol) {
      $env:OLLAMA_HOST = '127.0.0.1:11499'; $env:OLLAMA_MODELS = $mdir
      $srv = Start-Process -FilePath $ol.FullName -ArgumentList 'serve' -WindowStyle Hidden -PassThru
      for ($i=0; $i -lt 30; $i++) { try { Invoke-RestMethod "http://127.0.0.1:11499/api/version" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1 } }
      foreach ($m in ($Models -split '\s+' | Where-Object { $_ })) {
        Write-Host "  pulling $m ..."
        & $ol.FullName pull $m; if ($LASTEXITCODE -eq 0) { Ok $m } else { Warn "could not pull $m" }
      }
      Stop-Process -Id $srv.Id -Force -EA SilentlyContinue
      Remove-Item Env:\OLLAMA_HOST, Env:\OLLAMA_MODELS -EA SilentlyContinue
      Ok "models in $mdir"
    } else { Warn 'ollama.exe not found in the portable zip; models skipped' }
    Remove-Item $tmp -Recurse -Force -EA SilentlyContinue; Remove-Item $tmpZip -Force -EA SilentlyContinue
  }
}

# ---------------------------------------------------------------------------
if (-not $NoLibrary) {
  Say "vor library -> offline\Vor\library"
  $lib = Join-Path $Offline 'Vor'; New-Item -ItemType Directory -Force -Path (Join-Path $lib 'library') | Out-Null
  $fetch = Join-Path $Here 'vor\fetch_asdso.py'
  if (Test-Path $fetch) {
    $env:VOR_HOME = $lib
    & $Py $fetch --urls (Join-Path $lib 'library\library-urls.txt')
    & $Py $fetch --catalog --asdso
    Remove-Item Env:\VOR_HOME -EA SilentlyContinue
    Ok "library in $lib\library"
  } else { Warn 'vor\fetch_asdso.py not found; skipped' }
}

# ---------------------------------------------------------------------------
Say 'Done'
Write-Host "  offline\ is now populated. Carry the whole damit_ai\ folder to the target and run:"
Write-Host "      powershell -ExecutionPolicy Bypass -File .\install-local-ai-windows.ps1"
Write-Host "  It uses offline\ollama (no Ollama download) and seeds models from offline\models."
