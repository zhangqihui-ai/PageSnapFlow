@echo off
setlocal
if "%~1"=="" (
    echo Usage: %~nx0 OUTPUT_DIR
    echo Example: %~nx0 screenshots\taptap_lite\pilot_tapmake_full_20260624_144104
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_tapmake_pilot.ps1" -UntilBottom -ResumeDir "%~1" -SkipNav
exit /b %ERRORLEVEL%
