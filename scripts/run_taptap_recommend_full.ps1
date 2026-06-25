# TapTap find_games -> recommend: full aligned scroll capture

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
Set-Location $Root

Write-Host ""
Write-Host "TapTap recommend feed: full scroll capture (text-bottom aligned)" -ForegroundColor Cyan
Write-Host "[1/3] Open TapTap on emulator: Find Games -> Recommend" -ForegroundColor Yellow
Write-Host "[2/3] Scrolling (max 150 swipes + 1 start, ~5-8 min)..." -ForegroundColor Yellow
Write-Host "[3/3] Collecting screenshots..." -ForegroundColor Yellow
Write-Host ""

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Error "Python not found. Install Python 3.8+ and add it to PATH."
}

$Pilot = Join-Path $PSScriptRoot "pilot_taptap_scroll.py"
& $Python.Source $Pilot --full
if ($LASTEXITCODE -ne 0) {
    Write-Error "Capture failed with exit code $LASTEXITCODE"
}

$Marker = Join-Path $Root "screenshots\taptap_lite\latest_output_dir.txt"
if (-not (Test-Path $Marker)) {
    Write-Error "Marker file not found: $Marker"
}
$Out = (Get-Content $Marker -Raw -Encoding UTF8).Trim()
if (-not (Test-Path $Out)) {
    Write-Error "Output directory not found: $Out"
}

& $Python.Source (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input (Join-Path $Out "adb_raw") `
    --output $Out `
    --app taptap_lite `
    --flow scroll_bottom1_top1_fast

if ($LASTEXITCODE -ne 0) {
    Write-Error "collect_screenshots failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "========== Done ==========" -ForegroundColor Green
Write-Host "Output: $Out"
Write-Host "=========================="
Write-Host ""
