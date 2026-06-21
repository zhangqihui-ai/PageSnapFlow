# Smoke test for collect_screenshots.py (no device / Maestro required)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\python.ps1")
$Python = Get-PythonCommand
if (-not $Python) { Write-Error "Python required for smoke test" }

$Tmp = Join-Path $Root "screenshots\_test_run"
$Raw = Join-Path $Tmp "maestro_raw"
$Out = Join-Path $Tmp "output"
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Raw | Out-Null

# Minimal 1x1 PNG (valid PNG header + IHDR + IEND)
$pngBytes = [byte[]]@(
    0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,
    0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,
    0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,
    0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,
    0xDE,0x00,0x00,0x00,0x0C,0x49,0x44,0x41,
    0x54,0x08,0xD7,0x63,0xF8,0xCF,0xC0,0x00,
    0x00,0x00,0x03,0x00,0x01,0x00,0x18,0xDD,
    0x8D,0xB4,0x00,0x00,0x00,0x00,0x49,0x45,
    0x4E,0x44,0xAE,0x42,0x60,0x82
)
foreach ($name in @("01_home.png", "02_swipe.png", "03_tab.png")) {
    [IO.File]::WriteAllBytes((Join-Path $Raw $name), $pngBytes)
}

& $Python (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input $Raw --output $Out --app test --flow smoke

if (-not (Test-Path (Join-Path $Out "run_manifest.json"))) {
    Write-Error "run_manifest.json not created"
}

Write-Host "collect_screenshots smoke test OK" -ForegroundColor Green
