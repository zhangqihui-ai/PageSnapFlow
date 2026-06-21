@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_env.ps1" %*
