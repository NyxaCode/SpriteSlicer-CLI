@echo off
REM Drag-and-drop launcher: drop a sprite sheet (or a folder) onto this file.
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo   [i] Run install.bat first.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo   Drag a sprite sheet image or a folder onto this file.
    pause
    exit /b 1
)

if exist "%~1\" (
    ".venv\Scripts\python.exe" cli.py -d "%~1"
) else (
    ".venv\Scripts\python.exe" cli.py -i "%~1"
)
echo.
pause
exit /b %errorlevel%
