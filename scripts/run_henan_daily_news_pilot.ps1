param(
    [int]$Shots = 10,
    [switch]$Full,
    [switch]$UntilBottom,
    [string]$Device = $null,
    [string]$ResumeDir = $null
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Error "Python not found."
}

$Pilot = Join-Path $PSScriptRoot "pilot_henan_daily_news_scroll.py"
$PilotArgs = @()
if ($UntilBottom) {
    $PilotArgs += "--until-bottom"
} elseif ($Full) {
    $PilotArgs += "--full"
} else {
    $PilotArgs += @("--shots", $Shots)
}
$PilotArgs += "--skip-nav"
if ($Device) {
    $PilotArgs += @("--device", $Device)
}
if ($ResumeDir) {
    $PilotArgs += @("--resume-dir", $ResumeDir)
}

Write-Host ""
if ($UntilBottom) {
    Write-Host "Henan Daily news-featured FULL capture (until bottom)" -ForegroundColor Cyan
    Write-Host "No shot limit — stops at bottom marker or when feed no longer scrolls." -ForegroundColor Yellow
} else {
    Write-Host "Henan Daily news-featured scroll capture" -ForegroundColor Cyan
}
Write-Host "Tip: open app -> News -> Featured (精选) on device; keep screen on." -ForegroundColor Yellow
Write-Host ""

& $Python.Source $Pilot @PilotArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Capture failed with exit code $LASTEXITCODE"
}

$Marker = Join-Path $Root "screenshots\henan_daily\latest_henan_news_featured_output_dir.txt"
$Out = (Get-Content $Marker -Raw -Encoding UTF8).Trim()

& $Python.Source (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input (Join-Path $Out "adb_raw") `
    --output $Out `
    --app henan_daily `
    --flow news_featured_pilot

Write-Host ""
Write-Host "Output: $Out" -ForegroundColor Green
Write-Host ""
