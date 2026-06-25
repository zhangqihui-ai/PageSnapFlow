@echo off
setlocal
if "%~1"=="" (
    echo Usage: %~nx0 OUTPUT_DIR
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_taptap_rank_reserve_pilot.ps1" -UntilBottom -ResumeDir "%~1" -SkipNav
exit /b %ERRORLEVEL%
