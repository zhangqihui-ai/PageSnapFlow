@echo off
echo.
echo ADB capture: direct screencap, no Maestro UI settle wait
echo [1/2] Open TapTap manually on the emulator (home tab)
echo [2/2] ADB scroll + capture starts when TapTap is detected
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_flow.ps1" -App taptap_lite -Flow scroll_bottom1_top1_fast -AdbCapture %*
