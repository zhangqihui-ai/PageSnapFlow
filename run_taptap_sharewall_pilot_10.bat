@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_sharewall_pilot.ps1" -Shots 10 -SkipNav %*
exit /b %ERRORLEVEL%
