@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\list_packages.ps1" %*
