# Run a single Maestro flow and collect screenshots.

param(
    [Parameter(Mandatory = $true)]
    [string]$App,

    [Parameter(Mandatory = $false)]
    [string]$Flow = "home_browse",

    [Parameter(Mandatory = $false)]
    [string]$Device = $null,

    [Parameter(Mandatory = $false)]
    [switch]$Dedup,

    [Parameter(Mandatory = $false)]
    [switch]$AutoLaunch,

    [Parameter(Mandatory = $false)]
    [switch]$AdbCapture,

    [Parameter(Mandatory = $false)]
    [string]$ResumeDir = $null,

    [Parameter(Mandatory = $false)]
    [string]$ResumeFrom = $null,

    [Parameter(Mandatory = $false)]
    [string]$BottomTab = "b01",

    [Parameter(Mandatory = $false)]
    [double]$Similarity = 0.95
)

$ErrorActionPreference = "Stop"
$RunStartedAt = Get-Date
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
. (Join-Path $PSScriptRoot "lib\python.ps1")
$Python = Get-PythonCommand

if ($AdbCapture) {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        Write-Error "AdbCapture requires adb in PATH."
    }
    if (-not $Python) {
        Write-Error "AdbCapture requires Python 3.8+."
    }
} else {
    Assert-PageSnapFlowToolchain
}

$FlowPath = Join-Path $Root "flows\$App\$Flow.yaml"
if (-not $AdbCapture -and -not (Test-Path $FlowPath)) {
    Write-Error "Flow not found: $FlowPath"
}

