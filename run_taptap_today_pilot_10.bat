@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_today_pilot.ps1" -Shots 10 %*
exit /b %ERRORLEVEL%
