"""Reusable floating response widget for the Echo backend."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


BG_COLOR = QColor("#00171D")
TEXT_COLOR = QColor("#F5F8F8")

WINDOW_WIDTH = 430
MIN_HEIGHT = 70
MAX_HEIGHT = 300
MARGIN = 18
RADIUS = 18


class ResponseWidget(QWidget):
    """Frameless, draggable response window that closes on outside click."""

    closed = Signal()

    def __init__(self, text: str):
        super().__init__()

        self.drag_position = QPoint()
        self._app = QApplication.instance()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.label.setStyleSheet(
            f"""
            QLabel {{
                color: {TEXT_COLOR.name()};
                background: transparent;
                font-size: 15px;
                line-height: 1.4;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.addWidget(self.label)

        self.label.setMaximumWidth(WINDOW_WIDTH - MARGIN * 2)
        self.adjustSize()

        width = min(
            WINDOW_WIDTH,
            max(180, self.label.sizeHint().width() + MARGIN * 2),
        )
        height = min(
            MAX_HEIGHT,
            max(MIN_HEIGHT, self.label.sizeHint().height() + MARGIN * 2),
        )

        self.resize(width, height)
        self._position_window()

        if self._app is not None:
            self._app.installEventFilter(self)

    def _position_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return

        geometry = screen.availableGeometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + geometry.height() - self.height() - 30
        self.move(x, y)

    def _point_inside_widget(self, global_pos) -> bool:
        return self.rect().contains(self.mapFromGlobal(global_pos))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if not self._point_inside_widget(
                event.globalPosition().toPoint()
            ):
                self.close()
                return True

        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(
            0,
            0,
            self.width(),
            self.height(),
            RADIUS,
            RADIUS,
        )
        painter.fillPath(path, BG_COLOR)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(
                event.globalPosition().toPoint()
                - self.drag_position
            )
            event.accept()
            return

        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._app is not None:
            self._app.removeEventFilter(self)

        event.accept()
        self.closed.emit()
