@echo off
echo Open Zcool on the competition tab (赛事) first, then capture starts.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_zcool_competition_quick.ps1"
pause
