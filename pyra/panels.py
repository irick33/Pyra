import difflib
import json
import re
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .services import Job, valid_package
from .storage import MAX_SOURCE, env_python, project_files, read_source
from .theme import mono


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def log_view():
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setFont(mono(10))
    view.setMaximumBlockCount(10000)
    return view


def append_output(view, text):
    cursor = view.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(text)
    view.setTextCursor(cursor)
    view.ensureCursorVisible()


class EnvironmentPanel(QWidget):
    interpreterChanged = pyqtSignal(str)
    packagesChanged = pyqtSignal()

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.job = Job(self)
        self.list_job = Job(self, merged=False)
        self.operation = ""
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.label = QLabel()
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.label, 1)
        self.choose = button("Выбрать Python…", self.choose_interpreter)
        self.venv = button("Создать .venv", self.create_venv)
        row.addWidget(self.choose)
        row.addWidget(self.venv)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.package = QLineEdit()
        self.package.setPlaceholderText(
            "Пакет PyPI: requests  или  requests==2.32.3  или  fastapi[standard]"
        )
        self.package.returnPressed.connect(self.install)
        row.addWidget(self.package, 1)
        self.install_button = button("Установить", self.install, True)
        self.requirements_button = button("requirements.txt…", self.install_requirements)
        self.uninstall_button = button("Удалить пакет", self.uninstall)
        self.refresh_button = button("Обновить список", self.refresh)
        for item in [
            self.install_button,
            self.requirements_button,
            self.uninstall_button,
            self.refresh_button,
        ]:
            row.addWidget(item)
        layout.addLayout(row)
        splitter = QSplitter()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Пакет", "Версия"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.log = log_view()
        splitter.addWidget(self.table)
        splitter.addWidget(self.log)
        splitter.setSizes([420, 600])
        layout.addWidget(splitter, 1)
        self.job.output.connect(lambda text: append_output(self.log, text))
        self.job.done.connect(self._done)
        self.job.running.connect(self._busy)
        self.list_job.done.connect(self._listed)
        self.update_context()

    def update_context(self):
        self.label.setText("Python  ·  " + self.context()["interpreter"])
        self.table.setRowCount(0)

    def _busy(self, active):
        for widget in [
            self.choose,
            self.venv,
            self.install_button,
            self.package,
            self.requirements_button,
            self.uninstall_button,
            self.refresh_button,
        ]:
            widget.setEnabled(not active)

    def choose_interpreter(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать python.exe / python", "", "Python (python*);;Все файлы (*)"
        )
        if path:
            # Resolving a venv symlink would silently select its base interpreter.
            self.interpreterChanged.emit(str(Path(path).absolute()))

    def create_venv(self):
        if self.job.active:
            return
        root = Path(self.context()["root"])
        destination = root / ".venv"
        if destination.exists():
            if env_python(destination).is_file():
                self.interpreterChanged.emit(str(env_python(destination)))
                return
            QMessageBox.warning(self, "Окружение", ".venv уже существует и не содержит Python.")
            return
        self.operation = "venv"
        self.venv_destination = destination
        self.log.setPlainText(f"Создание {destination}\n")
        self.job.start(self.context()["interpreter"], ["-m", "venv", str(destination)], root)

    def install(self):
        package = self.package.text().strip()
        if not valid_package(package):
            QMessageBox.information(
                self, "Имя пакета", "Пример: requests, numpy>=1.26 или fastapi[standard]."
            )
            return
        self._pip(["install", package])

    def install_requirements(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл зависимостей", self.context()["root"], "Text (*.txt)"
        )
        if path:
            self._pip(["install", "-r", str(Path(path).resolve())])

    def uninstall(self):
        row = self.table.currentRow()
        if row < 0:
            return
        package = self.table.item(row, 0).text()
        if (
            QMessageBox.question(self, "Удалить пакет", f"Удалить {package} из выбранного Python?")
            == QMessageBox.StandardButton.Yes
        ):
            self._pip(["uninstall", "-y", package])

    def _pip(self, args):
        if self.job.active:
            return
        self.operation = "pip"
        self.log.setPlainText("Python: " + self.context()["interpreter"] + "\n\n")
        self.job.start(
            self.context()["interpreter"],
            ["-m", "pip", "--disable-pip-version-check", *args],
            self.context()["root"],
        )

    def _done(self, code, _output):
        append_output(self.log, f"\n[Код завершения: {code}]\n")
        if code == 0 and self.operation == "venv":
            self.interpreterChanged.emit(str(env_python(self.venv_destination)))
        if code == 0:
            self.packagesChanged.emit()
        self.refresh()

    def refresh(self):
        if not self.job.active:
            self.list_job.start(
                self.context()["interpreter"],
                ["-m", "pip", "--disable-pip-version-check", "list", "--format=json"],
                self.context()["root"],
            )

    def _listed(self, code, output):
        if code != 0:
            append_output(
                self.log,
                output
                + self.list_job.error_text
                + "\nПри отсутствии pip: python -m ensurepip --upgrade\n",
            )
            return
        try:
            packages = json.loads(output)
        except ValueError:
            append_output(self.log, output)
            return
        self.table.setRowCount(len(packages))
        for row, package in enumerate(packages):
            self.table.setItem(row, 0, QTableWidgetItem(package["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(package["version"]))

    def close_jobs(self):
        self.job.close()
        self.list_job.close()


class SearchThread(QThread):
    results = pyqtSignal(list, str)

    def __init__(self, root, query, regex=False, case=False, filenames=False, parent=None):
        super().__init__(parent)
        self.root, self.query = Path(root), query
        self.regex, self.case, self.filenames = regex, case, filenames
        self.cancelled = threading.Event()

    def run(self):
        results = []
        note = ""
        try:
            pattern = re.compile(
                self.query if self.regex else re.escape(self.query),
                0 if self.case else re.IGNORECASE,
            )
            for path in project_files(self.root):
                if self.cancelled.is_set():
                    return
                relative = str(path.relative_to(self.root))
                if self.filenames:
                    if pattern.search(relative):
                        results.append((str(path), 1, relative))
                elif path.stat().st_size <= MAX_SOURCE:
                    try:
                        source = read_source(path)
                    except (OSError, UnicodeError, ValueError, SyntaxError):
                        continue
                    for number, line in enumerate(source.text.splitlines(), 1):
                        if pattern.search(line):
                            results.append(
                                (str(path), number, f"{relative}:{number}   {line.strip()[:180]}")
                            )
                        if len(results) >= 1000:
                            break
                if len(results) >= 1000:
                    note = "Показаны первые 1000 результатов; уточните запрос."
                    break
        except (OSError, re.error) as error:
            note = str(error)
        self.results.emit(results, note)


class SearchPanel(QWidget):
    openLocation = pyqtSignal(str, int)

    def __init__(self, context, filenames=False, parent=None):
        super().__init__(parent)
        self.context, self.filenames = context, filenames
        self.worker = None
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Имя файла…" if filenames else "Поиск по проекту…")
        self.query.returnPressed.connect(self.search)
        row.addWidget(self.query, 1)
        self.regex = QCheckBox("Regex")
        self.case = QCheckBox("Aa")
        row.addWidget(self.regex)
        row.addWidget(self.case)
        self.search_button = button("Найти", self.search)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.status = QLabel("Окружения, кеши и двоичные файлы исключены из поиска.")
        layout.addWidget(self.status)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.list.itemActivated.connect(self._open)

    def search(self):
        if not self.query.text() or (self.worker and self.worker.isRunning()):
            return
        self.list.clear()
        self.search_button.setEnabled(False)
        self.status.setText("Поиск…")
        self.worker = SearchThread(
            self.context()["root"],
            self.query.text(),
            self.regex.isChecked(),
            self.case.isChecked(),
            self.filenames,
            self,
        )
        self.worker.results.connect(self._results)
        self.worker.finished.connect(lambda: self.search_button.setEnabled(True))
        self.worker.start()

    def _results(self, results, note):
        self.status.setText(f"Найдено: {len(results)}. {note}")
        for path, line, label in results:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (path, line))
            self.list.addItem(item)

    def _open(self, item):
        path, line = item.data(Qt.ItemDataRole.UserRole)
        self.openLocation.emit(path, line)

    def shutdown(self):
        if self.worker:
            self.worker.cancelled.set()
            self.worker.wait(2500)


class DebugPanel(QWidget):
    openLocation = pyqtSignal(str, int)

    def __init__(self, debugger, parent=None):
        super().__init__(parent)
        self.debugger = debugger
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        for label, action in [
            ("Продолжить F5", "continue"),
            ("Через F10", "next"),
            ("Войти F11", "stepIn"),
            ("Выйти Shift+F11", "stepOut"),
            ("Пауза", "pause"),
        ]:
            row.addWidget(button(label, lambda _=False, a=action: debugger.action(a)))
        row.addWidget(button("Стоп", debugger.stop))
        row.addStretch()
        self.state_label = QLabel("Отладчик готов · точка останова: щелчок слева от строки")
        row.addWidget(self.state_label)
        layout.addLayout(row)
        splitter = QSplitter()
        self.frames = QListWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Переменная", "Значение", "Тип"])
        self.log = log_view()
        for widget in [self.frames, self.tree, self.log]:
            splitter.addWidget(widget)
        splitter.setSizes([230, 400, 470])
        layout.addWidget(splitter, 1)
        self.expression = QLineEdit()
        self.expression.setPlaceholderText("Вычислить выражение на паузе · Enter")
        self.expression.returnPressed.connect(lambda: debugger.evaluate(self.expression.text()))
        layout.addWidget(self.expression)
        debugger.state.connect(self.state_label.setText)
        debugger.stopped.connect(self._frames)
        debugger.scopes.connect(self._scopes)
        debugger.variables.connect(self._variables)
        debugger.output.connect(lambda text: append_output(self.log, text))
        debugger.evaluated.connect(
            lambda text: append_output(
                self.log, ">>> " + self.expression.text() + "\n" + text + "\n"
            )
        )
        self.frames.itemActivated.connect(self._frame)
        self.tree.itemExpanded.connect(self._expand)
        self.references = {}

    def _frames(self, frames):
        self.frames.clear()
        for frame in frames:
            path = frame.get("source", {}).get("path", "")
            item = QListWidgetItem(f"{frame['name']}  ·  {frame.get('line', 1)}")
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, frame)
            self.frames.addItem(item)
        if self.frames.count():
            self.frames.setCurrentRow(0)
            self._frame(self.frames.item(0))

    def _frame(self, item):
        frame = item.data(Qt.ItemDataRole.UserRole)
        self.debugger.select_frame(frame["id"])
        path = frame.get("source", {}).get("path")
        if path:
            self.openLocation.emit(path, frame.get("line", 1))

    def _scopes(self, scopes):
        self.tree.clear()
        self.references.clear()
        for scope in scopes:
            item = QTreeWidgetItem([scope["name"]])
            reference = scope["variablesReference"]
            item.setData(0, Qt.ItemDataRole.UserRole, reference)
            self.tree.addTopLevelItem(item)
            self.references[reference] = item
            if not scope.get("expensive"):
                self.debugger.fetch_variables(reference)
            else:
                item.setChildIndicatorPolicy(item.ChildIndicatorPolicy.ShowIndicator)

    def _variables(self, reference, variables):
        item = self.references.get(reference)
        if item is None:
            return
        item.takeChildren()
        for variable in variables:
            child = QTreeWidgetItem(
                [variable["name"], variable.get("value", "")[:2000], variable.get("type", "")]
            )
            child.setToolTip(1, variable.get("value", "")[:10000])
            item.addChild(child)
            ref = variable.get("variablesReference", 0)
            if ref:
                child.setData(0, Qt.ItemDataRole.UserRole, ref)
                child.setChildIndicatorPolicy(child.ChildIndicatorPolicy.ShowIndicator)
                self.references[ref] = child
        item.setExpanded(True)

    def _expand(self, item):
        reference = item.data(0, Qt.ItemDataRole.UserRole)
        if reference and item.childCount() == 0:
            self.debugger.fetch_variables(reference)


class GitPanel(QWidget):
    """Local Git operations only; no remote authentication or background fetch."""

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.job = Job(self, merged=False)
        self.operation = ""
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.controls = []
        for label, callback in [
            ("Обновить", self.refresh),
            ("Индексировать", self.stage),
            ("Убрать из индекса", self.unstage),
            ("Diff", self.diff),
            ("git init", self.initialize),
        ]:
            item = button(label, callback)
            self.controls.append(item)
            row.addWidget(item)
        self.staged = QCheckBox("Diff индекса")
        row.addWidget(self.staged)
        self.message = QLineEdit()
        self.message.setPlaceholderText("Сообщение коммита")
        row.addWidget(self.message, 1)
        commit = button("Commit", self.commit)
        self.controls.append(commit)
        row.addWidget(commit)
        layout.addLayout(row)
        split = QSplitter()
        self.files = QListWidget()
        self.log = log_view()
        split.addWidget(self.files)
        split.addWidget(self.log)
        split.setSizes([350, 700])
        layout.addWidget(split, 1)
        self.job.done.connect(self._done)
        self.job.running.connect(lambda active: [c.setEnabled(not active) for c in self.controls])
        self.files.itemActivated.connect(lambda _: self.diff())

    def _run(self, operation, args):
        if self.job.active:
            return
        self.operation = operation
        self.job.start("git", args, self.context()["root"])

    def refresh(self):
        self._run("status", ["status", "--porcelain=v1", "-z"])

    def selected_path(self):
        item = self.files.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def stage(self):
        path = self.selected_path()
        if path:
            self._run("mutate", ["add", "--", path])

    def unstage(self):
        path = self.selected_path()
        if path:
            self._run("mutate", ["restore", "--staged", "--", path])

    def diff(self):
        path = self.selected_path()
        if path:
            self._run(
                "diff",
                [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    *(["--cached"] if self.staged.isChecked() else []),
                    "--",
                    path,
                ],
            )

    def initialize(self):
        if (
            QMessageBox.question(self, "Git", "Создать Git-репозиторий в текущей папке проекта?")
            == QMessageBox.StandardButton.Yes
        ):
            self._run("mutate", ["init"])

    def commit(self):
        message = self.message.text().strip()
        if message:
            self._run("mutate", ["commit", "-m", message])

    def _done(self, code, output):
        if code != 0:
            self.log.setPlainText(
                output + self.job.error_text + "\nУстановите Git и откройте папку репозитория."
            )
            return
        if self.operation == "status":
            self.files.clear()
            entries = iter(output.split("\0"))
            for entry in entries:
                if len(entry) < 4:
                    continue
                status, path = entry[:2], entry[3:]
                if "R" in status or "C" in status:
                    next(entries, None)
                item = QListWidgetItem(status + "   " + path)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.files.addItem(item)
            if not self.files.count():
                self.log.setPlainText("Рабочая папка чистая.")
        elif self.operation == "mutate":
            self.log.setPlainText(output + self.job.error_text)
            self.refresh()
        else:
            self.log.setPlainText(
                output
                or "Нет diff. Новый файл сначала добавьте в индекс и включите «Diff индекса»."
            )


class RefactorDialog(QDialog):
    def __init__(self, changes, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Переименование · изменяемых файлов: {len(changes)}")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Проверьте изменения. Все файлы будут сохранены после применения."))
        diff = log_view()
        diff.setPlainText(
            "\n\n".join(
                "".join(
                    difflib.unified_diff(
                        change["before"].splitlines(True),
                        change["after"].splitlines(True),
                        fromfile=change["path"],
                        tofile=change["path"],
                    )
                )
                for change in changes
            )
        )
        layout.addWidget(diff)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class RunDialog(QDialog):
    def __init__(self, args, cwd, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры запуска")
        self.resize(650, 200)
        layout = QFormLayout(self)
        self.args = QLineEdit(json.dumps(args, ensure_ascii=False))
        self.cwd = QLineEdit(cwd)
        layout.addRow("Аргументы · JSON-массив", self.args)
        layout.addRow("Рабочая папка", self.cwd)
        layout.addRow(QLabel('Пример аргументов: ["--port", "8080", "имя с пробелами"]'))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate(self):
        try:
            args = json.loads(self.args.text())
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("Аргументы должны быть массивом строк")
            if not Path(self.cwd.text()).is_dir():
                raise ValueError("Рабочая папка не существует")
        except ValueError as error:
            QMessageBox.warning(self, "Параметры", str(error))
            return
        self.accept()
