<#
.SYNOPSIS
  Removes Kitchen Coach. Your saved recipes are kept unless you add -RemoveData.
#>
[CmdletBinding()]
param(
    [switch]$RemoveData,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\KitchenCoach')
)
$ErrorActionPreference = 'Continue'
Get-Process -Name 'KitchenCoach' -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*KitchenCoach*launcher.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# Close the Kitchen Coach app window (it uses its own browser profile)
Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*KitchenCoach\window-profile*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

foreach ($folder in 'Desktop', 'Programs', 'Startup') {
    $dir = [Environment]::GetFolderPath($folder)
    Remove-Item (Join-Path $dir 'Kitchen Coach.lnk') -ErrorAction SilentlyContinue
}
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'Uninstall Kitchen Coach.lnk') -ErrorAction SilentlyContinue
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

if ($RemoveData) {
    Remove-Item (Join-Path $env:LOCALAPPDATA 'KitchenCoach') -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '  Kitchen Coach and your saved recipes have been removed.' -ForegroundColor Green
} else {
    Write-Host '  Kitchen Coach has been removed. Saved recipes are kept in %LOCALAPPDATA%\KitchenCoach' -ForegroundColor Green
    Write-Host '  (run again with -RemoveData to delete them too).'
}
