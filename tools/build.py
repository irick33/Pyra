"""Build on the target OS: python tools/build.py --mode onefile|onedir|both."""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(mode, console=False):
    import ruff
    stage = ROOT / "build" / f"services-{mode}"
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("jedi", "parso", "debugpy"):
        source = Path(importlib.util.find_spec(name).origin).parent
        shutil.copytree(source, stage / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The worker needs stdlib-only Pyra modules. Do not expose Qt to project Python.
    target = stage / "pyra"
    target.mkdir(exist_ok=True)
    for name in ("__init__.py", "worker.py", "storage.py"):
        shutil.copy2(ROOT / "pyra" / name, target / name)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", f"--{mode}",
               "--console" if console or sys.platform != "win32" else "--windowed",
               "--name", "Pyra", "--distpath", str(ROOT / "dist" / mode),
               "--workpath", str(ROOT / "build" / mode), "--specpath", str(ROOT / "build"),
               "--hidden-import", "PyQt6.Qsci", "--collect-all", "pyte",
               "--add-binary", f"{ruff.find_ruff_bin()}{os.pathsep}tools"]
    if sys.platform == "win32":
        command += ["--collect-all", "winpty"]
    # Use native path-list separator; arguments remain separate with spaces/Unicode.
    for source, destination in [(stage, "services"),
                                (ROOT / "tools/service_bootstrap.py", "."),
                                (ROOT / "README_RU.md", "."), (ROOT / "THIRD_PARTY.md", "."),
                                (ROOT / "LICENSE", "."), (ROOT / "examples", "examples")]:
        command += ["--add-data", f"{source}{os.pathsep}{destination}"]
    command.append(str(ROOT / "run.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    metadata = {"platform": platform.platform(), "python": sys.version, "mode": mode,
                "pyinstaller": version("pyinstaller"), "dependencies": {
                    name: version(name) for name in ("PyQt6", "PyQt6-QScintilla", "jedi", "parso",
                                                    "debugpy", "ruff", "pyte")}}
    (ROOT / "dist" / mode / "build-info.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Build complete: {ROOT / 'dist' / mode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("onefile", "onedir", "both"), default="onefile")
    parser.add_argument("--console", action="store_true", help="Keep console for diagnostics")
    args = parser.parse_args()
    for mode in (("onedir", "onefile") if args.mode == "both" else (args.mode,)):
        build(mode, args.console)


if __name__ == "__main__":
    main()
