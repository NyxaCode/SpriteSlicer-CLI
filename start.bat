@echo off
setlocal EnableDelayedExpansion
title SpriteSlicer CLI
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   [i] First run detected - no .venv found.
    echo.
    set /p "RUNINSTALL=  Run the installer now? (Y/n): "
    if /i "!RUNINSTALL!"=="n" (
        echo   Run install.bat first, then start.bat again.
        echo.
        pause
        exit /b 1
    )
    call install.bat
    if errorlevel 1 exit /b 1
    echo.
)

REM Forward every argument to the CLI; no args opens the interactive menu
if "%~1"=="" (
    ".venv\Scripts\python.exe" cli.py
    set "RC=!errorlevel!"
    echo.
    pause
    exit /b !RC!
)

".venv\Scripts\python.exe" cli.py %*
exit /b %errorlevel%
