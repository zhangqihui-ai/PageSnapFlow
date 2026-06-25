# Zcool online activity (线上活动) page: 10-shot test capture.

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
$out = Join-Path $Root "screenshots\zcool\${activityLabel}_$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host ""
Write-Host "Zcool online activity ($activityLabel) - 10 screenshots" -ForegroundColor Cyan
Write-Host "Open Zcool on the $activityLabel tab first, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host ""

& python $py --output $out --tab online_activity --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
