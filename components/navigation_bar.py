"""
Left-side navigation sidebar.

A dark, rounded, independent widget containing a vertical stack of
SVG-based icon buttons.

Icons are loaded from assets/images/ and recolored dynamically:
    - inactive -> Colors.ICON_INACTIVE
    - active   -> Colors.ICON_ACTIVE

Clicking a button emits ``navigate(index)`` so the main window can
switch the visible section.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QImage,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QButtonGroup,
)

from styles.theme import Colors, RADIUS_NAV, NAV_WIDTH


# ------------------------------------------------------------
# Asset location
# ------------------------------------------------------------

ASSETS_DIR = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "images"
)


class NavButton(QPushButton):
    """A single checkable navigation button using an SVG icon."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        parent=None,
    ):
        super().__init__(parent)

        self.icon_name = icon_name

        self.setCheckable(True)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFlat(True)

        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)

        # --------------------------------------------------------
        # SVG
        # --------------------------------------------------------

        self.icon_path = ASSETS_DIR / f"{icon_name}.svg"

        if not self.icon_path.exists():
            print(f"Could not load navigation icon: {self.icon_path}")
            self.svg_renderer = None
        else:
            self.svg_renderer = QSvgRenderer(str(self.icon_path))

            if not self.svg_renderer.isValid():
                print(f"Invalid SVG icon: {self.icon_path}")
                self.svg_renderer = None

        self.icon_size = QSize(21, 21)

    # ------------------------------------------------------------
    # SVG rendering + recoloring
    # ------------------------------------------------------------

    def _render_colored_icon(self, color: QColor) -> QImage:
        """
        Render the SVG into a transparent image and recolor it.

        The SVG's alpha is preserved while its visible pixels are
        replaced with the supplied color.
        """

        image = QImage(
            self.icon_size,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)

        if self.svg_renderer is None:
            return image

        # Render SVG
        svg_painter = QPainter(image)
        svg_painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )
        svg_painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

        self.svg_renderer.render(
            svg_painter,
            QRectF(
                0,
                0,
                self.icon_size.width(),
                self.icon_size.height(),
            ),
        )

        svg_painter.end()

        # Replace the visible pixels with the chosen color
        color_painter = QPainter(image)
        color_painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn
        )
        color_painter.fillRect(
            image.rect(),
            color,
        )
        color_painter.end()

        return image

    # ------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

        # --------------------------------------------------------
        # Active background
        # --------------------------------------------------------

        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(Colors.ICON_ACTIVE_BG)
            )

            painter.drawRoundedRect(
                QRectF(self.rect()),
                12,
                12,
            )

            icon_color = QColor(Colors.ICON_ACTIVE)

        else:
            icon_color = QColor(Colors.ICON_INACTIVE)

        # --------------------------------------------------------
        # Render icon
        # --------------------------------------------------------

        icon_image = self._render_colored_icon(
            icon_color
        )

        x = (self.width() - icon_image.width()) // 2
        y = (self.height() - icon_image.height()) // 2

        painter.drawImage(
            x,
            y,
            icon_image,
        )

        painter.end()


class NavigationBar(QWidget):
    """Dark, rounded, vertically arranged navigation sidebar."""

    navigate = Signal(int)

    # ------------------------------------------------------------
    # SVG filename, tooltip
    # Order defines section index.
    # ------------------------------------------------------------

    SECTIONS = [
        ("home", "Home"),
        ("add", "New"),
        ("list", "List"),
        ("doc", "Documents"),
        ("settings", "Settings"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedWidth(NAV_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            0,
            28,
            0,
            20,
        )
        layout.setSpacing(15)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
        )

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        # --------------------------------------------------------
        # Main navigation buttons
        # --------------------------------------------------------

        for index, (icon_name, tooltip) in enumerate(
            self.SECTIONS[:-1]
        ):
            btn = NavButton(
                icon_name,
                tooltip,
                self,
            )

            self.group.addButton(
                btn,
                index,
            )

            layout.addWidget(
                btn,
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )

            if index == 0:
                btn.setChecked(True)

        # --------------------------------------------------------
        # Push Settings to the bottom
        # --------------------------------------------------------

        layout.addStretch(1)

        settings_index = len(self.SECTIONS) - 1
        icon_name, tooltip = self.SECTIONS[-1]

        settings_btn = NavButton(
            icon_name,
            tooltip,
            self,
        )

        self.group.addButton(
            settings_btn,
            settings_index,
        )

        layout.addWidget(
            settings_btn,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        

        # Home selected by default
        if index == 0:
            btn.setChecked(True)

        layout.addStretch()

        # --------------------------------------------------------
        # Navigation signal
        # --------------------------------------------------------

        self.group.idClicked.connect(
            self.navigate.emit
        )

    # ------------------------------------------------------------
    # Navigation bar background
    # ------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()),
            RADIUS_NAV,
            RADIUS_NAV,
        )

        painter.fillPath(
            path,
            QColor(Colors.NAV_BG),
        )

        painter.end()