
@echo off
setlocal
cd /d "%~dp0"

:: Путь к установленному Python
set "PYRA_BOOTSTRAP_PYTHON=D:\Python315\python.exe"

:: Режим сборки
set "PYRA_MODE=%~1"
if not defined PYRA_MODE set "PYRA_MODE=onefile"

if /I "%PYRA_MODE%"=="onefile" goto build
if /I "%PYRA_MODE%"=="onedir" goto build
if /I "%PYRA_MODE%"=="both" goto build

echo Usage: build_exe.bat [onefile ^| onedir ^| both]
exit /b 2

:build
call start.bat --prepare-only
if errorlevel 1 goto failure

".ide-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto failure

".ide-venv\Scripts\python.exe" tools\build.py --mode "%PYRA_MODE%"
if errorlevel 1 goto failure

echo.
echo Build successful!
echo See dist\onefile and/or dist\onedir.
pause
exit /b 0

:failure
echo.
echo Build failed. Copy the error above.
pause
exit /b 1
