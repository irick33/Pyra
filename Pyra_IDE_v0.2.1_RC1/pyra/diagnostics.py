"""Bounded diagnostics with no source-code or environment-variable dumps."""

import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def fallback_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "PyraIDE" / "Pyra"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "PyraIDE" / "Pyra"


def setup_logging(data_dir):
    logger = logging.getLogger("pyra")
    path = Path(data_dir) / "logs" / "pyra.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path


def close_logging():
    """Release handles before deleting a disposable Windows test workspace."""
    logger = logging.getLogger("pyra")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def diagnostic_text(data_dir, interpreter=""):
    from . import __version__
    path = Path(data_dir) / "logs" / "pyra.log"
    header = (f"Pyra {__version__}\n{platform.platform()}\n"
              f"IDE Python: {platform.python_version()}\n"
              f"Упакованная сборка: {bool(getattr(sys, 'frozen', False))}\n"
              f"Python проекта: {interpreter or 'не выбран'}\nЖурнал: {path}\n\n")
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            return header + stream.read().decode("utf-8", errors="replace")
    except OSError:
        return header + "Ошибки пока не зарегистрированы."


def show_diagnostics(parent, data_dir, interpreter):
    from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                                QMessageBox, QVBoxLayout)
    from .panels import button, log_view
    dialog = QDialog(parent)
    dialog.setWindowTitle("Журнал ошибок Pyra")
    dialog.resize(850, 540)
    layout = QVBoxLayout(dialog)
    view = log_view()
    view.setPlainText(diagnostic_text(data_dir, interpreter))
    layout.addWidget(view)
    row = QHBoxLayout()
    row.addWidget(button("Обновить", lambda: view.setPlainText(diagnostic_text(data_dir, interpreter))))
    row.addWidget(button("Копировать", lambda: QApplication.clipboard().setText(view.toPlainText())))

    def export():
        path, _ = QFileDialog.getSaveFileName(dialog, "Сохранить журнал", "pyra-diagnostics.txt", "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(view.toPlainText(), encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(dialog, "Не удалось сохранить", str(error))

    row.addWidget(button("Сохранить…", export))
    row.addStretch()
    row.addWidget(button("Закрыть", dialog.accept))
    layout.addLayout(row)
    dialog.exec()
