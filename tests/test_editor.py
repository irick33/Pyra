from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from pyra.editor import Editor


def test_auto_pairs_and_colon_indent(app):
    editor = Editor()
    editor.show()
    QTest.keyClicks(editor, "print(")
    assert editor.text() == "print()"
    editor.setText("if True:")
    editor.setCursorPosition(0, 8)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.indentation(1) == 4
    editor.close()


def test_breakpoints_follow_inserted_lines(app):
    editor = Editor()
    editor.setText("a=1\nb=2\n")
    editor.toggle_breakpoint(1)
    assert editor.breakpoints() == [2]
    editor.insertAt("# comment\n", 0, 0)
    assert editor.breakpoints() == [3]
    editor.close()


def test_replace_document_undo_and_unicode(app):
    editor = Editor()
    editor.setText('имя = "Ярослав"\n')
    editor.replace_document('имя = "Python"\n')
    assert "Python" in editor.text()
    editor.undo()
    assert "Ярослав" in editor.text()
    editor.close()


def test_comment_multiple_lines(app):
    editor = Editor()
    original = "a = 1\n    b = 2\n"
    editor.setText(original)
    editor.setSelection(0, 0, 2, 0)
    editor.toggle_comment()
    assert editor.text() == "# a = 1\n    # b = 2\n"
    editor.setSelection(0, 0, 2, 0)
    editor.toggle_comment()
    assert editor.text() == original
    editor.close()
