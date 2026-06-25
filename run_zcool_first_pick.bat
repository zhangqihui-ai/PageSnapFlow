@echo off
setlocal
echo Open Zcool on Home ^> first_pick (首推), then capture starts.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_zcool_first_pick_quick.ps1"
pause
