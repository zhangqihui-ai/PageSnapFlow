@echo off
setlocal
set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not exist "%ADB%" (
  echo adb not found: %ADB%
  exit /b 1
)

echo Hide gesture hint bar (safe mode, no overlay)...
"%ADB%" shell settings put global navigation_bar_gesture_hint 0
echo.
echo Done. Lock/unlock screen or switch apps to see the change.
echo To restore: hide_gesture_hint_restore.bat
pause
