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
  * the local AIs from damit_ai: Heim and vor (Ollama, env, models, library)
  * the DamIT Crest desk (damit_crest) and the North Dakota Crest desk (nd_crest, from the crest
    repo), both run on the ndqgis env; they open in the browser and can run side by side
  * a launcher per profile (in %USERPROFILE%\dam-suite and on the Desktop), and
    build-offline-pack.cmd (the DamSafety offline pack without opening QGIS)

OFFLINE: if offline\ is filled (an offline set unzipped here, or download-all run on any
networked machine), NOTHING is downloaded. Otherwise the missing files are fetched first
by download-all-windows.ps1, each checked against the sha256 pinned in locks\.

Options: -Offline (refuse to download)  -Check  -NoDamSafety  -NoDamIT  -NoAI  -NoHeim
         -NoVor  -SkipLisflood  -NoShortcuts
Somewhere other than your normal QGIS profiles and home folder (a test install):
         -Prefix DIR  (the suite folder; default %USERPROFILE%\dam-suite, env DAMSUITE_PREFIX)
         -QgisProfilesPath DIR  (profiles in DIR\profiles, QGIS's own layout; the launchers
                                 pass --profiles-path DIR; env DAMSUITE_QGIS_PROFILES_PATH)
         -DamSafetyProfile NAME  -DamitProfile NAME  (default damsafety / damit)
         -Root DIR  (all of these under DIR, Miniforge in DIR\miniforge3 when it is not
                     installed yet; the local AIs always use your home folder, so -Root
                     turns them off unless -AI is given too)
EVERYTHING in one folder (a sandbox: nothing outside DIR is written; remove it by deleting DIR):
         -Sandbox DIR  launchers, LISFLOOD-FP, logs, desks, the Absaraka run, env.cmd / env.ps1
                       in DIR; QGIS profiles in DIR\qgis_profile\profiles\<damsafety|damit> (the
                       launchers set QGIS_CUSTOM_CONFIG_PATH=DIR\qgis_profile); Miniforge and the
                       conda envs in DIR\miniforge3 (no Start-menu entries, no registry); the local
                       AIs in DIR\local-ai and DIR\Vor with their own Ollama on port 11435; no
                       Desktop shortcuts, no user environment variables, no PowerShell profile edits.
                       qgis_process for one profile: DIR\qgis-process-damsafety.cmd / -damit.cmd.
                       Not combined with -Prefix, -QgisProfilesPath or -Root.
         -OllamaPort N  the sandbox Ollama's port (default 11435; env DAMSUITE_OLLAMA_PORT)
         -QgisEnv DIR  use this existing QGIS 3.34 conda env (by path) as it is: no conda env
                       is built and no conda package is needed (ANUGA off unless -AnugaEnv DIR)
