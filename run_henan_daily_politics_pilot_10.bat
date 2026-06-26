@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_henan_daily_politics_pilot.ps1" -Shots 10 -Device CUYDU19620001160 %*
exit /b %ERRORLEVEL%
