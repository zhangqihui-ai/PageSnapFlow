@echo off
REM Henan Daily 新闻-河南: scroll until bottom (no shot limit). Keep device awake.
REM Prerequisite: app open -> 新闻 -> 河南. Optional: -Device SERIAL -ResumeDir path
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_henan_daily_henan_pilot.ps1" -UntilBottom %*
exit /b %ERRORLEVEL%
