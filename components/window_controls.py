"""
Top-right window control pill.

Three custom-painted circular buttons standing in for the native title
bar controls, since the application window is frameless. Colors follow
the macOS-style convention requested in the spec: red = close,
yellow = minimize, green = maximize/restore.
"""

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton

from styles.theme import Colors, CONTROLS_HEIGHT


class ControlDot(QPushButton):
    """A single flat, filled circular control button."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())
        painter.end()


class WindowControls(QWidget):
    """Pill-shaped container holding the close / minimize / maximize dots."""

    
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, CONTROLS_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        
        self.btn_min = ControlDot(Colors.CONTROL_MINIMIZE)
        self.btn_max = ControlDot(Colors.CONTROL_MAXIMIZE)
        self.btn_close = ControlDot(Colors.CONTROL_CLOSE)

        for dot in ( self.btn_min, self.btn_max,self.btn_close):
            layout.addWidget(dot)

        
        self.btn_min.clicked.connect(self.minimize_clicked.emit)
        #self.btn_max.clicked.connect(self.maximize_clicked.emit)
        self.btn_close.clicked.connect(self.close_clicked.emit)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Colors.CONTROLS_PILL_BG))
        painter.drawRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        painter.end()
