
@echo off
setlocal
cd /d "%~dp0"

:: Python на диске D:
set "PYRA_BOOTSTRAP_PYTHON=D:\Python315\python.exe"

:: Проверка Python
if not exist "%PYRA_BOOTSTRAP_PYTHON%" (
    echo ERROR: Python not found at %PYRA_BOOTSTRAP_PYTHON%
    pause
    exit /b 1
)

:: Режим сборки
set "PYRA_MODE=%~1"
if not defined PYRA_MODE set "PYRA_MODE=onefile"

if /I "%PYRA_MODE%"=="onefile" goto build
if /I "%PYRA_MODE%"=="onedir" goto build
if /I "%PYRA_MODE%"=="both" goto build

echo Usage: build_exe.bat [onefile ^| onedir ^| both]
exit /b 2

:build
echo Preparing Pyra environment...

call start.bat --prepare-only
if errorlevel 1 goto failure

echo Installing build dependencies...

".ide-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto failure

echo Building Pyra.exe...

".ide-venv\Scripts\python.exe" tools\build.py --mode "%PYRA_MODE%"
if errorlevel 1 goto failure

echo.
echo Build successful!
echo Check dist\onefile or dist\onedir
pause
exit /b 0

:failure
echo.
echo Build failed. Copy the error above.
pause
exit /b 1
