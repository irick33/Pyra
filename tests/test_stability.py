import json
import os
import subprocess
import sys

import pytest

from conftest import wait_until
from pyra import runtime
from pyra.interpreters import (PROBE_CODE, discover, folder_candidates, launcher_paths,
                               parse_probe, probe_python)
from pyra.services import Job
from pyra.window import MainWindow


def test_default_python_never_spawns_or_returns_frozen_exe(tmp_path, monkeypatch):
    exe = tmp_path / "Pyra.exe"
    exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(runtime.shutil, "which", lambda _: str(exe))
    monkeypatch.delenv("PYRA_PYTHON", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("Startup spawned Python"))
    assert runtime.default_python() == ""
    assert not runtime.usable_python_path(exe)


def test_launcher_parses_alternate_drives_spaces_unicode():
    text = ' -V:3.15 * D:\\Питон 3.15\\python.exe\n -3.12-64 C:\\Program Files\\Python312\\python.exe\n'
    assert list(launcher_paths(text)) == [r"D:\Питон 3.15\python.exe", r"C:\Program Files\Python312\python.exe"]


def test_folder_scan_is_bounded_and_finds_non_system_drive_layout(tmp_path):
    folder = tmp_path / "Python 315"
    folder.mkdir()
    python = folder / "python.exe"
    python.touch()
    unrelated = tmp_path / "Documents" / "deep" / "Python315"
    unrelated.mkdir(parents=True)
    nested = unrelated / "python.exe"
    nested.touch()
    candidates = list(folder_candidates(tmp_path))
    assert python in candidates
    assert nested not in candidates


def test_discovery_deduplicates_without_resolving_venv(monkeypatch):
    import pyra.interpreters as module
    monkeypatch.setattr(module, "candidate_paths", lambda *a: iter([(sys.executable, "a"), (sys.executable, "b")]))
    found, errors = discover()
    assert len(found) == 1 and not errors
    assert found[0].path == os.path.abspath(sys.executable)
    found, errors = discover(cancelled=lambda: True)
    assert found == []


def test_probe_venv_unicode_spaces_without_pip(tmp_path):
    folder = tmp_path / "Мой Python"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder)], check=True)
    python = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    info = probe_python(python)
    assert info.path == str(python)
    assert info.prefix == str(folder)
    assert info.prefix != info.base_prefix


@pytest.mark.parametrize("update", [{"version": [3, 16, 0]}, {"version": [3, 9, 0]},
                                    {"free_threaded": True}, {"implementation": "pypy"}])
def test_unsupported_runtime_rejected(update):
    data = json.loads(subprocess.check_output([sys.executable, "-I", "-c", PROBE_CODE], text=True))
    data.update(update)
    with pytest.raises(ValueError):
        parse_probe(sys.executable, json.dumps(data))


def test_packaged_services_use_real_python_and_separate_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "сборка с пробелом"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Pyra.exe"))
    python = tmp_path / "Python 315" / "python.exe"
    python.parent.mkdir()
    python.touch()
    program, args = runtime.service_command("worker", str(python))
    assert program == str(python)
    assert args == ["-I", str(tmp_path / "сборка с пробелом" / "service_bootstrap.py"), "worker"]
    with pytest.raises(ValueError):
        runtime.service_command("worker", str(tmp_path / "Pyra.exe"))


def test_external_environment_restores_loader_and_venv(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    folder = tmp_path / "Мой проект" / ".venv"
    folder.mkdir(parents=True)
    (folder / "pyvenv.cfg").touch()
    python = folder / "bin" / "python"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/external/lib")
    monkeypatch.setenv("PYTHONHOME", "/wrong/python")
    monkeypatch.setenv("PYTHONPATH", "/wrong/modules")
    monkeypatch.setenv("PATH", os.pathsep.join([str(bundle / "Qt"), "/usr/bin"]))
    env = runtime.external_environment(python)
    assert env["LD_LIBRARY_PATH"] == "/external/lib"
    assert "PYTHONHOME" not in env and "PYTHONPATH" not in env
    assert str(bundle) not in env["PATH"]
    assert env["VIRTUAL_ENV"] == str(folder)
    assert os.environ["PYTHONHOME"] == "/wrong/python"


def test_job_timeout_then_reuse_and_failure_once(app, tmp_path):
    job = Job(merged=False)
    completions = []
    job.done.connect(lambda code, output: completions.append((code, output)))
    try:
        job.start(sys.executable, ["-c", "import time;time.sleep(30)"], timeout_ms=80)
        wait_until(app, lambda: not job.active)
        assert completions[0][0] == -2 and "время" in job.error_text
        job.start(sys.executable, ["-c", "print('OK')"], timeout_ms=1000)
        wait_until(app, lambda: not job.active)
        assert completions[1] == (0, "OK\n")
        job.start(str(tmp_path / "missing.exe"), [], timeout_ms=1000)
        wait_until(app, lambda: not job.active)
        assert len(completions) == 3 and completions[2][0] == -1
    finally:
        job.close()


def test_select_interpreter_persists_and_invalid_keeps_previous(app, tmp_path):
    settings = tmp_path / "settings"
    window = MainWindow(tmp_path, settings, restore=False)
    errors = []
    window.error = lambda title, message: errors.append(str(message))
    try:
        window.set_interpreter(sys.executable)
        wait_until(app, lambda: not window.env_probe.active)
        assert window.interpreter == sys.executable
        assert window.environment.interpreters.findData(sys.executable) >= 0
        window.set_interpreter(str(tmp_path / "missing.exe"))
        assert errors and window.interpreter == sys.executable
        saved = json.loads((settings / "settings.json").read_text())
        assert saved["default_interpreter"] == sys.executable
        assert saved["interpreters"][0]["path"] == sys.executable
    finally:
        window.close()
    reopened = MainWindow(tmp_path, settings, restore=False)
    try:
        assert reopened.interpreter == sys.executable
    finally:
        reopened.close()


def test_discovery_ui_remains_responsive_and_can_cancel(app, tmp_path, monkeypatch):
    import pyra.panels as panels
    from PyQt6.QtCore import QTimer
    import time
    def slow_discover(*args, cancelled, **kwargs):
        while not cancelled():
            time.sleep(.01)
        return [], []
    monkeypatch.setattr(panels, "discover", slow_discover)
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    ticks = []
    try:
        window.environment.discover_interpreters()
        QTimer.singleShot(20, lambda: ticks.append(True))
        wait_until(app, lambda: ticks)
        assert window.environment.discovery.isRunning()
        window.environment.discover_interpreters()
        wait_until(app, lambda: window.environment.discovery is None)
    finally:
        window.close()


def test_updating_interpreter_list_keeps_current_packages(app, tmp_path):
    from PyQt6.QtWidgets import QTableWidgetItem
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    try:
        window.environment.table.setRowCount(1)
        window.environment.table.setItem(0, 0, QTableWidgetItem("package"))
        window.environment.update_context()
        assert window.environment.table.rowCount() == 1
        window.interpreter = str(tmp_path / "another" / "python.exe")
        window.environment.update_context()
        assert window.environment.table.rowCount() == 0
    finally:
        window.close()


def test_diagnostics_release_log_file_before_windows_cleanup(tmp_path):
    import logging
    from pyra.diagnostics import setup_logging, diagnostic_text, close_logging
    path = setup_logging(tmp_path)
    logging.getLogger("pyra").error("Diagnostic test")
    assert "Diagnostic test" in diagnostic_text(tmp_path, sys.executable)
    close_logging()
    assert not logging.getLogger("pyra").handlers
    path.rename(path.with_suffix(".closed"))
