"""Separate the IDE's bundled runtime from the user's Python environment."""

import os
import shutil
import sys
from pathlib import Path


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def default_python() -> str:
    """Cheap startup hint only: no process launch, drive scan or cached failure."""
    if not getattr(sys, "frozen", False):
        return str(Path(getattr(sys, "_base_executable", sys.executable)))
    for candidate in (os.environ.get("PYRA_PYTHON"), shutil.which("python"),
                      shutil.which("python3")):
        if candidate and usable_python_path(candidate):
            return str(Path(candidate).absolute())
    return ""


def usable_python_path(path) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if not candidate.is_file() or "windowsapps" in str(candidate).lower():
        return False
    if getattr(sys, "frozen", False) and candidate.resolve() == Path(sys.executable).resolve():
        return False
    return candidate.name.lower() not in {"pythonw.exe", "py.exe"}


def external_environment(interpreter=None, extra=None) -> dict:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "LIBPATH"):
            original = env.pop(key + "_ORIG", None)
            if original is None:
                env.pop(key, None)
            else:
                env[key] = original
        bundle = os.path.normcase(str(resource_root()))
        env["PATH"] = os.pathsep.join(
            entry for entry in env.get("PATH", "").split(os.pathsep)
            if entry and not os.path.normcase(entry).startswith(bundle + os.sep)
            and os.path.normcase(entry) != bundle
        )
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            env.pop(key, None)
    if interpreter:
        folder = Path(interpreter).absolute().parent
        env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
        if (folder.parent / "pyvenv.cfg").is_file():
            env["VIRTUAL_ENV"] = str(folder.parent)
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def initialize_external_processes():
    """Call once after Qt imports; avoid process-global DLL-path races on Windows."""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes
        if not ctypes.windll.kernel32.SetDllDirectoryW(None):
            raise OSError("Не удалось сбросить путь DLL для внешнего Python")


def service_command(service: str, interpreter=None):
    if service not in {"worker", "debug-adapter"}:
        raise ValueError(service)
    if getattr(sys, "frozen", False):
        if not usable_python_path(interpreter):
            raise ValueError("Выберите установленный python.exe в меню «Окружение».")
        # Real Python supplies stdio and Jedi's subprocess runtime. All service
        # sources are bundled, including in onefile; no pip install in the project.
        return str(interpreter), ["-I", str(resource_root() / "service_bootstrap.py"), service]
    return sys.executable, ["-m", "pyra.worker" if service == "worker" else "debugpy.adapter"]
