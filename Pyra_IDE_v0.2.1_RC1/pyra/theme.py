from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtCore import Qt

BG = "#11141c"
PANEL = "#171b26"
TEXT = "#d5dbea"
MUTED = "#8690a8"
ACCENT = "#9b8afb"

STYLE = """
QWidget { color: #d5dbea; font-family: 'Segoe UI', 'DejaVu Sans'; font-size: 12px; }
QMainWindow, QDialog { background: #11141c; }
QMenuBar { background: #171b26; padding: 4px; border-bottom: 1px solid #282e3e; }
QMenuBar::item { padding: 5px 10px; border-radius: 4px; }
QMenuBar::item:selected, QMenu::item:selected { background: #31354e; }
QMenu { background: #1d2230; border: 1px solid #363e53; padding: 5px; }
QMenu::item { padding: 7px 24px; }
QMenu::separator { height: 1px; background: #30374a; margin: 5px; }
QToolTip { color: #d5dbea; background: #252b3b; border: 1px solid #414a64; padding: 6px; }
QPushButton, QToolButton { background: #232a3b; border: 1px solid #343d53; border-radius: 5px; padding: 6px 12px; }
QPushButton:hover, QToolButton:hover { background: #303a52; border-color: #635b99; }
QPushButton:pressed { background: #3f4264; }
QPushButton:disabled { color: #596278; background: #1a1f2c; border-color: #252c3c; }
QPushButton#primary { color: #101721; background: #8cdab6; border: 0; font-weight: 600; }
QPushButton#primary:hover { background: #abebcc; }
QPushButton#quiet { background: transparent; border: 0; color: #a5afc6; }
QPushButton#rail { background: transparent; border: 0; border-radius: 0; font-size: 19px; padding: 14px 4px; }
QPushButton#rail:checked { color: #b8a9ff; background: #29283f; border-left: 2px solid #aa94ff; }
QLineEdit, QComboBox, QSpinBox { background: #111622; selection-background-color: #534779; border: 1px solid #343d51; border-radius: 5px; padding: 6px 9px; }
QLineEdit:focus, QComboBox:focus { border-color: #9583e8; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView { background: #212738; selection-background-color: #45405f; }
QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget, QTreeView, QTableWidget {
  background: #11141c; border: 0; selection-background-color: #34334e; outline: none;
}
QTreeView { background: #171b26; }
QTreeView::item, QListWidget::item { padding: 5px 4px; }
QTreeView::item:hover, QListWidget::item:hover { background: #22293a; }
QHeaderView::section { background: #1b2130; color: #8f9bb5; padding: 7px; border: 0; border-bottom: 1px solid #2b3448; }
QTabWidget::pane { border: 0; }
QTabBar { background: #171b26; }
QTabBar::tab { background: #171b26; color: #8c97b0; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #e0dcff; background: #11141c; border-bottom: 2px solid #9b8afb; }
QTabBar::tab:hover { color: #e1e5ee; }
QSplitter::handle { background: #262d3d; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QStatusBar { background: #1b2030; color: #a4afc5; border-top: 1px solid #30374a; }
QStatusBar::item { border: 0; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #384259; border-radius: 4px; min-height: 26px; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #384259; border-radius: 4px; min-width: 26px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QLabel#section { color: #8793ad; font-size: 10px; font-weight: 600; padding: 12px 10px 7px; }
QLabel#brand { color: #b4a5ff; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
QCheckBox { spacing: 6px; }
"""


def mono(size=11):
    font = QFont(
        "Cascadia Code" if __import__("sys").platform == "win32" else "DejaVu Sans Mono", size
    )
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def dark_palette():
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: PANEL,
        QPalette.ColorRole.Base: BG,
        QPalette.ColorRole.AlternateBase: "#1d2433",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Button: "#252d40",
        QPalette.ColorRole.Highlight: "#464063",
        QPalette.ColorRole.HighlightedText: "#eee9ff",
        QPalette.ColorRole.ToolTipBase: PANEL,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Link: ACCENT,
    }.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#67738b"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#67738b"))
    return palette


def app_icon():
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#9785f1"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
    painter.setPen(QColor("#131523"))
    painter.setFont(QFont("DejaVu Sans", 32, QFont.Weight.Bold))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    return QIcon(image)
