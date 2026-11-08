"""Bundled source, launched with the selected real Python and -I, never Pyra.exe."""
import os
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "services"))
service = sys.argv[1]
sys.argv = [sys.argv[0]]
if service == "worker":
    runpy.run_module("pyra.worker", run_name="__main__")
elif service == "debug-adapter":
    # Native extensions belong to the build Python; use the fallback for other ABIs.
    os.environ["PYDEVD_USE_CYTHON"] = "NO"
    os.environ["PYDEVD_USE_FRAME_EVAL"] = "NO"
    runpy.run_module("debugpy.adapter", run_name="__main__")
else:
    raise SystemExit("Unknown Pyra service")
