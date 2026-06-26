@echo off
REM Henan Daily 新闻-精选: scroll until bottom (no shot limit). Keep device awake ~1h.
REM Prerequisite: app open -> 新闻 -> 精选. Optional: -Device SERIAL -ResumeDir path
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_henan_daily_news_pilot.ps1" -UntilBottom %*
exit /b %ERRORLEVEL%
