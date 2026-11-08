#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .ide-venv/bin/python ]; then
    pyra_python="${PYRA_BOOTSTRAP_PYTHON:-python3}"
    "$pyra_python" -c 'import sys,sysconfig; assert (3, 10) <= sys.version_info[:2] < (3, 16), "Use Python 3.10-3.15"; assert not sysconfig.get_config_var("Py_GIL_DISABLED"), "Use a regular CPython build"'
    "$pyra_python" -m venv .ide-venv
fi
if [ ! -f .ide-venv/pyra-ready-v2 ]; then
    .ide-venv/bin/python -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt
    touch .ide-venv/pyra-ready-v2
fi
exec .ide-venv/bin/python run.py "$@"
