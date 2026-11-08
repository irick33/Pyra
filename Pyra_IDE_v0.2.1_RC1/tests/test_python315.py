"""Real-runtime checks. Set PYRA_TEST_PYTHON315 for a Python 3.12 IDE host."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import wait_until
from pyra.services import Intelligence
from pyra.storage import env_python
from pyra.window import MainWindow


@pytest.fixture(scope="module")
def python315():
    candidate = os.environ.get("PYRA_TEST_PYTHON315")
    if not candidate and sys.version_info[:2] == (3, 15):
        candidate = sys.executable
    if not candidate:
        pytest.skip("Requires an actual Python 3.15 interpreter")
    version = subprocess.check_output(
        [candidate, "-c", "import sys;print(sys.version_info[:2])"], text=True
    )
    assert "(3, 15)" in version
    return candidate


def test_selected_python315_creates_python315_venv(app, tmp_path, python315):
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    try:
        window.set_interpreter(python315)
        wait_until(app, lambda: not window.env_probe.active)
        assert window.interpreter_version[:2] == [3, 15]
        wait_until(app, lambda: not window.environment.list_job.active)
        window.environment.create_venv()
        wait_until(app, lambda: not window.environment.job.active, 35)
        target = env_python(tmp_path / ".venv")
        wait_until(app, lambda: window.interpreter == str(target))
        version = subprocess.check_output(
            [str(target), "-c", "import sys;print(sys.version_info[:2])"], text=True
        )
        assert "(3, 15)" in version
        assert window.interpreter_version[:2] == [3, 15]
        assert "3.15" in window.python_button.text()
    finally:
        window.close()


def test_new315_syntax_run_lint_and_format(app, tmp_path, python315):
    path = tmp_path / "new_syntax.py"
    code = (
        "lazy import math\n\n"
        "def answer():\n    values = frozendict(value=81)\n"
        '    return math.sqrt(values["value"])\n\n'
        'print("ANSWER", answer())\n'
    )
    path.write_text(code)
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    editor = window.open_file(path)
    try:
        window.set_interpreter(python315)
        wait_until(app, lambda: not window.env_probe.active)
        window.analyze()
        wait_until(app, lambda: editor.token in window.diagnostics)
        assert not [
            p
            for p in window.diagnostics[editor.token]
            if "syntax" in str(p.get("code", "")).lower()
        ]
        assert window._ruff_target_args() == ["--target-version", "py315"]
        wait_until(app, lambda: window.outline.topLevelItemCount() > 0)
        assert window.outline.topLevelItem(0).text(0) == "ƒ answer"
        window.format_code()
        wait_until(app, lambda: not window.formatter.active)
        assert "lazy import math" in editor.text()
        window.run_file()
        wait_until(app, lambda: window.runner and not window.runner.alive)
        assert "ANSWER 9.0" in "\n".join(window.runner.screen.display)
        assert window.runner.reader.exit_code == 0
    finally:
        editor.setModified(False)
        window.close()


def test_outline_does_not_import_jedi_or_execute_project(python315, tmp_path):
    script = Path(__file__).resolve().parents[1] / "pyra" / "worker.py"
    # -S prevents access to installed Jedi. Outline still works using only stdlib AST.
    request = {
        "id": 7,
        "operation": "outline",
        "code": 'lazy import math\ndef example():\n    return 1\nraise RuntimeError("DO NOT RUN")\n',
    }
    completed = subprocess.run(
        [python315, "-S", str(script)],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["result"][0]["name"] == "example"
    assert "error" not in result


def test_python315_completions_from_real_environment(app, tmp_path, python315):
    service = Intelligence()
    results, errors = [], []
    service.result.connect(lambda request, result: results.append(result))
    service.failure.connect(lambda request, error: errors.append(error))
    try:
        service.request(
            operation="complete",
            code="lazy import math\nmath.sq",
            path=str(tmp_path / "main.py"),
            root=str(tmp_path),
            interpreter=python315,
            python_version=[3, 15, 1],
            line=2,
            column=7,
            token="315",
            revision=1,
        )
        wait_until(app, lambda: results or errors, 20)
        assert not errors
        assert "sqrt" in results[0]
    finally:
        service.close()


def test_normal_run_has_no_debugger_or_analysis_dependency(app, tmp_path, monkeypatch):
    script = tmp_path / "hello.py"
    script.write_text('print("DIRECT_RUN")\n')
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    window.open_file(script)
    window.debounce.stop()

    def forbidden(*args, **kwargs):
        raise AssertionError("Normal Run must not depend on analysis/debugger")

    monkeypatch.setattr(window.debugger, "launch", forbidden)
    monkeypatch.setattr(window.intelligence, "request", forbidden)
    try:
        window.run_file()
        wait_until(app, lambda: window.runner and not window.runner.alive)
        assert "DIRECT_RUN" in "\n".join(window.runner.screen.display)
    finally:
        window.close()
