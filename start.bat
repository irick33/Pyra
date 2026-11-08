@echo off
setlocal
cd /d "%~dp0"
if exist ".ide-venv\Scripts\python.exe" goto check
for %%V in (3.15 3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sysconfig; assert not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>&1
    if not errorlevel 1 (
        py -%%V -m venv .ide-venv
        if errorlevel 1 goto error
        goto check
    )
)
python -c "import sys,sysconfig; assert (3,10) <= sys.version_info[:2] < (3,16); assert not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>&1
if errorlevel 1 (
    echo Install regular CPython 3.10-3.15 x64 from https://www.python.org/downloads/windows/
    echo Python 3.15 is supported. Free-threaded builds are not supported by this GUI bundle.
    pause
    exit /b 1
)
python -m venv .ide-venv
if errorlevel 1 goto error
:check
if exist ".ide-venv\pyra-ready-v2" goto launch
".ide-venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt
if errorlevel 1 goto error
type nul > ".ide-venv\pyra-ready-v2"
:launch
".ide-venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo Setup or launch failed. Copy the error message above.
pause
exit /b 1
