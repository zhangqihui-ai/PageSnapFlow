@echo off
setlocal
set "ROOT=%~dp0"

echo Open Zcool on the competition tab (赛事) first, then capture starts.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run_zcool_competition_full.ps1"
set "ERR=%ERRORLEVEL%"

echo.
if %ERR% neq 0 (
  echo Failed with exit code %ERR%.
) else (
  echo Finished.
)
pause
exit /b %ERR%
