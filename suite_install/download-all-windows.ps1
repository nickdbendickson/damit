<#
=============================================================================
download-all-windows.ps1  -  fill this package's offline\ folder so install-all can run
                             with NO network (Windows host)
=============================================================================
Double-click download-all-windows.cmd, or:
    powershell -ExecutionPolicy Bypass -File .\download-all-windows.ps1 [options]

  -Platform win-64      (default) or linux-64 / osx-arm64 / osx-64 / all: build a set for
                        another machine (the same files download-all.sh fetches)
  -NoModels             skip the AI models (the AI installer pulls them online instead)
  -Models "a b"         which models (default: qwen3:30b-a3b qwen3:14b nomic-embed-text qwen3-embedding:0.6b)
  -NoLibrary            skip the vor reference library
  -Pack                 also zip each platform's set as offline-<platform>.zip

Every file is checked against the sha256 pinned in locks\ before it is put in place; a
cut-off download is resumed, and up to 4 passes run by themselves (DAMSUITE_DL_PASSES).
Files are downloaded only; nothing downloaded is run, except the pinned portable Ollama on a
side port (127.0.0.1:11499) to pull the models. No admin, nothing installed.
=============================================================================
#>
param([string[]]$Platform = @('win-64'), [switch]$NoModels, [string]$Models = '', [switch]$NoLibrary, [switch]$Pack)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Locks = Join-Path $Here 'locks'
if (-not $Models) { $Models = if ($env:DAMSUITE_MODELS) { $env:DAMSUITE_MODELS } else { 'qwen3:30b-a3b qwen3:14b nomic-embed-text qwen3-embedding:0.6b' } }
function Say($m)  { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  ok  $m" }
function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Sha($f)  { (Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower() }
function LockLines($f) { Get-Content -LiteralPath $f | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { ,($_ -split '\s+') } }
if ($Platform -contains 'all') { $Platform = @('linux-64','osx-arm64','osx-64','win-64') }
foreach ($p in $Platform) { if (-not (Test-Path (Join-Path $Locks $p))) { throw "no locks for platform '$p'" } }
$Curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
$script:Bad = 0

# Fetch-List: items with Url, Dest, Sha. Each missing file is downloaded to <Dest>.part and
# moved into place only once its sha256 matches (same scheme as download-all.sh):
#   DAMSUITE_DL_PARALLEL (default 3) at a time with curl.exe; curl retries every error and
#   resumes a cut-off .part (-C -); up to DAMSUITE_DL_PASSES (default 4) passes run by
#   themselves. A .part that did not grow in a pass and still fails its sha256 is deleted and
#   starts over. Without a new enough curl.exe, Invoke-WebRequest fetches one by one (no resume).
$DlParallel = if ($env:DAMSUITE_DL_PARALLEL) { [int]$env:DAMSUITE_DL_PARALLEL } else { 3 }
$DlPasses = if ($env:DAMSUITE_DL_PASSES) { [int]$env:DAMSUITE_DL_PASSES } else { 4 }
$CurlMaj = 0; $CurlMin = 0
if ($Curl) { $v = (& $Curl --version | Select-Object -First 1); if ($v -match 'curl (\d+)\.(\d+)') { $CurlMaj = [int]$matches[1]; $CurlMin = [int]$matches[2] } }
function CurlAtLeast($maj, $min) { ($CurlMaj -gt $maj) -or ($CurlMaj -eq $maj -and $CurlMin -ge $min) }
function FSize($f) { if (Test-Path -LiteralPath $f) { (Get-Item -LiteralPath $f).Length } else { 0 } }

function Fetch-List($items) {
  $pass = 1
  while ($true) {
    $todo = New-Object System.Collections.Generic.List[object]
    foreach ($t in $items) {
      if ((Test-Path -LiteralPath $t.Dest) -and ((Sha $t.Dest) -eq $t.Sha)) { continue }
      New-Item -ItemType Directory -Force -Path (Split-Path $t.Dest) | Out-Null
      Remove-Item -LiteralPath $t.Dest -ErrorAction SilentlyContinue
      $part = "$($t.Dest).part"
      if ((Test-Path -LiteralPath $part) -and ((Sha $part) -eq $t.Sha)) { Move-Item -Force -LiteralPath $part -Destination $t.Dest; continue }
      $todo.Add([pscustomobject]@{ Url = $t.Url; Dest = $t.Dest; Part = $part; Sha = $t.Sha; Before = (FSize $part) })
    }
    if ($todo.Count -eq 0) { break }
    if ($pass -gt $DlPasses) {
      foreach ($t in $todo) { Warn "still missing after $DlPasses passes: $(Split-Path $t.Dest -Leaf)"; $script:Bad++ }
      Warn 're-run to carry on: finished files are kept and partial ones (.part) resume'
      break
    }
    Write-Host "  downloading $($todo.Count) file(s), $DlParallel at a time (pass $pass of $DlPasses) ..."
    if (CurlAtLeast 7 66) {
      $cfg = Join-Path $env:TEMP 'damsuite-curl.cfg'
      $lines = foreach ($t in $todo) { "url = `"$($t.Url)`""; "output = `"$($t.Part -replace '\\','/')`"" }
      [IO.File]::WriteAllLines($cfg, $lines)
      $opts = @('-fsSL', '--connect-timeout', '30', '--speed-limit', '1024', '--speed-time', '60', '--retry', '5', '--retry-delay', '5', '-C', '-')
      if (CurlAtLeast 7 71) { $opts += '--retry-all-errors' }
      if ($DlParallel -gt 1) { $opts += @('--parallel', '--parallel-max', "$DlParallel") }
      & $Curl @opts -K $cfg
      if ($LASTEXITCODE -ne 0) { Write-Host '  some downloads were cut off; checking ...' }
      Remove-Item $cfg -ErrorAction SilentlyContinue
    } else {
      foreach ($t in $todo) { try { Invoke-WebRequest -UseBasicParsing -Uri $t.Url -OutFile $t.Part } catch { Write-Host "  download cut off: $(Split-Path $t.Dest -Leaf)" } }
    }
    $left = 0
    foreach ($t in $todo) {
      if ((Test-Path -LiteralPath $t.Part) -and ((Sha $t.Part) -eq $t.Sha)) { Move-Item -Force -LiteralPath $t.Part -Destination $t.Dest }
      else { $left++; if ((FSize $t.Part) -le $t.Before) { Remove-Item -LiteralPath $t.Part -ErrorAction SilentlyContinue } }
    }
    $pass++
    if ($left -gt 0 -and $pass -le $DlPasses) { Write-Host "  $left file(s) not finished; pass $pass in $($pass*10) s ..."; Start-Sleep -Seconds ($pass*10) }
  }
}

$extra = LockLines (Join-Path $Locks 'extra.lock')
foreach ($P in $Platform) {
  Say "Platform $P"
  $seen = @{}; $items = New-Object System.Collections.Generic.List[object]
  foreach ($lf in Get-ChildItem (Join-Path $Locks $P) -Filter '*.lock') {
    foreach ($l in (LockLines $lf.FullName)) {
      $parts = $l[0] -split '/'; $n = "$($parts[-2])\$($parts[-1])"; if ($seen.ContainsKey($n)) { continue }; $seen[$n] = 1
      $items.Add([pscustomobject]@{ Url = $l[0]; Dest = (Join-Path $Here "offline\conda\$P\$n"); Sha = $l[1] })
    }
  }
  Write-Host "  conda packages: $($items.Count)"
  foreach ($l in $extra) { if ($l[0] -eq $P -and $l[1] -ne 'ollama-pull') {
    $items.Add([pscustomobject]@{ Url = $l[3]; Dest = (Join-Path $Here ($l[2] -replace '/','\')); Sha = $l[4] }) } }
  Fetch-List $items
  $od = Join-Path $Here 'damit_ai\offline\ollama'
  if (Test-Path $od) {
    $sums = foreach ($l in $extra) { if ($l[1] -eq 'ollama') { $n = ($l[2] -split '/')[-1]; if (Test-Path (Join-Path $od $n)) { "$($l[4])  $n" } } }
    [IO.File]::WriteAllLines((Join-Path $od 'SHA256SUMS'), [string[]]($sums | Select-Object -Unique))
  }
  Ok "$P done"
}

if (-not $NoModels -and $Models) {
  Say "AI models -> damit_ai\offline\models: $Models"
  $mdir = Join-Path $Here 'damit_ai\offline\models'; New-Item -ItemType Directory -Force -Path $mdir | Out-Null
  $pl = $extra | Where-Object { $_[1] -eq 'ollama-pull' } | Select-Object -First 1
  $zip = Join-Path $Here ($pl[2] -replace '/','\')
  Fetch-List @([pscustomobject]@{ Url = $pl[3]; Dest = $zip; Sha = $pl[4] })
  if (Test-Path $zip) {
    $tmp = Join-Path $env:TEMP 'damsuite-ollama'; if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp
    $ol = (Get-ChildItem $tmp -Recurse -Filter 'ollama.exe' | Select-Object -First 1).FullName
    $env:OLLAMA_HOST = '127.0.0.1:11499'; $env:OLLAMA_MODELS = $mdir
    $srv = Start-Process -FilePath $ol -ArgumentList 'serve' -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:11499/api/version' | Out-Null; break } catch { Start-Sleep 1 } }
    foreach ($m in ($Models -split '\s+')) { if (-not $m) { continue }
      Write-Host "  pulling $m ..."; & $ol pull $m; if ($LASTEXITCODE -eq 0) { Ok $m } else { Warn "could not pull $m"; $script:Bad++ } }
    Stop-Process -Id $srv.Id -ErrorAction SilentlyContinue
    Remove-Item Env:OLLAMA_HOST, Env:OLLAMA_MODELS -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
  } else { Warn 'no portable Ollama to pull models with; models skipped' }
}

if (-not $NoLibrary) {
  Say 'vor library -> damit_ai\offline\Vor\library'
  $fa = Join-Path $Here 'damit_ai\vor\fetch_asdso.py'
  $py = $null
  foreach ($c in @((Join-Path $env:USERPROFILE 'miniforge3\envs\ndvor\python.exe'), (Join-Path $env:USERPROFILE 'miniforge3\python.exe'))) { if (Test-Path $c) { $py = $c; break } }
  if (-not $py) { $g = Get-Command python.exe -ErrorAction SilentlyContinue; if ($g -and $g.Source -notmatch 'WindowsApps') { $py = $g.Source } }
  if ($py -and (Test-Path $fa)) {
    $lib = Join-Path $Here 'damit_ai\offline\Vor'; New-Item -ItemType Directory -Force -Path (Join-Path $lib 'library') | Out-Null
    $env:VOR_HOME = $lib; & $py $fa --catalog --asdso; if ($LASTEXITCODE -ne 0) { Warn 'some library files failed' }
    Remove-Item Env:VOR_HOME
  } else { Warn 'library skipped (needs a Python: run it again after install-all, or use download-all.sh on a Mac / Linux box)' }
}

if ($Pack) {
  Say 'Packing offline sets'
  foreach ($P in $Platform) {
    $z = Join-Path $Here "offline-$P.zip"; if (Test-Path $z) { Remove-Item $z }
    $rel = @("offline/conda/$P")
    foreach ($l in $extra) { if ($l[0] -eq $P -and $l[1] -ne 'ollama-pull' -and (Test-Path (Join-Path $Here $l[2]))) { $rel += $l[2] } }
    if (Test-Path (Join-Path $Here 'damit_ai\offline\ollama\SHA256SUMS')) { $rel += 'damit_ai/offline/ollama/SHA256SUMS' }
    # tar.exe (built into Windows 10+) keeps the folder paths, so the zip unzips into place on any OS
    & tar.exe -a -c -f $z --exclude '*.part' -C $Here @($rel | Select-Object -Unique)
    if ($LASTEXITCODE -eq 0) { Ok "$z ($([math]::Round((Get-Item $z).Length / 1MB)) MB); unzip it in the package folder on the target" } else { Warn "could not pack $z" }
  }
}

Say $(if ($script:Bad -gt 0) { "Done with $($script:Bad) problem(s): run it again to retry." } else { 'Done.' })
Write-Host '  Now run install-all-windows.cmd from this folder (it uses offline\ and downloads nothing).'
if ($script:Bad -gt 0) { exit 1 }
