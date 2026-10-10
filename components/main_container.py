from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QSize
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QImage,
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget

from styles.theme import Colors, RADIUS_CARD
from components.window_controls import WindowControls


class MainContainer(QWidget):
    """Rounded card with a PNG silhouette cutout and window controls."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Allow transparent pixels to reveal the background behind the card
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        self.stack.setStyleSheet("""
            QStackedWidget {
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self.stack)

        # ------------------------------------------------------------
        # Window controls overlay
        # ------------------------------------------------------------

        self.window_controls = WindowControls(self)
        self.window_controls.raise_()

        self.window_controls.close_clicked.connect(
            self._close_window
        )

        self.window_controls.minimize_clicked.connect(
            self._minimize_window
        )

        self.window_controls.maximize_clicked.connect(
            self._toggle_maximize
        )

        # ------------------------------------------------------------
        # Load silhouette PNG
        # ------------------------------------------------------------

        self.silhouette_path = (
            Path(__file__).resolve().parent.parent
            / "assets"
            / "images"
            / "silhouette.png"
        )

        self.silhouette = QImage(
            str(self.silhouette_path)
        )

        if self.silhouette.isNull():
            print(
                f"Could not load silhouette: "
                f"{self.silhouette_path}"
            )

        # ------------------------------------------------------------
        # Cutout position and size
        # ------------------------------------------------------------

        self.cutout_width = 117
        self.cutout_height = 55
        self.cutout_x = 0
        self.cutout_y = 0

        # ------------------------------------------------------------
        # Window controls positioning
        # ------------------------------------------------------------

        self.controls_margin_right = 0
        self.controls_margin_top = 0

        # ------------------------------------------------------------
        # Rendering quality
        # ------------------------------------------------------------

        # Render the card at a higher resolution and downsample it.
        # This gives significantly smoother rounded corners and
        # smoother PNG cutout edges.
        self.render_scale = 4

    # ------------------------------------------------------------
    # Window controls behavior
    # ------------------------------------------------------------

    def _close_window(self):
        window = self.window()

        if window is not self:
            window.close()

    def _minimize_window(self):
        window = self.window()

        if window is not self:
            window.showMinimized()

    def _toggle_maximize(self):
        window = self.window()

        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()

    # ------------------------------------------------------------
    # Window controls positioning
    # ------------------------------------------------------------

    def resizeEvent(self, event):
        margin_top = self.controls_margin_top
        margin_right = self.controls_margin_right

        self.window_controls.adjustSize()

        self.window_controls.move(
            self.width()
            - self.window_controls.width()
            - margin_right,
            margin_top,
        )

        self.window_controls.raise_()

        super().resizeEvent(event)

    # ------------------------------------------------------------
    # Section management
    # ------------------------------------------------------------

    def add_section(self, widget: QWidget) -> int:
        return self.stack.addWidget(widget)

    def set_current(self, index: int):
        self.stack.setCurrentIndex(index)

    # ------------------------------------------------------------
    # Card shape
    # ------------------------------------------------------------

    def create_shape(self, width, height):
        """
        Create the rounded card path at the requested size.

        Using a slightly inset rectangle prevents the antialiased
        edge from being clipped at the image boundary.
        """

        rect = QRectF(
            0.5,
            0.5,
            max(0.0, width - 1.0),
            max(0.0, height - 1.0),
        )

        path = QPainterPath()

        path.addRoundedRect(
            rect,
            RADIUS_CARD,
            RADIUS_CARD,
        )

        return path

    # ------------------------------------------------------------
    # Cutout rectangle
    # ------------------------------------------------------------

    def get_cutout_rect(self):
        """
        Position the silhouette at the top-right corner
        using normal widget coordinates.
        """

        return QRectF(
            self.width()
            - self.cutout_width
            - self.cutout_x,

            self.cutout_y,

            self.cutout_width,
            self.cutout_height,
        )

    # ------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------

    def paintEvent(self, event):
        width = self.width()
        height = self.height()

        if width <= 0 or height <= 0:
            return

        scale = self.render_scale

        # ========================================================
        # 1. Create a high-resolution transparent layer
        # ========================================================

        high_width = width * scale
        high_height = height * scale

        layer = QImage(
            QSize(
                high_width,
                high_height,
            ),
            QImage.Format.Format_ARGB32_Premultiplied,
        )

        layer.fill(
            Qt.GlobalColor.transparent
        )

        # ========================================================
        # 2. Draw rounded card at high resolution
        # ========================================================

        painter = QPainter(layer)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            True,
        )

        # Work in normal widget coordinates while painting to the
        # high-resolution image.
        painter.scale(
            scale,
            scale,
        )

        path = self.create_shape(
            width,
            height,
        )

        painter.fillPath(
            path,
            QColor(Colors.CARD_BG),
        )

        # ========================================================
        # 3. Subtract the PNG silhouette
        # ========================================================

        if not self.silhouette.isNull():

            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut
            )

            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                True,
            )

            painter.drawImage(
                self.get_cutout_rect(),
                self.silhouette,
            )

        painter.end()

        # ========================================================
        # 4. Downsample the high-resolution result
        # ========================================================

        final_image = layer.scaled(
            QSize(
                width,
                height,
            ),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # ========================================================
        # 5. Draw final smooth image
        # ========================================================

        final_painter = QPainter(self)

        final_painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        final_painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            True,
        )

        final_painter.drawImage(
            0,
            0,
            final_image,
        )

        final_painter.end()