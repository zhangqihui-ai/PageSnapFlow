@echo off
setlocal
set RESUME=
if not "%~1"=="" set RESUME=-ResumeDir "%~1"

echo.
echo TapTap ADB: find games b01 -- 14 sub-tabs, then STOP
echo.
echo Usage:
echo   .\run_taptap_find_games_adb.bat
echo   Next: .\run_taptap_ranking_adb.bat screenshots\taptap_lite\YYYYMMDD_HHMMSS
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" ^
  -App taptap_lite -Flow scroll_all_tabs -AdbCapture -BottomTab b01 %RESUME%
