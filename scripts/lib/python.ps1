function Get-PythonCommand {
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        return $VenvPython
    }
    foreach ($cmd in @("python", "python3", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            return (Get-Command $cmd).Source
        }
    }
    return $null
}

function Test-PythonModule($Python, $Module) {
    & $Python -c "import $Module" 2>$null
    return $LASTEXITCODE -eq 0
}

function Ensure-PythonDeps($Python) {
    if (Test-PythonModule $Python "cv2") {
        return $true
    }
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $Requirements = Join-Path $Root "requirements.txt"
    if (-not (Test-Path $Requirements)) {
        return $false
    }
    Write-Host "Installing Python deps (opencv for dedup)..." -ForegroundColor Yellow
    & $Python -m pip install -r $Requirements
    return (Test-PythonModule $Python "cv2")
}
