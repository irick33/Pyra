"""Measure complete GUI-process startup and Run-to-first-output separately."""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pump(app, predicate, timeout=15):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.0005)
    raise RuntimeError("Benchmark timed out")


def summary(samples):
    values = sorted(samples)
    return {
        "samples_ms": [round(s, 3) for s in samples],
        "median_ms": round(statistics.median(samples), 3),
        "max_ms": round(values[-1], 3),
    }


def gui_probe():
    from PyQt6.QtWidgets import QApplication
    from pyra.window import MainWindow
    from pyra.theme import STYLE, dark_palette

    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as temp:
        window = MainWindow(data_dir=temp, restore=False)
        window.show()
        app.processEvents()
        window.grab()  # force first offscreen paint
        print("PYRA_GUI_READY", flush=True)
        window.close()


def benchmark(target_python, samples):
    start_samples = []
    for _ in range(samples):
        start = time.perf_counter()
        process = subprocess.Popen(
            [sys.executable, __file__, "--gui-probe"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            line = process.stdout.readline().strip()
            if line != "PYRA_GUI_READY":
                raise RuntimeError(f"GUI probe failed: {line}")
            start_samples.append((time.perf_counter() - start) * 1000)
            process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    from PyQt6.QtWidgets import QApplication
    from pyra.window import MainWindow
    from pyra.theme import STYLE, dark_palette

    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    run_samples, direct_samples = [], []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        script = root / "hello.py"
        script.write_text('print("PYRA_SCRIPT_READY", flush=True)\n', encoding="utf-8")
        window = MainWindow(root, root / "settings", restore=False)
        window.interpreter = str(target_python)
        window.open_file(script)
        window.show()
        app.processEvents()
        for _ in range(samples):
            tick = time.perf_counter()
            direct = subprocess.Popen(
                [str(target_python), "-u", str(script)],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                if direct.stdout.readline().strip() != "PYRA_SCRIPT_READY":
                    raise RuntimeError(direct.stderr.read())
                direct_samples.append((time.perf_counter() - tick) * 1000)
                direct.wait(timeout=10)
            finally:
                if direct.poll() is None:
                    direct.kill()
                    direct.wait()
            tick = time.perf_counter()
            window.run_file()
            terminal = window.runner
            if terminal is None:
                raise RuntimeError("Run did not start")
            pump(app, lambda: "PYRA_SCRIPT_READY" in "\n".join(terminal.screen.display))
            run_samples.append((time.perf_counter() - tick) * 1000)
            pump(app, lambda: not terminal.alive and not terminal.reader.isRunning())
            window.run_terminals.close_tab(window.run_terminals.indexOf(terminal))
            window.runner = None
        window.close()
    return {
        "platform": platform.platform(),
        "ide_python": platform.python_version(),
        "target_python": subprocess.check_output(
            [str(target_python), "--version"], text=True
        ).strip(),
        "gui_process_to_first_paint": summary(start_samples),
        "run_to_first_output": summary(run_samples),
        "direct_python_to_first_output": summary(direct_samples),
        "notes": [
            "Linux/offscreen if QT_QPA_PLATFORM=offscreen; not a Windows measurement.",
            "Startup includes Python process boot/imports, QApplication and first paint; no restored project.",
            "Repeated new processes, OS filesystem cache is not cleared.",
            "Run starts an actual fresh Python process in the IDE terminal; no debugger.",
            "Direct baseline uses pipes rather than a terminal; timing difference includes PTY and GUI output handling.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui-probe", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.gui_probe:
        gui_probe()
        return
    result = benchmark(args.python, args.samples)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
