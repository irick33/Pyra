"""Exercise the actual GUI/services in a disposable workspace, also from Pyra.exe."""
import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import __version__
from .runtime import default_python, external_environment, initialize_external_processes


def wait(app, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise TimeoutError("Операция не завершилась вовремя")


def run(interpreter):
    from PyQt6.QtWidgets import QApplication
    from .window import MainWindow
    from .storage import env_python
    from .interpreters import probe_python
    from .diagnostics import setup_logging, close_logging
    from .theme import STYLE, dark_palette

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    initialize_external_processes()
    result = {"version": __version__, "platform": platform.platform(),
              "ide_python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False)),
              "checks": [], "passed": False}

    def check(name, callback):
        start = time.perf_counter()
        try:
            callback()
        except Exception:
            result["checks"].append({"name": name, "passed": False, "error": traceback.format_exc()})
            raise
        result["checks"].append({"name": name, "passed": True,
                                 "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)})

    window = None
    with tempfile.TemporaryDirectory(prefix="Pyra_проверка ") as directory:
        root = Path(directory)
        settings = root / "settings"
        setup_logging(settings)
        try:
            check("interpreter", lambda: result.update(interpreter=probe_python(interpreter).to_dict()))
            target = env_python(root / ".venv")

            def create_env():
                subprocess.run([interpreter, "-m", "venv", "--without-pip", str(root / ".venv")],
                               check=True, capture_output=True, timeout=45,
                               env=external_environment(interpreter))
                assert probe_python(target).prefix != probe_python(target).base_prefix

            check("venv_with_unicode_path", create_env)
            window = MainWindow(root, settings, restore=False)
            errors = []
            window.error = lambda title, message: errors.append(f"{title}: {message}")
            window.show()
            app.processEvents()
            script = root / "привет мир.py"
            script.write_text('name = input("Name? ")\nanswer = "Привет " + name\nprint(answer)\n', encoding="utf-8")
            editor = window.open_file(script)
            check("gui_open_project_file", lambda: require(editor and editor.text().startswith("name =")))
            window.set_interpreter(str(target))
            wait(app, lambda: not window.env_probe.active)
            check("select_venv", lambda: require(window.interpreter == str(target) and not errors))

            def run_script():
                window.run_file()
                wait(app, lambda: window.runner is not None and "Name?" in "\n".join(window.runner.screen.display))
                window.runner.reader.write("Ярослав\r")
                wait(app, lambda: not window.runner.alive)
                require("Привет Ярослав" in "\n".join(window.runner.screen.display))
                require(window.runner.reader.exit_code == 0)

            check("run_terminal_input_unicode", run_script)

            def complete():
                replies, failures = [], []
                def success(request, response):
                    if request.get("token") == "selftest":
                        replies.append(response)
                def failure(request, message):
                    if request.get("token") == "selftest":
                        failures.append(message)
                window.intelligence.result.connect(success)
                window.intelligence.failure.connect(failure)
                window.intelligence.request(operation="complete", code="import math\nmath.sq",
                    path=str(root / "completion.py"), root=str(root), interpreter=str(target),
                    line=2, column=7, token="selftest", revision=0)
                wait(app, lambda: replies or failures)
                require(not failures, str(failures))
                require("sqrt" in replies[0])

            check("bundled_jedi_in_clean_venv", complete)
            lint_path = root / "форматирование.py"
            lint_path.write_text("import os\nx=  1\n", encoding="utf-8")
            lint_editor = window.open_file(lint_path)

            def lint():
                window.analyze()
                wait(app, lambda: lint_editor.token in window.diagnostics)
                require(any(item["code"] == "F401" for item in window.diagnostics[lint_editor.token]))

            check("bundled_ruff_diagnostics", lint)

            def formatting():
                window.format_code()
                wait(app, lambda: not window.formatter.active)
                require(lint_editor.text() == "import os\n\nx = 1\n", repr(lint_editor.text()))
                lint_editor.setModified(False)

            check("bundled_ruff_format", formatting)
            window.tabs.setCurrentWidget(editor)

            def debug():
                editor.toggle_breakpoint(1)
                stops = []
                window.debugger.stopped.connect(stops.append)
                window.debug_file()
                wait(app, lambda: hasattr(window, "debug_terminal"))
                terminal = window.debug_terminal
                wait(app, lambda: "Name?" in "\n".join(terminal.screen.display))
                terminal.reader.write("Ярослав\r")
                wait(app, lambda: stops)
                require(stops[0][0]["line"] == 2)
                window.debugger.action("continue")
                wait(app, lambda: not window.debugger.active)
                wait(app, lambda: not terminal.alive)
                require("Привет Ярослав" in "\n".join(terminal.screen.display))

            check("bundled_debugpy_breakpoint_and_input", debug)
            require(not errors, str(errors))
            result["passed"] = True
        except Exception:
            result["error"] = traceback.format_exc()
        finally:
            if window:
                for editor in window.editors():
                    editor.setModified(False)
                window.close()
                app.processEvents()
                window.deleteLater()
                from PyQt6.QtCore import QEvent
                app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            close_logging()
    return result


def require(condition, message="Self-test assertion failed"):
    if not condition:
        raise AssertionError(message)


def startup_probe(report):
    """First-paint marker for an external timer; no saved sessions or service startup."""
    from PyQt6.QtWidgets import QApplication
    from .window import MainWindow
    from .theme import STYLE, dark_palette
    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    initialize_external_processes()
    with tempfile.TemporaryDirectory() as folder:
        window = MainWindow(data_dir=folder, restore=False, discover_missing=False)
        window.show()
        app.processEvents()
        window.grab()
        Path(report).write_text(json.dumps({"ready": True, "version": __version__}), encoding="utf-8")
        window.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=default_python())
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.python)
    except Exception:
        result = {"passed": False, "error": traceback.format_exc()}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        print(text)
    return 0 if result["passed"] else 1
