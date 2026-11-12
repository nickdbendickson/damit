@echo off
rem Installs the dam suite for you (no admin). Options, e.g.:  install-all-windows.cmd -NoAI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-all-windows.ps1" %*
echo.
pause
