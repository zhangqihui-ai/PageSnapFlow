# PageSnapFlow environment setup (Windows)
# Installs Maestro CLI and verifies ADB availability.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ToolsDir = Join-Path $Root "tools"
$MaestroDir = Join-Path $ToolsDir "maestro"
. (Join-Path $PSScriptRoot "lib\bootstrap.ps1")

function Test-Command($Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Step($Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

Write-Step "Checking ADB"
$AdbPath = Get-AdbPath
if ($AdbPath) {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        $env:PATH = "$(Split-Path -Parent $AdbPath);$env:PATH"
    }
    Write-Host "ADB found: $AdbPath"
    adb version 2>&1 | Select-Object -First 1
} else {
    Write-Host "ADB not found." -ForegroundColor Yellow
    Write-Host @"
Android Studio already includes ADB. Finish SDK setup in Android Studio:
  Settings -> Languages & Frameworks -> Android SDK -> SDK Tools
  Check "Android SDK Platform-Tools", click Apply

Default location:
  $env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe

Then run: init.bat
"@
}

Write-Step "Checking Maestro CLI"
if (Test-Command maestro) {
    Write-Host "Maestro found: $(maestro --version 2>&1)"
} else {
    Write-Host "Maestro not found. Attempting local install..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $MaestroDir | Out-Null

    $MaestroZip = Join-Path $env:TEMP "maestro.zip"
    $DownloadUrl = "https://github.com/mobile-dev-inc/maestro/releases/latest/download/maestro.zip"

    try {
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $MaestroZip -UseBasicParsing
        Expand-Archive -Path $MaestroZip -DestinationPath $MaestroDir -Force
        Remove-Item $MaestroZip -Force

        $MaestroBin = Get-ChildItem -Path $MaestroDir -Recurse -Filter "maestro.bat" | Select-Object -First 1
        if ($MaestroBin) {
            $BinDir = $MaestroBin.DirectoryName
            Write-Host "Maestro installed to: $BinDir" -ForegroundColor Green
            Write-Host "Add to PATH for this session:"
            Write-Host "  `$env:PATH = `"$BinDir;`$env:PATH`"" -ForegroundColor White
            $env:PATH = "$BinDir;$env:PATH"
            maestro --version
        } else {
            Write-Host "Maestro zip extracted but maestro.bat not found. Install manually:" -ForegroundColor Red
            Write-Host "  curl -fsSL https://get.maestro.mobile.dev | bash"
        }
    } catch {
        Write-Host "Auto-install failed: $_" -ForegroundColor Red
        Write-Host @"

Manual install options:
  1. Download maestro.zip from https://github.com/mobile-dev-inc/maestro/releases
  2. Extract and add bin folder to PATH
  3. Or run: curl -fsSL https://get.maestro.mobile.dev | bash  (Git Bash / WSL)
"@
    }
}

Write-Step "Checking connected Android device"
if (Test-Command adb) {
    $devices = adb devices 2>&1 | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
    if ($devices) {
        Write-Host "Connected device(s):" -ForegroundColor Green
        $devices | ForEach-Object { Write-Host "  $_" }
        adb shell wm size 2>$null
    } else {
        Write-Host "No Android device connected." -ForegroundColor Yellow
        Write-Host @"
Connect a phone (USB debugging) or start an Android emulator, then run:
  adb devices
  maestro studio
"@
    }
}

Write-Step "Setup complete"
Write-Host "Next steps:"
Write-Host "  1. Connect device / start emulator"
Write-Host "  2. Install target apps on device"
Write-Host "  3. Run: .\scripts\verify_env.ps1"
Write-Host "  4. Record flows: maestro studio"
Write-Host "  5. Run flow:  .\scripts\run_flow.ps1 -App breaking_news_us -Flow home_browse"