if ($App -eq "taptap_lite") {
    if ($AutoLaunch -and -not $AdbCapture) {
        Write-Host "Auto-launching TapTap via Maestro..." -ForegroundColor Cyan
        $LaunchFlow = Join-Path $Root "flows\common\launch_taptap.yaml"
        & maestro test $LaunchFlow
        if ($LASTEXITCODE -ne 0) {
            Write-Host "TapTap auto-launch failed." -ForegroundColor Yellow
        }
    } else {
        & (Join-Path $PSScriptRoot "wait_for_taptap.ps1") -TimeoutSec 120
        if ($LASTEXITCODE -ne 0) {
            exit 1
        }
    }
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if ($ResumeDir) {
    if ([System.IO.Path]::IsPathRooted($ResumeDir)) {
        $OutputDir = $ResumeDir
    } else {
        $OutputDir = Join-Path $Root $ResumeDir
    }
    if (-not (Test-Path $OutputDir)) {
        Write-Error "ResumeDir not found: $OutputDir"
    }
    Write-Host "Resume run folder: $OutputDir" -ForegroundColor Cyan
} else {
    $OutputDir = Join-Path $Root "screenshots\$App\$Timestamp"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

$CaptureMode = if ($AdbCapture) { "adb" } else { "maestro" }
$ExitCode = 0
$DeviceName = $Device

if ($AdbCapture) {
    if ($App -ne "taptap_lite") {
        Write-Error "AdbCapture is currently supported for App=taptap_lite only."
    }

    $AdbRaw = Join-Path $OutputDir "adb_raw"
    New-Item -ItemType Directory -Force -Path $AdbRaw | Out-Null

    Write-Host "Capture mode: ADB (direct screencap, no Maestro takeScreenshot)" -ForegroundColor Cyan
    if ($ResumeDir) {
        Write-Host "Resume: continuing previous capture in same folder" -ForegroundColor Yellow
    }
    Write-Host "Flow profile: $Flow" -ForegroundColor Cyan
    if ($BottomTab -and $BottomTab -ne "all") {
        Write-Host "Bottom tab scope: $BottomTab (this run stops after its sub-tabs finish)" -ForegroundColor Cyan
    } elseif ($BottomTab -eq "all") {
        Write-Host "Bottom tab scope: all (full crawl)" -ForegroundColor Cyan
    }
    Write-Host "Output: $OutputDir"

    $AdbArgs = @(
        (Join-Path $PSScriptRoot "adb_taptap_capture.py"),
        "--output", $AdbRaw,
        "--flow", $Flow,
        "--bottom-tab", $BottomTab
    )
    if ($ResumeDir) {
        $AdbArgs += @("--resume")
    }
    if ($ResumeFrom) {
        $AdbArgs += @("--resume-from", $ResumeFrom)
    }
    if ($DeviceName) {
        $AdbArgs += @("--device", $DeviceName)
    }

    & $Python @AdbArgs
    $ExitCode = $LASTEXITCODE
    $CollectInput = $AdbRaw
    $DupReportSrc = Join-Path $AdbRaw "duplicate_report.json"
    if (Test-Path $DupReportSrc) {
        Copy-Item $DupReportSrc (Join-Path $OutputDir "duplicate_report.json") -Force
    }
} else {
    $MaestroOut = Join-Path $OutputDir "maestro_raw"
    New-Item -ItemType Directory -Force -Path $MaestroOut | Out-Null

    Write-Host "Capture mode: Maestro (default takeScreenshot)" -ForegroundColor Cyan
    Write-Host "Running flow: $FlowPath" -ForegroundColor Cyan
    Write-Host "Output: $OutputDir"

    $MaestroArgs = @(
        "test",
        $FlowPath,
        "--test-output-dir", $MaestroOut
    )

    $env:MAESTRO_DRIVER_STARTUP_TIMEOUT = "120000"

    if ($DeviceName) {
        $MaestroArgs += @("--device", $DeviceName)
    }

    Push-Location $Root
    try {
        & maestro @MaestroArgs
        $ExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $CollectInput = $MaestroOut
}

if (-not $DeviceName -and (Get-Command adb -ErrorAction SilentlyContinue)) {
    $DeviceName = (adb devices 2>&1 | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" } | Select-Object -First 1)
    if ($DeviceName) { $DeviceName = ($DeviceName -split "\t")[0] }
}

if (-not $Python) {
    Write-Error "Python not found. Install Python 3.8+ and run: pip install -r requirements.txt"
}

& $Python (Join-Path $PSScriptRoot "collect_screenshots.py") `
    --input $CollectInput `
    --output $OutputDir `
    --app $App `
    --flow $Flow `
    --device $DeviceName

if ($Dedup) {
    if (-not (Ensure-PythonDeps $Python)) {
        Write-Host "Dedup skipped: install deps with: python -m pip install -r requirements.txt" -ForegroundColor Yellow
    } else {
        $UniqueDir = Join-Path $OutputDir "unique"
        Write-Host "Deduplicating similar frames -> $UniqueDir (similarity=$Similarity)" -ForegroundColor Cyan
        & $Python (Join-Path $PSScriptRoot "dedup_screenshots.py") `
            --input $OutputDir `
            --output $UniqueDir `
            --similarity $Similarity

        if ($LASTEXITCODE -eq 0) {
            $UniqueCount = (Get-ChildItem -Path $UniqueDir -Filter "*.png" -ErrorAction SilentlyContinue).Count
            Write-Host "Unique screenshots (deduped): $UniqueDir ($UniqueCount files)" -ForegroundColor Green
        }
    }
}

$RunEndedAt = Get-Date
$Elapsed = $RunEndedAt - $RunStartedAt
$ScreenshotCount = (Get-ChildItem -Path $OutputDir -Filter "*.png" -ErrorAction SilentlyContinue).Count
$UniqueCountFinal = 0
if ($Dedup) {
    $UniqueDirFinal = Join-Path $OutputDir "unique"
    $UniqueCountFinal = (Get-ChildItem -Path $UniqueDirFinal -Filter "*.png" -ErrorAction SilentlyContinue).Count
}

$DurationSec = [math]::Round($Elapsed.TotalSeconds, 1)
$DurationMin = [math]::Floor($Elapsed.TotalMinutes)
$DurationSecPart = [math]::Floor($Elapsed.TotalSeconds - ($DurationMin * 60))
$DurationLabel = "{0} min {1} sec" -f $DurationMin, $DurationSecPart

$ManifestPath = Join-Path $OutputDir "run_manifest.json"
if (Test-Path $ManifestPath) {
    $Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $Manifest | Add-Member -NotePropertyName "capture_mode" -NotePropertyValue $CaptureMode -Force
    if ($AdbCapture -and $BottomTab) {
        $Manifest | Add-Member -NotePropertyName "bottom_tab" -NotePropertyValue $BottomTab -Force
    }
    $Manifest | Add-Member -NotePropertyName "run_started_at_local" -NotePropertyValue ($RunStartedAt.ToString("yyyy-MM-dd HH:mm:ss")) -Force
    $Manifest | Add-Member -NotePropertyName "run_finished_at_local" -NotePropertyValue ($RunEndedAt.ToString("yyyy-MM-dd HH:mm:ss")) -Force
    $Manifest | Add-Member -NotePropertyName "duration_seconds" -NotePropertyValue $DurationSec -Force
    $Manifest | Add-Member -NotePropertyName "duration_display" -NotePropertyValue $DurationLabel -Force
    if ($Dedup) {
        $Manifest | Add-Member -NotePropertyName "unique_screenshot_count" -NotePropertyValue $UniqueCountFinal -Force
    }
    if ($ScreenshotCount -gt 0 -and $Elapsed.TotalSeconds -gt 0) {
        $SecPerShot = [math]::Round($Elapsed.TotalSeconds / $ScreenshotCount, 2)
        $Manifest | Add-Member -NotePropertyName "seconds_per_screenshot" -NotePropertyValue $SecPerShot -Force
    }
    $Manifest | ConvertTo-Json -Depth 10 | Set-Content $ManifestPath -Encoding UTF8
}

if ($ExitCode -ne 0) {
    Write-Host "Capture exited with code $ExitCode (screenshots may still be partial)." -ForegroundColor Yellow
    exit $ExitCode
}

Write-Host ""
Write-Host "========== Run summary ==========" -ForegroundColor Cyan
Write-Host ("Mode:     {0}" -f $CaptureMode)
Write-Host ("Started:  {0:yyyy-MM-dd HH:mm:ss}" -f $RunStartedAt)
Write-Host ("Finished: {0:yyyy-MM-dd HH:mm:ss}" -f $RunEndedAt)
Write-Host ("Duration: {0} min {1} sec ({2:N0} seconds total)" -f $DurationMin, $DurationSecPart, $Elapsed.TotalSeconds)
Write-Host ("Screenshots: {0} raw" -f $ScreenshotCount) -NoNewline
if ($Dedup) {
    Write-Host (", {0} unique" -f $UniqueCountFinal)
} else {
    Write-Host ""
}
if ($ScreenshotCount -gt 0 -and $Elapsed.TotalSeconds -gt 0) {
    $PerShot = $Elapsed.TotalSeconds / $ScreenshotCount
    Write-Host ("Avg: {0:N1}s per screenshot" -f $PerShot)
}
$DupReportPath = Join-Path $OutputDir "duplicate_report.json"
if (Test-Path $DupReportPath) {
    $DupReport = Get-Content $DupReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($DupReport.PSObject.Properties.Name -contains "saved") {
        Write-Host (
            "Duplicates: {0} saved, {1} skipped ({2:P1} of {3} attempts)" -f
            $DupReport.saved,
            $DupReport.skipped_duplicates,
            $DupReport.duplicate_rate,
            $DupReport.total_attempts
        )
    } else {
        Write-Host (
            "Duplicates: {0}/{1} unique ({2:P1} duplicate rate at capture)" -f
            $DupReport.unique,
            $DupReport.total,
            $DupReport.duplicate_rate
        )
    }
}
Write-Host "Output: $OutputDir" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Cyan

Write-Host "Done." -ForegroundColor Green
