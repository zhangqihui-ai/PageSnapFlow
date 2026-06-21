@echo off
setlocal
set RESUME=
if not "%~1"=="" set RESUME=-ResumeDir "%~1"

echo.
echo TapTap ADB: 社区 b03 — 发现 / 热榜 / 论坛 (3 sub-tabs), then STOP
echo.
echo Usage:
echo   .\run_taptap_community_adb.bat
echo   .\run_taptap_community_adb.bat screenshots\taptap_lite\YYYYMMDD_HHMMSS
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" ^
  -App taptap_lite -Flow scroll_all_tabs -AdbCapture -BottomTab b03 %RESUME% %*
