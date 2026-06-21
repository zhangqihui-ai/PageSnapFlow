# Deduplicate screenshots from a PageSnapFlow run using image-filtering.

param(
    [Parameter(Mandatory = $true)]
    [string]$InputDir,

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "",

    [Parameter(Mandatory = $false)]
    [double]$Similarity = 0.92
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "lib\python.ps1")
$Python = Get-PythonCommand
$InputPath = if ([System.IO.Path]::IsPathRooted($InputDir)) { $InputDir } else { Join-Path $Root $InputDir }

if (-not (Test-Path $InputPath)) {
    Write-Error "Input directory not found: $InputPath"
}

if (-not $OutputDir) {
    $OutputDir = Join-Path (Split-Path $InputPath -Parent) "filtered_$(Split-Path $InputPath -Leaf)"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $Root $OutputDir
}

$DedupScript = Join-Path $PSScriptRoot "dedup_screenshots.py"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Deduplicating: $InputPath -> $OutputDir (similarity=$Similarity)" -ForegroundColor Cyan

if (-not $Python) {
    Write-Error "Python not found. Install Python 3.8+ and run: pip install -r requirements.txt"
}

& $Python $DedupScript --input $InputPath --output $OutputDir --similarity $Similarity

Write-Host "Filtered output: $OutputDir" -ForegroundColor Green
