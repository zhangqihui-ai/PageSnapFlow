@echo off
echo.
echo [1/2] Open TapTap manually on the emulator (home tab)
echo [2/2] Script detects TapTap then scrolls and captures screenshots
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" -App taptap_lite -Flow scroll_bottom1_top1 -Dedup -Similarity 0.90 %*
