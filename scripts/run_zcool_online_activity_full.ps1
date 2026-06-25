# Zcool online activity (线上活动) page: scroll to bottom and capture all unique frames.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$activityLabel = -join ([char]0x7EBF, [char]0x4E0A, [char]0x6D3B, [char]0x52A8)

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zcool\${activityLabel}_full_$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host ""
Write-Host "Zcool online activity ($activityLabel) - full scroll capture" -ForegroundColor Cyan
Write-Host "Open Zcool on the $activityLabel tab first, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host "Starting..." -ForegroundColor Yellow
Write-Host ""

& python $py --output $out --tab online_activity --skip-nav --until-bottom
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$reportPath = Join-Path $out "capture_report.json"
if (Test-Path $reportPath) {
    $r = Get-Content $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ""
    Write-Host "========== Done ==========" -ForegroundColor Cyan
    Write-Host "Saved:    $($r.saved)"
    Write-Host "Duration: $($r.duration_seconds)s"
    Write-Host "Bottom:   $($r.reached_bottom)"
    Write-Host "Folder:   $out" -ForegroundColor Green
}
