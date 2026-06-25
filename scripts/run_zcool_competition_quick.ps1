# Zcool competition (赛事) page: 10-shot test capture.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

# Build "赛事" from code points so folder names stay correct on Windows PS 5.1 (non-UTF-8 BOM scripts).
$competitionLabel = -join ([char]0x8D5B, [char]0x4E8B)

$sdkAdb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools"
if (Test-Path (Join-Path $sdkAdb "adb.exe")) {
    $env:PATH = "$sdkAdb;$env:PATH"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $Root "screenshots\zcool\${competitionLabel}_$stamp"
$py = Join-Path $Root "scripts\adb_zcool_capture.py"

Write-Host ""
Write-Host "Zcool competition ($competitionLabel) - 10 screenshots" -ForegroundColor Cyan
Write-Host "Open Zcool on the $competitionLabel tab first, then capture starts." -ForegroundColor Yellow
Write-Host "Output: $out" -ForegroundColor Cyan
Write-Host ""

& python $py --output $out --tab competition --skip-nav --count 10
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host $out
Get-ChildItem $out -Filter "*.png" | ForEach-Object { $_.Name }
