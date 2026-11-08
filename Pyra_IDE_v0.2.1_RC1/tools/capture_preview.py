"""Capture the demo workspace after a real interactive execution."""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pyra.window import MainWindow
from pyra.theme import STYLE, dark_palette


def wait(app, condition, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise RuntimeError("Demo timed out")


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as data:
        window = MainWindow(ROOT / "examples" / "hello_pyra", data, restore=False)
        editor = window.open_file(ROOT / "examples" / "hello_pyra" / "main.py")
        window.show()
        window.vertical.setSizes([530, 330])
        wait(app, lambda: window.proxy.rowCount(window.tree.rootIndex()) > 0)
        window.analyze()
        wait(app, lambda: window.outline.topLevelItemCount() > 0)
        window.run_file()
        wait(app, lambda: "Как вас зовут?" in "\n".join(window.runner.screen.display))
        window.runner.reader.write("Ярослав\r")
        wait(app, lambda: not window.runner.alive)
        editor.toggle_breakpoint(25)
        editor.setCursorPosition(17, 0)
        editor.ensureCursorVisible()
        window.statusBar().showMessage("Готово · Python-мастерская")
        app.processEvents()
        # Flush QFileSystemModel's deferred layout before an offscreen capture.
        window.tree.setCurrentIndex(window.proxy.index(0, 0, window.tree.rootIndex()))
        window.tree.viewport().repaint()
        QTest.qWait(450)  # QFileSystemModel uses a deferred sorting timer.
        path = ROOT / "docs" / "preview.png"
        path.parent.mkdir(exist_ok=True)
        window.grab().save(str(path))
        window.close()
        print(path)


if __name__ == "__main__":
    main()
