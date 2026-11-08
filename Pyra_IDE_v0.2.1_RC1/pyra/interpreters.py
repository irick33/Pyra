"""Bounded Python discovery and validation. Run discovery off the GUI thread."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .runtime import default_python, external_environment, usable_python_path

PROBE_CODE = (
    "import json,sys,sysconfig,struct; "
    "print(json.dumps(dict(executable=sys.executable,version=list(sys.version_info[:3]),"
    "prefix=sys.prefix,base_prefix=sys.base_prefix,implementation=sys.implementation.name,"
    "bits=struct.calcsize('P')*8,free_threaded=bool(sysconfig.get_config_var('Py_GIL_DISABLED')))))"
)


@dataclass
class Interpreter:
    path: str
    version: list
    prefix: str
    base_prefix: str
    bits: int
    source: str = "Выбран вручную"

    @property
    def label(self):
        kind = "venv" if self.prefix != self.base_prefix else "CPython"
        return f"Python {'.'.join(map(str, self.version))} · {self.bits} bit · {kind}"

    def to_dict(self):
        return asdict(self)


def parse_probe(path, output, source="Выбран вручную"):
    try:
        data = json.loads(output)
        version = data["version"]
        if not (isinstance(version, list) and len(version) == 3
                and all(type(x) is int for x in version)):
            raise ValueError("Некорректная версия")
        if data["implementation"] != "cpython" or not (3, 10) <= tuple(version[:2]) < (3, 16):
            raise ValueError("Выберите CPython 3.10–3.15, поддерживаемый инструментами Pyra.")
        if data["free_threaded"]:
            raise ValueError("Выберите обычную сборку CPython с GIL; free-threaded пока не проверена.")
        if not data["executable"]:
            raise ValueError("Python не вернул путь к исполняемому файлу")
        # Keep the venv path, never resolve its symlink to the base interpreter.
        return Interpreter(str(Path(path).absolute()), version, str(data["prefix"]),
                           str(data["base_prefix"]), int(data["bits"]), source)
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Интерпретатор не вернул корректные сведения о Python.") from error


def probe_python(path, source="Выбран вручную", timeout=3):
    if not usable_python_path(path):
        raise ValueError("Файл Python не найден. Выберите python.exe, а не Pyra.exe или pythonw.exe.")
    result = subprocess.run(
        [str(path), "-I", "-c", PROBE_CODE], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=external_environment(path), creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    if result.returncode:
        raise ValueError((result.stderr or result.stdout)[-2000:] or "Python завершился с ошибкой")
    return parse_probe(path, result.stdout, source)


def launcher_paths(output):
    for line in output.splitlines():
        match = re.search(r'((?:[A-Za-z]:[\\/]|\\\\).*?python(?:[\d.]*)?\.exe)\s*$', line, re.I)
        if match:
            yield match.group(1)


def registry_paths():
    if sys.platform != "win32":
        return
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Python", 0, winreg.KEY_READ | view) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        company = winreg.EnumKey(root, i)
                        with winreg.OpenKey(root, company) as vendor:
                            for j in range(winreg.QueryInfoKey(vendor)[0]):
                                tag = winreg.EnumKey(vendor, j)
                                try:
                                    with winreg.OpenKey(vendor, tag + r"\InstallPath") as install:
                                        try:
                                            yield winreg.QueryValueEx(install, "ExecutablePath")[0]
                                        except OSError:
                                            yield str(Path(winreg.QueryValue(install, "")) / "python.exe")
                                except OSError:
                                    continue
            except OSError:
                continue


def fixed_drives():
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        mask = kernel.GetLogicalDrives()
        for index in range(26):
            drive = f"{chr(65 + index)}:\\"
            if mask & (1 << index) and kernel.GetDriveTypeW(drive) == 3:
                yield Path(drive)


def folder_candidates(root):
    """Known layouts, at most two directory levels; never recurse over a disk."""
    root = Path(root)
    for tail in ("python.exe", "Scripts/python.exe", "bin/python"):
        yield root / tail
    try:
        for index, folder in enumerate(root.iterdir()):
            if index >= 256:
                break
            name = folder.name.lower()
            if folder.is_dir() and name.startswith(("python", "cpython", "miniconda", "anaconda")):
                yield folder / "python.exe"
                yield folder / "bin/python"
    except OSError:
        pass


def candidate_paths(project=None, saved=(), extra_folders=(), cancelled=lambda: False):
    if project:
        for name in (".venv", "venv", "env"):
            folder = Path(project) / name
            yield folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"), "Проект"
    for item in saved:
        path = item.get("path") if isinstance(item, dict) else item
        if path:
            yield path, "Сохранён"
    yield default_python(), "Система"
    for name in ("python", "python3", *(f"python3.{i}" for i in range(15, 9, -1))):
        yield shutil.which(name), "PATH"
    for path in registry_paths():
        if cancelled():
            return
        yield path, "Реестр Windows"
    launcher = shutil.which("py") if sys.platform == "win32" else None
    if launcher and not cancelled():
        try:
            result = subprocess.run([launcher, "-0p"], capture_output=True, text=True,
                                    errors="replace", timeout=3, creationflags=0x08000000,
                                    env=external_environment())
            for path in launcher_paths(result.stdout + "\n" + result.stderr):
                yield path, "Python Launcher"
        except (OSError, subprocess.SubprocessError):
            pass
    roots = list(extra_folders)
    if sys.platform == "win32":
        for variable, tail in (("LOCALAPPDATA", "Programs/Python"), ("LOCALAPPDATA", "Python"),
                               ("ProgramFiles", ""), ("ProgramFiles(x86)", "")):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]) / tail)
        for drive in fixed_drives():
            roots.extend((drive, drive / "Programs", drive / "Program Files", drive / "Tools"))
    for root in roots:
        if cancelled():
            return
        for path in folder_candidates(root):
            yield path, "Папка"


def discover(project=None, saved=(), extra_folders=(), cancelled=lambda: False, budget=12):
    deadline = time.monotonic() + budget
    seen, found, errors = set(), [], []
    for path, source in candidate_paths(project, saved, extra_folders, cancelled):
        if cancelled() or time.monotonic() >= deadline or len(seen) >= 48:
            break
        if not path or not usable_python_path(path):
            continue
        identity = os.path.normcase(os.path.abspath(path))
        if identity in seen:
            continue
        seen.add(identity)
        try:
            found.append(probe_python(path, source, timeout=max(.1, min(2, deadline - time.monotonic()))))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"{path}: {error}")
    return found, errors
