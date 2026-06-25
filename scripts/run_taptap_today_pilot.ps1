param(
    [int]$Shots = 10,
    [switch]$Full,
    [switch]$SkipNav
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Error "Python not found."
}

$Pilot = Join-Path $PSScriptRoot "pilot_taptap_today_scroll.py"
$PilotArgs = @()
if ($Full) {
    $PilotArgs += "--full"
} else {
    $PilotArgs += @("--shots", $Shots)
}
if ($SkipNav) {
    $PilotArgs += "--skip-nav"
}

Write-Host ""
Write-Host "TapTap Today Games scroll capture (first-game text aligned)" -ForegroundColor Cyan
Write-Host "Tip: open TapTap -> Find Games -> Today Games before running." -ForegroundColor Yellow
Write-Host "     Add -SkipNav if you are already on Today Games." -ForegroundColor Yellow
Write-Host ""

& $Python.Source $Pilot @PilotArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Capture failed with exit code $LASTEXITCODE"
}

$Marker = Join-Path $Root "screenshots\taptap_lite\latest_today_output_dir.txt"
if (-not (Test-Path $Marker)) {
    Write-Error "Marker file not found: $Marker"
}
$Out = (Get-Content $Marker -Raw -Encoding UTF8).Trim()

& $Python.Source (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input (Join-Path $Out "adb_raw") `
    --output $Out `
    --app taptap_lite `
    --flow scroll_today_games_pilot

Write-Host ""
Write-Host "Output: $Out" -ForegroundColor Green
Write-Host ""
