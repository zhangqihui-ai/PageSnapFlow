@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_henan_daily_news_pilot.ps1" -Shots 10 -SkipNav %*
exit /b %ERRORLEVEL%
