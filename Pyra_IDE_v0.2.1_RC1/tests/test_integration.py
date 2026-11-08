import json
import sys


from conftest import wait_until
from pyra.debugger import DAPClient
from pyra.services import Intelligence, Job
from pyra.terminal import Terminal
from pyra.window import MainWindow


def test_jedi_completion_goto_and_signatures(app, tmp_path):
    service = Intelligence()
    results, errors = [], []
    service.result.connect(lambda request, result: results.append((request, result)))
    service.failure.connect(lambda request, error: errors.append(error))
    try:
        service.request(
            operation="complete",
            code="import math\nmath.sq",
            path=str(tmp_path / "main.py"),
            root=str(tmp_path),
            interpreter=sys.executable,
            line=2,
            column=7,
            token="x",
            revision=1,
        )
        wait_until(app, lambda: results or errors, 20)
        assert not errors
        assert "sqrt" in results[-1][1]
        service.request(
            operation="goto",
            code="def square(x):\n    return x*x\nsquare(2)\n",
            path=str(tmp_path / "main.py"),
            root=str(tmp_path),
            interpreter=sys.executable,
            line=3,
            column=3,
            token="x",
            revision=2,
        )
        wait_until(app, lambda: len(results) == 2 or errors)
        assert results[-1][1][0]["line"] == 1
        service.request(
            operation="signature",
            code="def square(x):\n    return x*x\nsquare(",
            path=str(tmp_path / "main.py"),
            root=str(tmp_path),
            interpreter=sys.executable,
            line=3,
            column=7,
            token="x",
            revision=3,
        )
        wait_until(app, lambda: len(results) == 3 or errors)
        assert "square(x)" in results[-1][1][0]
    finally:
        service.close()


def test_ruff_works_with_unsaved_stdin(app, tmp_path):
    job = Job()
    results = []
    job.done.connect(lambda code, output: results.append((code, output)))
    try:
        job.start(
            sys.executable,
            ["-m", "ruff", "check", "--output-format=json", "--stdin-filename", "test.py", "-"],
            tmp_path,
            stdin="print(undefined_name)\n",
        )
        wait_until(app, lambda: results)
        assert results[0][0] == 1
        assert json.loads(results[0][1])[0]["code"] == "F821"
    finally:
        job.close()


def test_true_terminal_input_and_unicode(app, tmp_path):
    code = 'name=input("Name? "); print("Привет, " + name)'
    terminal = Terminal([sys.executable, "-u", "-c", code], tmp_path, sys.executable)
    terminal.resize(900, 200)
    terminal.show()
    try:
        wait_until(app, lambda: "Name?" in "\n".join(terminal.screen.display))
        terminal.reader.write("Ярослав\r")
        wait_until(app, lambda: not terminal.alive)
        assert "Привет, Ярослав" in "\n".join(terminal.screen.display)
        assert terminal.reader.exit_code == 0
    finally:
        assert terminal.shutdown()
        terminal.close()


def test_debugpy_breakpoint_variables_step_and_continue(app, tmp_path):
    path = tmp_path / "debug_me.py"
    path.write_text("value = 40\nvalue += 2\nprint(value)\n", encoding="utf-8")
    client = DAPClient()
    stops, scopes, variables, output = [], [], [], []
    client.stopped.connect(stops.append)
    client.scopes.connect(scopes.append)
    client.variables.connect(lambda reference, values: variables.extend(values))
    client.output.connect(output.append)
    try:
        assert client.launch(path, sys.executable, tmp_path, breakpoints={str(path): [2]})
        wait_until(app, lambda: stops, 25)
        assert stops[0][0]["line"] == 2
        wait_until(app, lambda: scopes)
        client.fetch_variables(scopes[0][0]["variablesReference"])
        wait_until(app, lambda: variables)
        assert any(v["name"] == "value" and v["value"] == "40" for v in variables)
        client.action("next")
        wait_until(app, lambda: len(stops) >= 2)
        assert stops[1][0]["line"] == 3
        client.action("continue")
        wait_until(app, lambda: not client.active)
        assert "42" in "".join(output)
    finally:
        client.close()


