@echo off
echo.
echo FULL ADB crawl: all bottom tabs (50 segments)
echo   Per-tab runs (recommended): run_taptap_find_games_adb.bat, run_taptap_ranking_adb.bat, ...
echo.
python "%~dp0scripts\estimate_capture_plan.py" --bottom-tab all
echo.
python "%~dp0scripts\generate_taptap_scroll_flow.py"
if errorlevel 1 exit /b 1
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" -App taptap_lite -Flow scroll_all_tabs -AdbCapture -BottomTab all %*
