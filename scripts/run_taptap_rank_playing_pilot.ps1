param(
    [int]$Shots = 10,
    [switch]$Full,
    [switch]$UntilBottom,
    [switch]$SkipNav,
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

$Pilot = Join-Path $PSScriptRoot "pilot_taptap_rank_playing_scroll.py"
$PilotArgs = @()
if ($UntilBottom) {
    $PilotArgs += "--until-bottom"
} elseif ($Full) {
    $PilotArgs += "--full"
} else {
    $PilotArgs += @("--shots", $Shots)
}
if ($SkipNav) {
    $PilotArgs += "--skip-nav"
}
if ($ResumeDir) {
    $PilotArgs += @("--resume-dir", $ResumeDir)
    if (-not $SkipNav) {
        $PilotArgs += "--skip-nav"
    }
}

Write-Host ""
Write-Host "TapTap ranking hot-play list scroll capture" -ForegroundColor Cyan
Write-Host "Tip: open TapTap -> Rankings -> Hot Play before running." -ForegroundColor Yellow
Write-Host "     Add -SkipNav if already on Hot Play." -ForegroundColor Yellow
Write-Host "     First run scrolls list to top, then ~8 games per page." -ForegroundColor Yellow
if ($ResumeDir) {
    Write-Host "Resume mode: append to existing folder" -ForegroundColor Yellow
}
Write-Host ""

& $Python.Source $Pilot @PilotArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Capture failed with exit code $LASTEXITCODE"
}

$Marker = Join-Path $Root "screenshots\taptap_lite\latest_rank_playing_output_dir.txt"
$Out = (Get-Content $Marker -Raw -Encoding UTF8).Trim()

& $Python.Source (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input (Join-Path $Out "adb_raw") `
    --output $Out `
    --app taptap_lite `
    --flow scroll_rank_playing_pilot

Write-Host ""
Write-Host "Output: $Out" -ForegroundColor Green
Write-Host ""
