# Zcool home recommend: quick 10-shot test capture.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zcool\$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host "Output: $out" -ForegroundColor Cyan
& python $py --output $out --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. Screenshots:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
