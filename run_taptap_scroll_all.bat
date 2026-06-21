@echo off
echo.
echo FULL crawl: all bottom + top tabs, ~5000-6000 screenshots (no dedup)
echo WARNING: This run may take several hours. Keep emulator awake and TapTap open.
echo.
echo Step 1: Open TapTap on emulator (home tab: find games)
echo Step 2: Full scroll capture starts when TapTap is detected
echo.
python "%~dp0scripts\generate_taptap_scroll_flow.py"
if errorlevel 1 exit /b 1
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" -App taptap_lite -Flow scroll_all_tabs %*
