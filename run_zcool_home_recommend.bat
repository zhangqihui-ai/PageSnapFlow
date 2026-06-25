@echo off
setlocal
set "ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run_zcool_quick_capture.ps1"
exit /b %ERRORLEVEL%
