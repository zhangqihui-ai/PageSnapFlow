# Verify TapTap can launch before running Maestro flows.

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")

Write-Host "Launching TapTap via ADB..." -ForegroundColor Cyan
adb shell am force-stop com.taptap
Start-Sleep -Seconds 1
adb shell am start -n com.taptap/com.play.taptap.ui.SplashAct

Write-Host "Waiting 8s for app to load..." -ForegroundColor Cyan
Start-Sleep -Seconds 8

$focus = adb shell dumpsys window 2>$null | Select-String "mCurrentFocus"
Write-Host "Current focus: $focus"

if ($focus -match "taptap") {
    Write-Host "TapTap is in foreground. Safe to run run_taptap_scroll.bat" -ForegroundColor Green
} else {
    Write-Host "TapTap NOT in foreground. Fix emulator before running Maestro." -ForegroundColor Red
    Write-Host "Try: Cold Boot emulator, or tap TapTap icon manually once." -ForegroundColor Yellow
}
