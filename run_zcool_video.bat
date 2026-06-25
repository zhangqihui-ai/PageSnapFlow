@echo off
echo Open Zcool on Video tab first, then capture starts.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_zcool_video_quick.ps1"
pause
