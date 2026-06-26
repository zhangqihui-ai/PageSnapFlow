@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lib\bootstrap.ps1"
cd /d "%~dp0"
echo.
echo Trip ADB: 综合 tab full capture until 5000 shots
echo Prerequisite: open Trip app on 首页 -^> 综合 tab first.
echo Output: screenshots\trip\综合\
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_trip_capture.ps1" -OutputSubdir 综合 -MaxShots 5000 %*
if errorlevel 1 exit /b 1
echo.
echo Done. Check screenshots\trip\综合\
