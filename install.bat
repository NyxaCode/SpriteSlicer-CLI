@echo off
setlocal EnableDelayedExpansion
title SpriteSlicer CLI - Install

cd /d "%~dp0"
set "VENVPY=.venv\Scripts\python.exe"

echo.
echo ============================================================
echo   SPRITESLICER CLI  -  INSTALLER
echo ============================================================
echo   Creates a local Python environment in .venv\ and installs
echo   the required packages. Your system Python is not modified.
echo.

REM ---------- 1. Find a Python 3.8+ interpreter ----------
set "PY="
py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11"
if not defined PY ( python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1 && set "PY=python" )
if not defined PY ( py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1 && set "PY=py -3" )

if not defined PY (
    echo   [X] Python 3.8+ was not found.
    echo.
    echo       Install it from https://www.python.org/downloads/
    echo       IMPORTANT: tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%v"
echo   [OK] Python !PYVER! found via: %PY%
echo.

REM ---------- 2. Create the virtual environment ----------
if exist "%VENVPY%" (
    "%VENVPY%" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        echo   [OK] Existing .venv is usable - reusing it.
        goto have_venv
    )
    echo   [!]  Existing .venv is broken - rebuilding it ...
    rmdir /s /q ".venv"
)

echo   [..] Creating virtual environment in .venv ...
%PY% -m venv .venv >nul 2>&1
if exist "%VENVPY%" goto venv_ok

REM Fallback: some Python installs (notably 3.14 on Windows) fail inside
REM ensurepip. Creating without pip still works; we bootstrap pip next.
echo   [!]  Standard venv creation failed - retrying without pip ...
rmdir /s /q ".venv" >nul 2>&1
%PY% -m venv --without-pip .venv >nul 2>&1
if not exist "%VENVPY%" (
    echo   [X] Could not create a virtual environment.
    echo       Try installing Python 3.11 from python.org and rerun.
    pause
    exit /b 1
)

echo   [..] Bootstrapping pip ...
"%VENVPY%" -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    echo   [!]  ensurepip failed - attempting get-pip.py download ...
    "%VENVPY%" -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '_get_pip.py')" >nul 2>&1
    if exist "_get_pip.py" (
        "%VENVPY%" _get_pip.py --quiet >nul 2>&1
        del /q "_get_pip.py" >nul 2>&1
    )
)

:venv_ok
echo   [OK] Virtual environment ready.

:have_venv
echo.

REM ---------- 3. Make sure pip exists ----------
"%VENVPY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo   [..] pip missing - bootstrapping ...
    "%VENVPY%" -m ensurepip --upgrade >nul 2>&1
    "%VENVPY%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        "%VENVPY%" -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '_get_pip.py')" >nul 2>&1
        if exist "_get_pip.py" (
            "%VENVPY%" _get_pip.py --quiet >nul 2>&1
            del /q "_get_pip.py" >nul 2>&1
        )
    )
    "%VENVPY%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo   [X] pip could not be installed. Check your internet connection.
        pause
        exit /b 1
    )
)
echo   [OK] pip is available.
echo.

REM ---------- 4. Install requirements ----------
echo   [..] Installing requirements: numpy, opencv-python, Pillow
echo        First run downloads ~80 MB, please wait ...
echo.
REM --no-cache-dir is deliberate: pip's wheel cache can hold tens of
REM thousands of files and rescanning it makes resolution appear to hang.
REM --disable-pip-version-check / --no-input keep the run non-interactive.
".venv\Scripts\python.exe" -m pip install --no-cache-dir --no-input ^
    --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo   [X] Package installation failed. See the error above.
    echo       If you are offline, connect and run install.bat again.
    pause
    exit /b 1
)
echo.
echo   [OK] Packages installed.
echo.

REM ---------- 5. Verify ----------
echo   [..] Verifying installation ...
"%VENVPY%" -c "import cv2, numpy, PIL; print('       opencv-python ' + cv2.__version__ + '  |  numpy ' + numpy.__version__ + '  |  Pillow ' + PIL.__version__)"
if errorlevel 1 (
    echo   [X] Verification failed - a package is missing.
    pause
    exit /b 1
)
echo.

if exist "bin\realesrgan\realesrgan-ncnn-vulkan.exe" (
    echo   [OK] Real-ESRGAN GPU upscaler bundled.
) else (
    echo   [!]  bin\realesrgan is missing - upscaling falls back to Lanczos.
)
echo.
echo ============================================================
echo   INSTALL COMPLETE
echo ============================================================
echo   Run the tool:   start.bat
echo   Or directly:    .venv\Scripts\python.exe cli.py --help
echo.
pause
exit /b 0
