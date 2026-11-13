@echo off
rem Double-click to install Kitchen Coach (desktop icon + start automatically at sign-in).
rem To install WITHOUT starting at sign-in, run:  Install.bat -NoStartup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-KitchenCoach.ps1" %*
echo.
pause
