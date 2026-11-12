<#
=============================================================================
install-all-windows.ps1  -  the whole dam suite on Windows 10/11 (x64), in one go
=============================================================================
Double-click install-all-windows.cmd, or in PowerShell:
    powershell -ExecutionPolicy Bypass -File .\install-all-windows.ps1 [options]

Installs, for you only (no admin, no pip, no system packages):
  * DamSafety plugins (Core FIRST, then Setup, Data, Screening, Runner, Hazard,
    Hazard Lite, PMP)                                  -> QGIS profile "damsafety"
  * DamIT plugins (Core, Catalog, Setup, Data, Screener, Runner, Hazard, Hazard Lite,
    PMP)                                               -> QGIS profile "damit"
  * QGIS 3.34 (conda env ndqgis), ANUGA 4.1 + gmsh 4.15 (env ndanuga)
  * LISFLOOD-FP 8.3 with the Runner patch (lisflood\windows-x64\lisflood.exe, no DLLs)
  * the local AIs from damit_ai: Lumo and dam-research (Ollama, env, models, library)
  * a launcher per profile (in %USERPROFILE%\dam-suite and on the Desktop)

OFFLINE: if offline\ is filled (an offline set unzipped here, or download-all run on any
networked machine), NOTHING is downloaded. Otherwise the missing files are fetched first
by download-all-windows.ps1, each checked against the sha256 pinned in locks\.

Options: -Offline (refuse to download)  -Check  -NoDamSafety  -NoDamIT  -NoAI  -NoLumo
         -NoResearch  -SkipLisflood  -NoShortcuts
