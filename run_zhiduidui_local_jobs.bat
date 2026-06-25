@echo off
echo Open Zhiduidui on Home ^> Local Jobs tab first, then capture starts.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_zhiduidui_local_jobs_quick.ps1"
pause
