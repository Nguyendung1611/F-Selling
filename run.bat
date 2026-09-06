@echo off
cd /d "%~dp0"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local_runtime.ps1" "%ACTION%"
if errorlevel 1 (
    echo.
    echo F-Selling could not complete: %ACTION%
    pause
)
