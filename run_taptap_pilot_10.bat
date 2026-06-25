@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lib\bootstrap.ps1"
cd /d "%~dp0"
python "%~dp0scripts\pilot_taptap_scroll.py" --shots 10
if errorlevel 1 exit /b 1
for /f "tokens=2 delims==" %%a in ('findstr /C:"OUTPUT_DIR="') do set OUT=%%a
python "%~dp0scripts\collect_screenshots.py" --input "%OUT%\adb_raw" --output "%OUT%" --app taptap_lite --flow scroll_bottom1_top1_fast
echo.
echo Output: %OUT%
