# Restore Android navigation / gesture hint after capture.

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

Write-Host "Restoring navigation settings..." -ForegroundColor Yellow
adb shell settings put global policy_control null
adb shell settings put global navigation_bar_gesture_hint 1
adb shell cmd overlay disable com.android.internal.systemui.navbar.transparent
adb shell cmd window set-hide-nav-bar false 2>$null
Write-Host "Done. Lock/unlock screen or restart emulator if bar still looks wrong." -ForegroundColor Green
