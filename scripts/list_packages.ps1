# Verify TapTap package name on connected device.
# Usage: .\scripts\list_packages.ps1 taptap

param(
    [Parameter(Mandatory = $false)]
    [string]$Keyword = "taptap"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")

Write-Host "Packages matching '$Keyword':" -ForegroundColor Cyan
adb shell pm list packages | findstr /i $Keyword

Write-Host "`nLaunchable activity:" -ForegroundColor Cyan
adb shell cmd package resolve-activity --brief com.taptap 2>$null

Write-Host "`nTrying to launch app..." -ForegroundColor Cyan
$null = adb shell monkey -p com.taptap -c android.intent.category.LAUNCHER 1 2>&1
Write-Host "If TapTap opened on emulator, package name is correct."
