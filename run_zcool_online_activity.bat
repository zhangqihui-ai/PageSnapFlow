@echo off
echo Open Zcool on the online activity tab (线上活动) first, then capture starts.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_zcool_online_activity_quick.ps1"
pause
