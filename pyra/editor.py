import re
import uuid
from pathlib import Path

from PyQt6.Qsci import QsciLexerJSON, QsciLexerPython, QsciScintilla
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QMenu

from .storage import MAX_SOURCE, read_source, save_source
from .theme import BG, mono


class Editor(QsciScintilla):
    intelligenceRequested = pyqtSignal(str, object)
    breakpointChanged = pyqtSignal()
    edited = pyqtSignal(object)

    BREAKPOINT = 1
    EXECUTION = 2
    ERROR = 8

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.path = Path(path).resolve() if path else None
        self.token = uuid.uuid4().hex
        self.revision = 0
        self.encoding = "utf-8"
        self.newline = "\n"
        self.disk_mtime = None
        self.untitled_name = "untitled.py"
        self.large = False
        self.setUtf8(True)
        self.setFont(mono())
        self.setMarginsFont(mono(9))
        self.setPaper(QColor(BG))
        self.setColor(QColor("#d3d9e7"))
        self.setMarginsBackgroundColor(QColor(BG))
        self.setMarginsForegroundColor(QColor("#56627d"))
        self.setMarginLineNumbers(0, True)
        self.setMarginWidth(0, "00000")
        self.setMarginType(1, self.MarginType.SymbolMargin)
        self.setMarginWidth(1, 16)
        self.setMarginMarkerMask(1, (1 << self.BREAKPOINT) | (1 << self.EXECUTION))
        self.setMarginSensitivity(1, True)
        self.markerDefine(self.MarkerSymbol.Circle, self.BREAKPOINT)
        self.setMarkerBackgroundColor(QColor("#ee7d94"), self.BREAKPOINT)
        self.setMarkerForegroundColor(QColor("#ee7d94"), self.BREAKPOINT)
        self.markerDefine(self.MarkerSymbol.RightArrow, self.EXECUTION)
        self.setMarkerBackgroundColor(QColor("#f0cb7f"), self.EXECUTION)
        self.setMarkerForegroundColor(QColor("#f0cb7f"), self.EXECUTION)
        self.setFolding(self.FoldStyle.PlainFoldStyle, 2)
        self.setFoldMarginColors(QColor(BG), QColor(BG))
        self.setIndentationGuides(True)
        self.setIndentationGuidesForegroundColor(QColor("#293145"))
        self.setIndentationGuidesBackgroundColor(QColor(BG))
        self.setIndentationsUseTabs(False)
        self.setIndentationWidth(4)
        self.setTabWidth(4)
        self.setTabIndents(True)
        self.setBackspaceUnindents(True)
        self.setAutoIndent(True)
        self.setCaretForegroundColor(QColor("#ded6ff"))
        self.setCaretWidth(2)
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#1a2030"))
        self.setSelectionBackgroundColor(QColor("#3e3c61"))
        self.setBraceMatching(self.BraceMatch.SloppyBraceMatch)
        self.setMatchedBraceBackgroundColor(QColor("#423958"))
        self.setMatchedBraceForegroundColor(QColor("#ddc6ff"))
        self.setUnmatchedBraceForegroundColor(QColor("#ff7d93"))
        self.setUnmatchedBraceBackgroundColor(QColor(BG))
        self.setEolMode(self.EolMode.EolUnix)
        self.setWrapMode(self.WrapMode.WrapNone)
        self.setScrollWidth(1)
        self.setScrollWidthTracking(True)
        self.setAutoCompletionSource(self.AutoCompletionSource.AcsNone)
        self.setAutoCompletionCaseSensitivity(True)
        self.setAutoCompletionReplaceWord(True)
        self.setCallTipsBackgroundColor(QColor("#262b3d"))
        self.setCallTipsForegroundColor(QColor("#dcd9ed"))
        self.setCallTipsHighlightColor(QColor("#b9a1ff"))
        self.SendScintilla(self.SCI_SETMULTIPLESELECTION, 1)
        self.SendScintilla(self.SCI_SETADDITIONALSELECTIONTYPING, 1)
        self.SendScintilla(self.SCI_AUTOCSETMAXHEIGHT, 10)
        self.indicatorDefine(self.IndicatorStyle.SquiggleIndicator, self.ERROR)
        self.setIndicatorForegroundColor(QColor("#f18d9b"), self.ERROR)
        self.setIndicatorDrawUnder(True, self.ERROR)
        self.completion_timer = QTimer(self)
        self.completion_timer.setSingleShot(True)
        self.completion_timer.setInterval(220)
        self.completion_timer.timeout.connect(lambda: self.request("complete"))
        self.textChanged.connect(self._changed)
        self.marginClicked.connect(self._margin)
        self.SCN_CHARADDED.connect(self._char_added)
        self.configure_lexer()
        if self.path:
            self.load()

    @property
    def is_python(self):
        return self.path is None or self.path.suffix.lower() in {".py", ".pyw", ".pyi"}

    @property
    def name(self):
        return self.path.name if self.path else self.untitled_name

    def configure_lexer(self):
        lexer = None
        if self.is_python:
            lexer = QsciLexerPython(self)
            lexer.setHighlightSubidentifiers(True)
            lexer.setFoldComments(True)
            lexer.setFoldQuotes(True)
        elif self.path and self.path.suffix == ".json":
            lexer = QsciLexerJSON(self)
        self.setLexer(lexer)
        old = getattr(self, "_lexer", None)
        self._lexer = lexer
        if old:
            old.deleteLater()
        if lexer:
            lexer.setDefaultFont(mono())
            lexer.setDefaultPaper(QColor(BG))
            lexer.setDefaultColor(QColor("#d3d9e7"))
            for style in range(128):
                lexer.setPaper(QColor(BG), style)
                lexer.setFont(mono(), style)
                lexer.setColor(QColor("#d3d9e7"), style)
            if self.is_python:
                colors = {
                    0: "#d3d9e7",
                    1: "#697992",
                    2: "#edb980",
                    3: "#a4d6ae",
                    4: "#a4d6ae",
                    5: "#b39bfa",
                    6: "#a4d6ae",
                    7: "#a4d6ae",
                    8: "#f0d18f",
                    9: "#83cafa",
                    10: "#9fb2cf",
                    11: "#d3d9e7",
                    12: "#697992",
                    13: "#ee8a9b",
                    14: "#86d1d9",
                    15: "#ca9fe9",
                    16: "#a4d6ae",
                    17: "#a4d6ae",
                    18: "#a4d6ae",
                    19: "#a4d6ae",
                }
                for style, color in colors.items():
                    lexer.setColor(QColor(color), style)

    def load(self):
        source = read_source(self.path)
        cursor = self.getCursorPosition()
        self.encoding, self.newline = source.encoding, source.newline
        self.setText(source.text)
        self.setModified(False)
        self.disk_mtime = self.path.stat().st_mtime_ns
        self.large = self.length() > MAX_SOURCE
        self.setCursorPosition(min(cursor[0], self.lines() - 1), cursor[1])
        self.SendScintilla(self.SCI_EMPTYUNDOBUFFER)

    def save(self, path=None):
        target = Path(path).resolve() if path else self.path
        if target is None:
            raise ValueError("Нужно имя файла")
        save_source(target, self.text(), self.encoding, self.newline)
        self.path = target
        self.configure_lexer()
        self.disk_mtime = target.stat().st_mtime_ns
        self.setModified(False)

    def _changed(self):
        self.revision += 1
        self.large = self.length() > MAX_SOURCE
        self.edited.emit(self)

    def request(self, operation):
        if self.is_python and not self.large:
            self.intelligenceRequested.emit(operation, self)

    def _char_added(self, char):
        if self.large or not self.is_python:
            return
        if char < 128 and (chr(char).isalnum() or char in (46, 95)):
            self.completion_timer.start()
        elif char in (40, 44):
            self.request("signature")

    def show_completions(self, names):
        if not names:
            return
        line, column = self.getCursorPosition()
        prefix = re.search(r"[\w]*$", self.text(line)[:column]).group()
        self.SendScintilla(
            self.SCI_AUTOCSHOW, len(prefix.encode("utf-8")), " ".join(names).encode("utf-8")
        )

    def show_signature(self, signatures):
        if signatures:
            position = self.SendScintilla(self.SCI_GETCURRENTPOS)
            self.SendScintilla(
                self.SCI_CALLTIPSHOW, position, "\n".join(signatures).encode("utf-8")
            )

    def _margin(self, margin, line, _modifiers):
        if margin == 1:
            self.toggle_breakpoint(line)

    def toggle_breakpoint(self, line=None):
        if line is None:
            line = self.getCursorPosition()[0]
        if self.markersAtLine(line) & (1 << self.BREAKPOINT):
            self.markerDelete(line, self.BREAKPOINT)
        else:
            self.markerAdd(line, self.BREAKPOINT)
        self.breakpointChanged.emit()

    def breakpoints(self):
        result, line = [], 0
        while True:
            line = self.markerFindNext(line, 1 << self.BREAKPOINT)
            if line < 0:
                return result
            result.append(line + 1)
            line += 1

    def set_diagnostics(self, diagnostics):
        self.SendScintilla(self.SCI_SETINDICATORCURRENT, self.ERROR)
        self.SendScintilla(self.SCI_INDICATORCLEARRANGE, 0, self.length())
        for item in diagnostics:
            line = item.get("location", {}).get("row", 1) - 1
            column = item.get("location", {}).get("column", 1) - 1
            end = item.get("end_location", item.get("location", {}))
            end_line = end.get("row", line + 1) - 1
            end_column = end.get("column", column + 2) - 1
            if line < self.lines():
                self.fillIndicatorRange(
                    line,
                    column,
                    min(end_line, self.lines() - 1),
                    max(end_column, column + 1),
                    self.ERROR,
                )

    def replace_document(self, text):
        cursor = self.getCursorPosition()
        self.beginUndoAction()
        self.selectAll()
        self.replaceSelectedText(text)
        self.endUndoAction()
        self.setCursorPosition(min(cursor[0], self.lines() - 1), cursor[1])

    def toggle_comment(self):
        first, _, last, last_column = self.getSelection()
        if first < 0:
            first = last = self.getCursorPosition()[0]
        elif last_column == 0 and last > first:
            last -= 1
        lines = [self.text(i).rstrip("\r\n") for i in range(first, last + 1)]
        remove = all(not line.strip() or line.lstrip().startswith("#") for line in lines)
        self.beginUndoAction()
        for number in reversed(range(first, last + 1)):
            line = self.text(number)
            indent = len(line) - len(line.lstrip(" \t"))
            if not line.strip():
                continue
            if remove:
                count = 2 if line[indent : indent + 2] == "# " else 1
                self.setSelection(number, indent, number, indent + count)
                self.replaceSelectedText("")
            else:
                self.insertAt("# ", number, indent)
        self.endUndoAction()

    def keyPressEvent(self, event):
        key, modifiers = event.key(), event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        if control and key == Qt.Key.Key_Space:
            self.request("complete")
            return
        if self.isListActive() and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            super().keyPressEvent(event)
            return
        line, column = self.getCursorPosition()
        text = event.text()
        pairs = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
        if not control and text in pairs and text:
            selected = self.selectedText() if self.hasSelectedText() else ""
            next_char = self.text(line)[column : column + 1]
            previous = self.text(line)[column - 1 : column] if column else ""
            if selected:
                self.replaceSelectedText(text + selected + pairs[text])
                return
            if text not in "\"'" or (not previous.isalnum() and not previous == "\\"):
                if not next_char or next_char.isspace() or next_char in ")]},:":
                    self.beginUndoAction()
                    self.insert(text + pairs[text])
                    self.setCursorPosition(line, column + 1)
                    self.endUndoAction()
                    self._char_added(ord(text))
                    return
        if text and text in ")]}'\"" and not control and not self.hasSelectedText():
            if self.text(line)[column : column + 1] == text:
                self.setCursorPosition(line, column + 1)
                return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.hasSelectedText():
            before = self.text(line)[:column]
            extra = before.rstrip().endswith(":") and self.is_python
            super().keyPressEvent(event)
            if extra:
                new_line, _ = self.getCursorPosition()
                self.setIndentation(new_line, self.indentation(line) + 4)
                self.setCursorPosition(new_line, self.indentation(new_line))
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu: QMenu = self.createStandardContextMenu()
        menu.addSeparator()
        for label, operation in [
            ("Перейти к определению  F12", "goto"),
            ("Документация  Ctrl+Q", "help"),
            ("Найти использования  Shift+F12", "references"),
            ("Переименовать символ  Shift+F6", "rename"),
        ]:
            menu.addAction(label, lambda _=False, op=operation: self.request(op))
        menu.exec(event.globalPos())
        menu.deleteLater()
