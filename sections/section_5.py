"""
Settings tab.

This section intentionally contains only the Rick Roll GIF.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from styles.theme import Colors


class SettingsSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet(
            f"background: {Colors.CARD_BG};"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        self.gif_label = QLabel()
        self.gif_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.gif_label.setStyleSheet(
            "background: transparent; border: none;"
        )

        # section_5.py -> project root -> assets/images/rickroll.gif
        app_dir = Path(__file__).resolve().parent.parent

        gif_path = (
            app_dir
            / "assets"
            / "images"
            / "rickroll.gif"
        )

        self.movie = QMovie(str(gif_path))

        if self.movie.isValid():
            self.gif_label.setMovie(self.movie)
            self.movie.start()
        else:
            self.gif_label.setText(
                "rickroll.gif not found"
            )
            self.gif_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {Colors.TEXT_MUTED};
                    background: transparent;
                    font-size: 14px;
                }}
                """
            )

        layout.addWidget(self.gif_label)