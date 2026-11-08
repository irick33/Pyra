import json
import keyword
import shutil
import sys
from pathlib import Path

from PyQt6.QtCore import (
    QDir,
    QSortFilterProxyModel,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import QAction, QDesktopServices, QFileSystemModel, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .debugger import DAPClient
from .editor import Editor
from .panels import (
    DebugPanel,
    EnvironmentPanel,
    GitPanel,
    RefactorDialog,
    RunDialog,
    SearchPanel,
    append_output,
    button,
    log_view,
)
from .services import Intelligence, Job, ruff_command
from .storage import (
    IGNORED,
    MAX_SOURCE,
    apply_refactor,
    env_python,
    interpreter_version_hint,
    load_json,
    recovery_name,
    save_json,
)
from .terminal import TerminalTabs


class ProjectFilter(QSortFilterProxyModel):
    def filterAcceptsRow(self, row, parent):
        source = self.sourceModel()
        index = source.index(row, 0, parent)
        return source.fileName(index) not in IGNORED


class MainWindow(QMainWindow):
    def __init__(self, project=None, data_dir=None, restore=True):
        super().__init__()
        self.resize(1440, 920)
        self.setMinimumSize(950, 650)
        self.data_dir = Path(
            data_dir
            or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.recovery_dir = self.data_dir / "recovery"
        self.config = load_json(self.data_dir / "settings.json")
        if not isinstance(self.config, dict):
            self.config = {}
        self.root = None
        self.interpreter = getattr(sys, "_base_executable", sys.executable)
        self.interpreter_version = list(sys.version_info[:3])
        self.run_args, self.run_cwd = [], ""
        self.runner = None
        self.analysis_target = None
        self.pending_analysis = None
        self.format_target = None
        self.diagnostics = {}
        self.closing = False
        self.intelligence = Intelligence(self)
        self.intelligence.result.connect(self._intelligence_result)
        self.intelligence.failure.connect(self._intelligence_error)
        self.linter = Job(self, merged=False)
        self.linter.done.connect(self._lint_done)
        self.formatter = Job(self, merged=False)
        self.formatter.done.connect(self._format_done)
        self.env_probe = Job(self, merged=False)
        self.env_probe.done.connect(self._interpreter_probed)
        self.debugger = DAPClient(self)
        self.debugger.terminalRequested.connect(self._debug_terminal_requested)
        self.debugger.finished.connect(self._debug_finished)
        self.debugger.state.connect(lambda text: self.statusBar().showMessage(text, 4000))
        self.debugger.state.connect(
            lambda text: self._clear_execution() if text == "Выполняется" else None
        )
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(650)
        self.debounce.timeout.connect(self.analyze)
        self._build_ui()
        self._build_menus()
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setInterval(15000)
        self.recovery_timer.timeout.connect(self.checkpoint)
        self.recovery_timer.start()
        app = QApplication.instance()
        app.applicationStateChanged.connect(self._application_state)
        restore_files = list(self.config.get("files", [])) if restore and not project else []
        document_states = self.config.get("documents", {}) if restore and not project else {}
        selected = project or (self.config.get("project") if restore else None)
        if selected and Path(selected).is_dir():
            self.open_project(selected, initial=True)
        if restore:
            for path in restore_files[:40]:
                if Path(path).is_file():
                    editor = self.open_file(path)
                    if editor:
                        state = document_states.get(path, {})
                        cursor = state.get("cursor", [0, 0])
                        editor.setCursorPosition(min(cursor[0], editor.lines() - 1), cursor[1])
                        for line in state.get("breakpoints", []):
                            if 1 <= line <= editor.lines():
                                editor.markerAdd(line - 1, Editor.BREAKPOINT)
            QTimer.singleShot(150, self.recover)
        self.update_ui()

    def context(self):
        editor = self.editor()
        return {
            "root": str(
                self.root or (editor.path.parent if editor and editor.path else Path.home())
            ),
            "interpreter": self.interpreter,
        }

    def _build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QWidget()
        top.setObjectName("topbar")
        top.setStyleSheet(
            "QWidget#topbar { background: #1b2030; border-bottom: 1px solid #2b3244; }"
        )
        header = QHBoxLayout(top)
        header.setContentsMargins(17, 9, 15, 9)
        brand = QLabel("PYRA")
        brand.setObjectName("brand")
        header.addWidget(brand)
        self.project_label = QLabel("  /  Python workspace")
        header.addWidget(self.project_label, 1)
        header.addWidget(button("Найти файл  Ctrl+P", self.quick_open))
        self.python_button = button("Python", self.show_environment)
        header.addWidget(self.python_button)
        self.run_button = button("▶  Запустить", self.run_file, True)
        self.run_button.setToolTip("Shift+F10 · запуск текущего Python-файла")
        header.addWidget(self.run_button)
        self.debug_button = button("Отладка", self.debug_file)
        header.addWidget(self.debug_button)
        self.stop_button = button("■", self.stop)
        self.stop_button.setToolTip("Остановить программу / отладку · Shift+F5")
        header.addWidget(self.stop_button)
        outer.addWidget(top)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        rail = QWidget()
        rail.setFixedWidth(51)
        rail.setObjectName("activityRail")
        rail.setStyleSheet(
            "QWidget#activityRail { background:#131722; border-right: 1px solid #2a3040; }"
        )
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 6, 0, 6)
        rail_layout.setSpacing(0)
        for glyph, tip, callback in [
            ("▤", "Проводник", self.toggle_sidebar),
            ("⌕", "Поиск по проекту", self.show_search),
            ("▷", "Запуск и отладка", lambda: self.show_panel(self.debug_panel)),
            (">_", "Терминал", self.show_terminal),
            ("⬡", "Окружение и пакеты", self.show_environment),
        ]:
            item = button(glyph, callback)
            item.setObjectName("rail")
            item.setToolTip(tip)
            rail_layout.addWidget(item)
        rail_layout.addStretch()
        item = button("?", self.about)
        item.setObjectName("rail")
        rail_layout.addWidget(item)
        body.addWidget(rail)
        self.horizontal = QSplitter()
        self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        row = QHBoxLayout()
        label = QLabel("ПРОЕКТ")
        label.setObjectName("section")
        row.addWidget(label, 1)
        plus = button("+", self.new_project_file)
        plus.setObjectName("quiet")
        row.addWidget(plus)
        sidebar_layout.addLayout(row)
        self.model = QFileSystemModel(self)
        self.model.directoryLoaded.connect(self._sync_tree_selection)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.proxy = ProjectFilter(self)
        self.proxy.setSourceModel(self.model)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(False)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.doubleClicked.connect(self._tree_open)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        sidebar_layout.addWidget(self.tree, 3)
        label = QLabel("СТРУКТУРА ФАЙЛА")
        label.setObjectName("section")
        sidebar_layout.addWidget(label)
        self.outline = QTreeWidget()
        self.outline.setHeaderHidden(True)
        self.outline.setIndentation(14)
        self.outline.itemActivated.connect(
            lambda item, _: self.goto_line(item.data(0, Qt.ItemDataRole.UserRole))
        )
        sidebar_layout.addWidget(self.outline, 2)
        self.horizontal.addWidget(self.sidebar)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        editor_area = QWidget()
        editor_layout = QVBoxLayout(editor_area)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.welcome = self._welcome()
        self.stack.addWidget(self.welcome)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.stack.addWidget(self.tabs)
        editor_layout.addWidget(self.stack, 1)
        self.find_bar = QWidget()
        find_row = QHBoxLayout(self.find_bar)
        self.find_text = QLineEdit()
        self.find_text.setPlaceholderText("Найти в файле · Enter: далее")
        self.find_text.returnPressed.connect(self.find_next)
        self.replace_text = QLineEdit()
        self.replace_text.setPlaceholderText("Заменить на…")
        self.find_regex, self.find_case = QCheckBox(".*"), QCheckBox("Aa")
        for item in [
            self.find_text,
            self.replace_text,
            self.find_regex,
            self.find_case,
            button("↓", self.find_next),
            button("Заменить", self.replace_one),
            button("Все", self.replace_all),
            button("×", self.find_bar.hide),
        ]:
            find_row.addWidget(item)
        editor_layout.addWidget(self.find_bar)
        self.find_bar.hide()
        self.vertical.addWidget(editor_area)
        self.bottom = QTabWidget()
        self.terminals = TerminalTabs()
        self.run_terminals = TerminalTabs()
        self.problems = QListWidget()
        self.problems.itemActivated.connect(self._open_problem)
        self.search_panel = SearchPanel(self.context)
        self.search_panel.openLocation.connect(self.open_location)
        self.environment = EnvironmentPanel(self.context)
        self.environment.interpreterChanged.connect(self.set_interpreter)
        self.environment.packagesChanged.connect(self._packages_changed)
        self.debug_panel = DebugPanel(self.debugger)
        self.debug_panel.openLocation.connect(self._debug_location)
        self.git_panel = GitPanel(self.context)
        self.console = log_view()
        for widget, label in [
            (self.terminals, "Терминал"),
            (self.run_terminals, "Запуск"),
            (self.problems, "Проблемы"),
            (self.search_panel, "Поиск"),
            (self.environment, "Пакеты"),
            (self.debug_panel, "Отладка"),
            (self.git_panel, "Git"),
            (self.console, "Журнал"),
        ]:
            self.bottom.addTab(widget, label)
        self.bottom.setCurrentWidget(self.problems)
        self.bottom.currentChanged.connect(self._panel_changed)
        self.vertical.addWidget(self.bottom)
        self.vertical.setSizes([600, 245])
        self.vertical.setStretchFactor(0, 3)
        self.vertical.setStretchFactor(1, 1)
        self.horizontal.addWidget(self.vertical)
        self.horizontal.setStretchFactor(1, 1)
        self.horizontal.setSizes([250, 1140])
        body.addWidget(self.horizontal, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.location_label = QLabel("  Python  ·  UTF-8  ·  4 пробела  ")
        self.statusBar().addPermanentWidget(self.location_label)
        self.statusBar().showMessage("Готово")

    def _welcome(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(70, 40, 70, 40)
        layout.addStretch()
        eyebrow = QLabel("PYTHON, В ЦЕНТРЕ ВНИМАНИЯ")
        eyebrow.setStyleSheet("color:#9a89e7; font-size:11px; letter-spacing:3px;")
        layout.addWidget(eyebrow)
        title = QLabel("Меньше шума.\nБольше кода.")
        title.setStyleSheet("font-size:40px; font-weight:600; color:#e1e5f2;")
        layout.addWidget(title)
        subtitle = QLabel("Нативный редактор. Ваш Python. Всё под рукой.")
        subtitle.setStyleSheet("font-size:14px; color:#8c99b5; padding:10px 0 28px;")
        layout.addWidget(subtitle)
        row = QHBoxLayout()
        row.addWidget(button("Открыть проект…", self.choose_project, True))
        row.addWidget(button("Новый файл", self.new_file))
        row.addWidget(button("Демо-проект", self.open_demo))
        row.addStretch()
        layout.addLayout(row)
        shortcuts = QLabel("Ctrl+P  найти файл      Ctrl+Space  подсказки      Shift+F10  запуск")
        shortcuts.setStyleSheet("color:#697791; padding-top:28px;")
        layout.addWidget(shortcuts)
        layout.addStretch(2)
        return widget

    def _action(self, menu, text, shortcut, callback):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _build_menus(self):
        file = self.menuBar().addMenu("Файл")
        for text, shortcut, callback in [
            ("Новый файл", "Ctrl+N", self.new_file),
            ("Открыть файл…", "Ctrl+O", self.choose_file),
            ("Открыть проект…", "Ctrl+Alt+O", self.choose_project),
            ("Новая папка проекта…", "", self.new_project),
            ("Сохранить", "Ctrl+S", self.save_current),
            ("Сохранить как…", "Ctrl+Shift+S", lambda: self.save_current(True)),
            ("Сохранить всё", "Ctrl+Alt+S", self.save_all),
            ("Закрыть файл", "Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex())),
            ("Выход", "Alt+F4", self.close),
        ]:
            self._action(file, text, shortcut, callback)
        edit = self.menuBar().addMenu("Правка")
        for text, shortcut, callback in [
            ("Отменить", "Ctrl+Z", lambda: self.editor_call("undo")),
            ("Повторить", "Ctrl+Y", lambda: self.editor_call("redo")),
            ("Найти / заменить", "Ctrl+F", self.show_find),
            ("Заменить", "Ctrl+H", self.show_find),
            ("Поиск в проекте", "Ctrl+Shift+F", self.show_search),
            ("Комментарий", "Ctrl+/", lambda: self.editor_call("toggle_comment")),
            ("Форматировать Python", "Ctrl+Alt+L", self.format_code),
            ("Увеличить шрифт", "Ctrl+=", lambda: self.editor_call("zoomIn")),
            ("Уменьшить шрифт", "Ctrl+-", lambda: self.editor_call("zoomOut")),
        ]:
            self._action(edit, text, shortcut, callback)
        navigate = self.menuBar().addMenu("Навигация")
        for text, shortcut, callback in [
            ("Найти файл…", "Ctrl+P", self.quick_open),
            ("Перейти к строке…", "Ctrl+G", self.choose_line),
            ("К определению", "F12", lambda: self.request_current("goto")),
            ("Найти использования", "Shift+F12", lambda: self.request_current("references")),
            ("Документация", "Ctrl+Q", lambda: self.request_current("help")),
            ("Переименовать символ…", "Shift+F6", lambda: self.request_current("rename")),
        ]:
            self._action(navigate, text, shortcut, callback)
        run = self.menuBar().addMenu("Выполнение")
        for text, shortcut, callback in [
            ("Запустить файл", "Shift+F10", self.run_file),
            ("Отладка / продолжить", "F5", self.debug_file),
            ("Остановить", "Shift+F5", self.stop),
            ("Точка останова", "F9", lambda: self.editor_call("toggle_breakpoint")),
            ("Шаг через", "F10", lambda: self.debugger.action("next")),
            ("Шаг внутрь", "F11", lambda: self.debugger.action("stepIn")),
            ("Шаг наружу", "Shift+F11", lambda: self.debugger.action("stepOut")),
            ("Параметры запуска…", "", self.run_settings),
            ("Тесты · unittest", "", lambda: self.run_tests("unittest")),
            ("Тесты · pytest", "", lambda: self.run_tests("pytest")),
            ("Новый терминал", "Ctrl+`", lambda: self.show_terminal(True)),
        ]:
            self._action(run, text, shortcut, callback)
        environment = self.menuBar().addMenu("Окружение")
        self._action(environment, "Python и библиотеки", "Ctrl+Alt+P", self.show_environment)
        self._action(environment, "Создать .venv", "", self.environment.create_venv)
        view = self.menuBar().addMenu("Вид")
        self._action(view, "Проводник", "Ctrl+B", self.toggle_sidebar)
        self._action(view, "Нижняя панель", "Ctrl+J", self.toggle_bottom)
        self._action(view, "Перенос строк", "Alt+Z", self.toggle_wrap)
        help_menu = self.menuBar().addMenu("Справка")
        self._action(help_menu, "Руководство", "F1", self.open_readme)
        self._action(help_menu, "О Pyra", "", self.about)

    def editor(self):
        return self.tabs.currentWidget()

    def editors(self):
        return [self.tabs.widget(index) for index in range(self.tabs.count())]

    def editor_call(self, method):
        if self.editor():
            getattr(self.editor(), method)()

    def new_file(self):
        editor = self._add_editor(Editor())
        editor.untitled_name = f"untitled_{self.tabs.count()}.py"
        self._tab_label(editor)
        return editor

    def _add_editor(self, editor):
        self.tabs.addTab(editor, editor.name)
        self.tabs.setCurrentWidget(editor)
        editor.modificationChanged.connect(lambda _: self._tab_label(editor))
        editor.cursorPositionChanged.connect(lambda *_: self.update_location())
        editor.edited.connect(self._edited)
        editor.intelligenceRequested.connect(self.request_intelligence)
        editor.breakpointChanged.connect(lambda: self._breakpoints_changed(editor))
        self.stack.setCurrentWidget(self.tabs)
        editor.setFocus()
        self.debounce.start()
        self.update_ui()
        return editor

    def open_file(self, path):
        path = Path(path).resolve()
        for editor in self.editors():
            if editor.path == path:
                self.tabs.setCurrentWidget(editor)
                return editor
        try:
            size = path.stat().st_size
            if size > 20 * 1024 * 1024:
                raise ValueError(
                    "Лимит открытия — 20 МиБ. Для больших файлов используйте потоковые инструменты."
                )
            if size > 2 * MAX_SOURCE:
                if (
                    QMessageBox.question(
                        self, "Большой файл", "Открыть файл в облегчённом режиме без анализа кода?"
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return None
            return self._add_editor(Editor(path))
        except (OSError, UnicodeError, ValueError, SyntaxError) as error:
            self.error("Не удалось открыть файл", error)
            return None

    def choose_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Открыть файлы",
            str(self.root or Path.home()),
            "Python (*.py *.pyw *.pyi);;Все файлы (*)",
        )
        for path in paths:
            self.open_file(path)

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(
            self, "Открыть проект", str(self.root or Path.home())
        )
        if path:
            self.open_project(path)

    def new_project(self):
        parent = QFileDialog.getExistingDirectory(self, "Где создать проект?", str(Path.home()))
        if not parent:
            return
        name, ok = QInputDialog.getText(self, "Новый проект", "Имя папки:")
        if ok and name:
            try:
                path = self._child_path(Path(parent), name)
                path.mkdir(exist_ok=False)
                self.open_project(path)
            except (OSError, ValueError) as error:
                self.error("Проект", error)

    def open_project(self, path, initial=False):
        if not initial and (
            self.debugger.active
            or (self.runner and self.runner.alive)
            or self.environment.job.active
            or self.git_panel.job.active
        ):
            self.statusBar().showMessage(
                "Сначала завершите запуск, отладку или установку пакетов.", 6000
            )
            return False
        if not initial:
            self._save_project_settings()
            for editor in self.editors():
                if not self.confirm_close(editor):
                    return False
            while self.tabs.count():
                self.close_tab(0, confirmed=True)
        self.root = Path(path).resolve()
        self.model.setRootPath(str(self.root))
        self.tree.setRootIndex(self.proxy.mapFromSource(self.model.index(str(self.root))))
        settings = self.config.get("projects", {}).get(str(self.root), {})
        detected = env_python(self.root / ".venv")
        interpreter = settings.get("interpreter")
        self.interpreter = (
            interpreter
            if interpreter and Path(interpreter).is_file()
            else str(
                detected
                if detected.is_file()
                else Path(getattr(sys, "_base_executable", sys.executable))
            )
        )
        self.run_args = settings.get("args", [])
        self.interpreter_version = interpreter_version_hint(self.interpreter) or settings.get(
            "python_version"
        )
        self.run_cwd = settings.get("cwd") or str(self.root)
        if not Path(self.run_cwd).is_dir():
            self.run_cwd = str(self.root)
        self.environment.update_context()
        self.project_label.setText("  /  " + self.root.name)
        self.update_ui()
        self._persist()
        return True

    def open_demo(self):
        source = Path(__file__).resolve().parent.parent / "examples" / "hello_pyra"
        destination = (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
            / "PyraDemo"
        )
        try:
            if not destination.exists():
                shutil.copytree(source, destination)
            if self.open_project(destination):
                self.open_file(destination / "main.py")
        except OSError as error:
            self.error("Демо-проект", error)

    @staticmethod
    def _child_path(parent, name):
        if name in {".", ".."} or Path(name).name != name or any(c in name for c in "/\\\x00"):
            raise ValueError("Укажите одно имя без пути")
        return parent / name

    def new_project_file(self, directory=None):
        if isinstance(directory, bool):
            directory = None
        if not self.root:
            self.new_file()
            return
        directory = Path(directory or self.root)
        name, ok = QInputDialog.getText(self, "Новый файл", "Имя файла:", text="main.py")
        if ok and name:
            try:
                path = self._child_path(directory, name)
                with path.open("x", encoding="utf-8"):
                    pass
                self.open_file(path)
            except (OSError, ValueError) as error:
                self.error("Создание файла", error)

    def _tree_path(self, index=None):
        index = self.tree.currentIndex() if index is None else index
        return Path(self.model.filePath(self.proxy.mapToSource(index)))

    def _tree_open(self, index):
        path = self._tree_path(index)
        if path.is_file():
            self.open_file(path)

    def _tree_menu(self, point):
        index = self.tree.indexAt(point)
        path = self._tree_path(index) if index.isValid() else self.root
        if not path:
            return
        directory = path if path.is_dir() else path.parent
        menu = QMenu(self)
        menu.addAction("Новый файл…", lambda: self.new_project_file(directory))
        menu.addAction("Новая папка…", lambda: self.new_folder(directory))
        menu.addAction(
            "Открыть папку в системе",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))),
        )
        if path.is_file():
            menu.addAction("Переименовать файл…", lambda: self.rename_file(path))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def new_folder(self, directory):
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя:")
        if ok and name:
            try:
                self._child_path(directory, name).mkdir(exist_ok=False)
            except (OSError, ValueError) as error:
                self.error("Создание папки", error)

    def rename_file(self, path):
        editor = next((e for e in self.editors() if e.path == path), None)
        if editor and not self.confirm_close(editor):
            return
        name, ok = QInputDialog.getText(self, "Переименовать файл", "Новое имя:", text=path.name)
        if ok and name and name != path.name:
            try:
                target = self._child_path(path.parent, name)
                if target.exists():
                    raise ValueError("Файл с таким именем уже существует")
                path.rename(target)
                if editor:
                    editor.path = target
                    editor.configure_lexer()
                    self._tab_label(editor)
            except (OSError, ValueError) as error:
                self.error("Переименование файла", error)

    def save_current(self, save_as=False):
        if isinstance(save_as, bool) and save_as:
            return self.save_editor(self.editor(), True)
        return self.save_editor(self.editor())

    def save_editor(self, editor, save_as=False):
        if editor is None:
            return False
        path = editor.path
        if save_as or path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить файл",
                str(path or (self.root or Path.home()) / editor.name),
                "Python (*.py);;Все файлы (*)",
            )
            if not chosen:
                return False
            path = Path(chosen).resolve()
            if any(e is not editor and e.path == path for e in self.editors()):
                self.error("Сохранение", "Этот файл уже открыт в другой вкладке.")
                return False
        elif (
            path.exists()
            and editor.disk_mtime is not None
            and path.stat().st_mtime_ns != editor.disk_mtime
        ):
            if (
                QMessageBox.question(
                    self,
                    "Файл изменился",
                    "На диске другая версия. Перезаписать её текущим текстом?",
                )
                != QMessageBox.StandardButton.Yes
            ):
                return False
        try:
            editor.save(path)
            self._tab_label(editor)
            self._clear_recovery(editor)
            self.statusBar().showMessage("Сохранено: " + str(path), 3000)
            return True
        except (OSError, UnicodeError, ValueError) as error:
            self.error("Не удалось сохранить", error)
            return False

    def save_all(self):
        for editor in self.editors():
            if editor.isModified() or editor.path is None:
                if not self.save_editor(editor):
                    return False
        return True

    def confirm_close(self, editor):
        if not editor.isModified() and editor.path:
            return True
        if not editor.isModified() and not editor.text():
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            f"Сохранить {editor.name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_editor(editor)
        return answer == QMessageBox.StandardButton.Discard

    def close_tab(self, index, confirmed=False):
        if index < 0:
            return
        editor = self.tabs.widget(index)
        if not confirmed and not self.confirm_close(editor):
            return
        self._clear_recovery(editor)
        self.tabs.removeTab(index)
        self.diagnostics.pop(editor.token, None)
        editor.deleteLater()
        self.refresh_problems()
        if not self.tabs.count():
            self.stack.setCurrentWidget(self.welcome)
        self.update_ui()

    def _tab_label(self, editor):
        index = self.tabs.indexOf(editor)
        if index >= 0:
            self.tabs.setTabText(index, ("●  " if editor.isModified() else "") + editor.name)
            self.tabs.setTabToolTip(index, str(editor.path or "Несохранённый файл"))

    def _tab_changed(self, _index):
        self.outline.clear()
        self._sync_tree_selection()
        self.debounce.start()
        self.update_ui()

    def _sync_tree_selection(self, *_):
        editor = self.editor()
        if not self.root or not editor or not editor.path:
            return
        if editor.path.is_relative_to(self.root):
            index = self.proxy.mapFromSource(self.model.index(str(editor.path)))
            if index.isValid():
                self.tree.setCurrentIndex(index)

    def _edited(self, editor):
        self.diagnostics.pop(editor.token, None)
        if editor == self.editor():
            self.debounce.start()

    def analyze(self):
        editor = self.editor()
        if not editor or not editor.is_python or editor.large:
            return
        self.request_intelligence("outline", editor)
        payload = (editor.token, editor.revision, editor.text(), str(editor.path or "untitled.py"))
        if self.linter.active:
            self.pending_analysis = payload
        else:
            self._start_lint(payload)

    def _start_lint(self, payload):
        self.analysis_target = payload[:2]
        program, prefix = ruff_command()
        self.linter.start(
            program,
            [
                *prefix,
                "check",
                *self._ruff_target_args(),
                "--output-format=json",
                "--stdin-filename",
                payload[3],
                "-",
            ],
            self.context()["root"],
            stdin=payload[2],
        )

    def _lint_done(self, code, output):
        token, revision = self.analysis_target or (None, None)
        editor = next((e for e in self.editors() if e.token == token), None)
        if editor and editor.revision == revision:
            try:
                items = json.loads(output) if code in (0, 1) else []
                self.diagnostics[token] = items
                editor.set_diagnostics(items)
                self.refresh_problems()
            except ValueError:
                append_output(self.console, output + "\n")
        if self.linter.error_text:
            append_output(self.console, self.linter.error_text + "\n")
        if self.pending_analysis and not self.closing:
            payload = self.pending_analysis
            self.pending_analysis = None
            self._start_lint(payload)

    def refresh_problems(self):
        self.problems.clear()
        for editor in self.editors():
            for problem in self.diagnostics.get(editor.token, []):
                line = problem["location"]["row"]
                item = QListWidgetItem(
                    f"{editor.name}:{line}   {problem.get('code') or 'Syntax'}  {problem['message']}"
                )
                item.setData(Qt.ItemDataRole.UserRole, (editor.token, line))
                self.problems.addItem(item)
        self.bottom.setTabText(
            self.bottom.indexOf(self.problems), f"Проблемы · {self.problems.count()}"
        )

    def _open_problem(self, item):
        token, line = item.data(Qt.ItemDataRole.UserRole)
        editor = next((e for e in self.editors() if e.token == token), None)
        if editor:
            self.tabs.setCurrentWidget(editor)
            self.goto_line(line)

    def request_current(self, operation):
        if self.editor():
            self.request_intelligence(operation, self.editor())

    def request_intelligence(self, operation, editor):
        if editor.large or not editor.is_python:
            return
        extra = {}
        if operation == "rename":
            if not self.root or not editor.path:
                self.statusBar().showMessage(
                    "Для переименования откройте проект и сохраните файл.", 5000
                )
                return
            if not self.save_all():
                return
            name, ok = QInputDialog.getText(
                self,
                "Переименовать символ",
                "Новое имя:",
                text=editor.wordAtLineIndex(*editor.getCursorPosition()),
            )
            if not ok:
                return
            if not name.isidentifier() or keyword.iskeyword(name):
                self.error("Имя символа", "Введите допустимое имя Python.")
                return
            extra["new_name"] = name
        line, column = editor.getCursorPosition()
        self.intelligence.request(
            operation=operation,
            code=editor.text(),
            path=str(editor.path or ""),
            root=self.context()["root"],
            interpreter=self.interpreter,
            python_version=self.interpreter_version,
            line=line + 1,
            column=column,
            token=editor.token,
            revision=editor.revision,
            **extra,
        )

    def _intelligence_result(self, request, result):
        editor = next((e for e in self.editors() if e.token == request["token"]), None)
        if not editor or editor.revision != request["revision"]:
            return
        op = request["operation"]
        if op in {"complete", "signature"}:
            if editor != self.editor() or editor.getCursorPosition() != (
                request["line"] - 1,
                request["column"],
            ):
                return
            if op == "complete":
                editor.show_completions(result)
            else:
                editor.show_signature(result)
        elif op == "outline" and editor == self.editor():
            self.outline.clear()
            parents = {}
            for symbol in result:
                item = QTreeWidgetItem(
                    [("◇ " if symbol["kind"] == "class" else "ƒ ") + symbol["name"]]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, symbol["line"])
                depth = symbol["depth"]
                if depth and depth - 1 in parents:
                    parents[depth - 1].addChild(item)
                else:
                    self.outline.addTopLevelItem(item)
                parents[depth] = item
                item.setExpanded(True)
        elif op == "goto":
            if result and result[0]["path"]:
                self.open_location(result[0]["path"], result[0]["line"], result[0]["column"])
            else:
                self.statusBar().showMessage("Определение в исходных файлах не найдено.", 4000)
        elif op == "help":
            dialog = QDialog(self)
            dialog.setWindowTitle("Документация")
            dialog.resize(750, 550)
            layout = QVBoxLayout(dialog)
            text = log_view()
            text.setPlainText(
                "\n\n".join(n["name"] + "\n" + n["doc"] for n in result)
                or "Документация не найдена."
            )
            layout.addWidget(text)
            dialog.exec()
        elif op == "references":
            self.search_panel.list.clear()
            self.search_panel.status.setText(f"Использований: {len(result)}")
            for name in result:
                if name["path"]:
                    item = QListWidgetItem(f"{name['path']}:{name['line']}   {name['name']}")
                    item.setData(Qt.ItemDataRole.UserRole, (name["path"], name["line"]))
                    self.search_panel.list.addItem(item)
            self.show_panel(self.search_panel)
        elif op == "rename":
            if not result:
                self.statusBar().showMessage("Нет изменений для применения.", 4000)
                return
            if RefactorDialog(result, self).exec() == QDialog.DialogCode.Accepted:
                try:
                    paths = {Path(c["path"]).resolve() for c in result}
                    if any(e.isModified() and e.path in paths for e in self.editors()):
                        raise ValueError(
                            "Файлы изменены в редакторе после начала переименования. Повторите операцию."
                        )
                    apply_refactor(result)
                    for opened in self.editors():
                        if opened.path in paths:
                            opened.load()
                    self.statusBar().showMessage("Переименование применено.", 4000)
                except (OSError, ValueError, UnicodeError) as error:
                    self.error("Переименование", error)

    def _intelligence_error(self, request, error):
        if request["operation"] in {"goto", "references", "help", "rename"}:
            self.error("Анализ кода", error)
        else:
            self.statusBar().showMessage("Анализ кода: " + error[:160], 5000)

    def format_code(self):
        editor = self.editor()
        if not editor or not editor.is_python or self.formatter.active:
            return
        self.format_target = (editor.token, editor.revision)
        program, prefix = ruff_command()
        self.formatter.start(
            program,
            [
                *prefix,
                "format",
                *self._ruff_target_args(),
                "--stdin-filename",
                str(editor.path or "untitled.py"),
                "-",
            ],
            self.context()["root"],
            stdin=editor.text(),
        )

    def _ruff_target_args(self):
        version = self.interpreter_version
        if version and version[0] == 3 and 10 <= version[1] <= 15:
            return ["--target-version", f"py3{version[1]}"]
        return []

    def _format_done(self, code, output):
        editor = next((e for e in self.editors() if e.token == self.format_target[0]), None)
        if editor and code == 0 and editor.revision == self.format_target[1]:
            if output != editor.text():
                editor.replace_document(output)
        elif code != 0:
            self.error("Форматирование", output + self.formatter.error_text)
        else:
            self.statusBar().showMessage("Текст изменился; повторите форматирование.", 4000)

    def _prepare_run(self):
        editor = self.editor()
        if not editor or not editor.is_python:
            self.statusBar().showMessage("Откройте Python-файл для запуска.", 4000)
            return None
        if self.debugger.active or (self.runner and self.runner.alive):
            self.statusBar().showMessage("Программа уже выполняется. Сначала остановите её.", 4000)
            return None
        if not self.save_all():
            return None
        return editor

    def run_file(self):
        editor = self._prepare_run()
        if editor:
            self._start_run([self.interpreter, "-u", str(editor.path), *self.run_args], editor.name)

    def _start_run(self, command, title):
        if self.run_terminals.count() >= 6:
            self.run_terminals.close_tab(0)
        self.show_panel(self.run_terminals)
        self.runner = self.run_terminals.add_terminal(
            self.run_cwd or self.context()["root"], self.interpreter, command, title
        )
        self.runner.finished.connect(lambda _: self.update_ui())
        self.update_ui()

    def run_tests(self, framework):
        if not self.root:
            self.statusBar().showMessage("Сначала откройте проект.", 4000)
            return
        if self.debugger.active or (self.runner and self.runner.alive) or not self.save_all():
            return
        args = (
            ["-m", "unittest", "discover", "-v"]
            if framework == "unittest"
            else ["-m", "pytest", "-v"]
        )
        self._start_run([self.interpreter, *args], framework)

    def debug_file(self):
        if self.debugger.active:
            self.debugger.action("continue")
            return
        editor = self._prepare_run()
        if not editor:
            return
        breakpoints = {
            str(e.path): e.breakpoints() for e in self.editors() if e.path and e.breakpoints()
        }
        self.debug_panel.log.clear()
        self.show_panel(self.debug_panel)
        self.debugger.launch(
            editor.path,
            self.interpreter,
            self.run_cwd or self.context()["root"],
            self.run_args,
            breakpoints,
            integrated=True,
        )
        self.update_ui()

    def _debug_terminal_requested(self, sequence, arguments):
        command = arguments.get("args", [])
        if not command:
            self.debugger.terminal_response(sequence, error="Пустая команда отладчика")
            return
        self.debug_terminal = self.run_terminals.add_terminal(
            arguments.get("cwd") or self.context()["root"],
            self.interpreter,
            command=command,
            title="Отладка · ввод/вывод",
            extra_env=arguments.get("env"),
        )
        answered = [False]

        def ready(pid):
            if answered[0]:
                return
            answered[0] = True
            self.debugger.terminal_response(sequence, pid=pid)

        def failed(_):
            if not answered[0]:
                self.debugger.terminal_response(
                    sequence, error="Не удалось запустить терминал отладки"
                )

        self.debug_terminal.reader.ready.connect(ready)
        self.debug_terminal.finished.connect(failed)
        if self.debug_terminal.reader.process is not None:
            ready(self.debug_terminal.reader.process.pid)
        self.statusBar().showMessage("Ввод программы доступен во вкладке «Запуск».", 6000)

    def _breakpoints_changed(self, editor):
        if editor.path:
            self.debugger.update_breakpoints(editor.path, editor.breakpoints())

    def _debug_location(self, path, line):
        self._clear_execution()
        editor = self.open_location(path, line)
        if editor:
            editor.markerAdd(line - 1, Editor.EXECUTION)

    def _clear_execution(self):
        for editor in self.editors():
            editor.markerDeleteAll(Editor.EXECUTION)

    def _debug_finished(self):
        self._clear_execution()
        self.update_ui()

    def stop(self):
        self.debugger.stop()
        if self.runner and self.runner.alive:
            self.runner.reader.stop()

    def run_settings(self):
        dialog = RunDialog(self.run_args, self.run_cwd or self.context()["root"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.run_args = json.loads(dialog.args.text())
            self.run_cwd = dialog.cwd.text()
            self._persist()

    def set_interpreter(self, path):
        if self.env_probe.active:
            self.statusBar().showMessage("Проверяется выбранный Python…", 2500)
            return
        if self.debugger.active or (self.runner and self.runner.alive):
            self.statusBar().showMessage("Сначала остановите программу.", 5000)
            return
        self.candidate_interpreter = path
        self.env_probe.start(
            path,
            [
                "-c",
                "import json,sys; print(json.dumps({'version': list(sys.version_info[:3]), 'executable': sys.executable}))",
            ],
        )

    def _interpreter_probed(self, code, output):
        if code != 0:
            self.error("Не удалось запустить Python", output + self.env_probe.error_text)
            return
        try:
            self.interpreter_version = json.loads(output)["version"]
        except (ValueError, KeyError):
            self.error("Проверка Python", "Интерпретатор не вернул информацию о версии.")
            return
        self.interpreter = self.candidate_interpreter
        self._packages_changed()
        self.environment.update_context()
        self.environment.refresh()
        self.update_ui()
        self._persist()

    def _packages_changed(self):
        self.intelligence.process.kill()
        self.debounce.start()

    def _panel_changed(self, index):
        panel = self.bottom.widget(index)
        if panel is self.terminals and not self.terminals.count():
            self.terminals.add_terminal(self.context()["root"], self.interpreter)
        elif panel is self.environment:
            self.environment.refresh()
        elif panel is self.git_panel:
            self.git_panel.refresh()

    def show_panel(self, widget):
        self.bottom.show()
        self.bottom.setCurrentWidget(widget)
        sizes = self.vertical.sizes()
        if sizes[1] < 140:
            self.vertical.setSizes([max(300, sum(sizes) - 260), 260])

    def show_terminal(self, new=False):
        if new or not self.terminals.count():
            self.terminals.add_terminal(self.context()["root"], self.interpreter)
        self.show_panel(self.terminals)
        if self.terminals.currentWidget():
            self.terminals.currentWidget().setFocus()

    def show_environment(self):
        self.show_panel(self.environment)

    def show_search(self):
        if not self.root:
            self.statusBar().showMessage("Сначала откройте папку проекта.", 5000)
            return
        self.show_panel(self.search_panel)
        self.search_panel.query.setFocus()

    def quick_open(self):
        if not self.root:
            self.choose_file()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Найти файл в проекте")
        dialog.resize(780, 500)
        layout = QVBoxLayout(dialog)
        panel = SearchPanel(self.context, filenames=True, parent=dialog)
        layout.addWidget(panel)
        panel.openLocation.connect(
            lambda path, line: (self.open_location(path, line), dialog.accept())
        )
        panel.query.setFocus()
        dialog.exec()
        panel.shutdown()

    def show_find(self):
        self.find_bar.show()
        if self.editor() and self.editor().hasSelectedText():
            self.find_text.setText(self.editor().selectedText())
        self.find_text.setFocus()
        self.find_text.selectAll()

    def find_next(self):
        if self.editor() and self.find_text.text():
            self.editor().findFirst(
                self.find_text.text(),
                self.find_regex.isChecked(),
                self.find_case.isChecked(),
                False,
                True,
            )

    def replace_one(self):
        editor = self.editor()
        if editor and editor.hasSelectedText():
            editor.replace(self.replace_text.text())
        self.find_next()

    def replace_all(self):
        editor = self.editor()
        if not editor or not self.find_text.text():
            return
        import re

        try:
            pattern = re.compile(
                self.find_text.text()
                if self.find_regex.isChecked()
                else re.escape(self.find_text.text()),
                0 if self.find_case.isChecked() else re.IGNORECASE,
            )
            replacement = self.replace_text.text()
            result, count = pattern.subn(
                replacement if self.find_regex.isChecked() else lambda _: replacement, editor.text()
            )
            if count:
                editor.replace_document(result)
            self.statusBar().showMessage(f"Замен: {count}", 4000)
        except re.error as error:
            self.error("Замена", error)

    def open_location(self, path, line, column=0):
        editor = self.open_file(path)
        if editor:
            editor.setCursorPosition(max(0, line - 1), column)
            editor.ensureCursorVisible()
            editor.setFocus()
        return editor

    def goto_line(self, line):
        if self.editor() and line:
            self.editor().setCursorPosition(max(0, line - 1), 0)
            self.editor().ensureCursorVisible()
            self.editor().setFocus()

    def choose_line(self):
        if self.editor():
            line, ok = QInputDialog.getInt(
                self,
                "Перейти к строке",
                "Строка:",
                self.editor().getCursorPosition()[0] + 1,
                1,
                self.editor().lines(),
            )
            if ok:
                self.goto_line(line)

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_bottom(self):
        self.bottom.setVisible(not self.bottom.isVisible())

    def toggle_wrap(self):
        editor = self.editor()
        if editor:
            editor.setWrapMode(
                Editor.WrapMode.WrapWord
                if editor.wrapMode() == Editor.WrapMode.WrapNone
                else Editor.WrapMode.WrapNone
            )

    def update_ui(self):
        if not hasattr(self, "python_button"):
            return
        name = self.editor().name if self.editor() else "Python IDE"
        self.setWindowTitle(f"{name} — {self.root.name if self.root else 'Workspace'} — Pyra")
        folder = Path(self.interpreter).parent
        env_name = folder.parent.name if (folder.parent / "pyvenv.cfg").exists() else "системный"
        version = (
            " " + ".".join(map(str, self.interpreter_version)) if self.interpreter_version else ""
        )
        self.python_button.setText("Python" + version + " · " + env_name)
        self.python_button.setToolTip(self.interpreter)
        active = self.debugger.active or bool(self.runner and self.runner.alive)
        self.run_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.update_location()

    def update_location(self):
        editor = self.editor()
        if editor:
            line, column = editor.getCursorPosition()
            mode = "  ·  большой файл" if editor.large else ""
            self.location_label.setText(
                f"  Стр {line + 1}, стл {column + 1}   ·   {editor.encoding.upper()}   ·   {'CRLF' if editor.newline == chr(13) + chr(10) else 'LF'}   ·   4 пробела{mode}  "
            )

    def _save_project_settings(self):
        if self.root:
            self.config.setdefault("projects", {})[str(self.root)] = {
                "interpreter": self.interpreter,
                "python_version": self.interpreter_version,
                "args": self.run_args,
                "cwd": self.run_cwd,
            }

    def _persist(self):
        self._save_project_settings()
        self.config["project"] = str(self.root) if self.root else None
        self.config["files"] = [str(e.path) for e in self.editors() if e.path]
        self.config["documents"] = {
            str(e.path): {"cursor": list(e.getCursorPosition()), "breakpoints": e.breakpoints()}
            for e in self.editors()
            if e.path
        }
        try:
            save_json(self.data_dir / "settings.json", self.config)
        except OSError as error:
            self.statusBar().showMessage("Не удалось сохранить настройки: " + str(error), 6000)

    def _recovery_path(self, editor):
        return self.recovery_dir / recovery_name(editor.token)

    def checkpoint(self):
        for editor in self.editors():
            if editor.isModified() and editor.length() <= 5 * MAX_SOURCE:
                try:
                    save_json(
                        self._recovery_path(editor),
                        {
                            "path": str(editor.path or ""),
                            "text": editor.text(),
                            "encoding": editor.encoding,
                            "newline": editor.newline,
                        },
                    )
                except OSError:
                    pass

    def _clear_recovery(self, editor):
        try:
            self._recovery_path(editor).unlink(missing_ok=True)
        except OSError as error:
            self.statusBar().showMessage("Резервная копия недоступна: " + str(error), 5000)

    def recover(self):
        if not self.recovery_dir.exists():
            return
        files = list(self.recovery_dir.glob("*.json"))
        if not files:
            return
        choice = QMessageBox.question(
            self,
            "Восстановление текста",
            f"Найдено резервных копий: {len(files)}. Восстановить их в новых вкладках?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        for path in files:
            data = load_json(path)
            if (
                choice == QMessageBox.StandardButton.Yes
                and isinstance(data, dict)
                and "text" in data
            ):
                editor = self.new_file()
                editor.untitled_name = "Восстановлено_" + (
                    Path(data["path"]).name if data.get("path") else "untitled.py"
                )
                editor.setText(data["text"])
                editor.encoding = data.get("encoding", "utf-8")
                editor.newline = data.get("newline", "\n")
                editor.setModified(True)
                self._tab_label(editor)
            path.unlink(missing_ok=True)
        self.checkpoint()

    def _application_state(self, state):
        if state != Qt.ApplicationState.ApplicationActive or self.closing:
            return
        for editor in self.editors():
            if editor.path and editor.path.is_file():
                try:
                    if editor.path.stat().st_mtime_ns != editor.disk_mtime:
                        if editor.isModified():
                            if (
                                QMessageBox.question(
                                    self,
                                    "Файл изменён извне",
                                    f"{editor.name}: загрузить версию с диска? Текущий текст будет заменён.",
                                )
                                != QMessageBox.StandardButton.Yes
                            ):
                                continue
                        editor.load()
                except (OSError, UnicodeError, ValueError, SyntaxError) as error:
                    self.error("Обновление файла", error)

    def open_readme(self):
        path = Path(__file__).resolve().parent.parent / "README_RU.md"
        self.open_file(path)

    def about(self):
        QMessageBox.about(
            self,
            "Pyra",
            f"Pyra {__version__}\n\nНативная IDE для Python.\nQt + QScintilla · Jedi · Ruff · debugpy · PTY/ConPTY\n\nТолько тёмная тема. Плагины не подключены.\nAI-чат и генерация кода пока не реализованы.\n\nЛицензии компонентов: THIRD_PARTY.md",
        )

    def error(self, title, error):
        QMessageBox.warning(self, title, str(error)[:8000])

    def closeEvent(self, event):
        for editor in self.editors():
            if not self.confirm_close(editor):
                event.ignore()
                return
        self.closing = True
        self.recovery_timer.stop()
        self.debounce.stop()
        self.checkpoint()
        self._persist()
        self.search_panel.shutdown()
        self.debugger.close()
        if not self.terminals.shutdown() or not self.run_terminals.shutdown():
            self.closing = False
            self.recovery_timer.start()
            self.statusBar().showMessage("Ожидание завершения терминала. Повторите закрытие.", 5000)
            event.ignore()
            return
        for job in (self.linter, self.formatter, self.env_probe):
            job.close()
        self.environment.close_jobs()
        self.git_panel.job.close()
        self.intelligence.close()
        for editor in self.editors():
            self._clear_recovery(editor)
        event.accept()
