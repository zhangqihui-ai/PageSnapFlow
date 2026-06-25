# Run Booking.com hotel list ADB scroll capture.

param(
    [string]$Device = $null,
    [int]$MaxShots = 10,
    [string]$ResumeDir = $null
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
. (Join-Path $PSScriptRoot "lib\python.ps1")
$Python = Get-PythonCommand

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Error "adb not found. Run: . .\scripts\lib\bootstrap.ps1"
}
if (-not $Python) {
    Write-Error "Python 3.8+ required."
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ($ResumeDir) {
    if ([System.IO.Path]::IsPathRooted($ResumeDir)) {
        $OutputDir = $ResumeDir
    } else {
        $OutputDir = Join-Path $Root $ResumeDir
    }
} else {
    $OutputDir = Join-Path $Root "screenshots\booking\$Timestamp"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Booking capture: $MaxShots shots (auto scroll-to-top first)" -ForegroundColor Cyan
Write-Host "Output: $OutputDir" -ForegroundColor Cyan

$AdbArgs = @(
    (Join-Path $PSScriptRoot "adb_booking_capture.py"),
    "--output", $OutputDir,
    "--max-shots", $MaxShots
)
if ($Device) {
    $AdbArgs += @("--device", $Device)
}

& $Python @AdbArgs
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    exit $ExitCode
}

# Flatten adb_raw screenshots into output folder for easy review
$RawShots = Join-Path $OutputDir "adb_raw\screenshots"
if (Test-Path $RawShots) {
    $idx = 1
    Get-ChildItem $RawShots -Filter "*.png" | Sort-Object Name | ForEach-Object {
        $dest = Join-Path $OutputDir ("{0:D3}_{1}" -f $idx, $_.Name)
        Copy-Item $_.FullName $dest -Force
        $idx++
    }
    Write-Host "Flattened $($idx - 1) PNG(s) to $OutputDir" -ForegroundColor Green
}

exit 0
