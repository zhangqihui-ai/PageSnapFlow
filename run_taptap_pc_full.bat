@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_pc_pilot.ps1" -UntilBottom -SkipNav %*
exit /b %ERRORLEVEL%
