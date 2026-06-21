@echo off
echo.
echo PILOT: Today Games tab - horizontal dates + drill-down cards (ADB)
echo [1/2] Open TapTap on emulator, stay on Find Games home
echo [2/2] ADB hybrid capture for Today Games tab
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" -App taptap_lite -Flow scroll_today_games_pilot -AdbCapture %*
