# Poll ADB until TapTap is foreground (manual launch mode).

param(
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")

Write-Host ""
Write-Host "Please open TapTap on the emulator (wait until you see bottom tab: 找游戏)." -ForegroundColor Cyan
Write-Host "Waiting up to ${TimeoutSec}s ..." -ForegroundColor Cyan
Write-Host ""

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    $focus = adb shell dumpsys window 2>$null | Select-String "mCurrentFocus"
    if ($focus -match "taptap") {
        Write-Host "TapTap is in foreground. Starting Maestro flow..." -ForegroundColor Green
        exit 0
    }
    $remaining = [int]($deadline - (Get-Date)).TotalSeconds
    Write-Host "  TapTap not detected yet (${remaining}s left) ..."
    Start-Sleep -Seconds 3
}

Write-Host "Timeout: TapTap not in foreground. Open TapTap manually and retry." -ForegroundColor Red
exit 1
