# Run all registered app flows sequentially.

param(
    [Parameter(Mandatory = $false)]
    [string[]]$Apps = @(),

    [Parameter(Mandatory = $false)]
    [string]$Device = $null,

    [Parameter(Mandatory = $false)]
    [switch]$ContinueOnError
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")
Assert-PageSnapFlowToolchain
$RunFlow = Join-Path $PSScriptRoot "run_flow.ps1"
$AppsYaml = Join-Path $Root "config\apps.yaml"

if (-not (Test-Path $AppsYaml)) {
    Write-Error "Missing config/apps.yaml"
}

$content = Get-Content $AppsYaml -Raw
$appKeys = @()
if ($Apps.Count -gt 0) {
    $appKeys = $Apps
} else {
    $matches = [regex]::Matches($content, '(?m)^  (\w+):\s*$')
    foreach ($m in $matches) { $appKeys += $m.Groups[1].Value }
}

Write-Host "Batch run: $($appKeys -join ', ')" -ForegroundColor Cyan
$Results = @()

foreach ($App in $appKeys) {
    Write-Host "`n========== $App ==========" -ForegroundColor Yellow
    try {
        if ($Device) {
            & $RunFlow -App $App -Flow home_browse -Device $Device
        } else {
            & $RunFlow -App $App -Flow home_browse
        }
        $Results += [pscustomobject]@{ App = $App; Status = "OK" }
    } catch {
        $Results += [pscustomobject]@{ App = $App; Status = "FAIL"; Error = $_.Exception.Message }
        if (-not $ContinueOnError) {
            Write-Error "Failed on $App. Use -ContinueOnError to skip failures."
        }
        Write-Host "Failed: $_" -ForegroundColor Red
    }
}

Write-Host "`n========== Summary =========="
$Results | Format-Table -AutoSize

$SummaryPath = Join-Path $Root "screenshots\batch_summary_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
$Results | ConvertTo-Json | Set-Content -Path $SummaryPath -Encoding UTF8
Write-Host "Summary saved: $SummaryPath"
