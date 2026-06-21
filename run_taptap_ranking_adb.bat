@echo off
setlocal
set RESUME=
if not "%~1"=="" set RESUME=-ResumeDir "%~1"

echo.
echo TapTap ADB: ranking b02 -- 14 sub-tabs, then STOP
echo.
echo Usage:
echo   .\run_taptap_ranking_adb.bat
echo   .\run_taptap_ranking_adb.bat screenshots\taptap_lite\20260620_111750
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" ^
  -App taptap_lite -Flow scroll_all_tabs -AdbCapture -BottomTab b02 %RESUME%