-Prefix / DAMSUITE_PREFIX keep their meaning (the suite folder only); only -Sandbox moves everything.
It never touches your data folders, offline packs, or other QGIS profiles.
=============================================================================
#>
param(
  [switch]$Offline, [switch]$Check, [switch]$NoDamSafety, [switch]$NoDamIT, [switch]$NoCrest,
  [switch]$NoAI, [switch]$NoHeim, [switch]$NoVor, [switch]$SkipLisflood, [switch]$NoShortcuts,
  [string]$Prefix = '', [string]$QgisProfilesPath = '', [string]$DamSafetyProfile = 'damsafety',
  [string]$DamitProfile = 'damit', [string]$Root = '', [switch]$AI,
  [string]$Sandbox = '', [int]$OllamaPort = 0, [string]$QgisEnv = '', [string]$AnugaEnv = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$P = 'win-64'
$Ver = if (Test-Path (Join-Path $Here 'VERSION')) { (Get-Content (Join-Path $Here 'VERSION') -TotalCount 1) } else { 'dev' }
$Stamp = "dam-suite install-all $Ver"
$MiniforgeDir = if ($env:DAMSUITE_MINIFORGE) { $env:DAMSUITE_MINIFORGE } else { Join-Path $env:USERPROFILE 'miniforge3' }
if (-not $OllamaPort -and $env:DAMSUITE_OLLAMA_PORT) { $OllamaPort = [int]$env:DAMSUITE_OLLAMA_PORT }
if ($Sandbox) {
  # -Sandbox: one folder for everything; it places the suite folder, the profiles and Miniforge itself
  if ($Prefix -or $QgisProfilesPath -or $Root) { throw '-Sandbox puts everything in its folder; it cannot be combined with -Prefix, -QgisProfilesPath or -Root' }
  $Sandbox = [IO.Path]::GetFullPath($Sandbox).TrimEnd('\')
  if ($Sandbox -eq $env:USERPROFILE -or $Sandbox.Length -le 3) { throw '-Sandbox needs its own folder (not a drive root or your home folder)' }
  $Prefix = $Sandbox; $QgisProfilesPath = Join-Path $Sandbox 'qgis_profile'
  if (-not $env:DAMSUITE_MINIFORGE) { $MiniforgeDir = Join-Path $Sandbox 'miniforge3' }
  if (-not $OllamaPort) { $OllamaPort = 11435 }
  $NoShortcuts = $true                  # the Desktop is outside the sandbox
  # conda's package cache and env registry, and pip's cache, would otherwise land outside it
  $env:CONDA_PKGS_DIRS = Join-Path $Sandbox 'conda-pkgs'; $env:CONDA_REGISTER_ENVS = 'false'; $env:PIP_NO_CACHE_DIR = '1'
}
if ($AnugaEnv -and -not $QgisEnv) { throw '-AnugaEnv is only used with -QgisEnv' }
if ($QgisEnv) { $QgisEnv = [IO.Path]::GetFullPath($QgisEnv).TrimEnd('\'); if (-not (Test-Path (Join-Path $QgisEnv 'conda-meta'))) { throw "-QgisEnv: $QgisEnv is not a conda env (no conda-meta)" } }
if ($AnugaEnv) { $AnugaEnv = [IO.Path]::GetFullPath($AnugaEnv).TrimEnd('\'); if (-not (Test-Path (Join-Path $AnugaEnv 'conda-meta'))) { throw "-AnugaEnv: $AnugaEnv is not a conda env (no conda-meta)" } }
if ($Root) {
  if (-not $Prefix) { $Prefix = Join-Path $Root 'dam-suite' }
  if (-not $QgisProfilesPath) { $QgisProfilesPath = Join-Path $Root 'qgis' }
  if (-not (Test-Path (Join-Path $MiniforgeDir 'Scripts\conda.exe'))) { $MiniforgeDir = Join-Path $Root 'miniforge3' }
  if (-not $AI) { $NoAI = $true }
}
if (-not $Prefix) { $Prefix = if ($env:DAMSUITE_PREFIX) { $env:DAMSUITE_PREFIX } else { Join-Path $env:USERPROFILE 'dam-suite' } }
$Prefix = [IO.Path]::GetFullPath($Prefix)
if (-not $QgisProfilesPath -and $env:DAMSUITE_QGIS_PROFILES_PATH) { $QgisProfilesPath = $env:DAMSUITE_QGIS_PROFILES_PATH }
$ProfilesArg = ''
if ($QgisProfilesPath) {
  $QgisProfilesPath = [IO.Path]::GetFullPath($QgisProfilesPath)
  # QGIS keeps the profiles in <path>\profiles for --profiles-path <path> and QGIS_CUSTOM_CONFIG_PATH
  # (QgsUserProfileManager::resolveProfilesFolder); up to 2026-11-19 this wrote <path>\QGIS3\profiles,
  # which QGIS opened from the launchers never read
  $Profiles = Join-Path $QgisProfilesPath 'profiles'; $ProfilesArg = " --profiles-path `"$QgisProfilesPath`""
} else { $Profiles = Join-Path $env:APPDATA 'QGIS\QGIS3\profiles' }
$DsProfile = $DamSafetyProfile; $DiProfile = $DamitProfile
foreach ($n in @($DsProfile, $DiProfile)) {
  if (-not $n -or $n -match '[\\/:]' -or $n -eq '.' -or $n -eq '..') { throw "profile name '$n' is not a plain folder name" }
}
if ($DsProfile -eq $DiProfile) { throw "the DamSafety and DamIT sets need different profiles (both are '$DsProfile'): their Processing ids clash" }
$DsDir = Join-Path $Profiles $DsProfile; $DiDir = Join-Path $Profiles $DiProfile
$DsPlugins = @('DamSafety_Core','DamSafety_Setup','DamSafety_Data','DamSafety_Screening','DamSafety_Runner','DamSafety_Hazard','DamSafety_HazardLite','DamSafety_PMP','DamSafety_Finder')
$DiPlugins = @('damit_core','damit_catalog','damit_setup','damit_data','damit_screener','damit_runner','damit_hazard','damit_hazardlite','damit_pmp','damit_finder')
$DoDs = -not $NoDamSafety; $DoDi = -not $NoDamIT; $DoCrest = -not $NoCrest
$DoHeim = -not ($NoAI -or $NoHeim); $DoVor = -not ($NoAI -or $NoVor)
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
  # -Sandbox builds its envs in its own Miniforge, never in a conda you already have (with -QgisEnv
  # nothing is built, so any conda will do: it only runs the given env)
  if ($Sandbox -and -not $QgisEnv) {
    foreach ($c in @($env:DAMSUITE_CONDA, (Join-Path $MiniforgeDir 'Scripts\conda.exe'))) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
  }
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
    foreach ($e in 'ndqgis','ndanuga','ndvor','ndheim') { Write-Host ("    env {0}: {1}" -f $e, $(if (Test-Path "$base\envs\$e\conda-meta") {'present'} else {'missing'})) } }
  else { Write-Host '  conda: not found' }
  $lf = Join-Path $Prefix 'bin\lisflood.exe'
  Write-Host ("  LISFLOOD-FP: $lf " + $(if (Test-Path $lf) { if (-not (HasText $lf 'inittm_depth')) {'UNPATCHED'} elseif (HasText $lf 'nd-breach-runner: SGC arrival depth') {'OK (Runner patch with sub-grid channels)'} else {'OK (Runner patch present; no sub-grid channels in this build)'} } else {'missing'}))
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
$Roles = @('ndqgis','ndanuga'); if ($DoHeim -or $DoVor) { $Roles += 'ndvor' }
if ($QgisEnv) { $Roles = @() }          # -QgisEnv: no conda env is built, so no package is needed
# 2026-11-18: name the missing files, not only count them (the local AIs' Ollama installer is in
# damit_ai\offline\, so a copy of offline\ alone from an older package folder leaves it behind)
$missing = @()
foreach ($r in $Roles) {
  foreach ($l in (LockLines (Join-Path $Here "locks\$P\$r.lock"))) {
    $f = PkgPath $l[0]
    if (-not (Test-Path $f)) { $missing += $f.Substring($Here.Length).TrimStart('\') } } }
foreach ($l in ExtraLines) {
  if ($QgisEnv -and ($l[1] -eq 'miniforge' -or ($l[1] -eq 'ollama' -and -not ($DoHeim -or $DoVor)))) { continue }
  if (-not (Test-Path (Join-Path $Here $l[2]))) { $missing += $l[2] } }
$miss = $missing.Count
if ($miss -gt 0) {
  Say "Missing ($miss):"
  $missing | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
  if ($miss -gt 20) { Write-Host "  ... and $($miss - 20) more" }
  if ($Offline) { Die "$miss file(s) are missing (listed above) and -Offline was given. Unzip offline-$P.zip here, copy them (offline\ AND damit_ai\offline\) from an older package folder, or run download-all-windows.cmd (it fetches only what is missing)" }
  Say "$miss file(s) not in offline\ yet: fetching them (pinned, sha256-checked)."
  $dl = @{ Platform = $P; NoModels = $true }; if (-not $DoVor) { $dl.NoLibrary = $true }
  & (Join-Path $Here 'download-all-windows.ps1') @dl
  if (-not $?) { Warn 'download-all reported problems (continuing; checked below)' }
} else { Ok 'every installer file is in offline\ (nothing will be downloaded)' }

# ---------------------------------------------------------------------------
# 2. conda (Miniforge 26.9.4-2 from offline\miniforge, sha256-checked, just for you)
# ---------------------------------------------------------------------------
if ($QgisEnv -and -not $Conda) { Die '-QgisEnv needs a conda (Miniforge) for the launchers, and none was found (set DAMSUITE_CONDA to its conda.exe)' }
if (-not $Conda) {
  $mf = ExtraLines | Where-Object { $_[1] -eq 'miniforge' } | Select-Object -First 1
  $exe = Join-Path $Here $mf[2]
  if (-not (Test-Path $exe)) { Die "No conda found and no Miniforge installer at $exe" }
  if ((Sha $exe) -ne $mf[4]) { Die "Miniforge installer failed its sha256 check: $exe" }
  Say "Installing Miniforge (checked) to $MiniforgeDir (just for you, not on PATH)"
  $mfArgs = @('/InstallationType=JustMe','/RegisterPython=0','/AddToPath=0','/S')
  if ($Sandbox) { $mfArgs += @('/NoRegistry=1','/NoShortcuts=1') }   # no uninstall entry or Start-menu items outside it
  Start-Process -Wait -FilePath $exe -ArgumentList ($mfArgs + "/D=$MiniforgeDir")
  $Conda = Join-Path $MiniforgeDir 'Scripts\conda.exe'
  if (-not (Test-Path $Conda)) { Die "Miniforge did not install to $MiniforgeDir" }
} else { Ok "conda: $Conda" }
$CondaBase = (& $Conda info --base).Trim()
# envs are built with mamba (in every Miniforge): it installs the locked file:/// packages offline,
# which conda 26 itself refuses
$Mamba = @("$CondaBase\Library\bin\mamba.exe", "$CondaBase\Scripts\mamba.exe", "$CondaBase\condabin\mamba.bat") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Mamba) { Die "no mamba in $CondaBase (install Miniforge, or set DAMSUITE_CONDA to a Miniforge conda.exe)" }
$CondaBat = Join-Path $CondaBase 'condabin\conda.bat'
function EnvPrefix($n) {
  # -Sandbox: the local AIs' envs live with the AIs, in DIR\local-ai\envs (the AI installer looks there)
  if ($Sandbox -and ($n -eq 'ndvor' -or $n -eq 'ndheim')) { return (Join-Path $Sandbox "local-ai\envs\$n") }
  if ($n -eq 'ndqgis' -and $QgisEnv) { return $QgisEnv }
  Join-Path $CondaBase "envs\$n" }

function Make-Env($name, $role) {
  if (Test-Path (Join-Path (EnvPrefix $name) 'conda-meta')) { Ok "conda env $name already exists (kept)"; return $true }
  if ($QgisEnv) { Warn "-QgisEnv: conda env $name is not built (no env is built with -QgisEnv)"; return $false }
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
  # -Sandbox: mamba's home is the sandbox while it runs (it rewrites ~\.conda\environments.txt otherwise)
  $keep = @{ USERPROFILE = $env:USERPROFILE; HOME = $env:HOME }
  if ($Sandbox) { $env:USERPROFILE = Join-Path $Sandbox '.home'; $env:HOME = $env:USERPROFILE }
  try { & $Mamba create -y --offline -p (EnvPrefix $name) --file $tmp }
  finally { $env:USERPROFILE = $keep.USERPROFILE; $env:HOME = $keep.HOME }
  $okc = ($LASTEXITCODE -eq 0); Remove-Item $tmp -ErrorAction SilentlyContinue
  return $okc
}

Say 'Conda environments'
if (-not (Make-Env 'ndqgis' 'ndqgis')) { Die 'the QGIS env could not be built' }
if ($QgisEnv) {
  Ok "QGIS env: $QgisEnv (-QgisEnv: used as it is, nothing built)"
  $AnugaPy = if ($AnugaEnv) { Join-Path $AnugaEnv 'python.exe' } else { Warn '-QgisEnv without -AnugaEnv: ANUGA tier off'; '' }
} else {
$AnugaPy = Join-Path (EnvPrefix 'ndanuga') 'python.exe'
if (-not (Make-Env 'ndanuga' 'ndanuga')) { Warn 'the ANUGA env could not be built: the ANUGA tier will be off'; $AnugaPy = '' }
}
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
  # Windows: Qt names the folder after the organisation name (QGIS); only macOS uses qgis.org
  $ini = Join-Path $profileDir 'QGIS\QGIS3.ini'
  New-Item -ItemType Directory -Force -Path (Split-Path $ini) | Out-Null
  QPy $SettingsPy $ini $which "$AnugaPy" "$Lisflood" "$Threads" (Join-Path $Run 'Dams') $Stamp @names
}
function Make-Launcher($file, $profile) {
  $lines = @(
    '@echo off',
    "rem QGIS 3.34 (conda env ndqgis) in profile '$profile'. Written by $Stamp.",
    "call `"$CondaBat`" activate `"$QP`"",
    'set NDBREACH_ANUGA_MESHER=gmsh',
    "set `"NDBREACH_ANUGA_PYTHON=$AnugaPy`"",
    "set `"NDBREACH_LISFLOOD=$Lisflood`"")
  # -Sandbox: anything QGIS starts (a plugin's qgis_process, Crest) stays in the sandbox's profiles too
  if ($Sandbox) { $lines += "set `"QGIS_CUSTOM_CONFIG_PATH=$QgisProfilesPath`"" }
  $lines += @(
    "start `"`" `"%CONDA_PREFIX%\Library\bin\qgis.exe`" --profile $profile$ProfilesArg %*")
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
# build-offline-pack.cmd [folder]: the DamSafety offline pack without opening QGIS (default folder
# %USERPROFILE%\ND_Suite_Data). A stopped build picks up where it left off; when it finishes the
# folder becomes the suite data folder (~\.ndsuite\config.json, read when the profile has none).
function Make-PackBuilder($file) {
  $lines = @(
    '@echo off',
    "rem DamSafety offline pack (conda env ndqgis, profile '$DsProfile'). Written by $Stamp.",
    "call `"$CondaBat`" activate `"$QP`" || exit /b 1",
    $(if ($Sandbox) { "set `"OUT=$Sandbox\ND_Suite_Data`"" } else { 'set "OUT=%USERPROFILE%\ND_Suite_Data"' }),
    'if not "%~1"=="" set "OUT=%~f1"',
    'if "%OUT:~-1%"=="\" set "OUT=%OUT%."',
    "pushd `"$DsDir\python\plugins`" || exit /b 1",
    'set PYTHONUNBUFFERED=1',
    'echo Building the offline pack in %OUT% (a stopped build picks up where it left off)',
    'python -m DamSafety_Data.pack_build --out "%OUT%" || exit /b 1',
    # adopt_folder writes ~\.ndsuite\config.json, outside a sandbox: there the folder is only reported
    $(if ($Sandbox) { 'echo Pack built in %OUT%. Sandbox: pick it as the data folder in DamSafety Setup.' }
      else { 'python -c "import sys, DamSafety_Core.damsuite.suitedata as S; S._qsettings = lambda: None; print(S.adopt_folder(sys.argv[1]))" "%OUT%"' }))
  [IO.File]::WriteAllLines($file, $lines)
}
Say 'Settings and launchers'
if ($DoDs) { Write-Settings $DsDir 'damsafety' $DsPlugins; Make-Launcher (Join-Path $Prefix 'open-damsafety-qgis.cmd') $DsProfile
             Make-PackBuilder (Join-Path $Prefix 'build-offline-pack.cmd') }
if ($DoDi) { Write-Settings $DiDir 'damit' $DiPlugins;     Make-Launcher (Join-Path $Prefix 'open-damit-qgis.cmd') $DiProfile }

# DamIT Crest desk. It runs on the ndqgis env: that env already has pyproj (Crest's only
# third-party import) and puts qgis_process on PATH, which Crest's Report step calls. pywebview is
# not installed, so the desk opens in the browser, which is Crest's documented fallback.
#
# The tree layout matters: damit_desktop\nid_rule.py loads DamIT Catalog's NID-ID rule from
# <parents[3]>\damit_catalog\handoff.py and refuses to start without it, so Crest keeps its
# damit_crest\desktop nesting and gets a damit_catalog\handoff.py beside it, taken from the
# Catalog plugin zip we just installed so the rule always matches the plugin.
# QgisProcessProfile <profile> <profile dir>: the line a Crest launcher needs so the desk's Report
# step finds that profile's plugins. qgis_process (3.34) has no profile option and always loads the
# profile named "default" under QGIS_CUSTOM_CONFIG_PATH, so the launcher points that at
# <prefix>\qgis-process\<profile>, whose profiles\default is a junction to the real profile (a
# junction needs no admin rights; `rmdir` removes only the junction, never the profile).
function QgisProcessProfile($profile, $dir) {
  if (-not (Test-Path $dir)) { return 'rem (no QGIS profile folder yet for ' + $profile + ')' }
  $root = Join-Path $Prefix "qgis-process\$profile"
  $link = Join-Path $root 'profiles\default'
  New-Item -ItemType Directory -Force -Path (Join-Path $root 'profiles') | Out-Null
  $old = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
  if ($old) {
    # A real folder there is a profile qgis_process made itself when the junction was missing: keep it.
    if ($old.Attributes -band [IO.FileAttributes]::ReparsePoint) { cmd /c rmdir "`"$link`"" | Out-Null }
    else { Rename-Item -LiteralPath $link -NewName ('default.bak-' + (Get-Date -Format 'yyyyMMddHHmmss')) }
  }
  cmd /c mklink /J "`"$link`"" "`"$dir`"" | Out-Null
  $made = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
  if (-not $made -or -not ($made.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not (Test-Path (Join-Path $link 'python'))) {
    Warn "could not link ${link} -> ${dir}: Crest's Report step will not find the $profile plugins"
    return "rem QGIS_CUSTOM_CONFIG_PATH not set: the junction $link was not made"
  }
  return "set `"QGIS_CUSTOM_CONFIG_PATH=$root`""
}
$CrestSrc = Join-Path $Here 'damit_crest'
$CatZip = Get-ChildItem (Join-Path $Here 'plugins\damit') -Filter 'damit_catalog_*.zip' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($DoCrest -and (Test-Path (Join-Path $CrestSrc 'desktop'))) {
  if (-not $CatZip) { Warn "no DamIT Catalog zip: the Crest desk needs its NID-ID rule, so Crest was skipped" }
  else {
    Say "DamIT Crest desk -> $Prefix\damit_crest"
    $CrestDir = Join-Path $Prefix 'damit_crest'
    New-Item -ItemType Directory -Force -Path $CrestDir, (Join-Path $Prefix 'damit_catalog') | Out-Null
    Copy-Item -Recurse -Force (Join-Path $CrestSrc '*') $CrestDir
    $ho = Join-Path $Prefix 'damit_catalog\handoff.py'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zf = [System.IO.Compression.ZipFile]::OpenRead($CatZip.FullName)
    try {
      $ent = $zf.Entries | Where-Object { $_.FullName -eq 'damit_catalog/handoff.py' } | Select-Object -First 1
      if ($ent) { [System.IO.Compression.ZipFileExtensions]::ExtractToFile($ent, $ho, $true) }
    } finally { $zf.Dispose() }
    if (Test-Path $ho) {
      $cl = Join-Path $Prefix 'open-damit-crest.cmd'
      @("@echo off", "call `"$CondaBat`" activate `"$QP`" || exit /b 1",
        (QgisProcessProfile $DiProfile $DiDir),
        "cd /d `"$CrestDir\desktop`"", "python run.py %*") | Set-Content $cl -Encoding ASCII
      Ok "Crest desk (open: $cl)"
    } else { Warn "could not read damit_catalog/handoff.py from $($CatZip.Name): Crest was skipped" }
  }
}
# North Dakota Crest desk (crest repo, crest-desktop\). Same engine as DamIT Crest with the ND
# inventory and the DamSafety hand-off (profile damsafety). Standard library only; its port differs
# from DamIT Crest's, so both desks can be open at once.
$NdCrestSrc = Join-Path $Here 'nd_crest'
if ($DoCrest -and (Test-Path (Join-Path $NdCrestSrc 'crest-desktop\run.py'))) {
  Say "North Dakota Crest desk -> $Prefix\nd_crest"
  $NdCrestDir = Join-Path $Prefix 'nd_crest'
  New-Item -ItemType Directory -Force -Path $NdCrestDir | Out-Null
  Copy-Item -Recurse -Force (Join-Path $NdCrestSrc '*') $NdCrestDir
  $cl = Join-Path $Prefix 'open-nd-crest.cmd'
  @("@echo off", "call `"$CondaBat`" activate `"$QP`" || exit /b 1",
    (QgisProcessProfile $DsProfile $DsDir),
    "cd /d `"$NdCrestDir\crest-desktop`"", "python run.py %*") | Set-Content $cl -Encoding ASCII
  Ok "North Dakota Crest desk (open: $cl)"
}
Remove-Item $SettingsPy -ErrorAction SilentlyContinue

# -Sandbox: qgis_process for one profile (it loads the profile "default" under QGIS_CUSTOM_CONFIG_PATH,
# here the qgis-process\<profile> junction folder), and env.cmd / env.ps1
if ($Sandbox) {
  Say 'Sandbox: qgis_process launchers and env files'
  foreach ($s in @(@($DoDs, 'damsafety', $DsProfile, $DsDir), @($DoDi, 'damit', $DiProfile, $DiDir))) {
    if (-not $s[0]) { continue }
    $f = Join-Path $Sandbox "qgis-process-$($s[1]).cmd"
    @('@echo off', "call `"$CondaBat`" activate `"$QP`" || exit /b 1",
      (QgisProcessProfile $s[2] $s[3]),
      "set `"NDBREACH_LISFLOOD=$Lisflood`"", "qgis_process %*") | Set-Content $f -Encoding ASCII
    Ok $f
  }
  $aiEnv = Join-Path $Sandbox 'local-ai\env.ps1'
  @("# dam suite sandbox: dot-source this file ( . '$Sandbox\env.ps1' ). Written by $Stamp.",
    "# Everything this install made is in $Sandbox; to remove it, stop its Ollama and delete the folder.",
    "`$env:DAMSUITE_SANDBOX = '$Sandbox'", "`$env:QGIS_CUSTOM_CONFIG_PATH = '$QgisProfilesPath'",
    "`$env:Path = '$Sandbox\bin;' + `$env:Path", "`$env:NDBREACH_LISFLOOD = '$Lisflood'",
    "if (Test-Path '$aiEnv') { . '$aiEnv' }") | Set-Content (Join-Path $Sandbox 'env.ps1') -Encoding UTF8
  @('@echo off', "rem dam suite sandbox: run this in cmd.exe first. Written by $Stamp.",
    "set `"DAMSUITE_SANDBOX=$Sandbox`"", "set `"QGIS_CUSTOM_CONFIG_PATH=$QgisProfilesPath`"",
    "set `"PATH=$Sandbox\bin;%PATH%`"", "set `"NDBREACH_LISFLOOD=$Lisflood`"",
    "if exist `"$Sandbox\local-ai\env.cmd`" call `"$Sandbox\local-ai\env.cmd`"") | Set-Content (Join-Path $Sandbox 'env.cmd') -Encoding ASCII
  Ok "$Sandbox\env.ps1 and env.cmd"
}

# ---------------------------------------------------------------------------
# 6. the local AIs (damit_ai's own installer; envs, Ollama and models from offline\)
# ---------------------------------------------------------------------------
$AiOk = $true
$AiHome = if ($Sandbox) { Join-Path $Sandbox 'local-ai' } else { Join-Path $env:USERPROFILE 'local-ai' }
$VorLib = if ($Sandbox) { Join-Path $Sandbox 'Vor\library' } else { Join-Path $env:USERPROFILE 'Vor\library' }
if ($DoHeim -or $DoVor) {
  Say "Local AIs (Heim $(if ($DoHeim) {'on'} else {'off'}), vor $(if ($DoVor) {'on'} else {'off'}))"
  if ($DoVor -and -not (Make-Env 'ndvor' 'ndvor')) { Warn 'ndvor env not built from offline\ (the AI installer will try conda-forge)' }
  if ($DoHeim -and -not (Make-Env 'ndheim' 'ndvor')) { Warn 'ndheim env not built from offline\ (the AI installer will try conda-forge)' }
  $om = Join-Path $Here 'damit_ai\offline\models'
  if (Test-Path (Join-Path $om 'manifests')) {
    $md = Join-Path $AiHome 'models'; New-Item -ItemType Directory -Force -Path $md | Out-Null
    robocopy $om $md /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null; Ok "models copied to $md (no pull needed)"
  }
  $ol = Join-Path $Here 'damit_ai\offline\Vor\library'
  if ($DoVor -and (Test-Path $ol)) {
    $ld = $VorLib; New-Item -ItemType Directory -Force -Path $ld | Out-Null
    robocopy $ol $ld /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null; Ok "reference library copied to $ld"
  }
  $ai = @{}; if (-not $DoHeim) { $ai.NoHeim = $true }; if (-not $DoVor) { $ai.NoVor = $true }
  if ($Sandbox) { $ai.Prefix = $Sandbox }
  if ($OllamaPort) { $ai.OllamaPort = $OllamaPort }
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
if (($DoHeim -or $DoVor) -and -not $AiOk) { $Fail = $true }

$rec = @("Installed by $Stamp on $(Get-Date)",
         "  platform $P | QGIS $qv | ANUGA python $(if ($AnugaPy) {$AnugaPy} else {'none'}) | LISFLOOD-FP $(if ($Lisflood) {$Lisflood} else {'built-in engine'})")
if ($DoDs) { $rec += "  DamSafety -> profile $DsProfile  (open: $Prefix\open-damsafety-qgis.cmd)" }
if ($DoDi) { $rec += "  DamIT     -> profile $DiProfile  (open: $Prefix\open-damit-qgis.cmd)" }
if (Test-Path (Join-Path $Prefix 'open-damit-crest.cmd')) { $rec += "  DamIT Crest desk              (open: $Prefix\open-damit-crest.cmd)" }
if (Test-Path (Join-Path $Prefix 'open-nd-crest.cmd')) { $rec += "  North Dakota Crest desk       (open: $Prefix\open-nd-crest.cmd)" }
if (Test-Path (Join-Path $Prefix 'build-offline-pack.cmd')) { $rec += "  DamSafety offline pack        (build: $Prefix\build-offline-pack.cmd)" }
if ($Sandbox) {
  $rec += "  SANDBOX: everything is in $Sandbox (QGIS profiles in $Profiles)"
  $rec += "    use it:    . $Sandbox\env.ps1  (PowerShell) or  $Sandbox\env.cmd  (cmd.exe), or the launchers above"
  $rec += "    remove it: stop its Ollama (Stop-Process -Id (Get-Content $Sandbox\local-ai\ollama-serve.pid)), then delete $Sandbox"
}
$rec | Set-Content (Join-Path $Prefix 'INSTALLED.txt')
Say $(if ($Fail) { "Done, with warnings (see above and $Log)." } else { 'Done: all checks passed.' })
$rec | ForEach-Object { Write-Host $_ }
Write-Host "`n  Open one profile at a time with its launcher$(if (-not $NoShortcuts) {" (Desktop shortcuts 'QGIS damsafety' / 'QGIS damit')"})." 
Write-Host "  Absaraka run folder: $Run     Check later:  install-all-windows.cmd -Check"
Stop-Transcript | Out-Null
