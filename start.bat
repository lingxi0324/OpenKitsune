@echo off
rem ============================================================
rem OpenKitsune launcher wrapper - delegates to start.ps1
rem Usage: start.bat [port]
rem Always runs with live WSL serve log and pauses before exit,
rem so the window never disappears before you can read errors.
rem ============================================================
title OpenKitsune Launcher
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem Strip legacy "debug" args; everything else (e.g. port) passes through
set "PSARGS="
if not "%~1"=="" (
    for %%A in (%*) do (
        if /i "%%~A"=="debug" (
            rem ignored, log mode is always on
        ) else if /i "%%~A"=="--debug" (
            rem ignored
        ) else if /i "%%~A"=="-debug" (
            rem ignored
        ) else (
            set "PSARGS=!PSARGS! %%~A"
        )
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"!PSARGS! -ShowLog
set "EXITCODE=%ERRORLEVEL%"

echo.
echo [INFO] Launcher log: %~dp0data\logs\launcher_*.log
if not "%EXITCODE%"=="0" echo [FAIL] start.ps1 exited with code %EXITCODE%.
pause
exit /b %EXITCODE%
