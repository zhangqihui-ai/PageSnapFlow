# Shared PATH helpers for PageSnapFlow (Maestro + Android Studio SDK)

function Get-AndroidSdkPath {
    if ($env:ANDROID_HOME -and (Test-Path $env:ANDROID_HOME)) {
        return $env:ANDROID_HOME
    }
    if ($env:ANDROID_SDK_ROOT -and (Test-Path $env:ANDROID_SDK_ROOT)) {
        return $env:ANDROID_SDK_ROOT
    }
    $DefaultSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $DefaultSdk) {
        return $DefaultSdk
    }
    return $null
}

function Get-AdbPath {
    if (Get-Command adb -ErrorAction SilentlyContinue) {
        return (Get-Command adb).Source
    }
    $Sdk = Get-AndroidSdkPath
    if ($Sdk) {
        $AdbExe = Join-Path $Sdk "platform-tools\adb.exe"
        if (Test-Path $AdbExe) { return $AdbExe }
    }
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $LocalAdb = Join-Path $Root "tools\platform-tools\adb.exe"
    if (Test-Path $LocalAdb) { return $LocalAdb }
    return $null
}

function Get-MaestroBinDir {
    if (Get-Command maestro -ErrorAction SilentlyContinue) {
        return (Get-Command maestro).DirectoryName
    }
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $MaestroBat = Get-ChildItem -Path (Join-Path $Root "tools\maestro") -Recurse -Filter "maestro.bat" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($MaestroBat) { return $MaestroBat.DirectoryName }
    return $null
}

function Initialize-PageSnapFlowPath {
    $paths = @()

    $MaestroBin = Get-MaestroBinDir
    if ($MaestroBin) { $paths += $MaestroBin }

    $AdbPath = Get-AdbPath
    if ($AdbPath) {
        $paths += (Split-Path -Parent $AdbPath)
    }

    if ($env:JAVA_HOME) {
        $paths += (Join-Path $env:JAVA_HOME "bin")
    }

    foreach ($p in ($paths | Select-Object -Unique)) {
        if ($p -and ($env:PATH -notlike "*$p*")) {
            $env:PATH = "$p;$env:PATH"
        }
    }

    if (-not $env:ANDROID_HOME) {
        $Sdk = Get-AndroidSdkPath
        if ($Sdk) { $env:ANDROID_HOME = $Sdk }
    }
}

function Get-JavaHomeHint {
    $Candidates = @(
        $env:JAVA_HOME,
        "C:\Program Files\Android\Android Studio\jbr",
        "C:\Program Files\Java\*\",
        "C:\Program Files\Eclipse Adoptium\*\"
    )
    foreach ($c in $Candidates) {
        if (-not $c) { continue }
        $resolved = Resolve-Path $c -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($resolved -and (Test-Path (Join-Path $resolved "bin\java.exe"))) {
            return $resolved.Path
        }
    }
    return $null
}
