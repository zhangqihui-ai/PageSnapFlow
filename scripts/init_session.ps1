# Load Maestro + ADB + Java into current PowerShell session.
# Usage: . .\scripts\init_session.ps1

$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")

Write-Host "`nSession PATH ready:" -ForegroundColor Cyan
if (Get-Command java -ErrorAction SilentlyContinue) {
    Write-Host "  java:  $(java -version 2>&1 | Select-Object -First 1)"
} else {
    Write-Host "  java:  NOT FOUND" -ForegroundColor Yellow
}
if (Get-Command adb -ErrorAction SilentlyContinue) {
    Write-Host "  adb:   $(adb version 2>&1 | Select-Object -First 1)"
} else {
    Write-Host "  adb:   NOT FOUND (finish Android Studio SDK setup first)" -ForegroundColor Yellow
}
if (Get-Command maestro -ErrorAction SilentlyContinue) {
    Write-Host "  maestro: $(maestro --version 2>&1 | Select-Object -First 1)"
} else {
    Write-Host "  maestro: NOT FOUND (run setup.bat first)" -ForegroundColor Yellow
}
if ($env:ANDROID_HOME) {
    Write-Host "  ANDROID_HOME: $env:ANDROID_HOME"
}