def test_session_restore_and_async_analysis(app, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "main.py"
    path.write_text("def greet(name):\n    return name\n", encoding="utf-8")
    data = tmp_path / "settings"
    first = MainWindow(root, data, restore=False)
    first.open_file(path)
    first.editor().toggle_breakpoint(1)
    first.editor().setCursorPosition(1, 4)
    first.analyze()
    try:
        wait_until(app, lambda: first.outline.topLevelItemCount() > 0)
        assert first.outline.topLevelItem(0).text(0) == "ƒ greet"
        assert first.tree.currentIndex().data() == "main.py"
    finally:
        first.close()
    second = MainWindow(data_dir=data, restore=True)
    try:
        assert second.editor().path == path
        assert second.editor().breakpoints() == [2]
        assert second.editor().getCursorPosition() == (1, 4)
    finally:
        second.close()


def test_pip_uses_selected_interpreter_and_venv(app, tmp_path):
    from pyra.storage import env_python

    root = tmp_path / "project with spaces"
    root.mkdir()
    window = MainWindow(root, tmp_path / "settings", restore=False)
    try:
        window.environment.create_venv()
        wait_until(app, lambda: not window.environment.job.active, 35)
        wait_until(app, lambda: window.interpreter == str(env_python(root / ".venv")), 15)
        assert env_python(root / ".venv").is_file()
        wait_until(app, lambda: not window.environment.list_job.active)
        assert any(
            window.environment.table.item(i, 0).text() == "pip"
            for i in range(window.environment.table.rowCount())
        )
        # Install a real, tiny local wheel: tests pip without internet or global writes.
        import zipfile

        wheel = root / "pyra_fixture-1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("pyra_fixture.py", "VALUE = 42\n")
            archive.writestr(
                "pyra_fixture-1.0.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: pyra-fixture\nVersion: 1.0\n",
            )
            archive.writestr(
                "pyra_fixture-1.0.dist-info/WHEEL",
                "Wheel-Version: 1.0\nGenerator: pyra-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            archive.writestr("pyra_fixture-1.0.dist-info/RECORD", "")
        window.environment._pip(["install", "--no-index", str(wheel)])
        wait_until(app, lambda: not window.environment.job.active, 20)
        wait_until(app, lambda: not window.environment.list_job.active)
        assert any(
            window.environment.table.item(i, 0).text() == "pyra-fixture"
            for i in range(window.environment.table.rowCount())
        )
        # debugpy is deliberately absent from this project venv.
        path = root / "external_debug.py"
        path.write_text("answer = 42\nprint(answer)\n")
        debugger = DAPClient()
        stops, output = [], []
        debugger.stopped.connect(stops.append)
        debugger.output.connect(output.append)
        try:
            debugger.launch(path, window.interpreter, root, breakpoints={str(path): [2]})
            wait_until(app, lambda: stops, 25)
            debugger.action("continue")
            wait_until(app, lambda: not debugger.active)
            assert "42" in "".join(output)
        finally:
            debugger.close()
    finally:
        window.close()


def test_formatter_stderr_never_enters_document(app, tmp_path):
    # Ruff warns about legacy config on stderr even when formatting succeeds.
    (tmp_path / "ruff.toml").write_text('select = ["E", "F"]\n')
    path = tmp_path / "main.py"
    path.write_text("x=  1\n")
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    editor = window.open_file(path)
    try:
        window.format_code()
        wait_until(app, lambda: not window.formatter.active)
        assert editor.text() == "x = 1\n"
        assert window.formatter.error_text  # warning separated from source bytes
        editor.setModified(False)
    finally:
        window.close()


def test_terminal_stops_an_infinite_output_process(app, tmp_path):
    terminal = Terminal(
        [sys.executable, "-u", "-c", 'while True: print("flood")'], tmp_path, sys.executable
    )
    try:
        wait_until(app, lambda: "flood" in "\n".join(terminal.screen.display))
        assert terminal.shutdown()
        app.processEvents()
        assert not terminal.reader.isRunning()
    finally:
        terminal.shutdown()
        terminal.close()


def test_jedi_project_rename_and_reference(app, tmp_path):
    from pyra.worker import Engine

    path = tmp_path / "main.py"
    code = "def square(x):\n    return x*x\nresult = square(3)\n"
    path.write_text(code)
    engine = Engine()
    payload = dict(
        code=code, path=str(path), root=str(tmp_path), interpreter=sys.executable, line=1, column=6
    )
    refs = engine.handle(dict(operation="references", **payload))
    assert len(refs) == 2
    changes = engine.handle(dict(operation="rename", new_name="area", **payload))
    assert len(changes) == 1
    assert changes[0]["after"] == code.replace("square", "area")


def test_local_git_status_stage_and_diff(app, tmp_path):
    import shutil
    import subprocess
    import pytest
    from pyra.panels import GitPanel

    if not shutil.which("git"):
        pytest.skip("Git not installed")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "hello world.py").write_text("print(42)\n")
    panel = GitPanel(lambda: {"root": str(tmp_path)})
    try:
        panel.refresh()
        wait_until(app, lambda: not panel.job.active)
        assert panel.files.count() == 1
        panel.files.setCurrentRow(0)
        panel.stage()
        wait_until(app, lambda: not panel.job.active)
        assert panel.files.item(0).text().startswith("A ")
        panel.files.setCurrentRow(0)
        panel.staged.setChecked(True)
        panel.diff()
        wait_until(app, lambda: not panel.job.active)
        assert "+print(42)" in panel.log.toPlainText()
    finally:
        panel.job.close()


def test_gui_debugger_supports_interactive_input(app, tmp_path):
    path = tmp_path / "interactive.py"
    path.write_text('name = input("Name? ")\nanswer = "Hello " + name\nprint(answer)\n')
    window = MainWindow(tmp_path, tmp_path / "settings", restore=False)
    editor = window.open_file(path)
    editor.toggle_breakpoint(1)
    stops = []
    window.debugger.stopped.connect(stops.append)
    try:
        window.debug_file()
        wait_until(app, lambda: hasattr(window, "debug_terminal"), 25)
        terminal = window.debug_terminal
        wait_until(app, lambda: "Name?" in "\n".join(terminal.screen.display), 25)
        terminal.reader.write("Yaroslav\r")
        wait_until(app, lambda: stops)
        assert stops[0][0]["line"] == 2
        window.debugger.action("continue")
        wait_until(app, lambda: not window.debugger.active)
        wait_until(app, lambda: not terminal.alive)
        assert "Hello Yaroslav" in "\n".join(terminal.screen.display)
    finally:
        window.close()
