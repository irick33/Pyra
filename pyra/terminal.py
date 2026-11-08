"""A real PTY/ConPTY with an ANSI screen, rather than a command/output textbox."""

import os
import sys
import threading
import time
from pathlib import Path

import pyte
from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QGuiApplication, QPainter
from PyQt6.QtWidgets import QMenu, QTabWidget, QWidget

from .services import stop_process_tree
from .theme import mono

ANSI = {
    "default": "#cbd5e7",
    "black": "#17202d",
    "red": "#f08599",
    "green": "#9ad6b3",
    "brown": "#e4c68b",
    "blue": "#8bb7f0",
    "magenta": "#c0a1ee",
    "cyan": "#8ad4d3",
    "white": "#d3dbea",
    "brightblack": "#66738d",
    "brightred": "#ff9bb0",
    "brightgreen": "#b9ecc9",
    "brightyellow": "#f7dcaa",
    "brightblue": "#afceff",
    "brightmagenta": "#dfb8ff",
    "brightcyan": "#b2f1ec",
    "brightwhite": "#f3f5ff",
    "yellow": "#e4c68b",
}


class Reader(QThread):
    received = pyqtSignal(str)
    ready = pyqtSignal(int)
    ended = pyqtSignal(int)

    def __init__(
        self, command, cwd, interpreter, rows=25, columns=100, parent=None, extra_env=None
    ):
        super().__init__(parent)
        self.command, self.cwd, self.interpreter = command, cwd, interpreter
        self.rows, self.columns = rows, columns
        self.process = None
        self.extra_env = extra_env or {}
        self.stopping = threading.Event()
        self.delivery_slots = threading.Semaphore(8)
        self.exit_code = -1

    def run(self):
        try:
            env = os.environ.copy()
            env.update(
                TERM="xterm-256color",
                COLORTERM="truecolor",
                PYTHONIOENCODING="utf-8",
                PYTHONUNBUFFERED="1",
            )
            folder = Path(self.interpreter).parent
            env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
            if (folder.parent / "pyvenv.cfg").exists():
                env["VIRTUAL_ENV"] = str(folder.parent)
            else:
                env.pop("VIRTUAL_ENV", None)
            for key, value in self.extra_env.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = str(value)
            if sys.platform == "win32":
                from winpty import PtyProcess

                self.process = PtyProcess.spawn(
                    self.command,
                    cwd=str(self.cwd),
                    env=env,
                    dimensions=(self.rows, self.columns),
                )
            else:
                from ptyprocess import PtyProcessUnicode

                env.setdefault("LC_ALL", "C.UTF-8")
                self.process = PtyProcessUnicode.spawn(
                    self.command, cwd=str(self.cwd), env=env, dimensions=(self.rows, self.columns)
                )
            self.ready.emit(self.process.pid)
            if self.stopping.is_set():
                self.stop()
            while not self.stopping.is_set():
                try:
                    data = self.process.read(32768)
                    if data:
                        self._deliver(data)
                    elif not self.process.isalive():
                        break
                    else:
                        time.sleep(0.01)
                except (EOFError, OSError):
                    break
            self.process.isalive()
            status = getattr(self.process, "exitstatus", None)
            signal = getattr(self.process, "signalstatus", None)
            self.exit_code = int(status if status is not None else -(signal or 1))
        except Exception as error:
            self._deliver(f"\r\nОшибка терминала: {error}\r\n")
        finally:
            self.ended.emit(self.exit_code)

    def _deliver(self, text):
        # At most eight chunks can await GUI handling, including for infinite stdout.
        while not self.stopping.is_set():
            if self.delivery_slots.acquire(timeout=0.05):
                self.received.emit(text)
                return

    def write(self, text):
        try:
            if self.process and self.process.isalive():
                self.process.write(text)
        except (OSError, EOFError):
            pass

    def resize(self, rows, columns):
        self.rows, self.columns = rows, columns
        try:
            if self.process and self.process.isalive():
                self.process.setwinsize(rows, columns)
        except (OSError, EOFError):
            pass

    def stop(self):
        self.stopping.set()
        if self.process:
            try:
                if self.process.isalive():
                    stop_process_tree(self.process.pid)
                    self.process.terminate(force=True)
            except (OSError, EOFError):
                pass


class TerminalScreen(pyte.HistoryScreen):
    def __init__(self, columns, lines, writer):
        self.writer = writer
        super().__init__(columns, lines, history=3000, ratio=0.25)

    def write_process_input(self, data):
        self.writer(data)


