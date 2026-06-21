@echo off
setlocal
set RUN_DIR=screenshots\taptap_lite\20260620_101828
if not "%~1"=="" set RUN_DIR=%~1

set EXTRA=
if not "%~2"=="" set EXTRA=-ResumeFrom %~2

set BOTTOM=all
if not "%~3"=="" set BOTTOM=%~3

echo.
echo RESUME ADB crawl from previous run folder: %RUN_DIR%
echo   - Keeps existing screenshots in folder
echo   - Optional 2nd arg: segment key e.g. b02_t01
echo   - Optional 3rd arg: bottom tab e.g. b01 b02 all (default all)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" ^
  -App taptap_lite -Flow scroll_all_tabs -AdbCapture ^
  -ResumeDir "%RUN_DIR%" -BottomTab %BOTTOM% %EXTRA%
