"""Source-run measurements: input, file/project open, Jedi and full process-tree RSS."""
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if sys.platform == "linux" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    import psutil
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from pyra.window import MainWindow
    from pyra.theme import STYLE, dark_palette
    from pyra.selftest import wait

    def memory():
        process = psutil.Process()
        total, entries = 0, []
        for child in [process, *process.children(recursive=True)]:
            try:
                rss = child.memory_info().rss
                total += rss
                entries.append({"name": child.name(), "rss_mib": round(rss / 2**20, 2)})
            except psutil.Error:
                pass
        return {"sum_rss_mib": round(total / 2**20, 2), "processes": entries}

    def summary(values):
        return {"samples_ms": [round(value, 3) for value in values],
                "median_ms": round(statistics.median(values), 3),
                "p95_ms": round(sorted(values)[max(0, int(len(values) * .95) - 1)], 3)}

    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    result = {"platform": platform.platform(), "python": platform.python_version(),
              "cpu": platform.processor() or platform.machine(), "logical_cpus": psutil.cpu_count(),
              "host_ram_gib": round(psutil.virtual_memory().total / 2**30, 2),
              "qt_platform": os.environ.get("QT_QPA_PLATFORM", "native"), "mode": "source",
              "notes": ["Synthetic input dispatch-to-event-processing, not hardware input latency.",
                        "Sum RSS double-counts shared pages. No other Python process is included.",
                        "No OS filesystem cache flush; no true cold-boot claim."]}
    if Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                result["cpu"] = line.partition(":")[2].strip()
                break
    with tempfile.TemporaryDirectory(prefix="Pyra benchmark ") as folder:
        root = Path(folder)
        for i in range(100):
            (root / f"module_{i}.py").write_text(f"VALUE = {i}\n", encoding="utf-8")
        path = root / "large.py"
        path.write_text("# benchmark\n" + "value = 42  # source\n" * 10000, encoding="utf-8")
        result["project_files"] = 101
        result["file_bytes"] = path.stat().st_size
        window = MainWindow(data_dir=root / "settings", restore=False)
        window.show()
        app.processEvents()
        result["idle_tree_memory"] = memory()
        tick = time.perf_counter()
        window.open_project(root)
        wait(app, lambda: window.proxy.rowCount(window.tree.rootIndex()) > 0)
        result["project_open_to_tree_ms"] = round((time.perf_counter() - tick) * 1000, 3)
        tick = time.perf_counter()
        editor = window.open_file(path)
        app.processEvents()
        result["file_open_to_event_processing_ms"] = round((time.perf_counter() - tick) * 1000, 3)
        values = []
        editor.setCursorPosition(5000, 0)
        for _ in range(200):
            tick = time.perf_counter()
            QTest.keyClick(editor, Qt.Key.Key_X)
            app.processEvents()
            values.append((time.perf_counter() - tick) * 1000)
        result["input"] = summary(values)
        window.debounce.stop()
        replies, errors = [], []
        window.intelligence.result.connect(lambda request, reply: replies.append(reply))
        window.intelligence.failure.connect(lambda request, error: errors.append(error))
        timings = []
        for i in range(7):
            expected = len(replies) + 1
            tick = time.perf_counter()
            window.intelligence.request(operation="complete", code="import math\nmath.sq",
                path=str(root / "completion.py"), root=str(root), interpreter=window.interpreter,
                token="benchmark", revision=i, line=2, column=7)
            wait(app, lambda: len(replies) >= expected or errors)
            if errors:
                raise RuntimeError(str(errors))
            timings.append((time.perf_counter() - tick) * 1000)
        result["completion_first_ms"] = round(timings[0], 3)
        result["completion_warm"] = summary(timings[1:])
        window.show_terminal(True)
        terminal = window.terminals.currentWidget()
        wait(app, lambda: terminal.reader.process is not None)
        app.processEvents()
        result["gui_jedi_and_shell_tree_memory"] = memory()
        editor.setModified(False)
        window.close()
        app.processEvents()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
