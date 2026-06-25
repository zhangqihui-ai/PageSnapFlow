@echo off
setlocal
set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not exist "%ADB%" (
  echo adb not found: %ADB%
  exit /b 1
)

echo Restore gesture hint bar...
"%ADB%" shell settings put global navigation_bar_gesture_hint 1
"%ADB%" shell cmd overlay disable com.android.internal.systemui.navbar.transparent
echo Done.
pause
