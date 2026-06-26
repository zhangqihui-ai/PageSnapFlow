@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lib\bootstrap.ps1"
cd /d "%~dp0"
echo.
echo Trip ADB: discovery feed scroll (10 shots, one page per swipe)
echo Prerequisite: open Trip app on 首页 -^> 综合 tab first.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_trip_capture.ps1" -MaxShots 10 %*
if errorlevel 1 exit /b 1
echo.
echo Done. Check screenshots\trip\ for latest output folder.
