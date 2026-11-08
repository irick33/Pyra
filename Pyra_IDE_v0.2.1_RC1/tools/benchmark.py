"""Reproducible local microbenchmark, not a comparison with other IDEs."""

import os
import sys
import time
from pathlib import Path

START = time.perf_counter()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import platform
import statistics
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pyra.window import MainWindow
from pyra.theme import STYLE, dark_palette


def rss_mb():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 2)
    except OSError:
        return None


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as folder:
        window = MainWindow(data_dir=Path(folder) / "settings", restore=False)
        window.show()
        app.processEvents()
        startup = time.perf_counter() - START
        idle_rss = rss_mb()
        path = Path(folder) / "large.py"
        path.write_text("# Python source\n" + "value = 42  # benchmark\n" * 10000)
        before = time.perf_counter()
        editor = window.open_file(path)
        app.processEvents()
        load = time.perf_counter() - before
        editor.setCursorPosition(5000, 0)
        latencies = []
        for _ in range(200):
            tick = time.perf_counter()
            QTest.keyClick(editor, Qt.Key.Key_X)
            app.processEvents()
            latencies.append((time.perf_counter() - tick) * 1000)
        results = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "qt_platform": os.environ["QT_QPA_PLATFORM"],
            "startup_to_first_offscreen_paint_ms": round(startup * 1000, 2),
            "idle_gui_rss_mib": idle_rss,
            "source_lines": editor.lines(),
            "source_bytes_before_edit": path.stat().st_size,
            "load_source_to_paint_ms": round(load * 1000, 2),
            "key_samples": len(latencies),
            "key_median_ms": round(statistics.median(latencies), 3),
            "key_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3),
            "gui_rss_after_edit_mib": rss_mb(),
            "scope": "Main GUI process, offscreen, no debugger, terminal or analysis worker. Cached dependencies. Not a Windows benchmark.",
        }
        window.debounce.stop()
        editor.setModified(False)
        window.close()
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
