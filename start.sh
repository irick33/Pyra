#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ -x .ide-venv/bin/python ]; then
    exec .ide-venv/bin/python tools/bootstrap.py "$@"
fi
pyra_python="${PYRA_BOOTSTRAP_PYTHON:-python3}"
exec "$pyra_python" tools/bootstrap.py "$@"
