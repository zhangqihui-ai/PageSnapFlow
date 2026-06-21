# Bootstrap Java, Maestro, and ADB for PageSnapFlow scripts.

. (Join-Path $PSScriptRoot "env_paths.ps1")

if (-not $env:JAVA_HOME) {
    $JavaHome = Get-JavaHomeHint
    if ($JavaHome) {
        $env:JAVA_HOME = $JavaHome
        $env:PATH = "$(Join-Path $JavaHome 'bin');$env:PATH"
    }
}

Initialize-PageSnapFlowPath

function Assert-PageSnapFlowToolchain {
    if (-not (Get-Command maestro -ErrorAction SilentlyContinue)) {
        Write-Error "Maestro not found. Run .\setup.bat first."
    }
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        Write-Error "ADB not found. Install Android SDK Platform-Tools in Android Studio."
    }
}
