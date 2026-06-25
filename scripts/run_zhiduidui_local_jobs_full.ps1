# Zhiduidui home > local jobs: scroll to bottom and capture.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$appLabel = -join ([char]0x804C, [char]0x5806, [char]0x5806, [char]0x517C, [char]0x804C)
$tabLabel = -join ([char]0x672C, [char]0x5730, [char]0x5DE5, [char]0x4F5C)

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zhiduidui\${appLabel}_${tabLabel}_full_$stamp"
$py = Join-Path $Root "scripts\adb_zhiduidui_capture.py"

Write-Host ""
Write-Host "$appLabel - $tabLabel - full scroll capture" -ForegroundColor Cyan
Write-Host "Open app on Home > $tabLabel, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host "Starting..." -ForegroundColor Yellow
Write-Host ""

& python $py --output $out --tab local_jobs --skip-nav --until-bottom
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