class Terminal(QWidget):
    finished = pyqtSignal(int)

    def __init__(self, command, cwd, interpreter, parent=None, extra_env=None):
        super().__init__(parent)
        self.setFont(mono(10))
        metrics = QFontMetricsF(self.font())
        self.cell_width = metrics.horizontalAdvance("M")
        self.cell_height = metrics.height() + 2
        self.ascent = metrics.ascent()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setMinimumSize(200, 90)
        self.reader = Reader(command, cwd, interpreter, parent=self, extra_env=extra_env)
        self.screen = TerminalScreen(100, 25, self.reader.write)
        self.stream = pyte.Stream(self.screen)
        self.reader.received.connect(self._received)
        self.reader.ended.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(24)
        self.timer.timeout.connect(self.update)
        self.selection_start = self.selection_end = None
        self.alive = True
        self.reader.ready.connect(
            lambda _: self.reader.resize(self.screen.lines, self.screen.columns)
        )
        # Let the tab receive its real size before a short command produces output.
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.reader.start)
        self.start_timer.start(0)

    def _received(self, text):
        try:
            self.feed(text)
        finally:
            self.reader.delivery_slots.release()

    def feed(self, text):
        self.stream.feed(text)
        if not self.timer.isActive():
            self.timer.start()

    def _finished(self, code):
        self.alive = False
        self.feed(f"\r\n\x1b[90m[Процесс завершён, код {code}]\x1b[0m\r\n")
        self.finished.emit(code)

    @staticmethod
    def color(value, background=False):
        if value == "default" and background:
            return QColor("#11141c")
        return QColor(ANSI.get(value, "#" + value if len(value) == 6 else ANSI["default"]))

    def selected(self, row, column):
        if self.selection_start is None or self.selection_end is None:
            return False
        first, last = sorted((self.selection_start, self.selection_end))
        return first <= (row, column) <= last

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11141c"))
        painter.setFont(self.font())
        first_row = max(0, int((event.rect().top() - 5) / self.cell_height))
        last_row = min(self.screen.lines, int((event.rect().bottom() - 5) / self.cell_height) + 1)
        for row in range(first_row, last_row):
            column = 0
            while column < self.screen.columns:
                start = column
                char = self.screen.buffer[row][start]
                selection = self.selected(row, start)
                data = [char.data]
                column += 1
                while column < self.screen.columns:
                    next_char = self.screen.buffer[row][column]
                    if next_char[1:] != char[1:] or self.selected(row, column) != selection:
                        break
                    data.append(next_char.data)
                    column += 1
                fg, bg = self.color(char.fg), self.color(char.bg, True)
                if char.reverse:
                    fg, bg = bg, fg
                if selection:
                    bg = QColor("#494268")
                rect = QRectF(
                    8 + start * self.cell_width,
                    5 + row * self.cell_height,
                    (column - start) * self.cell_width + 0.5,
                    self.cell_height,
                )
                painter.fillRect(rect, bg)
                text = "".join(data)
                if text.strip():
                    font = self.font()
                    font.setBold(char.bold)
                    font.setItalic(char.italics)
                    font.setUnderline(char.underscore)
                    painter.setFont(font)
                    painter.setPen(fg)
                    painter.drawText(QPointF(rect.x(), rect.y() + self.ascent + 1), text)
        if self.hasFocus() and not self.screen.cursor.hidden and self.alive:
            x, y = self.screen.cursor.x, self.screen.cursor.y
            painter.setPen(QColor("#c4b6ff"))
            painter.drawRect(
                QRectF(
                    8 + x * self.cell_width,
                    5 + y * self.cell_height,
                    self.cell_width,
                    self.cell_height - 1,
                )
            )
        painter.end()

    def resizeEvent(self, event):
        columns = max(20, min(350, int((self.width() - 16) / self.cell_width)))
        rows = max(4, min(120, int((self.height() - 10) / self.cell_height)))
        self.screen.resize(lines=rows, columns=columns)
        self.reader.resize(rows, columns)
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste()
            return
        keys = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Escape: "\x1b",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
        }
        if ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            text = chr(key - Qt.Key.Key_A + 1)
        elif ctrl and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            text = "\x1b[1;5D" if key == Qt.Key.Key_Left else "\x1b[1;5C"
        else:
            text = keys.get(key, event.text())
        if text:
            self.selection_start = self.selection_end = None
            self.reader.write(text)
            self.update()
        else:
            super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        self.reader.write(event.commitString())
        event.accept()

    def _cell(self, position):
        return (
            max(0, min(self.screen.lines - 1, int((position.y() - 5) / self.cell_height))),
            max(0, min(self.screen.columns - 1, int((position.x() - 8) / self.cell_width))),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_start = self.selection_end = self._cell(event.position())
            self.setFocus()
            self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.selection_end = self._cell(event.position())
            self.update()

    def copy(self):
        if self.selection_start is None or self.selection_end is None:
            return
        first, last = sorted((self.selection_start, self.selection_end))
        lines = []
        for row in range(first[0], last[0] + 1):
            start = first[1] if row == first[0] else 0
            end = last[1] + 1 if row == last[0] else self.screen.columns
            lines.append(
                "".join(self.screen.buffer[row][c].data for c in range(start, end)).rstrip()
            )
        QGuiApplication.clipboard().setText("\n".join(lines))

    def paste(self):
        text = QGuiApplication.clipboard().text().replace("\r\n", "\n")
        # Bracketed paste lets shells distinguish a paste from interactive keystrokes.
        if (2004 << 5) in self.screen.mode:
            text = "\x1b[200~" + text + "\x1b[201~"
        self.reader.write(text)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.screen.prev_page()
        else:
            self.screen.next_page()
        self.update()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Копировать  Ctrl+Shift+C", self.copy)
        menu.addAction("Вставить  Ctrl+Shift+V", self.paste)
        menu.addAction("Очистить", lambda: (self.screen.reset(), self.update()))
        menu.exec(event.globalPos())

    def shutdown(self):
        self.start_timer.stop()
        self.reader.stop()
        return self.reader.wait(2500)


class TerminalTabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.close_tab)

    def add_terminal(self, cwd, interpreter, command=None, title=None, extra_env=None):
        if command is None:
            command = (
                ["powershell.exe", "-NoLogo"]
                if sys.platform == "win32"
                else [os.environ.get("SHELL", "/bin/bash"), "-i"]
            )
        terminal = Terminal(command, cwd, interpreter, self, extra_env=extra_env)
        self.addTab(terminal, title or ("PowerShell" if sys.platform == "win32" else "Shell"))
        self.setCurrentWidget(terminal)
        terminal.setFocus()
        return terminal

    def close_tab(self, index):
        terminal = self.widget(index)
        if terminal.shutdown():
            self.removeTab(index)
            terminal.deleteLater()

    def shutdown(self):
        return all([self.widget(i).shutdown() for i in range(self.count())])
