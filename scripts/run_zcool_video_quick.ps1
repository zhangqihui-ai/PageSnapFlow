# Zcool video tab: 10 screenshots (1 per video, swipe up for next).

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zcool\video_$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host ""
Write-Host "Zcool video tab - 10 videos (1 shot each, swipe down for next)" -ForegroundColor Cyan
Write-Host "Open Zcool on Video tab first, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host ""

& python $py --output $out --tab video --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
