@echo off
setlocal
set "ROOT=%~dp0"

echo Open Zhiduidui on Home ^> Local Jobs tab first, then capture starts.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run_zhiduidui_local_jobs_full.ps1"
set "ERR=%ERRORLEVEL%"

echo.
if %ERR% neq 0 (
  echo Failed with exit code %ERR%.
) else (
  echo Finished.
)
pause
exit /b %ERR%
