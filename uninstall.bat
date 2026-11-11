@echo off
setlocal
title SpriteSlicer CLI - Uninstall

cd /d "%~dp0"

echo.
echo ============================================================
echo   SPRITESLICER CLI  -  UNINSTALLER
echo ============================================================
echo   This removes the local .venv\ folder only.
echo   Your sprite sheets, output folders and the program files
echo   themselves are NOT touched.
echo.

if not exist ".venv" (
    echo   [i] No .venv folder found - nothing to uninstall.
    echo.
    pause
    exit /b 0
)

REM /p reads the keyboard; a piped answer also works
set "CONFIRM="
set /p "CONFIRM=  Type Y and press Enter to remove .venv: "
if /i not "%CONFIRM%"=="Y" (
    echo   [i] Cancelled. Nothing was removed.
    echo.
    pause
    exit /b 0
)

if exist ".venv\Scripts\deactivate.bat" call ".venv\Scripts\deactivate.bat" >nul 2>&1

echo   [..] Removing .venv ...
rmdir /s /q ".venv"
if exist ".venv" (
    echo   [X] Could not fully remove .venv.
    echo       Close any terminal that is using it, then run uninstall.bat again.
    pause
    exit /b 1
)

echo   [OK] .venv removed.
echo.

set "PURGE="
set /p "PURGE=  Also delete __pycache__ and test output folders? (y/N): "
if /i "%PURGE%"=="y" (
    for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
    if exist "_t" rmdir /s /q "_t"
    echo   [OK] Cache and test output removed.
)

echo.
echo ============================================================
echo   UNINSTALL COMPLETE
echo ============================================================
echo   Run install.bat to set it up again.
echo.
pause
exit /b 0