It never touches your data folders, offline packs, or other QGIS profiles.
=============================================================================
#>
param(
  [switch]$Offline, [switch]$Check, [switch]$NoDamSafety, [switch]$NoDamIT, [switch]$NoAI,
  [switch]$NoLumo, [switch]$NoResearch, [switch]$SkipLisflood, [switch]$NoShortcuts
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$P = 'win-64'
$Ver = if (Test-Path (Join-Path $Here 'VERSION')) { (Get-Content (Join-Path $Here 'VERSION') -TotalCount 1) } else { 'dev' }
$Stamp = "dam-suite install-all $Ver"
$Prefix = if ($env:DAMSUITE_PREFIX) { $env:DAMSUITE_PREFIX } else { Join-Path $env:USERPROFILE 'dam-suite' }
$MiniforgeDir = if ($env:DAMSUITE_MINIFORGE) { $env:DAMSUITE_MINIFORGE } else { Join-Path $env:USERPROFILE 'miniforge3' }
$Profiles = Join-Path $env:APPDATA 'QGIS\QGIS3\profiles'
$DsProfile = 'damsafety'; $DiProfile = 'damit'
$DsDir = Join-Path $Profiles $DsProfile; $DiDir = Join-Path $Profiles $DiProfile
$DsPlugins = @('DamSafety_Core','DamSafety_Setup','DamSafety_Data','DamSafety_Screening','DamSafety_Runner','DamSafety_Hazard','DamSafety_HazardLite','DamSafety_PMP')
$DiPlugins = @('damit_core','damit_catalog','damit_setup','damit_data','damit_screener','damit_runner','damit_hazard','damit_hazardlite','damit_pmp')
$DoDs = -not $NoDamSafety; $DoDi = -not $NoDamIT
$DoLumo = -not ($NoAI -or $NoLumo); $DoResearch = -not ($NoAI -or $NoResearch)
$Threads = if ($env:DAMSUITE_THREADS) { $env:DAMSUITE_THREADS } else { [Environment]::ProcessorCount }
$CondaPkgs = Join-Path $Here "offline\conda\$P"

function Say($m)  { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK  $m" }
function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Sha($f)  { (Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower() }
function VerOf($d) { $m = Join-Path $d 'metadata.txt'; if (Test-Path $m) { ((Select-String -LiteralPath $m -Pattern '^version=' | Select-Object -First 1).Line -replace '^version=','').Trim() } else { '' } }
function HasText($f, $t) { [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($f)).Contains($t) }
function PkgPath($url) { $parts = $url -split '/'; Join-Path $CondaPkgs "$($parts[-2])\$($parts[-1])" }
function LockLines($f) { Get-Content -LiteralPath $f | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { ,($_ -split '\s+') } }
function ExtraLines { LockLines (Join-Path $Here 'locks\extra.lock') | Where-Object { $_[0] -eq $P -and $_[1] -ne 'ollama-pull' } }

if (-not [Environment]::Is64BitOperatingSystem) { Die 'This needs 64-bit Windows.' }

function Find-Conda {
  foreach ($c in @($env:DAMSUITE_CONDA, (Join-Path $MiniforgeDir 'Scripts\conda.exe'),
                   (Join-Path $env:USERPROFILE 'Miniforge3\Scripts\conda.exe'),
                   (Join-Path $env:USERPROFILE 'miniconda3\Scripts\conda.exe'))) {
    if ($c -and (Test-Path $c)) { return $c }
  }
  $g = Get-Command conda.exe -ErrorAction SilentlyContinue
  if ($g) { return $g.Source }
  return $null
}
$Conda = Find-Conda

# ---------------------------------------------------------------------------
if ($Check) {
  Say "dam suite on $P"
  if ($Conda) { $base = (& $Conda info --base).Trim(); Write-Host "  conda: $Conda"
    foreach ($e in 'ndqgis','ndanuga','ndresearch','ndlumo') { Write-Host ("    env {0}: {1}" -f $e, $(if (Test-Path "$base\envs\$e\conda-meta") {'present'} else {'missing'})) } }
  else { Write-Host '  conda: not found' }
  $lf = Join-Path $Prefix 'bin\lisflood.exe'
  Write-Host ("  LISFLOOD-FP: $lf " + $(if (Test-Path $lf) { if (HasText $lf 'inittm_depth') {'OK (Runner patch present)'} else {'UNPATCHED'} } else {'missing'}))
  Write-Host "  DamSafety profile ($DsProfile):"; foreach ($p in $DsPlugins) { $d = Join-Path $DsDir "python\plugins\$p"; Write-Host ("    $p " + $(if (Test-Path $d) { VerOf $d } else { 'missing' })) }
  Write-Host "  DamIT profile ($DiProfile):";     foreach ($p in $DiPlugins) { $d = Join-Path $DiDir "python\plugins\$p"; Write-Host ("    $p " + $(if (Test-Path $d) { VerOf $d } else { 'missing' })) }
  $inst = Join-Path $Prefix 'INSTALLED.txt'; if (Test-Path $inst) { Write-Host ''; Get-Content $inst }
  exit 0
}

New-Item -ItemType Directory -Force -Path (Join-Path $Prefix 'logs') | Out-Null
$Log = Join-Path $Prefix ("logs\install_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
Start-Transcript -Path $Log | Out-Null
Say "$Stamp on $P.  Log: $Log"

# ---------------------------------------------------------------------------
# 1. offline files: use them, or fetch what is missing (pinned + sha256-checked)
# ---------------------------------------------------------------------------
$Roles = @('ndqgis','ndanuga'); if ($DoLumo -or $DoResearch) { $Roles += 'ndresearch' }
$miss = 0
foreach ($r in $Roles) {
  foreach ($l in (LockLines (Join-Path $Here "locks\$P\$r.lock"))) {
    if (-not (Test-Path (PkgPath $l[0]))) { $miss++ } } }
foreach ($l in ExtraLines) { if (-not (Test-Path (Join-Path $Here $l[2]))) { $miss++ } }
if ($miss -gt 0) {
  if ($Offline) { Die "$miss file(s) are missing from offline\ and -Offline was given. Unzip offline-$P.zip here, or run download-all-windows.cmd" }
  Say "$miss file(s) not in offline\ yet: fetching them (pinned, sha256-checked)."
  $dl = @{ Platform = $P; NoModels = $true }; if (-not $DoResearch) { $dl.NoLibrary = $true }
  & (Join-Path $Here 'download-all-windows.ps1') @dl
  if (-not $?) { Warn 'download-all reported problems (continuing; checked below)' }
} else { Ok 'every installer file is in offline\ (nothing will be downloaded)' }

# ---------------------------------------------------------------------------
# 2. conda (Miniforge 26.9.4-2 from offline\miniforge, sha256-checked, just for you)
# ---------------------------------------------------------------------------
if (-not $Conda) {
  $mf = ExtraLines | Where-Object { $_[1] -eq 'miniforge' } | Select-Object -First 1
  $exe = Join-Path $Here $mf[2]
  if (-not (Test-Path $exe)) { Die "No conda found and no Miniforge installer at $exe" }
  if ((Sha $exe) -ne $mf[4]) { Die "Miniforge installer failed its sha256 check: $exe" }
  Say "Installing Miniforge (checked) to $MiniforgeDir (just for you, not on PATH)"
  Start-Process -Wait -FilePath $exe -ArgumentList '/InstallationType=JustMe','/RegisterPython=0','/AddToPath=0','/S',"/D=$MiniforgeDir"
  $Conda = Join-Path $MiniforgeDir 'Scripts\conda.exe'
  if (-not (Test-Path $Conda)) { Die "Miniforge did not install to $MiniforgeDir" }
} else { Ok "conda: $Conda" }
$CondaBase = (& $Conda info --base).Trim()
# envs are built with mamba (in every Miniforge): it installs the locked file:/// packages offline,
# which conda 26 itself refuses
$Mamba = @("$CondaBase\Library\bin\mamba.exe", "$CondaBase\Scripts\mamba.exe", "$CondaBase\condabin\mamba.bat") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Mamba) { Die "no mamba in $CondaBase (install Miniforge, or set DAMSUITE_CONDA to a Miniforge conda.exe)" }
$CondaBat = Join-Path $CondaBase 'condabin\conda.bat'
function EnvPrefix($n) { Join-Path $CondaBase "envs\$n" }

function Make-Env($name, $role) {
  if (Test-Path (Join-Path (EnvPrefix $name) 'conda-meta')) { Ok "conda env $name already exists (kept)"; return $true }
  $lock = Join-Path $Here "locks\$P\$role.lock"
  if (-not (Test-Path $lock)) { Warn "no lock for $role"; return $false }
  $spec = New-Object System.Collections.Generic.List[string]; $spec.Add('@EXPLICIT')
  foreach ($l in (LockLines $lock)) {
    $f = PkgPath $l[0]
    if (-not (Test-Path $f) -or (Sha $f) -ne $l[1]) { Warn "package missing or bad sha256: $(Split-Path $f -Leaf)"; return $false }
    $u = ([Uri]$f).AbsoluteUri       # file:///C:/Users/... (spaces encoded)
    $spec.Add("$u#$($l[2])")
  }
  $tmp = Join-Path $env:TEMP "damsuite-$name.txt"
  [IO.File]::WriteAllLines($tmp, $spec)
  Say "Creating conda env $name from $($spec.Count - 1) local packages (no download)"
  & $Mamba create -y --offline -n $name --file $tmp
  $okc = ($LASTEXITCODE -eq 0); Remove-Item $tmp -ErrorAction SilentlyContinue
  return $okc
}

Say 'Conda environments'
if (-not (Make-Env 'ndqgis' 'ndqgis')) { Die 'the QGIS env could not be built' }
$AnugaPy = Join-Path (EnvPrefix 'ndanuga') 'python.exe'
if (-not (Make-Env 'ndanuga' 'ndanuga')) { Warn 'the ANUGA env could not be built: the ANUGA tier will be off'; $AnugaPy = '' }
if ($AnugaPy) {
  & $AnugaPy -c "import anuga, gmsh" *> $null
  if ($LASTEXITCODE -ne 0) { Warn 'anuga/gmsh do not import: ANUGA tier off'; $AnugaPy = '' }
}
# the ndqgis python with what its activation sets (not `conda run`: it mangles paths with spaces)
$QP = EnvPrefix 'ndqgis'
function QPy {
  $save = @{}; foreach ($k in 'PATH','PYTHONPATH','QGIS_PREFIX_PATH','QT_PLUGIN_PATH','PROJ_DATA','GDAL_DATA','QT_QPA_PLATFORM') { $save[$k] = [Environment]::GetEnvironmentVariable($k) }
  $env:PATH = "$QP;$QP\Library\mingw-w64\bin;$QP\Library\usr\bin;$QP\Library\bin;$QP\Scripts;$QP\bin;$env:PATH"
  $env:PYTHONPATH = "$QP\Library\python;$QP\Library\python\plugins"
  $env:QGIS_PREFIX_PATH = "$QP\Library"; $env:QT_PLUGIN_PATH = "$QP\Library\plugins;$QP\Library\qtplugins"
  $env:PROJ_DATA = "$QP\Library\share\proj"; $env:GDAL_DATA = "$QP\Library\share\gdal"; $env:QT_QPA_PLATFORM = 'offscreen'
  try { & (Join-Path $QP 'python.exe') @args } finally { foreach ($k in $save.Keys) { [Environment]::SetEnvironmentVariable($k, $save[$k]) } }
}
QPy -c "import qgis.core" | Out-Null
if ($LASTEXITCODE -ne 0) { Die 'QGIS does not import in env ndqgis (see the log)' }

# ---------------------------------------------------------------------------
# 3. plugins (Core first)
# ---------------------------------------------------------------------------
function Install-Set($profileDir, $zipDir, $names) {
  $dest = Join-Path $profileDir 'python\plugins'; New-Item -ItemType Directory -Force -Path $dest | Out-Null
  foreach ($p in $names) {
    $z = Get-ChildItem -LiteralPath $zipDir -Filter "$($p)_*.zip" | Where-Object { $_.Name -match "^$([regex]::Escape($p))_[0-9]" } | Select-Object -First 1
    if (-not $z) { Warn "no zip for $p in $zipDir"; continue }
    $t = Join-Path $dest $p; if (Test-Path $t) { Remove-Item -Recurse -Force $t }
    Expand-Archive -LiteralPath $z.FullName -DestinationPath $dest -Force
    Write-Host ("    {0,-22} {1}" -f $p, (VerOf $t))
  }
}
if ($DoDs) { Say "DamSafety plugins -> profile '$DsProfile' (DamSafety Core first)"; Install-Set $DsDir (Join-Path $Here 'plugins\damsafety') $DsPlugins }
if ($DoDi) { Say "DamIT plugins -> profile '$DiProfile' (DamIT Core and Catalog first)"; Install-Set $DiDir (Join-Path $Here 'plugins\damit') $DiPlugins }

# ---------------------------------------------------------------------------
# 4. LISFLOOD-FP 8.3 + Runner patch (static build, no DLLs)
# ---------------------------------------------------------------------------
$Lisflood = ''
if ($SkipLisflood) { Warn 'LISFLOOD-FP skipped (-SkipLisflood): the Runners use their built-in engine' }
else {
  $src = Join-Path $Here 'lisflood\windows-x64\lisflood.exe'
  $dst = Join-Path $Prefix 'bin\lisflood.exe'
  New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
  if (Test-Path $src) { Copy-Item -Force $src $dst }
  if ((Test-Path $dst) -and (HasText $dst 'inittm_depth')) {
    $banner = (& $dst -version 2>&1 | Out-String)
    if ($banner -match 'LISFLOOD') { $Lisflood = $dst; Ok "LISFLOOD-FP: $dst (Runner patch present)" }
    else { Warn "lisflood.exe does not run here: $banner" }
  } else { Warn 'no patched lisflood.exe in this package: the Runners use their built-in engine' }
}

# ---------------------------------------------------------------------------
# 5. Absaraka folder, settings, launchers
# ---------------------------------------------------------------------------
$Run = Join-Path $Prefix 'absaraka-run'
$abs = Join-Path $Here 'absaraka'
if (Test-Path $abs) {
  Get-ChildItem -LiteralPath $abs -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($abs.Length).TrimStart('\')
    $t = Join-Path $Run $rel
    if (-not (Test-Path $t)) { New-Item -ItemType Directory -Force -Path (Split-Path $t) | Out-Null; Copy-Item $_.FullName $t }
  }
  New-Item -ItemType Directory -Force -Path (Join-Path $Run 'work') | Out-Null
}

$SettingsPy = Join-Path $env:TEMP 'damsuite_settings.py'
@'
import sys
from qgis.PyQt.QtCore import QSettings
ini, which, anuga, lisflood, threads, dams, stamp = sys.argv[1:8]
plugins = sys.argv[8:]
s = QSettings(ini, QSettings.IniFormat)
s.setValue("PythonPlugins/processing", True)
for p in plugins:
    s.setValue("PythonPlugins/" + p, True)
c = "Processing/Configuration/"
if anuga:
    s.setValue(c + "NDBREACH_ANUGA_PYTHON", anuga)
s.setValue(c + "NDBREACH_THREADS", threads)
s.setValue(c + "NDBREACH_LISFLOOD_EXE", lisflood)
if which == "damsafety":
    if anuga:
        s.setValue("ndsuite/anuga_python", anuga)
    s.setValue("ndsuite/lisflood_exe", lisflood)
    s.setValue("ndsuite/dams_folder", dams)
    s.setValue("ndsuite/setup_version", stamp)
else:
    s.setValue(c + "DAMIT_RUN_LISFLOOD_EXE", lisflood)
s.sync()
print("  wrote", ini)
'@ | Set-Content -LiteralPath $SettingsPy -Encoding ASCII

function Write-Settings($profileDir, $which, $names) {
  $ini = Join-Path $profileDir 'QGIS\QGIS3.ini'
  New-Item -ItemType Directory -Force -Path (Split-Path $ini) | Out-Null
  QPy $SettingsPy $ini $which "$AnugaPy" "$Lisflood" "$Threads" (Join-Path $Run 'Dams') $Stamp @names
}
function Make-Launcher($file, $profile) {
  $lines = @(
    '@echo off',
    "rem QGIS 3.34 (conda env ndqgis) in profile '$profile'. Written by $Stamp.",
    "call `"$CondaBat`" activate ndqgis",
    'set NDBREACH_ANUGA_MESHER=gmsh',
    "set `"NDBREACH_ANUGA_PYTHON=$AnugaPy`"",
    "set `"NDBREACH_LISFLOOD=$Lisflood`"",
    "start `"`" `"%CONDA_PREFIX%\Library\bin\qgis.exe`" --profile $profile %*")
  [IO.File]::WriteAllLines($file, $lines)
  if (-not $NoShortcuts) {
    try {
      $ws = New-Object -ComObject WScript.Shell
      $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) "QGIS $profile.lnk"))
      $lnk.TargetPath = $file; $lnk.WorkingDirectory = $Prefix; $lnk.WindowStyle = 7
      $ico = Join-Path (EnvPrefix 'ndqgis') 'Library\icons\qgis.ico'; if (Test-Path $ico) { $lnk.IconLocation = $ico }
      $lnk.Save()
    } catch { Warn "could not make the Desktop shortcut for $profile" }
  }
}
Say 'Settings and launchers'
if ($DoDs) { Write-Settings $DsDir 'damsafety' $DsPlugins; Make-Launcher (Join-Path $Prefix 'open-damsafety-qgis.cmd') $DsProfile }
if ($DoDi) { Write-Settings $DiDir 'damit' $DiPlugins;     Make-Launcher (Join-Path $Prefix 'open-damit-qgis.cmd') $DiProfile }
Remove-Item $SettingsPy -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 6. the local AIs (damit_ai's own installer; envs, Ollama and models from offline\)
# ---------------------------------------------------------------------------
$AiOk = $true
if ($DoLumo -or $DoResearch) {
  Say "Local AIs (Lumo $(if ($DoLumo) {'on'} else {'off'}), dam-research $(if ($DoResearch) {'on'} else {'off'}))"
  if ($DoResearch -and -not (Make-Env 'ndresearch' 'ndresearch')) { Warn 'ndresearch env not built from offline\ (the AI installer will try conda-forge)' }
  if ($DoLumo -and -not (Make-Env 'ndlumo' 'ndresearch')) { Warn 'ndlumo env not built from offline\ (the AI installer will try conda-forge)' }
  $om = Join-Path $Here 'damit_ai\offline\models'
  if (Test-Path (Join-Path $om 'manifests')) {
    $md = Join-Path $env:USERPROFILE 'local-ai\models'; New-Item -ItemType Directory -Force -Path $md | Out-Null
    robocopy $om $md /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null; Ok 'models copied to ~\local-ai\models (no pull needed)'
  }
  $ol = Join-Path $Here 'damit_ai\offline\DamResearch\library'
  if ($DoResearch -and (Test-Path $ol)) {
    $ld = Join-Path $env:USERPROFILE 'DamResearch\library'; New-Item -ItemType Directory -Force -Path $ld | Out-Null
    robocopy $ol $ld /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null; Ok 'reference library copied to ~\DamResearch\library'
  }
  $ai = @{}; if (-not $DoLumo) { $ai.NoLumo = $true }; if (-not $DoResearch) { $ai.NoResearch = $true }
  $env:Path = "$CondaBase\Scripts;$CondaBase\condabin;$env:Path"
  try { & (Join-Path $Here 'damit_ai\install-local-ai-windows.ps1') @ai }
  catch { $AiOk = $false; Warn "local AI setup failed ($_); the plugin sets are installed anyway. Re-run: damit_ai\install-local-ai-windows.ps1" }
}

# ---------------------------------------------------------------------------
# 7. self-check + record
# ---------------------------------------------------------------------------
Say 'Self-check'
$Fail = $false
$qv = (QPy -c "import qgis.core as q, numpy; print(q.Qgis.QGIS_VERSION, '| numpy', numpy.__version__)" | Select-Object -Last 1)
if ("$qv" -match '^3\.34') { Ok "QGIS $qv" } else { Warn 'QGIS 3.34 does not import'; $Fail = $true }
if ($AnugaPy) { Ok ("ANUGA " + (& $AnugaPy -c "import anuga,gmsh;print(anuga.__version__,'| gmsh',gmsh.__version__)" 2>$null | Select-Object -Last 1)) } else { $Fail = $true }
if (-not $Lisflood -and -not $SkipLisflood) { $Fail = $true }
foreach ($pair in @(@($DoDs, $DsDir, $DsPlugins), @($DoDi, $DiDir, $DiPlugins))) {
  if (-not $pair[0]) { continue }
  foreach ($p in $pair[2]) { $d = Join-Path $pair[1] "python\plugins\$p"
    if (Test-Path (Join-Path $d 'metadata.txt')) { Ok "$p $(VerOf $d)" } else { Warn "$p missing"; $Fail = $true } } }
if (($DoLumo -or $DoResearch) -and -not $AiOk) { $Fail = $true }

$rec = @("Installed by $Stamp on $(Get-Date)",
         "  platform $P | QGIS $qv | ANUGA python $(if ($AnugaPy) {$AnugaPy} else {'none'}) | LISFLOOD-FP $(if ($Lisflood) {$Lisflood} else {'built-in engine'})")
if ($DoDs) { $rec += "  DamSafety -> profile $DsProfile  (open: $Prefix\open-damsafety-qgis.cmd)" }
if ($DoDi) { $rec += "  DamIT     -> profile $DiProfile  (open: $Prefix\open-damit-qgis.cmd)" }
$rec | Set-Content (Join-Path $Prefix 'INSTALLED.txt')
Say $(if ($Fail) { "Done, with warnings (see above and $Log)." } else { 'Done: all checks passed.' })
$rec | ForEach-Object { Write-Host $_ }
Write-Host "`n  Open one profile at a time with its launcher (Desktop shortcuts 'QGIS damsafety' / 'QGIS damit')."
Write-Host "  Absaraka run folder: $Run     Check later:  install-all-windows.cmd -Check"
Stop-Transcript | Out-Null
