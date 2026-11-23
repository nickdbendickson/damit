@echo off
rem Double-click this file to install (or update) both local AIs, Heim and Vor, on this PC.
rem It starts install-local-ai-windows.ps1 from this folder (no admin rights needed).
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-local-ai-windows.ps1" %*
echo.
echo This window can be closed. Open a NEW PowerShell or Command Prompt window to use heim and vor.
pause
