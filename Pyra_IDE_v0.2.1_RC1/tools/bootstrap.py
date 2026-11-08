"""Create/update the IDE environment with this explicitly selected Python."""
import argparse
import hashlib
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".ide-venv"
PYTHON = ENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def prepare():
    if not (3, 10) <= sys.version_info[:2] < (3, 16) or sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SystemExit("Use regular CPython 3.10-3.15 with GIL.")
    if not PYTHON.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(ENV)], check=True)
    requirements = ROOT / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = ENV / "pyra-requirements.sha256"
    if not marker.exists() or marker.read_text().strip() != fingerprint:
        subprocess.run([str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
                        "--only-binary=:all:", "-r", str(requirements)], check=True)
        marker.write_text(fingerprint, encoding="ascii")
    return PYTHON


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    args, launch_args = parser.parse_known_args()
    python = prepare()
    if not args.prepare_only:
        os.chdir(ROOT)
        raise SystemExit(subprocess.call([str(python), str(ROOT / "run.py"), *launch_args]))


if __name__ == "__main__":
    main()
