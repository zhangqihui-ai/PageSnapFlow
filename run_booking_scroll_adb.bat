@echo off

setlocal

echo.

echo Booking ADB: hotel list scroll (~2 hotels per swipe)

echo Prerequisite: open Booking hotel results (e.g. Beijing) on device first.
echo Script will scroll to list top, then capture.

echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_booking_capture.ps1" %*

