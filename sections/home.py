"""
Home tab.

Recreates the reference design: a layered, procedurally painted
gray "mountain" backdrop, a centered robot-face mark with the ECHO
wordmark, and a bottom-center pill badge showing the launch shortcut.
Every visual element here is drawn with QPainter, so no external
image assets are required to reproduce the look.
"""

import math
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QFont, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from styles.theme import Colors, Fonts


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "images"


class MountainScene(QWidget):
    """Transparent widget displaying the mountain PNG."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.mountain = QPixmap(
            str(ASSETS_DIR / "mountain_bg.png")
        )

    def paintEvent(self, event):
        if self.mountain.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

        painter.drawPixmap(self.rect(), self.mountain)
        painter.end()


class ShortcutBadge(QWidget):
    """Pill badge displaying the launch shortcut."""

    def __init__(
        self,
        text="Alt + Space",
        chip_text="AI",
        parent=None
    ):
        super().__init__(parent)

        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 18, 5)
        layout.setSpacing(10)

        chip = QLabel(chip_text)
        chip.setFixedSize(28, 28)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setStyleSheet("""
            background: rgba(255, 255, 255, 45);
            color: white;
            border-radius: 7px;
            font-weight: 600;
            font-size: 10px;
        """)

        label = QLabel(text)
        label.setFont(
            Fonts.FAMILY and __import__("PySide6.QtGui", fromlist=["QFont"]).QFont(
                Fonts.FAMILY, Fonts.BADGE_SIZE
            )
        )
        label.setStyleSheet(
            f"color: {Colors.BADGE_TEXT}; background: transparent;"
        )

        layout.addWidget(chip)
        layout.addWidget(label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Colors.BADGE_BG))
        painter.drawRoundedRect(
            self.rect(),
            self.height() / 2,
            self.height() / 2
        )
        painter.end()


class HomeSection(QWidget):
    """Home tab with transparent mountain and branding PNGs."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        self.background = MountainScene(self)
        self.background.lower()

        overlay = QVBoxLayout(self)
        overlay.setContentsMargins(0, 36, 0, 35)
        overlay.setSpacing(20)

        # Robot face PNG
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(
            QPixmap(str(ASSETS_DIR / "robot_face.png"))
        )
        icon_label.setStyleSheet("background: transparent;")

        # ECHO wordmark PNG
        brand_label = QLabel()
        brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_label.setPixmap(
            QPixmap(str(ASSETS_DIR / "echo_logo.png"))
        )
        brand_label.setStyleSheet("background: transparent;")

        overlay.addWidget(icon_label)
        overlay.addWidget(brand_label)
        overlay.addStretch()
        overlay.addWidget(
            ShortcutBadge(),
            alignment=Qt.AlignmentFlag.AlignHCenter
        )

    def resizeEvent(self, event):
        self.background.setGeometry(self.rect())
        self.background.lower()
        super().resizeEvent(event)