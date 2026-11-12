@echo off
rem Downloads everything install-all needs into offline\ (run on a networked machine).
rem Options, e.g.:  download-all-windows.cmd -NoModels    or    -Platform all -Pack
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-all-windows.ps1" %*
echo.
pause
