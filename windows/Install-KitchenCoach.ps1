<#
.SYNOPSIS
  Installs Kitchen Coach for the current Windows user.

.DESCRIPTION
  * Works with the ready-built release (KitchenCoach\KitchenCoach.exe next to this script)
    or straight from the source code (needs Python 3.10+ from python.org).
  * Creates a Desktop icon, a Start menu entry and (unless -NoStartup) a Startup entry so
    Kitchen Coach opens automatically when you sign in to Windows.
  * No administrator rights needed. Installs to %LOCALAPPDATA%\Programs\KitchenCoach.

.EXAMPLE
  Right-click Install.bat > Run   (or)   powershell -ExecutionPolicy Bypass -File Install-KitchenCoach.ps1
.EXAMPLE
  .\Install-KitchenCoach.ps1 -NoStartup      # don't open automatically at sign-in
#>
[CmdletBinding()]
param(
    [switch]$NoStartup,
    [switch]$NoLaunch,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\KitchenCoach')
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
function Say($msg, $colour = 'Cyan') { Write-Host "  $msg" -ForegroundColor $colour }

Write-Host ''
Write-Host '  Kitchen Coach installer' -ForegroundColor Yellow
Write-Host '  -----------------------' -ForegroundColor Yellow

# Close any running copy so its files can be replaced.
function Stop-KitchenCoach {
    Get-Process -Name 'KitchenCoach' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*KitchenCoach*launcher.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 600
}
Stop-KitchenCoach

$exeSource = Join-Path $here 'KitchenCoach\KitchenCoach.exe'
$repoRoot = Split-Path $here -Parent
$isRelease = Test-Path $exeSource
$isSource = (-not $isRelease) -and (Test-Path (Join-Path $repoRoot 'launcher.py'))

# Files downloaded from the internet are "blocked" by Windows; unblock just our own files.
$ourFolder = $null
if ($isRelease) { $ourFolder = $here } elseif ($isSource) { $ourFolder = $repoRoot }
if ($ourFolder) {
    Get-ChildItem -Path $ourFolder -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if ($isRelease) {
    # ---------------------------------------------------------------- release build
    Say 'Installing the ready-built app...'
    $null = robocopy (Join-Path $here 'KitchenCoach') (Join-Path $InstallDir 'KitchenCoach') /MIR /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Copying files failed (robocopy code $LASTEXITCODE)." }
    $target = Join-Path $InstallDir 'KitchenCoach\KitchenCoach.exe'
    $arguments = ''
    $icon = $target
    $workDir = Join-Path $InstallDir 'KitchenCoach'
}
elseif ($isSource) {
    # ---------------------------------------------------------------- from source
    Say 'Installing from source code...'
    $python = $null
    $candidates = @(@{ Exe = 'py'; Pre = @('-3') }, @{ Exe = 'python'; Pre = @() })
    foreach ($c in $candidates) {
        try {
            $pre = $c.Pre
            $ver = & $c.Exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver -and ([version]"$ver" -ge [version]'3.10')) { $python = $c; break }
        } catch { }
    }
    if (-not $python) {
        Say 'Python 3.10 or newer was not found.' 'Red'
        Say 'Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),' 'Red'
        Say 'or download the ready-built KitchenCoach-Windows.zip from the GitHub Releases page.' 'Red'
        exit 1
    }
    Say "Using Python $ver"
    $appDir = Join-Path $InstallDir 'app'
    New-Item -ItemType Directory -Force -Path $appDir | Out-Null
    foreach ($f in 'app.py', 'launcher.py', 'recipe_parser.py', 'requirements.txt') {
        Copy-Item (Join-Path $repoRoot $f) $appDir -Force
    }
    foreach ($d in 'web', 'assets') {
        $null = robocopy (Join-Path $repoRoot $d) (Join-Path $appDir $d) /MIR /NFL /NDL /NJH /NJS /NP
        if ($LASTEXITCODE -ge 8) { throw "Copying $d failed (robocopy code $LASTEXITCODE)." }
    }
    $venv = Join-Path $InstallDir 'venv'
    if (-not (Test-Path (Join-Path $venv 'Scripts\pythonw.exe'))) {
        Say 'Creating a private Python environment...'
        $pre = $python.Pre
        & $python.Exe @pre -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    Say 'Installing components (Flask, pypdf, defusedxml, waitress)...'
    & (Join-Path $venv 'Scripts\python.exe') -m pip install --disable-pip-version-check -q --upgrade pip
    & (Join-Path $venv 'Scripts\python.exe') -m pip install --disable-pip-version-check -q -r (Join-Path $appDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing Python packages failed - check your internet connection.' }
    $target = Join-Path $venv 'Scripts\pythonw.exe'
    $arguments = '"' + (Join-Path $appDir 'launcher.py') + '"'
    $icon = Join-Path $appDir 'assets\kitchen_coach.ico'
    $workDir = $appDir
}
else {
    Say 'Could not find KitchenCoach\KitchenCoach.exe or the source code next to this script.' 'Red'
    exit 1
}

Copy-Item (Join-Path $here 'Uninstall-KitchenCoach.ps1') $InstallDir -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- shortcuts
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $tgt, $tgtArgs, $description) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $tgt
    $lnk.Arguments = $tgtArgs
    $lnk.WorkingDirectory = $workDir
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = $description
    $lnk.Save()
}
$desktop = [Environment]::GetFolderPath('Desktop')            # follows OneDrive desktop redirection
$programs = [Environment]::GetFolderPath('Programs')
$startup = [Environment]::GetFolderPath('Startup')

New-Shortcut (Join-Path $desktop 'Kitchen Coach.lnk') $target $arguments 'Kitchen Coach - timed, spoken recipe guide'
New-Shortcut (Join-Path $programs 'Kitchen Coach.lnk') $target $arguments 'Kitchen Coach - timed, spoken recipe guide'
$uninstallArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $InstallDir 'Uninstall-KitchenCoach.ps1') + '"'
New-Shortcut (Join-Path $programs 'Uninstall Kitchen Coach.lnk') 'powershell.exe' $uninstallArgs 'Remove Kitchen Coach'
Say 'Desktop and Start menu shortcuts created.' 'Green'

$startupLink = Join-Path $startup 'Kitchen Coach.lnk'
if ($NoStartup) {
    Remove-Item $startupLink -ErrorAction SilentlyContinue
    Say 'Automatic launch at sign-in: off'
} else {
    New-Shortcut $startupLink $target $arguments 'Open Kitchen Coach when you sign in'
    Say 'Automatic launch at sign-in: on (re-run with -NoStartup to turn off)' 'Green'
}

Write-Host ''
Say "Installed to $InstallDir" 'Green'
if (-not $NoLaunch) {
    Say 'Starting Kitchen Coach...'
    if ($arguments) { Start-Process -FilePath $target -ArgumentList $arguments -WorkingDirectory $workDir }
    else { Start-Process -FilePath $target -WorkingDirectory $workDir }
}
Write-Host ''
