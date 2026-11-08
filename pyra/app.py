import argparse
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Pyra — Python IDE")
    parser.add_argument("project", nargs="?", help="Project directory or Python file")
    parser.add_argument("--no-restore", action="store_true")
    args = parser.parse_args()
    from PyQt6.QtCore import QLockFile, QStandardPaths
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from .theme import STYLE, app_icon, dark_palette
    from .window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pyra")
    app.setOrganizationName("PyraIDE")
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    data_dir = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_dir / "session.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(
            None,
            "Pyra уже открыта",
            "Используйте открытое окно Pyra. Одновременно работает одна сессия.",
        )
        return 0

    def handle_exception(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        print(text, file=sys.stderr)
        try:
            (data_dir / "last_error.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        QMessageBox.critical(
            None, "Ошибка Pyra", f"{value}\n\nПодробности: {data_dir / 'last_error.log'}"
        )

    sys.excepthook = handle_exception
    selected = Path(args.project).resolve() if args.project else None
    file = selected if selected and selected.is_file() else None
    project = file.parent if file else selected
    if project and not project.is_dir():
        QMessageBox.warning(None, "Проект не найден", str(project))
        return 1
    window = MainWindow(project, data_dir, restore=not args.no_restore)
    if file:
        window.open_file(file)
    window.show()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
