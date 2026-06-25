# Zcool home first_pick: 10-shot test capture.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zcool\first_pick_$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host ""
Write-Host "Zcool home > first_pick - 10 screenshots" -ForegroundColor Cyan
Write-Host "Open Zcool on Home > first_pick (首推), then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host ""

& python $py --output $out --tab first_pick --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
