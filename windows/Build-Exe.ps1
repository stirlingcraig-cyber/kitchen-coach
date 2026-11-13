<#
.SYNOPSIS
  Builds KitchenCoach.exe with PyInstaller and packages dist\KitchenCoach-Windows.zip.
  Run from anywhere:  powershell -ExecutionPolicy Bypass -File windows\Build-Exe.ps1
  (GitHub Actions runs this automatically - see .github/workflows/windows-build.yml)
#>
[CmdletBinding()]
param([switch]$UseCurrentPython)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if ($UseCurrentPython) { $py = 'python' }
else {
    if (-not (Test-Path '.build-venv\Scripts\python.exe')) { py -3 -m venv .build-venv }
    $py = Resolve-Path '.build-venv\Scripts\python.exe'
}
& $py -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

& $py -m PyInstaller --noconfirm --clean --windowed --name KitchenCoach `
    --icon assets\kitchen_coach.ico `
    --add-data "web;web" `
    --version-file windows\version_info.txt `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$stage = Join-Path $root 'dist\KitchenCoach-Windows'
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item 'dist\KitchenCoach' $stage -Recurse
Copy-Item 'windows\Install.bat', 'windows\Install-KitchenCoach.ps1', 'windows\Uninstall-KitchenCoach.ps1' $stage
Copy-Item 'docs\Kitchen_Coach_User_Guide.pdf' $stage -ErrorAction SilentlyContinue
$zip = Join-Path $root 'dist\KitchenCoach-Windows.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
Write-Host "Built $zip" -ForegroundColor Green
