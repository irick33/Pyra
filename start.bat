@echo off
setlocal
cd /d "%~dp0"
if defined PYRA_BOOTSTRAP_PYTHON goto explicit
if exist ".ide-venv\Scripts\python.exe" (
    ".ide-venv\Scripts\python.exe" tools\bootstrap.py %*
    goto result
)
for %%V in (3.15 3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sysconfig; assert not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>&1
    if not errorlevel 1 (
        py -%%V tools\bootstrap.py %*
        goto result
    )
)
python tools\bootstrap.py %*
goto result
:explicit
"%PYRA_BOOTSTRAP_PYTHON%" tools\bootstrap.py %*
:result
if not errorlevel 1 exit /b 0
echo.
echo Setup or launch failed. Copy the error above.
echo For Python on any drive, run: set "PYRA_BOOTSTRAP_PYTHON=D:\Python315\python.exe"
pause
exit /b 1
