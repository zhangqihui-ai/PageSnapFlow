@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_community_discover_pilot.ps1" -UntilBottom -SkipNav %*
exit /b %ERRORLEVEL%
