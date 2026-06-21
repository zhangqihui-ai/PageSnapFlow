# Verify PageSnapFlow environment is ready to run flows.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
$Ok = $true

function Check($Label, $Pass, $Hint) {
    if ($Pass) {
        Write-Host "[OK]   $Label" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Label" -ForegroundColor Red
        if ($Hint) { Write-Host "       $Hint" -ForegroundColor Yellow }
        $script:Ok = $false
    }
}

Write-Host "PageSnapFlow environment check`n" -ForegroundColor Cyan

$hasMaestro = $null -ne (Get-Command maestro -ErrorAction SilentlyContinue)
Check "Maestro CLI" $hasMaestro "Run .\scripts\setup_env.ps1"

$hasAdb = $null -ne (Get-Command adb -ErrorAction SilentlyContinue)
Check "ADB" $hasAdb "Open Android Studio SDK Tools and install Platform-Tools, then run init.bat"

$hasDevice = $false
if ($hasAdb) {
    $lines = adb devices 2>&1 | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
    $hasDevice = @($lines).Count -gt 0
}
Check "Android device/emulator" $hasDevice "Connect phone or start emulator (adb devices)"

$flowsDir = Join-Path $Root "flows"
Check "flows/ directory" (Test-Path $flowsDir) "Missing project flows directory"

$appsYaml = Join-Path $Root "config\apps.yaml"
Check "config/apps.yaml" (Test-Path $appsYaml) "Missing app registry"

if ($hasMaestro) {
    Write-Host "`nMaestro version: $(maestro --version 2>&1)"
}

if ($hasAdb -and $hasDevice) {
    Write-Host "`nDevice info:"
    adb shell getprop ro.product.model 2>$null
    adb shell wm size 2>$null
}

if (-not $Ok) {
    Write-Host "`nEnvironment not ready. Fix issues above and re-run." -ForegroundColor Red
    exit 1
}

Write-Host "`nEnvironment ready. Try: maestro studio" -ForegroundColor Green
exit 0
