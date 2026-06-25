# Zhiduidui home > local jobs: 10-shot test capture.

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
$out = Join-Path $Root "screenshots\zhiduidui\${appLabel}_${tabLabel}_$stamp"
$py = Join-Path $Root "scripts\adb_zhiduidui_capture.py"

Write-Host ""
Write-Host "$appLabel - $tabLabel - 10 screenshots" -ForegroundColor Cyan
Write-Host "Open app on Home > $tabLabel, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host ""

& python $py --output $out --tab local_jobs --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
